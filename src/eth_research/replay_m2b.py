"""Deterministic offline replay of the Milestone 2B dataset from raw bytes.

Given the committed request plan, the committed raw Coinbase responses, and
the committed acquisition receipt, this reconstructs every *derived*
artifact — the daily OHLCV CSV, the acquisition evidence, and the canonical
dataset (Parquet + manifest + quality report) — entirely offline and
compares them against the frozen, committed metadata. The derived CSV and
Parquet are intentionally *not* committed (they are reproducible); this tool
is how a fresh clone materializes and verifies them.

It performs **no networking**, never touches the test-access ledger, never
calls the authorized evaluator, and never generates a strategy signal, a
fill, or any P&L. The reproducibility contract is the validated *content
fingerprint*, never Parquet container bytes (which vary across toolchains).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.data.acquisition_plan import (
    AcquisitionRequestPlan,
    load_acquisition_plan,
    load_acquisition_receipt,
)
from eth_research.data.builder import BuildResult, build_canonical_dataset, load_canonical_dataset
from eth_research.data.coinbase import (
    AcquisitionError,
    AcquisitionEvidence,
    ChunkRequest,
    derive_daily_ohlcv,
    verify_acquisition_evidence,
)
from eth_research.data.lock import load_dataset_lock, verify_dataset_lock
from eth_research.data.provenance import (
    DatasetIdentity,
    sha256_bytes,
    sha256_file,
)

DATASET_SOURCE: str = (
    "Coinbase Exchange public REST candles (GET /products/ETH-USD/candles), "
    "acquired via the GitHub Actions clean room; see research/m2b/"
)

RESEARCH_DIR: str = "research/m2b"
PLAN_RELPATH: str = "research/m2b/acquisition_request_plan.json"
EVIDENCE_RELPATH: str = "research/m2b/acquisition_evidence.json"
LOCK_RELPATH: str = "research/m2b/dataset_lock.json"
PROTOCOL_RELPATH: str = "research/m2b/protocol.json"
RAW_ROOT_RELPATH: str = "research/m2b/raw/coinbase"
DERIVED_CSV_NAME: str = "coinbase-eth-usd-1d.csv"


def coinbase_identity() -> DatasetIdentity:
    """The fixed ETH-USD spot daily identity of the real dataset."""
    return DatasetIdentity(
        quote_asset="USD",
        symbol="ETH-USD",
        venue="coinbase-exchange",
        interval=pd.Timedelta(days=1),
        source=DATASET_SOURCE,
    )


@dataclass(frozen=True)
class ReconstructResult:
    """Everything one offline reconstruction produced."""

    evidence: AcquisitionEvidence
    evidence_bytes: bytes
    build: BuildResult
    derived_csv: Path


def reconstruct_dataset(
    repo_root: str | Path,
    attempt_id: str,
    work_dir: str | Path,
) -> ReconstructResult:
    """Rebuild the derived CSV, evidence, and canonical dataset from raw.

    Reads the committed plan, the committed raw bodies for ``attempt_id``,
    and the committed receipt; re-hashes every raw body against the receipt;
    re-derives the CSV; runs the semantic acquisition verification; and
    builds the canonical dataset into ``work_dir`` (never a tracked path).
    """
    root = Path(repo_root)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    plan = load_acquisition_plan(root / PLAN_RELPATH)
    raw_dir = root / RAW_ROOT_RELPATH / attempt_id
    receipt = load_acquisition_receipt(raw_dir / "acquisition_receipt.json")
    if receipt.plan_sha256 != plan.plan_sha256():
        raise AcquisitionError(
            f"receipt plan_sha256 {receipt.plan_sha256} does not match the committed plan "
            f"{plan.plan_sha256()}"
        )
    responses = {response.ordinal: response for response in receipt.responses}

    requests: list[ChunkRequest] = []
    for window in plan.windows:
        response = responses.get(window.ordinal)
        if response is None:
            raise AcquisitionError(f"receipt has no response for window {window.ordinal}")
        path = raw_dir / window.filename
        if not path.exists():
            raise AcquisitionError(f"raw body {window.filename} missing from {raw_dir}")
        if sha256_file(path) != response.sha256:
            raise AcquisitionError(f"raw body {window.filename} does not match the receipt SHA-256")
        requests.append(
            ChunkRequest(
                path=path,
                window_start=window.window_start,
                window_end=window.window_end,
                requested_start=window.requested_start,
                requested_end=window.requested_end,
                retrieved_at=response.retrieved_at,
            )
        )

    derived_csv = work / DERIVED_CSV_NAME
    evidence = derive_daily_ohlcv(
        requests,
        overall_start=plan.overall_start,
        overall_end=plan.overall_end,
        output_csv=derived_csv,
        overwrite=True,
    )
    verify_acquisition_evidence(evidence, chunk_dir=raw_dir, derived_csv=derived_csv)

    build = build_canonical_dataset(
        derived_csv, coinbase_identity(), work / "datasets", overwrite=True
    )
    # Verification-on-read of what we just built.
    load_canonical_dataset(build.manifest_path)
    return ReconstructResult(
        evidence=evidence,
        evidence_bytes=evidence.to_json_bytes(),
        build=build,
        derived_csv=derived_csv,
    )


def _summary(result: ReconstructResult, plan: AcquisitionRequestPlan) -> dict[str, Any]:
    manifest = result.build.manifest
    return {
        "plan_sha256": plan.plan_sha256(),
        "derived_csv_sha256": sha256_file(result.derived_csv),
        "acquisition_evidence_sha256": sha256_bytes(result.evidence_bytes),
        "content_fingerprint": manifest.content_fingerprint,
        "manifest_sha256": sha256_bytes(manifest.to_json_bytes()),
        "row_count": manifest.row_count,
        "first_open_time": manifest.first_open_time.isoformat(),
        "last_open_time": manifest.last_open_time.isoformat(),
    }


def check_against_committed(repo_root: str | Path, result: ReconstructResult) -> dict[str, bool]:
    """Compare the reconstruction against the frozen committed metadata.

    Byte-compares the acquisition evidence, checks the manifest hash and the
    content fingerprint against the committed dataset lock, and re-runs the
    full lock verification with the mandatory raw arguments. Never compares
    Parquet container bytes. Missing committed artifacts are reported as
    ``False`` rather than raising, so a pre-freeze run is still informative.
    """
    root = Path(repo_root)
    checks: dict[str, bool] = {}

    evidence_path = root / EVIDENCE_RELPATH
    checks["evidence_bytes_match"] = (
        evidence_path.exists() and evidence_path.read_bytes() == result.evidence_bytes
    )

    lock_path = root / LOCK_RELPATH
    manifest = result.build.manifest
    if lock_path.exists():
        lock = load_dataset_lock(lock_path)
        checks["lock_content_fingerprint"] = (
            lock.content_fingerprint == manifest.content_fingerprint
        )
        checks["lock_manifest_sha256"] = lock.manifest_sha256 == sha256_bytes(
            manifest.to_json_bytes()
        )
        checks["lock_raw_file_sha256"] = lock.raw_file_sha256 == sha256_file(result.derived_csv)
        try:
            verify_dataset_lock(
                lock,
                manifest_path=result.build.manifest_path,
                acquisition_evidence_path=evidence_path,
                raw_chunk_dir=_raw_dir_for(root),
                derived_csv=result.derived_csv,
            )
            checks["lock_chain_verifies"] = True
        except (RuntimeError, ValueError):
            checks["lock_chain_verifies"] = False
    else:
        checks["lock_content_fingerprint"] = False
        checks["lock_manifest_sha256"] = False
        checks["lock_raw_file_sha256"] = False
        checks["lock_chain_verifies"] = False
    return checks


def _raw_dir_for(root: Path) -> Path:
    """The canonical committed attempt directory, pinned by name.

    Audit reacquisition attempts may sit beside it; replay and lock
    verification always run against the canonical attempt.
    """
    from eth_research.dossier import CANONICAL_ATTEMPT_ID

    attempt = root / RAW_ROOT_RELPATH / CANONICAL_ATTEMPT_ID
    if not attempt.is_dir():
        raise AcquisitionError(f"the canonical acquisition attempt directory {attempt} is missing")
    return attempt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eth_research.replay_m2b")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--attempt-id",
        default=None,
        help="raw acquisition attempt id (defaults to the single real attempt)",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="where to materialize derived artifacts (defaults to a temp dir)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the reconstruction against the committed frozen metadata",
    )
    args = parser.parse_args(argv)
    root = Path(args.repo_root)

    try:
        attempt_id = args.attempt_id or _raw_dir_for(root).name
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(args.work_dir) if args.work_dir else Path(tmp)
            result = reconstruct_dataset(root, attempt_id, work)
            plan = load_acquisition_plan(root / PLAN_RELPATH)
            report: dict[str, Any] = {"attempt_id": attempt_id, **_summary(result, plan)}
            if args.check:
                report["checks"] = check_against_committed(root, result)
    except (AcquisitionError, ValueError, RuntimeError) as exc:
        print(f"replay failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.check and not all(report["checks"].values()):
        print("replay check FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
