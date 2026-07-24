"""Shared fixtures for the test suite."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

import eth_research
from eth_research.data.acquisition_plan import (
    AcquisitionAttemptReceipt,
    AcquisitionRequestPlan,
    AcquisitionResponseReceipt,
    build_acquisition_plan,
)
from eth_research.data.builder import BuildResult, build_canonical_dataset
from eth_research.data.coinbase import (
    AcquisitionEvidence,
    ChunkRequest,
    derive_daily_ohlcv,
    write_acquisition_evidence,
)
from eth_research.data.lock import DatasetLock
from eth_research.data.provenance import DatasetIdentity, sha256_bytes, sha256_file
from eth_research.data.synthetic import make_synthetic_ohlcv
from eth_research.protocol import BenchmarkProtocol

if TYPE_CHECKING:
    from eth_research.m3d.receipt import ProspectiveAttemptReceipt
    from eth_research.m3e.proposal import AssembledProposal


@pytest.fixture
def synthetic_daily() -> pd.DataFrame:
    """400 daily bars of deterministic synthetic ETH-like data."""
    return make_synthetic_ohlcv(n_periods=400, seed=7)


def _build_frame(opens: Sequence[float], closes: Sequence[float]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(closes), freq="1D", tz="UTC", name="timestamp")
    open_array = np.asarray(list(opens), dtype=float)
    close_array = np.asarray(list(closes), dtype=float)
    high = np.maximum(open_array, close_array) * 1.01
    low = np.minimum(open_array, close_array) * 0.99
    return pd.DataFrame(
        {
            "open": open_array,
            "high": high,
            "low": low,
            "close": close_array,
            "volume": np.full(len(close_array), 1_000.0),
        },
        index=index,
    )


@pytest.fixture
def frame_from_bars() -> Callable[[Sequence[tuple[float, float]]], pd.DataFrame]:
    """Factory for a valid OHLCV frame with exactly the given (open, close) bars.

    Lets tests hand-compute expected fills and equity from known prices,
    including overnight gaps (open != previous close).
    """

    def build(bars: Sequence[tuple[float, float]]) -> pd.DataFrame:
        return _build_frame([bar[0] for bar in bars], [bar[1] for bar in bars])

    return build


@pytest.fixture
def frame_from_closes() -> Callable[[Sequence[float]], pd.DataFrame]:
    """Factory for a gapless frame with the given closes (open = previous close)."""

    def build(closes: Sequence[float]) -> pd.DataFrame:
        opens = [closes[0], *closes[:-1]]
        return _build_frame(opens, closes)

    return build


@dataclass(frozen=True)
class CoinbasePipeline:
    """A synthetic end-to-end fixture: chunks -> derived CSV -> canonical dataset.

    Everything here is deterministic synthetic data explicitly labelled as
    such in the dataset identity's ``source``; it exists so the Milestone 2B
    provenance/evaluation chain can be exercised without any real market
    data.
    """

    chunk_dir: Path
    derived_csv: Path
    evidence: AcquisitionEvidence
    evidence_path: Path
    build: BuildResult
    identity: DatasetIdentity
    plan: AcquisitionRequestPlan
    receipt: AcquisitionAttemptReceipt

    @property
    def manifest_sha256(self) -> str:
        return sha256_file(self.build.manifest_path)

    @property
    def evidence_sha256(self) -> str:
        return sha256_file(self.evidence_path)


def _synthetic_coinbase_rows(
    start: pd.Timestamp,
    days: int,
    *,
    first_row_index: int,
    price_shift_from_row: int | None,
    decline_from_row: int | None = None,
) -> list[list[float | int]]:
    """Deterministic plausible daily candles in Coinbase field order (ascending).

    ``decline_from_row`` switches to a steady downtrend from that row
    position onward — used to build a fixture whose fixed SMA beats
    buy-and-hold in validation (buy-and-hold rides the decline; the
    crossover goes to cash), so the derived research decision is *eligible*.
    """
    rows: list[list[float | int]] = []
    for i in range(days):
        row_index = first_row_index + i
        if decline_from_row is not None and row_index >= decline_from_row:
            open_ = 100.0 - (row_index - decline_from_row) * 1.5
            close = open_ - 1.0
        else:
            shift = (
                5.0
                if price_shift_from_row is not None and row_index >= price_shift_from_row
                else 0.0
            )
            open_ = 100.0 + (row_index % 17) - (row_index % 5) + shift
            close = open_ + ((row_index % 3) - 1) * 2.0
        high = max(open_, close) + 1.5
        low = min(open_, close) - 1.25
        volume = 10.0 + (row_index % 7)
        time_s = int(start.as_unit("ns").value) // 10**9 + i * 86_400
        rows.append([time_s, low, high, open_, close, volume])
    return rows


def build_coinbase_pipeline(
    root: Path,
    *,
    price_shift_from_row: int | None = None,
    decline_from_row: int | None = None,
    attempt_id: str = "coinbase-eth-usd-001",
) -> CoinbasePipeline:
    """120 synthetic days frozen through the full acquisition -> M2A chain.

    ``price_shift_from_row`` shifts prices from that row position onward —
    used to build a dataset that differs from the default *only* in later
    rows (e.g. only inside the test segment) for invariance proofs.
    ``decline_from_row`` switches to a steady downtrend from that position
    (see :func:`_synthetic_coinbase_rows`). The raw bodies are named by a
    real :class:`AcquisitionRequestPlan` and bound by a synthetic attempt
    receipt so a fixture repository can carry the complete dossier chain.
    """
    root.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp("2024-01-01", tz="UTC")
    total_days = 120
    chunk_days = 60
    plan = build_acquisition_plan(
        overall_start=start,
        overall_end=start + pd.Timedelta(days=total_days),
        max_window_days=chunk_days,
        filename_prefix="synthetic-eth-usd-1d",
    )
    chunk_dir = root / "raw"
    chunk_dir.mkdir()
    requests: list[ChunkRequest] = []
    responses: list[AcquisitionResponseReceipt] = []
    retrieved = pd.Timestamp("2026-07-11T12:00:00+00:00")
    for window in plan.windows:
        position = (window.window_start - start).days
        rows = _synthetic_coinbase_rows(
            window.window_start,
            (window.window_end - window.window_start).days,
            first_row_index=position,
            price_shift_from_row=price_shift_from_row,
            decline_from_row=decline_from_row,
        )
        path = chunk_dir / window.filename
        raw = json.dumps(rows).encode("ascii")
        path.write_bytes(raw)
        requests.append(
            ChunkRequest(
                path=path,
                window_start=window.window_start,
                window_end=window.window_end,
                requested_start=window.requested_start,
                requested_end=window.requested_end,
                retrieved_at=retrieved,
            )
        )
        responses.append(
            AcquisitionResponseReceipt(
                ordinal=window.ordinal,
                filename=window.filename,
                http_status=200,
                byte_length=len(raw),
                sha256=sha256_bytes(raw),
                retrieved_at=retrieved,
                content_type="application/json",
            )
        )
    receipt = AcquisitionAttemptReceipt(
        receipt_schema_version=1,
        package_version=eth_research.__version__,
        plan_sha256=plan.plan_sha256(),
        attempt_id=attempt_id,
        workflow_run_id="0000000000",
        source_commit="0" * 40,
        curl_version="synthetic fixture (no networking)",
        runner="synthetic fixture",
        user_agent=plan.user_agent,
        responses=tuple(responses),
    )
    derived_csv = root / "synthetic-eth-usd-daily.csv"
    evidence = derive_daily_ohlcv(
        requests,
        overall_start=start,
        overall_end=start + pd.Timedelta(days=total_days),
        output_csv=derived_csv,
    )
    evidence_path = root / "acquisition_evidence.json"
    write_acquisition_evidence(evidence, evidence_path)
    identity = DatasetIdentity(
        quote_asset="USD",
        symbol="ETH-USD",
        venue="coinbase-exchange",
        interval=pd.Timedelta(days=1),
        source="synthetic fixture — deterministic fake candles, not real market data",
    )
    build = build_canonical_dataset(derived_csv, identity, root / "datasets")
    return CoinbasePipeline(
        chunk_dir=chunk_dir,
        derived_csv=derived_csv,
        evidence=evidence,
        evidence_path=evidence_path,
        build=build,
        identity=identity,
        plan=plan,
        receipt=receipt,
    )


@pytest.fixture
def coinbase_pipeline(tmp_path: Path) -> CoinbasePipeline:
    return build_coinbase_pipeline(tmp_path)


# --- Synthetic git repository carrying the complete committed dossier --------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@dataclass
class GitPipeline:
    """An isolated git repo with the complete committed M2B dossier.

    Carries everything the shared authorization-preparation path verifies:
    the package source copy, lockfiles, acquisition plan + receipt +
    plan-named raw bodies, a synthetic discovery chain, evidence, manifest
    and quality byte anchors, dataset lock, runtime contract, holdout
    identity, train/validation results + report, the derived research
    decision, the provenance anchor, and an empty ledger.
    """

    repo_root: Path
    manifest_path: Path
    protocol_path: Path
    lock_path: Path
    evidence_path: Path
    ledger_path: Path
    output_dir: Path
    raw_chunk_dir: Path
    derived_csv: Path
    head: str
    registration_head: str
    protocol: BenchmarkProtocol
    lock: DatasetLock

    @property
    def package_source_root(self) -> Path:
        """The fixture's committed copy of ``src/eth_research``."""
        return self.repo_root / "src" / "eth_research"


def _write_synthetic_discovery(repo: Path, research: Path) -> None:
    """A one-window discovery chain proving the synthetic start choice."""
    discovery_plan = build_acquisition_plan(
        overall_start=pd.Timestamp("2023-12-01", tz="UTC"),
        overall_end=pd.Timestamp("2024-01-31", tz="UTC"),
        filename_prefix="synthetic-discovery-1d",
    )
    (research / "discovery_plan.json").write_bytes(discovery_plan.to_json_bytes())
    window = discovery_plan.windows[0]
    rows = _synthetic_coinbase_rows(
        pd.Timestamp("2024-01-01", tz="UTC"), 30, first_row_index=0, price_shift_from_row=None
    )
    raw = json.dumps(rows).encode("ascii")
    attempt = research / "raw" / "coinbase" / "discovery-001"
    attempt.mkdir(parents=True)
    (attempt / window.filename).write_bytes(raw)
    receipt = AcquisitionAttemptReceipt(
        receipt_schema_version=1,
        package_version=eth_research.__version__,
        plan_sha256=discovery_plan.plan_sha256(),
        attempt_id="discovery-001",
        workflow_run_id="0000000000",
        source_commit="0" * 40,
        curl_version="synthetic fixture (no networking)",
        runner="synthetic fixture",
        user_agent=discovery_plan.user_agent,
        responses=(
            AcquisitionResponseReceipt(
                ordinal=0,
                filename=window.filename,
                http_status=200,
                byte_length=len(raw),
                sha256=sha256_bytes(raw),
                retrieved_at=pd.Timestamp("2026-07-11T12:00:00+00:00"),
                content_type="application/json",
            ),
        ),
    )
    (attempt / "acquisition_receipt.json").write_bytes(receipt.to_json_bytes())


def make_git_pipeline(root: Path, *, eligible: bool = True) -> GitPipeline:
    """Build, commit, and freeze a complete synthetic dossier repository.

    ``eligible=True`` (the default) uses the validation-downtrend data so
    the deterministically derived research decision is
    ``eligible_for_test_promotion`` — required by tests that exercise the
    post-authorization machinery. ``eligible=False`` keeps the oscillating
    data whose fixed SMA underperforms buy-and-hold in validation, so the
    derived decision is ``rejected_for_test_promotion``.
    """
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test Researcher")
    # Anchored to the repo root: a bare "data/" pattern would also ignore the
    # committed package's src/eth_research/data/ subpackage.
    (repo / ".gitignore").write_text("/data/\n/reports/\n", encoding="utf-8")

    # The committed package source: an exact copy of the running package, so
    # the C1 source binding executes for real against this repository.
    real_root = Path(eth_research.__file__).resolve().parents[2]
    shutil.copytree(
        real_root / "src" / "eth_research",
        repo / "src" / "eth_research",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(real_root / "uv.lock", repo / "uv.lock")
    shutil.copy(real_root / "pyproject.toml", repo / "pyproject.toml")

    pipe = build_coinbase_pipeline(repo / "data", decline_from_row=72 if eligible else None)
    return commit_synthetic_dossier(repo, pipe)


def commit_synthetic_dossier(repo: Path, pipe: CoinbasePipeline) -> GitPipeline:
    """Write and commit the complete dossier into an initialized git repo.

    The repository must already contain its package source and lockfiles
    (either a fixture copy or a real clone). Two commits are produced: the
    pre-registration commit (all inputs) and the development-evidence
    commit (results, report, decision, frozen dossier) — mirroring the
    real repository's history shape.
    """
    from eth_research import m2b_report
    from eth_research.data.builder import load_canonical_dataset
    from eth_research.data.lock import build_dataset_lock
    from eth_research.decision import (
        build_research_decision_from_results,
        render_research_decision,
    )
    from eth_research.discovery import build_discovery_decision, render_discovery_decision
    from eth_research.dossier import build_frozen_dossier
    from eth_research.environment import RuntimeContract
    from eth_research.holdout import build_holdout_identity
    from eth_research.protocol import BenchmarkResults, build_benchmark_protocol

    research = repo / "research" / "m2b"
    research.mkdir(parents=True, exist_ok=True)

    (research / "acquisition_request_plan.json").write_bytes(pipe.plan.to_json_bytes())
    attempt = research / "raw" / "coinbase" / pipe.receipt.attempt_id
    attempt.mkdir(parents=True)
    for window in pipe.plan.windows:
        shutil.copy(pipe.chunk_dir / window.filename, attempt / window.filename)
    (attempt / "acquisition_receipt.json").write_bytes(pipe.receipt.to_json_bytes())
    _write_synthetic_discovery(repo, research)

    evidence_path = research / "acquisition_evidence.json"
    write_acquisition_evidence(pipe.evidence, evidence_path)
    shutil.copy(pipe.build.manifest_path, research / "dataset_manifest.json")
    shutil.copy(pipe.build.quality_report_path, research / "quality_report.json")
    lock = build_dataset_lock(
        pipe.build.manifest,
        manifest_sha256=pipe.manifest_sha256,
        acquisition_evidence_sha256=sha256_file(evidence_path),
    )
    lock_path = research / "dataset_lock.json"
    lock_path.write_bytes(lock.to_json_bytes())
    protocol = build_benchmark_protocol(lock, package_version=eth_research.__version__)
    protocol_path = research / "protocol.json"
    protocol_path.write_bytes(protocol.to_json_bytes())
    contract = RuntimeContract.for_current_runtime(repo)
    (research / "runtime_contract.json").write_bytes(contract.to_json_bytes())

    dataset = load_canonical_dataset(pipe.build.manifest_path)
    holdout = build_holdout_identity(dataset, protocol)
    (research / "holdout_identity.json").write_bytes(holdout.to_json_bytes())
    decision_doc = build_discovery_decision(repo)
    (research / "discovery_decision.json").write_bytes(decision_doc.to_json_bytes())
    (research / "EARLIEST_CONTINUOUS_DECISION.md").write_text(
        render_discovery_decision(decision_doc), encoding="utf-8"
    )
    ledger_path = research / "test_evaluations.jsonl"
    ledger_path.write_bytes(b"")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pre-register benchmark protocol")
    registration_head = _git(repo, "rev-parse", "HEAD")

    # Development evidence generated from the frozen protocol commit.
    results_bytes, report_md = m2b_report.generate(
        repo, pipe.build.manifest_path, protocol_registration_commit_sha=registration_head
    )
    (repo / m2b_report.RESULTS_RELPATH).write_bytes(results_bytes)
    (repo / m2b_report.REPORT_RELPATH).write_text(report_md, encoding="utf-8")
    research_decision = build_research_decision_from_results(
        BenchmarkResults.from_json_bytes(results_bytes)
    )
    (research / "validation_decision.json").write_bytes(research_decision.to_json_bytes())
    (research / "validation_decision.md").write_text(
        render_research_decision(research_decision), encoding="utf-8"
    )
    (research / "frozen_dossier.json").write_bytes(build_frozen_dossier(repo).to_json_bytes())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "record development evidence and frozen dossier")
    head = _git(repo, "rev-parse", "HEAD")

    return GitPipeline(
        repo_root=repo,
        manifest_path=pipe.build.manifest_path,
        protocol_path=protocol_path,
        lock_path=lock_path,
        evidence_path=evidence_path,
        ledger_path=ledger_path,
        output_dir=repo / "reports" / "m2b",
        raw_chunk_dir=pipe.chunk_dir,
        derived_csv=pipe.derived_csv,
        head=head,
        registration_head=registration_head,
        protocol=protocol,
        lock=lock,
    )


@pytest.fixture
def git_pipeline(tmp_path: Path) -> GitPipeline:
    """The default synthetic dossier repo (decision: eligible)."""
    return make_git_pipeline(tmp_path)


@pytest.fixture
def rejected_git_pipeline(tmp_path: Path) -> GitPipeline:
    """A synthetic dossier repo whose derived decision is rejected."""
    return make_git_pipeline(tmp_path, eligible=False)


# --- Disposable clone carrying the FULL real M2B+M3A layer (N9 rehearsal) ------

_REAL_REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def make_m3a_checkout(tmp_path: Path) -> Path:
    """A ``--local`` clone of the real repository with its full M2B+M3A layer intact.

    Unlike :func:`make_real_checkout` (which drops ``research/`` and rebuilds a
    tiny synthetic M2B dossier), this keeps the real committed raw Coinbase bytes,
    the frozen dossier, the M3A development partition / v1 protocol / v2
    methodology, the six-line v1 registry prefix, and both byte-empty ledgers — so
    the real M3A orchestrator lifecycle (which hard-pins the real 2221-row research
    train) can execute end-to-end inside the disposable clone via subprocess,
    consuming run-003's id only in the clone. The clone's own ``src/eth_research``
    is overlaid from the current working tree and committed, so it is the
    authorized running package under ``PYTHONPATH=<clone>/src``.

    Returns the clone root; its HEAD is a clean commit whose source tree equals the
    working-tree package (this is the rehearsal's execution-source commit ``E``).
    """
    clone = tmp_path / "m3a_checkout"
    subprocess.run(
        ["git", "clone", "--quiet", "--local", "--no-hardlinks", str(_REAL_REPO_ROOT), str(clone)],
        capture_output=True,
        text=True,
        check=True,
    )
    _git(clone, "config", "user.email", "test@example.com")
    _git(clone, "config", "user.name", "Test Researcher")
    # Pin the clone onto a real, named local branch representing the accepted cohort.
    # ``actions/checkout`` leaves the CI workspace on a *detached HEAD* for
    # ``pull_request`` events, and a ``--local`` clone of a detached repo is itself
    # detached — so ``current_branch()`` would return the literal ``"HEAD"`` and a
    # test's "return to the accepted branch" (``git checkout HEAD``) would be a no-op
    # that strands the working tree on a bot branch's staged growth. Forcing a named
    # branch models production (the accepted cohort lives on a named branch, never a
    # detached HEAD) and makes the rehearsal deterministic in both environments.
    _git(clone, "checkout", "-B", "accepted-cohort")
    # A ``--local`` clone of a source checked out *on* the accepted-cohort branch (the
    # push-to-``main`` checkout of post-merge main CI) carries a stray local ``main``
    # branch; a production update runner checks out a detached HEAD at ``main``'s SHA with
    # no local accepted branch. Drop the inherited ``main`` (if present) so the rehearsal
    # stays faithful and the seam tests' "the accepted branch is never materialised /
    # advanced" assertion (``not branch_exists("main")``) is meaningful in every CI event.
    subprocess.run(
        ["git", "-C", str(clone), "branch", "-D", "main"],
        capture_output=True,
        text=True,
        check=False,
    )
    # Overlay the working-tree source and the CI verifier scripts so the rehearsal
    # exercises the *current* package and CI gates (which may carry uncommitted
    # changes); commit only if they differ from the cloned HEAD, so a clean tree
    # needs no extra commit.
    for rel in ("src", ".github/scripts"):
        shutil.copytree(
            _REAL_REPO_ROOT / rel,
            clone / rel,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    _git(clone, "add", "-A", "src", ".github/scripts")
    if _git(clone, "status", "--porcelain"):
        _git(clone, "commit", "--quiet", "-m", "sync working source into the e2e checkout")
    return clone


@pytest.fixture
def m3a_checkout(tmp_path: Path) -> Path:
    """A disposable clone carrying the full real M2B+M3A layer (see helper)."""
    return make_m3a_checkout(tmp_path)


# --- Synthetic M3D prospective cohort staging --------------------------------

# Coinbase field order [time, low, high, open, close, volume]; three completed
# daily candles (07-12/07-13/07-14) in the newest-first order Coinbase returns.
_M3D_DEFAULT_ROWS: tuple[tuple[float, ...], ...] = (
    (1783987200.0, 1771.36, 1895.61, 1774.57, 1890.63, 138211.47661573),
    (1783900800.0, 1748.05, 1844.67, 1805.56, 1774.57, 106281.79272453),
    (1783814400.0, 1778.55, 1825.46, 1786.81, 1805.51, 39647.67901761),
)


def _build_m3d_staged_cohort(
    tmp_path: Path,
    *,
    rows: Sequence[Sequence[float]] = _M3D_DEFAULT_ROWS,
    m2b_last_open: str = "2026-07-11T00:00:00+00:00",
    attempt_id: str | None = None,
) -> Path:
    """Stage a synthetic committed repo with an M3D genesis acquisition + M2B lock.

    Builds the committed plan, writes a synthetic raw body + status sidecar, runs
    the real offline runner to produce the receipt, then drops the sidecar so the
    tree matches a real bot acquisition commit. ``rows`` are Coinbase-order candles
    (newest-first ok); ``m2b_last_open`` seeds the minimal M2B dataset lock used by
    the cross-dataset overlap check. No network, no strategy, no evaluation.
    """
    from eth_research.m3d.acquire_runner import (
        RESPONSES_SIDECAR,
        verify_responses_and_write_receipt,
    )
    from eth_research.m3d.acquisition_plan import (
        GENESIS_ATTEMPT_ID,
        build_prospective_acquisition_plan,
    )
    from eth_research.m3d.validation import canonical_json_bytes

    attempt = attempt_id or GENESIS_ATTEMPT_ID
    raw_dir = tmp_path / "research/m3d/raw/coinbase" / attempt
    raw_dir.mkdir(parents=True)
    plan = build_prospective_acquisition_plan(
        attempt_id=attempt,
        as_of_utc=pd.Timestamp("2026-07-15T00:00:00Z"),
        docs_recheck={
            "access_date": "2026-07-15",
            "http_status": 403,
            "accessible": False,
            "source_of_truth": "m2b_verified_adapter_contract",
        },
    )
    (raw_dir / "acquisition_plan.json").write_bytes(plan.to_json_bytes())
    filename = str(plan.windows[0]["raw_filename"])
    # Coinbase serves the bucket time as a JSON integer; keep it integral so the
    # strict adapter accepts the synthetic body exactly as it would a real one.
    body_rows = [[int(row[0]), *list(row[1:])] for row in rows]
    (raw_dir / filename).write_bytes(json.dumps(body_rows).encode())
    (raw_dir / RESPONSES_SIDECAR).write_text(
        json.dumps(
            {
                "content_type": "application/json",
                "filename": filename,
                "http_code": 200,
                "ordinal": 0,
                "retrieved_at": "2026-07-15T12:00:00Z",
            },
            sort_keys=True,
        )
        + "\n"
    )
    verify_responses_and_write_receipt(
        raw_dir / "acquisition_plan.json",
        raw_dir,
        raw_dir / "acquisition_receipt.json",
        attempt_id=attempt,
        workflow_run_id="123",
        source_commit="a" * 40,
        client_identity="curl/8.0",
        runner_identity="ubuntu-x64",
        created_at_utc="2026-07-15T12:00:05Z",
    )
    (raw_dir / RESPONSES_SIDECAR).unlink()
    m2b = tmp_path / "research/m2b"
    m2b.mkdir(parents=True, exist_ok=True)  # allow staging multiple attempts in one repo
    (m2b / "dataset_lock.json").write_bytes(canonical_json_bytes({"last_open_time": m2b_last_open}))
    return tmp_path


@pytest.fixture
def m3d_staged_cohort() -> Callable[..., Path]:
    """Factory for a synthetic committed repo carrying a staged M3D genesis cohort."""
    return _build_m3d_staged_cohort


# --- Synthetic M3E prospective update runner ---------------------------------

# A default synthetic ETH-USD price/volume series is a deterministic function of a
# candle's UTC open day-number, so two independent runners generating the same
# window produce byte-identical raw bodies (the canonical-equality happy path); a
# ``mutate`` hook lets a test perturb one runner to exercise the mismatch path.


def _m3e_descending_candles(window_start: str, window_end: str) -> list[list[float | int]]:
    """Coinbase-order [time, low, high, open, close, volume] rows, newest-first.

    Covers the half-open [window_start, window_end): opens run from
    ``window_end - 1 day`` down to ``window_start`` (the descending order Coinbase
    returns and the strict adapter reverses). All values are finite and satisfy the
    OHLC bracket the adapter enforces.
    """
    day = pd.Timedelta(days=1)
    start = pd.Timestamp(window_start)
    cursor = pd.Timestamp(window_end) - day
    rows: list[list[float | int]] = []
    while cursor >= start:
        n = int(cursor.timestamp()) // 86_400
        open_ = 1700.0 + float(n % 37)
        close = open_ + float((n % 7) - 3)
        high = max(open_, close) + 2.0
        low = min(open_, close) - 2.0
        volume = 40_000.0 + float(n % 100)
        rows.append([int(cursor.timestamp()), low, high, open_, close, volume])
        cursor = cursor - day
    return rows


def write_m3e_runner(
    raw_dir: Path,
    update_plan: object,
    *,
    attempt_id: str,
    source_commit: str,
    workflow_run_id: str,
    runner_identity: str,
    client_identity: str = "synthetic offline runner (no networking)",
    mutate: Callable[[int, list[list[float | int]]], list[list[float | int]]] | None = None,
) -> ProspectiveAttemptReceipt:
    """Write one runner's synthetic raw bodies + a validated M3D-schema receipt.

    Reuses the reviewed :class:`ProspectiveAttemptReceipt` schema (an M3E runner is
    just a prospective attempt over the update window). Returns the parsed receipt.
    """
    from eth_research.m3d.receipt import ProspectiveAttemptReceipt

    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    responses: list[dict[str, object]] = []
    for window in update_plan.windows:  # type: ignore[attr-defined]
        rows = _m3e_descending_candles(str(window["window_start"]), str(window["window_end"]))
        if mutate is not None:
            rows = mutate(int(window["ordinal"]), rows)
        raw = json.dumps(rows).encode("ascii")
        (raw_dir / str(window["raw_filename"])).write_bytes(raw)
        responses.append(
            {
                "ordinal": int(window["ordinal"]),
                "raw_filename": str(window["raw_filename"]),
                "start_param": str(window["start_param"]),
                "end_param": str(window["end_param"]),
                "http_status": 200,
                "content_type": "application/json",
                "response_byte_length": len(raw),
                "response_sha256": sha256_bytes(raw),
                "retrieved_at": "2026-07-22T02:17:05Z",
            }
        )
    document = {
        "schema_version": 1,
        "kind": "prospective_attempt_receipt",
        "package_version": eth_research.__version__,
        "attempt_id": attempt_id,
        "plan_sha256": update_plan.plan_sha256,  # type: ignore[attr-defined]
        "endpoint": update_plan.document["endpoint"],  # type: ignore[attr-defined]
        "user_agent": update_plan.document["user_agent"],  # type: ignore[attr-defined]
        "source_commit": source_commit,
        "workflow_run_id": workflow_run_id,
        "runner_identity": runner_identity,
        "client_identity": client_identity,
        "created_at_utc": "2026-07-22T02:17:06Z",
        "responses": responses,
    }
    receipt = ProspectiveAttemptReceipt.from_mapping(document)
    # Write the complete runner artifact directory (plan + receipt + raws) so the
    # workflow-artifact boundary can re-derive everything from committed bytes.
    (raw_dir / "update_plan.json").write_bytes(update_plan.to_json_bytes())  # type: ignore[attr-defined]
    (raw_dir / "acquisition_receipt.json").write_bytes(receipt.to_json_bytes())
    return receipt


@pytest.fixture
def m3e_write_runner() -> Callable[..., ProspectiveAttemptReceipt]:
    """Factory to stage one synthetic M3E update runner (raws + plan + receipt)."""
    return write_m3e_runner


def stage_m3e_proposal(
    proposal_dir: Path, *, repo_root: Path, as_of: str = "2026-07-22T02:17:00Z"
) -> AssembledProposal:
    """Stage a complete synthetic M3E proposal directory (two runners + derived evidence).

    Both runners replay the same update plan with distinct runner identities (so they
    are isolated), and the comparison/transition/manifest are assembled offline via
    the real assembler and written into ``proposal_dir``. ``repo_root`` supplies the
    accepted M3D base the transition re-derives from.
    """
    from eth_research.m3e.accepted_base import verify_accepted_base
    from eth_research.m3e.cutoff import plan_update_window
    from eth_research.m3e.proposal import assemble_proposal
    from eth_research.m3e.update_plan import build_update_plan

    proposal_dir = Path(proposal_dir)
    proposal_dir.mkdir(parents=True, exist_ok=True)
    base = verify_accepted_base(repo_root)
    plan = build_update_plan(base, plan_update_window(base, as_of))
    write_m3e_runner(
        proposal_dir / "runner_a",
        plan,
        attempt_id="coinbase-eth-usd-prospective-update-runner-a",
        source_commit="a" * 40,
        workflow_run_id="run-99",
        runner_identity="ubuntu-x64-a",
    )
    write_m3e_runner(
        proposal_dir / "runner_b",
        plan,
        attempt_id="coinbase-eth-usd-prospective-update-runner-b",
        source_commit="b" * 40,
        workflow_run_id="run-99",
        runner_identity="ubuntu-x64-b",
    )
    assembled = assemble_proposal(repo_root, proposal_dir)
    for rel, data in assembled.blobs:
        (proposal_dir / rel).write_bytes(data)
    return assembled


@pytest.fixture
def m3e_stage_proposal() -> Callable[..., AssembledProposal]:
    """Factory to stage a complete synthetic M3E proposal directory."""
    return stage_m3e_proposal


# --------------------------------------------------------------------------- #
# V2C OQ: the pristine (pre-run) repository tree                              #
# --------------------------------------------------------------------------- #
_OQ_ARCHIVE_DIR = "governance/v2c/qualifications/v2c_offline_operational_qualification_run_001"
_OQ_REGISTRY_RELPATH = "governance/v2c/oq_registry.jsonl"
_OQ_RUNTIME_CONTRACT_RELPATH = "research/m2b/runtime_contract.json"
_OQ_SEALED_LEDGER_RELPATHS = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)


@pytest.fixture(scope="session")
def pristine_oq_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A byte-faithful copy of the committed tree rewound to the PRE-run pristine OQ state.

    The canonical tree now carries a completed, qualified offline-operational-qualification run (a
    ``completed`` registry plus the immutable published archive). Tests that drive the pristine OQ
    lifecycle -- register/start on a byte-empty registry, the pristine status/replay/verify CLIs,
    the orchestrator's happy path -- need the pre-run tree. This reconstructs it in an isolated
    temp dir: the full frozen source (``src``), the frozen non-source evidence under ``docs`` (the
    freeze binds ``docs/V2C_PLAN.md``), and every governance artifact the orchestrator binds and
    re-derives (``governance``) are copied byte-for-byte; the runtime contract is copied; the
    registry is emptied; the three sealed ledgers are (re)written byte-empty; and the published run
    archive is removed. The tree is only ever READ, so one session-scoped copy is shared.
    """
    repo = Path(__file__).resolve().parents[1]
    root = tmp_path_factory.mktemp("pristine_oq_repo")
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(repo / "src", root / "src", ignore=ignore)
    shutil.copytree(repo / "governance", root / "governance", ignore=ignore)
    shutil.copytree(repo / "docs", root / "docs", ignore=ignore)
    contract = root / _OQ_RUNTIME_CONTRACT_RELPATH
    contract.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / _OQ_RUNTIME_CONTRACT_RELPATH, contract)
    # Rewind to the pristine pre-run state: empty registry, byte-empty sealed ledgers, no archive.
    (root / _OQ_REGISTRY_RELPATH).write_bytes(b"")
    for rel in _OQ_SEALED_LEDGER_RELPATHS:
        led = root / rel
        led.parent.mkdir(parents=True, exist_ok=True)
        led.write_bytes(b"")
    shutil.rmtree(root / _OQ_ARCHIVE_DIR, ignore_errors=True)
    return root
