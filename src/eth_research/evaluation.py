"""Deterministic benchmark evaluation and reporting on the frozen engine.

This layer runs the pinned protocol on a verified dataset without changing
the Milestone 1 engine. Its jobs:

* run train and validation freely (pipeline verification is allowed and
  repeatable) while remaining structurally unable to touch test strategy
  values — segment runners only ever receive the segment frame and its
  declared warm-up context;
* run the real test segment **only** through the guarded one-time path:
  refused by default, an explicit confirmation token required, the full
  provenance chain (dataset lock, manifest, acquisition evidence,
  protocol, quality report) re-verified first, the append-only ledger
  consulted, ``started`` recorded before any test signal exists, and
  completion or failure recorded honestly — a crash after ``started`` is
  a consumed access;
* reconcile every reported number against the engine's ``BacktestResult``
  (equity identity per bar, fill counts, turnover, boundaries) so a
  report can never drift from the accounting that produced it;
* publish deterministic JSON plus Markdown generated only from the
  validated JSON model, atomically and transactionally.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from eth_research import __version__
from eth_research._atomic import publish_atomically
from eth_research.backtest import BacktestResult, CostModel, run_backtest
from eth_research.data.builder import LoadedDataset, load_canonical_dataset
from eth_research.data.lock import load_dataset_lock, verify_dataset_lock
from eth_research.data.provenance import (
    content_fingerprint,
    require_nonempty_str,
    sha256_bytes,
)
from eth_research.data.validation import (
    require_commit_sha,
    require_evaluation_id,
)
from eth_research.environment import (
    CANONICAL_RUNTIME_CONTRACT_RELPATH,
    RuntimeVerificationError,
    load_runtime_contract,
    verify_runtime_contract,
)
from eth_research.gitcheck import (
    GitError,
    file_bytes_at_commit,
    head_commit,
    is_commit_object,
    relative_to_repo,
    resolve_repo_root,
    tracked_tree_is_clean,
    verify_package_source,
)
from eth_research.ledger import (
    EVENT_COMPLETED,
    EVENT_FAILED,
    EVENT_STARTED,
    LedgerEvent,
    accesses_for,
    append_event,
    read_ledger,
)
from eth_research.metrics import PerformanceSummary, summarize
from eth_research.protocol import (
    BUY_AND_HOLD_STRATEGY,
    RESULT_STRATEGY_NAMES,
    BenchmarkProtocol,
    BenchmarkResults,
    QualityWarningSummary,
    SegmentMetrics,
    SplitBoundary,
    verify_protocol,
)
from eth_research.splits import DataSplits, chronological_split
from eth_research.strategies import BuyAndHold, MovingAverageCrossover, Strategy

_SEGMENT_ORDER: dict[str, int] = {"train": 0, "validation": 1, "test": 2}

RESULTS_FILENAME: str = "benchmark_results.json"
REPORT_FILENAME: str = "benchmark_report.md"

CANONICAL_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"
"""The one authoritative, tracked location of the test-access ledger."""

EVALUATION_CONFIRM_TOKEN: str = (
    "I-UNDERSTAND-THIS-PERMANENTLY-CONSUMES-THE-ONE-TIME-TEST-EVALUATION"
)


class EvaluationError(RuntimeError):
    """Evaluation was refused, failed verification, or failed to reconcile."""


@dataclass(frozen=True)
class OneTimeTestAuthorization:
    """Explicit, single-use authorization to evaluate the real test segment."""

    evaluation_id: str
    reason: str
    code_commit_sha: str
    confirm_token: str

    def __post_init__(self) -> None:
        require_evaluation_id("evaluation_id", self.evaluation_id)
        require_nonempty_str("reason", self.reason)
        require_commit_sha("code_commit_sha", self.code_commit_sha)
        if self.confirm_token != EVALUATION_CONFIRM_TOKEN:
            raise ValueError(
                "confirm_token must be exactly EVALUATION_CONFIRM_TOKEN; test evaluation "
                "permanently consumes the one-time test access"
            )


@dataclass(frozen=True)
class BenchmarkRun:
    """Everything one authorized benchmark run produced."""

    results: BenchmarkResults
    markdown: str
    results_path: Path
    report_path: Path


def _default_clock() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _strategies(protocol: BenchmarkProtocol) -> tuple[tuple[Strategy, int], ...]:
    """Instantiate the pinned strategies with their warm-up context sizes."""
    built: list[tuple[Strategy, int]] = []
    for spec in protocol.strategies:
        if spec.name == BUY_AND_HOLD_STRATEGY:
            built.append((BuyAndHold(), protocol.buy_and_hold_context_bars))
        else:
            fast = spec.fast_window
            slow = spec.slow_window
            if fast is None or slow is None:
                raise EvaluationError("SMA strategy spec is missing its pinned windows")
            built.append(
                (
                    MovingAverageCrossover(fast_window=fast, slow_window=slow),
                    protocol.sma_context_bars,
                )
            )
    return tuple(built)


def _verify_dataset_matches_protocol(dataset: LoadedDataset, protocol: BenchmarkProtocol) -> None:
    if dataset.manifest.content_fingerprint != protocol.dataset_content_fingerprint:
        raise EvaluationError(
            "dataset/protocol mismatch: the loaded dataset's content fingerprint "
            f"{dataset.manifest.content_fingerprint!r} is not the protocol's "
            f"{protocol.dataset_content_fingerprint!r}"
        )


def _split(dataset: LoadedDataset, protocol: BenchmarkProtocol) -> DataSplits:
    return chronological_split(
        dataset.frame,
        train_fraction=protocol.train_fraction,
        validation_fraction=protocol.validation_fraction,
    )


def _context_for(splits: DataSplits, segment: str, context_bars: int) -> pd.DataFrame | None:
    if context_bars == 0:
        return None
    if segment == "train":
        return None
    if segment == "validation":
        return splits.validation_context(context_bars)
    return splits.test_context(context_bars)


def _reconcile(
    result: BacktestResult,
    summary: PerformanceSummary,
    segment_frame: pd.DataFrame,
    protocol: BenchmarkProtocol,
) -> None:
    """Every reported number must agree exactly with the engine's accounting."""
    if not result.equity.index.equals(segment_frame.index):
        raise EvaluationError(
            "reconciliation failed: the equity curve does not cover exactly the evaluated "
            "segment (context rows must contribute no accounting)"
        )
    closes = segment_frame["close"].to_numpy(dtype=float)
    recomputed = result.cash.to_numpy(dtype=float) + result.quantity.to_numpy(dtype=float) * closes
    if not np.array_equal(recomputed, result.equity.to_numpy(dtype=float)):
        raise EvaluationError(
            "reconciliation failed: equity != cash + quantity * close at some bar"
        )
    if summary.num_trades != len(result.fills):
        raise EvaluationError(
            "reconciliation failed: reported fill count does not equal the fill ledger length"
        )
    traded = float(sum(fill.gross_notional for fill in result.fills))
    if summary.total_traded_notional != traded:
        raise EvaluationError(
            "reconciliation failed: total traded notional does not equal the sum over fills"
        )
    if summary.turnover != traded / result.initial_cash:
        raise EvaluationError("reconciliation failed: turnover != traded notional / initial cash")
    if summary.terminal_equity != float(result.equity.iloc[-1]):
        raise EvaluationError(
            "reconciliation failed: terminal equity does not equal the final equity mark"
        )
    if summary.initial_equity != protocol.initial_cash:
        raise EvaluationError("reconciliation failed: initial equity is not the protocol's")
    if result.start_time != segment_frame.index[0]:
        raise EvaluationError("reconciliation failed: start time is not the segment's first open")
    if result.end_time != segment_frame.index[-1] + result.bar_interval:
        raise EvaluationError("reconciliation failed: end time is not the segment's last close")
    if summary.n_periods != len(segment_frame):
        raise EvaluationError("reconciliation failed: period count is not the segment length")


def _finite_or_none(value: float) -> float | None:
    return None if math.isnan(value) else float(value)


def _run_segment(
    segment_frame: pd.DataFrame,
    context: pd.DataFrame | None,
    strategy: Strategy,
    protocol: BenchmarkProtocol,
    segment: str,
) -> SegmentMetrics:
    costs = CostModel(fee_rate=protocol.fee_rate, slippage_rate=protocol.slippage_rate)
    result = run_backtest(
        segment_frame,
        strategy,
        costs,
        initial_cash=protocol.initial_cash,
        context=context,
    )
    summary = summarize(result, risk_free_rate=protocol.risk_free_rate)
    _reconcile(result, summary, segment_frame, protocol)
    return SegmentMetrics(
        strategy=result.strategy_name,
        segment=segment,
        n_bars=summary.n_periods,
        start_time=result.start_time,
        end_time=result.end_time,
        context_bars=result.context_bars,
        initial_cash=result.initial_cash,
        terminal_equity=summary.terminal_equity,
        terminal_liquidation_equity=result.terminal_liquidation_equity,
        total_return=summary.total_return,
        cagr=summary.cagr,
        sharpe=_finite_or_none(summary.sharpe),
        sortino=_finite_or_none(summary.sortino),
        max_drawdown=summary.max_drawdown,
        total_traded_notional=summary.total_traded_notional,
        turnover=summary.turnover,
        num_fills=summary.num_trades,
    )


def _recheck_frame_fingerprint(dataset: LoadedDataset) -> None:
    """The frame must recompute to its manifest fingerprint (guards forged
    hand-built ``LoadedDataset`` objects that could mislabel results)."""
    if content_fingerprint(dataset.frame) != dataset.manifest.content_fingerprint:
        raise EvaluationError(
            "the dataset frame does not recompute to its manifest content fingerprint — "
            "refusing to evaluate a dataset whose frame and manifest disagree"
        )


def evaluate_train_validation(
    dataset: LoadedDataset, protocol: BenchmarkProtocol
) -> tuple[SegmentMetrics, ...]:
    """Run both pinned strategies on train and validation only.

    May be repeated freely for pipeline verification; the test segment is
    split off mechanically but never handed to a strategy or the engine.
    """
    _verify_dataset_matches_protocol(dataset, protocol)
    _recheck_frame_fingerprint(dataset)
    splits = _split(dataset, protocol)
    segments: list[SegmentMetrics] = []
    for strategy, context_bars in _strategies(protocol):
        for segment in ("train", "validation"):
            frame = splits.train if segment == "train" else splits.validation
            context = _context_for(splits, segment, context_bars)
            segments.append(_run_segment(frame, context, strategy, protocol, segment))
    return tuple(segments)


def evaluate_train_validation_from_manifest(
    manifest_path: str | Path, protocol: BenchmarkProtocol
) -> tuple[SegmentMetrics, ...]:
    """Load and verify the dataset from its manifest, then run train/validation.

    The high-level entry point that never trusts a caller-built
    :class:`LoadedDataset`: :func:`load_canonical_dataset` re-verifies the
    Parquet, manifest, fingerprint, and quality report before evaluation.
    """
    dataset = load_canonical_dataset(manifest_path)
    return evaluate_train_validation(dataset, protocol)


def split_boundaries(
    dataset: LoadedDataset, protocol: BenchmarkProtocol
) -> tuple[SplitBoundary, ...]:
    """Mechanical split bounds (allowed on the whole dataset at any time)."""
    splits = _split(dataset, protocol)
    return tuple(
        SplitBoundary(
            segment=name,
            first_open_time=frame.index[0],
            last_open_time=frame.index[-1],
            n_bars=len(frame),
        )
        for name, frame in (
            ("train", splits.train),
            ("validation", splits.validation),
            ("test", splits.test),
        )
    )


def build_benchmark_results(
    dataset: LoadedDataset,
    protocol: BenchmarkProtocol,
    segments: tuple[SegmentMetrics, ...],
    *,
    pre_registered_commit_sha: str,
    test_evaluation_id: str | None,
) -> BenchmarkResults:
    """Assemble the validated result record from evaluated segments."""
    _verify_dataset_matches_protocol(dataset, protocol)
    manifest = dataset.manifest
    warnings = tuple(
        QualityWarningSummary(
            code=finding.code, count=finding.count, first_examples=finding.first_examples
        )
        for finding in dataset.quality_report.findings
        if finding.severity == "warning"
    )
    return BenchmarkResults(
        results_schema_version=1,
        package_version=__version__,
        base_asset=manifest.base_asset,
        quote_asset=manifest.quote_asset,
        symbol=manifest.symbol,
        venue=manifest.venue,
        market_type=manifest.market_type,
        candle_interval=manifest.candle_interval,
        dataset_content_fingerprint=manifest.content_fingerprint,
        dataset_manifest_sha256=protocol.dataset_manifest_sha256,
        dataset_lock_sha256=protocol.dataset_lock_sha256,
        quality_report_sha256=manifest.quality_report_sha256,
        acquisition_evidence_sha256=protocol.acquisition_evidence_sha256,
        protocol_sha256=sha256_bytes(protocol.to_json_bytes()),
        pre_registered_commit_sha=pre_registered_commit_sha,
        dataset_row_count=manifest.row_count,
        dataset_first_open_time=manifest.first_open_time,
        dataset_last_open_time=manifest.last_open_time,
        quality_warnings=warnings,
        splits=split_boundaries(dataset, protocol),
        segments=segments,
        accounting=protocol.accounting,
        test_evaluation_id=test_evaluation_id,
    )


def publish_benchmark_reports(
    results: BenchmarkResults,
    markdown: str,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Atomically publish the JSON results and Markdown report together.

    The Markdown must be exactly the rendering of ``results`` — it is
    regenerated and compared, so a hand-edited report can never ship. A
    failed publication rolls back completely.
    """
    if markdown != render_benchmark_markdown(results):
        raise EvaluationError(
            "refusing to publish: the markdown is not the rendering of the results model"
        )
    directory = Path(output_dir)
    results_path = directory / RESULTS_FILENAME
    report_path = directory / REPORT_FILENAME
    existing = [path for path in (results_path, report_path) if path.exists()]
    if existing and not overwrite:
        names = ", ".join(path.name for path in existing)
        raise EvaluationError(
            f"refusing to overwrite existing report(s) in {directory}: {names}. "
            "Pass overwrite=True to replace them explicitly."
        )
    directory.mkdir(parents=True, exist_ok=True)
    publish_atomically(
        [
            (report_path, markdown.encode("utf-8")),
            (results_path, results.to_json_bytes()),  # authoritative artifact last
        ],
        error=EvaluationError,
    )
    return results_path, report_path


def _running_package_root() -> Path:
    """The filesystem directory the running ``eth_research`` package lives in."""
    import eth_research

    location = eth_research.__file__
    if location is None:  # pragma: no cover - namespace package, not our layout
        raise EvaluationError("the running eth_research package has no filesystem location")
    return Path(location).resolve().parent


def _require_bytes_match_head(repo_root: Path, head: str, path: Path, label: str) -> None:
    """The working bytes of a tracked file must equal its bytes at ``head``."""
    try:
        relpath = relative_to_repo(repo_root, path)
    except GitError as exc:
        raise EvaluationError(f"{label} path is not inside the repository: {exc}") from exc
    if not path.exists():
        raise EvaluationError(f"{label} {path} does not exist")
    try:
        committed = file_bytes_at_commit(repo_root, head, relpath)
    except GitError as exc:
        raise EvaluationError(
            f"{label} {relpath!r} is not committed at the pre-registered revision: {exc}"
        ) from exc
    if path.read_bytes() != committed:
        raise EvaluationError(
            f"{label} {relpath!r} differs from its bytes committed at the pre-registered "
            "revision — refusing to run the one-time evaluation on modified inputs"
        )


def _verify_runtime_environment(repo_root: Path, head: str) -> None:
    """Prove the numerical runtime matches the frozen, committed contract.

    The C1 gate binds the executing *code* to the authorized commit; this
    gate binds the executing *numerical environment* (CPython patch, cache
    tag, OS/arch, exact numpy/pandas/pyarrow, and the locked dependency
    graph) to :data:`CANONICAL_RUNTIME_CONTRACT_RELPATH`. The contract, the
    ``uv.lock``, and the ``pyproject.toml`` must equal their committed
    ``head`` bytes, and the active runtime must match the contract exactly.
    A single-repository reproducibility control, not a cryptographic
    attestation.
    """
    contract_path = repo_root / CANONICAL_RUNTIME_CONTRACT_RELPATH
    if contract_path.is_symlink():
        raise EvaluationError("the runtime contract must be a real tracked file, not a symlink")
    _require_bytes_match_head(repo_root, head, contract_path, "runtime contract")
    _require_bytes_match_head(repo_root, head, repo_root / "uv.lock", "uv.lock")
    _require_bytes_match_head(repo_root, head, repo_root / "pyproject.toml", "pyproject.toml")
    try:
        contract = load_runtime_contract(contract_path)
        verify_runtime_contract(contract, repo_root=repo_root)
    except RuntimeVerificationError as exc:
        raise EvaluationError(f"runtime verification failed: {exc}") from exc


def run_authorized_benchmark(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    protocol_path: str | Path,
    lock_path: str | Path,
    acquisition_evidence_path: str | Path,
    output_dir: str | Path,
    raw_chunk_dir: str | Path,
    derived_csv: str | Path,
    authorization: OneTimeTestAuthorization | None = None,
    ledger_path: str | Path | None = None,
    clock: Callable[[], pd.Timestamp] | None = None,
    overwrite: bool = False,
) -> BenchmarkRun:
    """Run the complete benchmark including the one-time test evaluation.

    Refused by default: ``authorization`` must be an explicit
    :class:`OneTimeTestAuthorization` carrying the confirmation token whose
    ``code_commit_sha`` equals the repository's actual ``HEAD``.

    The **first** gate is a package-source binding (C1): before the ledger
    is read, the dataset loaded, or any signal computed, the running
    ``eth_research`` code is proven to be exactly the ``src/eth_research``
    tree committed at the authorized ``HEAD`` — not a foreign clone,
    site-packages install, shadow module, or modified copy
    (:func:`eth_research.gitcheck.verify_package_source`). The **second**
    gate is a runtime-environment binding: the active CPython patch, cache
    tag, OS/architecture, exact ``numpy``/``pandas``/``pyarrow`` versions,
    and the committed ``uv.lock``/``pyproject.toml`` must equal the frozen
    contract at :data:`CANONICAL_RUNTIME_CONTRACT_RELPATH`
    (:func:`eth_research.environment.verify_runtime_contract`). Both are
    single-repository, single-researcher operational controls; neither
    attests a remote or a cryptographic identity.

    ``raw_chunk_dir`` and ``derived_csv`` are **mandatory**: the one-time
    run always re-derives the CSV from the raw chunks (C2), so acquisition
    verification can never be silently skipped. The remaining boundary
    (git-revision binding, canonical ledger, internal dataset reload, and
    honest ``started``/``completed``/``failed`` recording) is unchanged.
    """
    if authorization is None:
        raise EvaluationError(
            "test evaluation refused: no authorization was provided. The real test segment "
            "is evaluated exactly once, with an explicit OneTimeTestAuthorization."
        )
    try:
        root = resolve_repo_root(repo_root)
        head = head_commit(root)
    except GitError as exc:
        raise EvaluationError(f"could not establish the repository revision: {exc}") from exc

    # --- C1: prove the running code IS the code committed at HEAD, first. ---
    try:
        verify_package_source(root, head, _running_package_root())
    except GitError as exc:
        raise EvaluationError(f"package source binding failed: {exc}") from exc

    # --- Runtime: prove the numerical environment matches the frozen contract. ---
    _verify_runtime_environment(root, head)

    return _run_bound_benchmark(
        repo_root=repo_root,
        manifest_path=manifest_path,
        protocol_path=protocol_path,
        lock_path=lock_path,
        acquisition_evidence_path=acquisition_evidence_path,
        output_dir=output_dir,
        raw_chunk_dir=raw_chunk_dir,
        derived_csv=derived_csv,
        authorization=authorization,
        ledger_path=ledger_path,
        clock=clock,
        overwrite=overwrite,
    )


def _run_bound_benchmark(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    protocol_path: str | Path,
    lock_path: str | Path,
    acquisition_evidence_path: str | Path,
    output_dir: str | Path,
    raw_chunk_dir: str | Path,
    derived_csv: str | Path,
    authorization: OneTimeTestAuthorization | None = None,
    ledger_path: str | Path | None = None,
    clock: Callable[[], pd.Timestamp] | None = None,
    overwrite: bool = False,
) -> BenchmarkRun:
    """The authorized evaluation after the package-source binding has passed.

    Performs the git-revision identity + clean-tree checks, the canonical
    ledger and committed-bytes checks, the mandatory raw→derived
    acquisition verification, the internal dataset reload, and the
    guarded one-time run. Callers must go through
    :func:`run_authorized_benchmark`; this is separated only so the
    source-binding gate has dedicated tests (it is exercised in production
    exclusively through the public entry point).
    """
    if authorization is None:
        raise EvaluationError(
            "test evaluation refused: no authorization was provided. The real test segment "
            "is evaluated exactly once, with an explicit OneTimeTestAuthorization."
        )
    if raw_chunk_dir is None or derived_csv is None:
        raise EvaluationError(
            "the one-time evaluation requires both raw_chunk_dir and derived_csv so the "
            "derived CSV is always re-derived from the raw chunks; neither may be omitted"
        )
    tick = clock if clock is not None else _default_clock

    # --- R3: bind to the actual, clean, pre-registered git revision. ---
    try:
        root = resolve_repo_root(repo_root)
        head = head_commit(root)
    except GitError as exc:
        raise EvaluationError(f"could not establish the repository revision: {exc}") from exc
    if not is_commit_object(root, authorization.code_commit_sha):
        raise EvaluationError(
            f"authorization code_commit_sha {authorization.code_commit_sha!r} is not a real "
            "commit in this repository"
        )
    if authorization.code_commit_sha != head:
        raise EvaluationError(
            f"authorization code_commit_sha {authorization.code_commit_sha!r} is not the "
            f"repository HEAD {head!r}; the frozen evaluation must run from the pre-registered "
            "revision"
        )
    try:
        clean = tracked_tree_is_clean(root)
    except GitError as exc:
        raise EvaluationError(f"could not check the working tree: {exc}") from exc
    if not clean:
        raise EvaluationError(
            "the tracked working tree is not clean; commit or discard tracked changes before "
            "the one-time evaluation (ignored raw/canonical data may remain)"
        )

    # --- R2: the ledger is the canonical tracked file, not caller-selected. ---
    ledger = root / CANONICAL_LEDGER_RELPATH
    if ledger.is_symlink():
        raise EvaluationError(
            "the canonical test-access ledger must be a real tracked file, not a symlink"
        )
    try:
        relative_to_repo(root, ledger)  # resolved path must remain inside the repo
    except GitError as exc:
        raise EvaluationError(
            f"the canonical ledger resolves outside the repository: {exc}"
        ) from exc
    if ledger_path is not None and Path(ledger_path).resolve() != ledger.resolve():
        raise EvaluationError(
            f"ledger path {Path(ledger_path)} is not the canonical tracked ledger "
            f"{CANONICAL_LEDGER_RELPATH!r}; an alternate, copied, or path-outside-repo ledger "
            "is refused"
        )

    # --- R3: every tracked input must equal its committed bytes at HEAD. ---
    protocol_file = Path(protocol_path)
    lock_file = Path(lock_path)
    evidence_file = Path(acquisition_evidence_path)
    _require_bytes_match_head(root, head, protocol_file, "protocol")
    _require_bytes_match_head(root, head, lock_file, "dataset lock")
    _require_bytes_match_head(root, head, evidence_file, "acquisition evidence")
    _require_bytes_match_head(root, head, ledger, "test-access ledger")

    # --- R4: load lock/protocol from the verified bytes; reload the dataset. ---
    lock = load_dataset_lock(lock_file)
    try:
        protocol = BenchmarkProtocol.from_json_bytes(protocol_file.read_bytes())
    except ValueError as exc:
        raise EvaluationError(f"invalid protocol {protocol_file.name!r}: {exc}") from exc

    manifest, _evidence = verify_dataset_lock(
        lock,
        manifest_path=manifest_path,
        acquisition_evidence_path=evidence_file,
        raw_chunk_dir=raw_chunk_dir,
        derived_csv=derived_csv,
    )
    dataset = load_canonical_dataset(manifest_path)
    if dataset.manifest != manifest:
        raise EvaluationError("the reloaded dataset's manifest is not the manifest the lock pins")
    verify_protocol(protocol, lock)
    _verify_dataset_matches_protocol(dataset, protocol)
    _recheck_frame_fingerprint(dataset)
    if content_fingerprint(dataset.frame) != protocol.dataset_content_fingerprint:
        raise EvaluationError(
            "the reloaded frame's recomputed fingerprint is not the protocol's dataset "
            "fingerprint — refusing to run the one-time evaluation on unverified data"
        )

    protocol_sha = sha256_bytes(protocol.to_json_bytes())
    lock_sha = sha256_bytes(lock.to_json_bytes())

    events = read_ledger(ledger)
    consumed = accesses_for(events, dataset_lock_sha256=lock_sha, protocol_sha256=protocol_sha)
    if consumed:
        raise EvaluationError(
            f"test evaluation refused: the one-time access for this dataset lock and "
            f"protocol was already consumed by evaluation id {consumed[0].evaluation_id!r} "
            f"({consumed[0].event!r}). Design a new holdout protocol instead of rerunning."
        )
    if any(event.evaluation_id == authorization.evaluation_id for event in events):
        raise EvaluationError(
            f"test evaluation refused: evaluation id {authorization.evaluation_id!r} was "
            "already used; evaluation ids are single-use"
        )

    ledger_path = ledger
    directory = Path(output_dir)
    results_path = directory / RESULTS_FILENAME
    report_path = directory / REPORT_FILENAME
    existing = [path for path in (results_path, report_path) if path.exists()]
    if existing and not overwrite:
        names = ", ".join(path.name for path in existing)
        raise EvaluationError(
            f"refusing to start the one-time evaluation: existing report(s) {names} in "
            f"{directory} would not be overwritten. Resolve the output location first."
        )

    # Everything below is allowed pre-authorization: train/validation runs
    # and mechanical split bounds.
    train_validation = evaluate_train_validation(dataset, protocol)
    boundaries = split_boundaries(dataset, protocol)
    test_bounds = boundaries[2]

    def event_for(kind: str, **extra: str | None) -> LedgerEvent:
        return LedgerEvent(
            ledger_schema_version=1,
            event=kind,
            evaluation_id=authorization.evaluation_id,
            dataset_content_fingerprint=protocol.dataset_content_fingerprint,
            dataset_lock_sha256=lock_sha,
            protocol_sha256=protocol_sha,
            code_commit_sha=authorization.code_commit_sha,
            test_first_open_time=test_bounds.first_open_time,
            test_last_open_time=test_bounds.last_open_time,
            reason=authorization.reason,
            event_time_utc=tick(),
            result_report_sha256=extra.get("result_report_sha256"),
            failure_description=extra.get("failure_description"),
        )

    # The point of no return: record the access before any test signal exists.
    append_event(ledger_path, event_for(EVENT_STARTED))

    try:
        splits = _split(dataset, protocol)
        test_segments: list[SegmentMetrics] = []
        for strategy, context_bars in _strategies(protocol):
            context = _context_for(splits, "test", context_bars)
            test_segments.append(_run_segment(splits.test, context, strategy, protocol, "test"))
        # Canonical strategy-major order: interleave train/validation/test.
        by_strategy: dict[str, list[SegmentMetrics]] = {name: [] for name in RESULT_STRATEGY_NAMES}
        for entry in train_validation:
            by_strategy[entry.strategy].append(entry)
        for entry in test_segments:
            by_strategy[entry.strategy].append(entry)
        ordered = tuple(entry for name in RESULT_STRATEGY_NAMES for entry in by_strategy[name])
        results = build_benchmark_results(
            dataset,
            protocol,
            ordered,
            pre_registered_commit_sha=authorization.code_commit_sha,
            test_evaluation_id=authorization.evaluation_id,
        )
        markdown = render_benchmark_markdown(results)
        results_path, report_path = publish_benchmark_reports(
            results, markdown, directory, overwrite=overwrite
        )
    except BaseException as exc:
        description = f"{type(exc).__name__}: {exc}"[:500].strip() or type(exc).__name__
        append_event(ledger_path, event_for(EVENT_FAILED, failure_description=description))
        raise
    append_event(
        ledger_path,
        event_for(EVENT_COMPLETED, result_report_sha256=sha256_bytes(results.to_json_bytes())),
    )
    return BenchmarkRun(
        results=results,
        markdown=markdown,
        results_path=results_path,
        report_path=report_path,
    )


_LIMITATIONS: tuple[str, ...] = (
    "One venue (Coinbase Exchange) and one instrument (ETH-USD spot).",
    "One daily dataset; no intraday behaviour is observed.",
    "One fixed SMA parameterization (20/50); nothing was tuned, and nothing "
    "should be inferred about other parameters.",
    "Costs are a simplified constant: proportional fee plus constant "
    "directional slippage; there is no spread, impact, or liquidity model.",
    "Drawdown is measured on close-marked equity and misses intrabar troughs.",
    "Annualized Sharpe/Sortino assume serially independent per-bar returns.",
    "Historical results are research observations, not evidence of future profitability.",
)


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _ratio(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.3f}"


def render_benchmark_markdown(results: BenchmarkResults) -> str:
    """Render the report purely from the validated results model."""
    lines: list[str] = []
    add = lines.append
    add("# ETH benchmark report")
    add("")
    add(
        "> Research observations on historical data — **not** expected future "
        "returns, and not investment advice. A positive number here is not a "
        "profitability claim."
    )
    add("")
    add("## Dataset")
    add("")
    add(
        f"- Instrument: {results.base_asset}/{results.quote_asset} "
        f"({results.symbol!r}) — {results.market_type} on {results.venue!r}"
    )
    add(f"- Candle interval: {results.candle_interval} (open-time timestamps, UTC)")
    add(
        f"- Rows: {results.dataset_row_count} "
        f"({results.dataset_first_open_time.isoformat()} .. "
        f"{results.dataset_last_open_time.isoformat()})"
    )
    add(f"- Content fingerprint: `{results.dataset_content_fingerprint}`")
    add(f"- Manifest SHA-256: `{results.dataset_manifest_sha256}`")
    add(f"- Dataset lock SHA-256: `{results.dataset_lock_sha256}`")
    add(f"- Quality report SHA-256: `{results.quality_report_sha256}`")
    add(f"- Acquisition evidence SHA-256: `{results.acquisition_evidence_sha256}`")
    add("")
    add("## Quality warnings")
    add("")
    if results.quality_warnings:
        add("| code | count | first examples |")
        add("| --- | ---: | --- |")
        for warning in results.quality_warnings:
            examples = "; ".join(warning.first_examples) or "—"
            add(f"| `{warning.code}` | {warning.count} | {examples} |")
        add("")
        add(
            "Warnings are reported, inspected, and explained — never removed; "
            "the audit never repairs data."
        )
    else:
        add("No warning-severity findings.")
    add("")
    add("## Protocol")
    add("")
    add(f"- Protocol SHA-256: `{results.protocol_sha256}`")
    add(f"- Pre-registered code commit: `{results.pre_registered_commit_sha}`")
    add(
        "- Split: 60% train / 20% validation / 20% test, chronological, positional floor semantics."
    )
    add(
        "- Strategies: buy-and-hold (ex-ante entry at the first evaluated open) "
        "and SMA crossover (fast 20, slow 50) — fixed, never tuned."
    )
    add("- Costs: 10 bps fee plus 5 bps directional slippage per fill.")
    add(
        "- Initial cash: 10,000.00 USD **per segment** — each segment starts "
        "independently with the same initial cash and pays its own entry "
        "costs; segment equity curves are never stitched into a continuous "
        "portfolio."
    )
    add("- SMA warm-up context: 50 preceding bars (signals only, no P&L); buy-and-hold uses none.")
    add(
        "- Terminal positions are marked to market; hypothetical liquidation "
        "equity is reported separately."
    )
    add("- Annualization: 365.25-day year derived from the candle interval; risk-free rate 0.")
    add("")
    add("## Split boundaries")
    add("")
    add("| segment | first open | last open | bars |")
    add("| --- | --- | --- | ---: |")
    for split in results.splits:
        add(
            f"| {split.segment} | {split.first_open_time.isoformat()} | "
            f"{split.last_open_time.isoformat()} | {split.n_bars} |"
        )
    add("")
    add("## Results")
    add("")
    evaluated = sorted(
        {entry.segment for entry in results.segments}, key=_SEGMENT_ORDER.__getitem__
    )
    add(
        "| strategy | segment | bars | total return | CAGR | Sharpe | Sortino | "
        "max drawdown | terminal equity | liquidation equity | traded notional | "
        "turnover | fills |"
    )
    add(
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    for entry in results.segments:
        add(
            f"| {entry.strategy} | {entry.segment} | {entry.n_bars} | "
            f"{_pct(entry.total_return)} | {_pct(entry.cagr)} | {_ratio(entry.sharpe)} | "
            f"{_ratio(entry.sortino)} | {_pct(entry.max_drawdown)} | "
            f"{_money(entry.terminal_equity)} | {_money(entry.terminal_liquidation_equity)} | "
            f"{_money(entry.total_traded_notional)} | {entry.turnover:.3f} | "
            f"{entry.num_fills} |"
        )
    add("")
    add("### SMA (20/50) versus buy-and-hold, after costs")
    add("")
    add("| segment | buy-and-hold return | SMA return | difference |")
    add("| --- | ---: | ---: | ---: |")
    by_key = {(entry.strategy, entry.segment): entry for entry in results.segments}
    for segment in evaluated:
        bnh = by_key[("buy_and_hold", segment)]
        sma = by_key[("sma_20_50", segment)]
        difference = sma.total_return - bnh.total_return
        add(
            f"| {segment} | {_pct(bnh.total_return)} | {_pct(sma.total_return)} | "
            f"{_pct(difference)} |"
        )
    add("")
    add("## Test-set discipline")
    add("")
    if results.test_evaluation_id is not None:
        add(
            f"The test segment was evaluated **exactly once**, under pre-registered "
            f"evaluation id `{results.test_evaluation_id}` recorded in the append-only "
            f"test-access ledger, at code commit "
            f"`{results.pre_registered_commit_sha}`."
        )
    else:
        add(
            "The test segment has **not** been evaluated: these are train and "
            "validation observations only."
        )
    add("")
    add("## Limitations")
    add("")
    for limitation in _LIMITATIONS:
        add(f"- {limitation}")
    add("")
    return "\n".join(lines)
