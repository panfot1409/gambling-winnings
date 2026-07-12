"""Shared fixtures for the test suite."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

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
    from eth_research import m2b_report
    from eth_research.data.lock import build_dataset_lock
    from eth_research.decision import (
        build_research_decision_from_results,
        render_research_decision,
    )
    from eth_research.discovery import build_discovery_decision, render_discovery_decision
    from eth_research.environment import RuntimeContract
    from eth_research.holdout import build_holdout_identity
    from eth_research.protocol import BenchmarkResults, build_benchmark_protocol
    from eth_research.provenance_v2 import build_provenance_v2

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
    research = repo / "research" / "m2b"
    research.mkdir(parents=True)

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
    from eth_research.data.builder import load_canonical_dataset

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
        repo, pipe.build.manifest_path, pre_registered_commit_sha=registration_head
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
    (research / "provenance_v2.json").write_bytes(build_provenance_v2(repo).to_json_bytes())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "record development evidence and provenance anchor")
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
