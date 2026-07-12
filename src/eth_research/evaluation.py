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

import hashlib
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
from eth_research.data.lock import DatasetLock, load_dataset_lock, verify_dataset_lock
from eth_research.data.provenance import (
    content_fingerprint,
    require_nonempty_str,
    sha256_bytes,
)
from eth_research.data.validation import (
    require_commit_sha,
    require_evaluation_id,
)
from eth_research.decision import (
    ELIGIBLE_FOR_TEST_PROMOTION,
    ResearchDecision,
    build_research_decision_from_results,
    render_research_decision,
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
from eth_research.holdout import (
    HoldoutConflict,
    HoldoutIdentity,
    build_holdout_identity,
    find_holdout_conflicts,
)
from eth_research.ledger import (
    EVENT_COMPLETED,
    EVENT_FAILED,
    EVENT_STARTED,
    LEDGER_SCHEMA_VERSION,
    LedgerEvent,
    append_event,
    read_ledger,
)
from eth_research.metrics import PerformanceSummary, summarize
from eth_research.protocol import (
    BUY_AND_HOLD_STRATEGY,
    RESULT_STRATEGY_NAMES,
    RESULTS_SCHEMA_VERSION,
    BenchmarkProtocol,
    BenchmarkResults,
    QualityWarningSummary,
    SegmentMetrics,
    SplitBoundary,
    verify_protocol,
)
from eth_research.provenance_v2 import ProvenanceV2Error, verify_provenance_graph
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

_RESULT_BUNDLE_HEADER: bytes = b"eth-research result-bundle-v1\n"


def compute_result_bundle_sha256(results_json: bytes, report_markdown: bytes) -> str:
    """Domain-separated SHA-256 binding the results JSON and report Markdown.

    A single hash over both published artifacts, so the ledger's completed
    event pins the *bundle*, not just the authoritative JSON. Hashing the
    two component digests (rather than concatenating the blobs) keeps the
    boundary between them unambiguous.
    """
    hasher = hashlib.sha256()
    hasher.update(_RESULT_BUNDLE_HEADER)
    hasher.update(f"{sha256_bytes(results_json)}|{sha256_bytes(report_markdown)}\n".encode("ascii"))
    return hasher.hexdigest()


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
    protocol_registration_commit_sha: str,
    test_evaluation_id: str | None,
    authorized_evaluation_code_commit_sha: str | None = None,
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
        results_schema_version=RESULTS_SCHEMA_VERSION,
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
        protocol_registration_commit_sha=protocol_registration_commit_sha,
        authorized_evaluation_code_commit_sha=authorized_evaluation_code_commit_sha,
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
            f"{label} {relpath!r} is not committed at the authorized revision: {exc}"
        ) from exc
    if path.read_bytes() != committed:
        raise EvaluationError(
            f"{label} {relpath!r} differs from its bytes committed at the authorized "
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


FROZEN_DOSSIER_RELPATH: str = "research/m2b/provenance_v2.json"
"""The committed provenance/dossier manifest every access is bound to."""
HOLDOUT_IDENTITY_RELPATH: str = "research/m2b/holdout_identity.json"
VALIDATION_DECISION_RELPATH: str = "research/m2b/validation_decision.json"
VALIDATION_DECISION_MD_RELPATH: str = "research/m2b/validation_decision.md"


@dataclass(frozen=True)
class PreparedEvaluation:
    """The frozen, fully verified context every pre-ledger check produced.

    Built exclusively by :func:`prepare_authorized_evaluation` — the single
    shared preparation implementation behind both the production evaluator
    and the read-only readiness command. Contains only verified models,
    hashes, and states; never a test signal, return, or metric.
    """

    repo_root: Path
    head: str
    protocol: BenchmarkProtocol
    lock: DatasetLock
    dataset: LoadedDataset
    holdout: HoldoutIdentity
    events: tuple[LedgerEvent, ...]
    conflicts: tuple[HoldoutConflict, ...]
    decision: ResearchDecision
    train_validation: tuple[SegmentMetrics, ...]
    ledger_path: Path
    protocol_sha256: str
    lock_sha256: str
    runtime_contract_sha256: str
    frozen_dossier_sha256: str
    holdout_identity_sha256: str
    validation_decision_sha256: str
    train_validation_results_sha256: str
    protocol_registration_commit_sha: str
    output_collision: bool

    @property
    def holdout_fresh(self) -> bool:
        """No recorded access conflicts with this holdout."""
        return not self.conflicts

    @property
    def promotion_eligible(self) -> bool:
        """The committed, re-derived scientific decision permits promotion."""
        return self.decision.decision == ELIGIBLE_FOR_TEST_PROMOTION


def prepare_authorized_evaluation(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    protocol_path: str | Path,
    lock_path: str | Path,
    acquisition_evidence_path: str | Path,
    output_dir: str | Path,
    raw_chunk_dir: str | Path,
    derived_csv: str | Path,
    running_package_root: Path,
    authorization_commit: str | None,
    overwrite: bool = False,
) -> PreparedEvaluation:
    """The one side-effect-free preparation path behind every pre-ledger check.

    Both public entry points call exactly this function: the production
    evaluator (with ``authorization_commit`` set) and the read-only
    readiness command (with ``authorization_commit=None``). It mutates
    nothing — no ledger append, no publication — and performs, in order:

    1. resolve the real repository root and real ``HEAD``;
    2. (production) require the authorization revision to name a real
       commit equal to ``HEAD``;
    3. verify the running package source equals ``src/eth_research`` at
       ``HEAD``;
    4. verify the frozen runtime contract and committed lockfiles;
    5. require a clean tracked tree;
    6. require canonical, non-symlinked, committed-at-``HEAD`` tracked
       inputs (protocol, lock, evidence, ledger, holdout identity,
       train/validation results + report, validation decision JSON + MD);
    7. read the canonical ledger strictly;
    8. parse the committed validation decision and — in production mode —
       refuse a non-eligible verdict *before any strategy, signal, or
       backtest exists* (a forged "eligible" verdict is re-proven and
       refused at step 14, still before any ledger append);
    9. run the complete provenance-graph verifier;
    10. semantically reconstruct the raw responses into the derived OHLCV
        data and verify the dataset lock + evidence chain;
    11. load the canonical dataset internally and recompute its content
        fingerprint against the protocol/lock bindings;
    12. recompute the :class:`HoldoutIdentity` from the verified dataset +
        protocol and require exact byte equality with the committed
        ``holdout_identity.json``;
    13. run the holdout conflict policy against the canonical ledger and
        check output collisions (both refuse, in production mode, before
        any engine work);
    14. regenerate the train/validation-only results and report and require
        exact byte equality with the committed artifacts, then rebuild the
        validation decision from those exact results and require exact byte
        equality with the committed decision JSON and Markdown;
    15. return the immutable prepared context.
    """
    production = authorization_commit is not None
    if raw_chunk_dir is None or derived_csv is None:
        raise EvaluationError(
            "preparation requires both raw_chunk_dir and derived_csv so the derived CSV is "
            "always re-derived from the raw chunks; neither may be omitted"
        )

    # 1. The real repository and revision.
    try:
        root = resolve_repo_root(repo_root)
        head = head_commit(root)
    except GitError as exc:
        raise EvaluationError(f"could not establish the repository revision: {exc}") from exc

    # 2. Production only: the authorized revision names this exact HEAD.
    if authorization_commit is not None:
        if not is_commit_object(root, authorization_commit):
            raise EvaluationError(
                f"authorization code_commit_sha {authorization_commit!r} is not a real "
                "commit in this repository"
            )
        if authorization_commit != head:
            raise EvaluationError(
                f"authorization code_commit_sha {authorization_commit!r} is not the "
                f"repository HEAD {head!r}; the authorized evaluation must run from the "
                "explicitly authorized revision"
            )

    # 3. The running package is the source committed at HEAD (C1).
    try:
        verify_package_source(root, head, running_package_root)
    except GitError as exc:
        raise EvaluationError(f"package source binding failed: {exc}") from exc

    # 4. The frozen numerical runtime and committed lockfiles.
    _verify_runtime_environment(root, head)

    # 5. A clean tracked tree.
    try:
        clean = tracked_tree_is_clean(root)
    except GitError as exc:
        raise EvaluationError(f"could not check the working tree: {exc}") from exc
    if not clean:
        raise EvaluationError(
            "the tracked working tree is not clean; commit or discard tracked changes before "
            "the one-time evaluation (ignored raw/canonical data may remain)"
        )

    # 6-7. Canonical, committed-at-HEAD inputs and the canonical ledger.
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

    protocol_file = Path(protocol_path)
    lock_file = Path(lock_path)
    evidence_file = Path(acquisition_evidence_path)
    holdout_file = root / HOLDOUT_IDENTITY_RELPATH
    decision_file = root / VALIDATION_DECISION_RELPATH
    decision_md_file = root / VALIDATION_DECISION_MD_RELPATH
    _require_bytes_match_head(root, head, protocol_file, "protocol")
    _require_bytes_match_head(root, head, lock_file, "dataset lock")
    _require_bytes_match_head(root, head, evidence_file, "acquisition evidence")
    _require_bytes_match_head(root, head, ledger, "test-access ledger")
    _require_bytes_match_head(root, head, holdout_file, "holdout identity")
    _require_bytes_match_head(root, head, decision_file, "validation decision")
    _require_bytes_match_head(root, head, decision_md_file, "validation decision report")
    events = read_ledger(ledger)

    # 8. The committed scientific decision gates production before ANY
    # strategy, signal, or backtest — including the permitted
    # train/validation regeneration below.
    try:
        committed_decision = ResearchDecision.from_json_bytes(decision_file.read_bytes())
    except ValueError as exc:
        raise EvaluationError(f"invalid committed validation decision: {exc}") from exc
    if production and committed_decision.decision != ELIGIBLE_FOR_TEST_PROMOTION:
        raise EvaluationError(
            "test evaluation refused: the committed validation decision records "
            f"{committed_decision.decision!r} for {committed_decision.subject!r}. The "
            "candidate is scientifically ineligible for the one-time test; a runtime "
            "authorization object cannot override the recorded decision."
        )

    # 9. The complete provenance graph — never optional, in either mode.
    try:
        verify_provenance_graph(root).raise_for_status()
    except ProvenanceV2Error as exc:
        raise EvaluationError(f"provenance graph verification failed: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise EvaluationError(f"provenance graph could not be verified: {exc}") from exc

    # 10. Lock + evidence + semantic raw→derived reconstruction.
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

    # 11. Internal dataset reload + fingerprint/protocol bindings.
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

    # 12. The committed holdout identity must recompute exactly from the
    # verified dataset + protocol — hashing the file is not enough.
    holdout = build_holdout_identity(dataset, protocol)
    if holdout.to_json_bytes() != holdout_file.read_bytes():
        raise EvaluationError(
            "the committed holdout_identity.json does not recompute from the verified "
            "dataset and protocol — refusing to treat a hand-edited holdout identity as "
            "the sealed one"
        )

    # 13. Freshness and output collisions — refused (in production) before
    # any engine work, so no refusal ever runs a strategy or backtest.
    conflicts = find_holdout_conflicts(events, holdout)
    if production and conflicts:
        first = conflicts[0]
        raise EvaluationError(
            f"test evaluation refused: this holdout was already consumed by evaluation id "
            f"{first.evaluation_id!r} ({first.event!r}) — {'; '.join(first.reasons)}. The "
            "one-time test holdout is permanently consumed; changing the protocol, lock, "
            "package version, schema, evaluation id, commit, or wording does not restore it. "
            "Design a genuinely new, non-overlapping holdout instead."
        )
    directory = Path(output_dir)
    existing = [
        path
        for path in (directory / RESULTS_FILENAME, directory / REPORT_FILENAME)
        if path.exists()
    ]
    output_collision = bool(existing)
    if production and existing and not overwrite:
        names = ", ".join(path.name for path in existing)
        raise EvaluationError(
            f"refusing to start the one-time evaluation: existing report(s) {names} in "
            f"{directory} would not be overwritten. Resolve the output location first."
        )

    # 14. Development evidence must regenerate byte-for-byte: the
    # train/validation results, the report, and the research decision are
    # re-derived and compared against the committed artifacts, so a forged
    # verdict or edited number can never survive to the ledger boundary.
    from eth_research import m2b_report  # local import: m2b_report imports this module

    registration = m2b_report.committed_protocol_registration_commit(root)
    if not is_commit_object(root, registration):
        raise EvaluationError(
            f"the recorded protocol-registration commit {registration!r} is not a real "
            "commit in this repository"
        )
    train_validation = evaluate_train_validation(dataset, protocol)
    results = build_benchmark_results(
        dataset,
        protocol,
        train_validation,
        protocol_registration_commit_sha=registration,
        test_evaluation_id=None,
    )
    if results.to_json_bytes() != (root / m2b_report.RESULTS_RELPATH).read_bytes():
        raise EvaluationError(
            "the committed train/validation results do not regenerate byte-for-byte from "
            "the verified dataset and protocol"
        )
    if m2b_report.render_report(root, results) != (root / m2b_report.REPORT_RELPATH).read_text(
        encoding="utf-8"
    ):
        raise EvaluationError(
            "the committed train/validation report does not regenerate byte-for-byte from "
            "the regenerated results"
        )
    rebuilt_decision = build_research_decision_from_results(results)
    if rebuilt_decision.to_json_bytes() != decision_file.read_bytes():
        raise EvaluationError(
            "the committed validation decision does not rebuild byte-for-byte from the "
            "regenerated results — an edited verdict or number cannot authorize anything"
        )
    if render_research_decision(rebuilt_decision) != decision_md_file.read_text(encoding="utf-8"):
        raise EvaluationError(
            "the committed validation decision report does not rebuild byte-for-byte from "
            "the decision model"
        )

    return PreparedEvaluation(
        repo_root=root,
        head=head,
        protocol=protocol,
        lock=lock,
        dataset=dataset,
        holdout=holdout,
        events=events,
        conflicts=conflicts,
        decision=rebuilt_decision,
        train_validation=train_validation,
        ledger_path=ledger,
        protocol_sha256=sha256_bytes(protocol.to_json_bytes()),
        lock_sha256=sha256_bytes(lock.to_json_bytes()),
        runtime_contract_sha256=sha256_bytes(
            (root / CANONICAL_RUNTIME_CONTRACT_RELPATH).read_bytes()
        ),
        frozen_dossier_sha256=sha256_bytes((root / FROZEN_DOSSIER_RELPATH).read_bytes()),
        holdout_identity_sha256=sha256_bytes(holdout_file.read_bytes()),
        validation_decision_sha256=sha256_bytes(decision_file.read_bytes()),
        train_validation_results_sha256=sha256_bytes(
            (root / m2b_report.RESULTS_RELPATH).read_bytes()
        ),
        protocol_registration_commit_sha=registration,
        output_collision=output_collision,
    )


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

    Every pre-ledger verification runs through
    :func:`prepare_authorized_evaluation` — the same single implementation
    the read-only readiness command uses, so production and readiness can
    never drift. The production-only steps after preparation are: the
    explicit confirmation token (validated at construction), the scientific
    eligibility gate, the single-use evaluation id, ``started``, the test
    segments, transactional publication with read-back verification, and
    ``completed``.
    """
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
        running_package_root=_running_package_root(),
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
    running_package_root: Path,
    authorization: OneTimeTestAuthorization | None = None,
    ledger_path: str | Path | None = None,
    clock: Callable[[], pd.Timestamp] | None = None,
    overwrite: bool = False,
) -> BenchmarkRun:
    """The authorized evaluation around the shared preparation path.

    Callers must go through :func:`run_authorized_benchmark`, which binds
    ``running_package_root`` to the interpreter's actual import location;
    this seam exists so the synthetic fixture repositories (which commit
    their own copy of the package source) can exercise the identical
    preparation path end-to-end.
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

    # The caller may not select an alternate ledger; the canonical tracked
    # file is resolved (and re-verified) inside the shared preparation.
    try:
        canonical_ledger = resolve_repo_root(repo_root) / CANONICAL_LEDGER_RELPATH
    except GitError as exc:
        raise EvaluationError(f"could not establish the repository revision: {exc}") from exc
    if ledger_path is not None and Path(ledger_path).resolve() != canonical_ledger.resolve():
        raise EvaluationError(
            f"ledger path {Path(ledger_path)} is not the canonical tracked ledger "
            f"{CANONICAL_LEDGER_RELPATH!r}; an alternate, copied, or path-outside-repo ledger "
            "is refused"
        )

    prepared = prepare_authorized_evaluation(
        repo_root=repo_root,
        manifest_path=manifest_path,
        protocol_path=protocol_path,
        lock_path=lock_path,
        acquisition_evidence_path=acquisition_evidence_path,
        output_dir=output_dir,
        raw_chunk_dir=raw_chunk_dir,
        derived_csv=derived_csv,
        running_package_root=running_package_root,
        authorization_commit=authorization.code_commit_sha,
        overwrite=overwrite,
    )
    if not prepared.promotion_eligible:  # defense in depth; prepare already refused
        raise EvaluationError(
            "test evaluation refused: the verified validation decision does not record "
            "eligible_for_test_promotion"
        )
    if any(event.evaluation_id == authorization.evaluation_id for event in prepared.events):
        raise EvaluationError(
            f"test evaluation refused: evaluation id {authorization.evaluation_id!r} was "
            "already used; evaluation ids are single-use"
        )

    dataset = prepared.dataset
    protocol = prepared.protocol
    holdout = prepared.holdout
    train_validation = prepared.train_validation
    protocol_sha = prepared.protocol_sha256
    lock_sha = prepared.lock_sha256
    runtime_sha = prepared.runtime_contract_sha256
    ledger_path = prepared.ledger_path
    directory = Path(output_dir)
    results_path = directory / RESULTS_FILENAME
    report_path = directory / REPORT_FILENAME

    def event_for(kind: str, **extra: str | None) -> LedgerEvent:
        return LedgerEvent(
            ledger_schema_version=LEDGER_SCHEMA_VERSION,
            event=kind,
            evaluation_id=authorization.evaluation_id,
            holdout_id=holdout.holdout_id,
            dataset_content_fingerprint=holdout.dataset_content_fingerprint,
            test_content_fingerprint=holdout.test_content_fingerprint,
            symbol=holdout.symbol,
            venue=holdout.venue,
            candle_interval=holdout.candle_interval,
            test_first_open_time=holdout.test_first_open_time,
            test_last_open_time=holdout.test_last_open_time,
            test_row_count=holdout.test_row_count,
            dataset_lock_sha256=lock_sha,
            protocol_sha256=protocol_sha,
            runtime_contract_sha256=runtime_sha,
            frozen_dossier_sha256=prepared.frozen_dossier_sha256,
            holdout_identity_sha256=prepared.holdout_identity_sha256,
            validation_decision_sha256=prepared.validation_decision_sha256,
            train_validation_results_sha256=prepared.train_validation_results_sha256,
            protocol_registration_commit_sha=prepared.protocol_registration_commit_sha,
            authorized_evaluation_code_commit_sha=authorization.code_commit_sha,
            reason=authorization.reason,
            event_time_utc=tick(),
            results_json_sha256=extra.get("results_json_sha256"),
            report_markdown_sha256=extra.get("report_markdown_sha256"),
            result_bundle_sha256=extra.get("result_bundle_sha256"),
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
            protocol_registration_commit_sha=prepared.protocol_registration_commit_sha,
            test_evaluation_id=authorization.evaluation_id,
            authorized_evaluation_code_commit_sha=authorization.code_commit_sha,
        )
        markdown = render_benchmark_markdown(results)
        results_path, report_path = publish_benchmark_reports(
            results, markdown, directory, overwrite=overwrite
        )
        # Verify-after-publish: read both files back and confirm they are
        # exactly the validated model before recording completion. Any failure
        # after 'started' — including this one — leaves the holdout consumed.
        results_bytes = results.to_json_bytes()
        report_bytes = markdown.encode("utf-8")
        if results_path.read_bytes() != results_bytes:
            raise EvaluationError(
                "published results JSON does not match the validated model after publication"
            )
        if report_path.read_bytes() != report_bytes:
            raise EvaluationError(
                "published report does not match the rendered model after publication"
            )
        if BenchmarkResults.from_json_bytes(results_bytes).to_json_bytes() != results_bytes:
            raise EvaluationError("published results JSON does not round-trip")
        completed_event = event_for(
            EVENT_COMPLETED,
            results_json_sha256=sha256_bytes(results_bytes),
            report_markdown_sha256=sha256_bytes(report_bytes),
            result_bundle_sha256=compute_result_bundle_sha256(results_bytes, report_bytes),
        )
    except BaseException as exc:
        description = f"{type(exc).__name__}: {exc}"[:500].strip() or type(exc).__name__
        append_event(ledger_path, event_for(EVENT_FAILED, failure_description=description))
        raise
    append_event(ledger_path, completed_event)
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


def _pp(value: float) -> str:
    """A gap between two return percentages, in percentage points (not a ratio)."""
    return f"{value * 100:+.2f} pp"


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
    add(f"- Protocol registration commit: `{results.protocol_registration_commit_sha}`")
    if results.authorized_evaluation_code_commit_sha is not None:
        add(
            "- Authorized evaluation code commit: "
            f"`{results.authorized_evaluation_code_commit_sha}`"
        )
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
    add(
        "The difference column is the arithmetic gap between the two return "
        "percentages, in percentage points (pp) — not a ratio and not a "
        "percentage of buy-and-hold."
    )
    add("")
    add("| segment | buy-and-hold return | SMA return | difference (pp) |")
    add("| --- | ---: | ---: | ---: |")
    by_key = {(entry.strategy, entry.segment): entry for entry in results.segments}
    for segment in evaluated:
        bnh = by_key[("buy_and_hold", segment)]
        sma = by_key[("sma_20_50", segment)]
        difference = sma.total_return - bnh.total_return
        add(
            f"| {segment} | {_pct(bnh.total_return)} | {_pct(sma.total_return)} | "
            f"{_pp(difference)} |"
        )
    add("")
    add("## Test-set discipline")
    add("")
    if results.test_evaluation_id is not None:
        add(
            f"The test segment was evaluated **exactly once**, under evaluation id "
            f"`{results.test_evaluation_id}` recorded in the append-only test-access "
            f"ledger, at authorized evaluation code commit "
            f"`{results.authorized_evaluation_code_commit_sha}` (protocol registered at "
            f"`{results.protocol_registration_commit_sha}`)."
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
