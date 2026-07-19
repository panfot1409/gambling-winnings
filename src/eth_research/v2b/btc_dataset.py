"""Frozen canonical BTC-USD research dataset, derived from the committed raw bundles.

The genesis and audit acquisitions each committed their raw candle bodies + a strict
receipt under ``research/v2b/raw/coinbase/<attempt>/``. This module re-derives — from
those committed bytes, offline — one canonical daily OHLCV series, re-proves that the
two independent acquisitions yield **identical canonical candles**, and freezes a small
set of byte-reproducible governance artifacts under ``research/v2b/btc/``:

* ``acquisition_plan.json`` — the one immutable request plan (hard-coded window);
* ``reacquisition_audit.json`` — genesis↔audit canonical-equality proof;
* ``dataset_manifest.json`` — the canonical series identity (rows, bounds, fingerprint);
* ``quality_report.json`` — gaps/dupes/finiteness/OHLCV-identity/cutoff quality facts;
* ``dataset_lock.json`` — the top-level lock that hash-anchors all of the above.

``verify_btc_dataset`` re-derives everything and refuses any drift. Nothing here reads a
network; the derived CSV/Parquet is never tracked (it is reproducible from the raw bytes).
The window is hard-coded in :mod:`eth_research.v2b.acquisition`; no row at or after the
research cutoff can enter this dataset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.v2.strict import V2ValidationError, canonical_json_bytes, sha256_bytes
from eth_research.v2b.acquisition import (
    AUDIT_ATTEMPT_ID,
    EXPECTED_DAILY_OPENS,
    GENESIS_ATTEMPT_ID,
    RESEARCH_CUTOFF_LAST_OPEN,
    BtcAcquisitionError,
    build_btc_acquisition_plan,
    build_window_receipt,
    canonical_daily_frame,
    content_fingerprint,
    parse_candles_body,
)

BTC_DATASET_DIR = "research/v2b/btc"
ACQUISITION_PLAN_RELPATH = f"{BTC_DATASET_DIR}/acquisition_plan.json"
REACQUISITION_AUDIT_RELPATH = f"{BTC_DATASET_DIR}/reacquisition_audit.json"
DATASET_MANIFEST_RELPATH = f"{BTC_DATASET_DIR}/dataset_manifest.json"
QUALITY_REPORT_RELPATH = f"{BTC_DATASET_DIR}/quality_report.json"
DATASET_LOCK_RELPATH = f"{BTC_DATASET_DIR}/dataset_lock.json"

BTC_DATASET_SCHEMA_VERSION = 1
SYMBOL = "BTC-USD"
VENUE = "coinbase-exchange"
INTERVAL_SECONDS = 86_400
BASE_CURRENCY = "USD"
_RAW_DIR = "research/v2b/raw/coinbase"


class BtcDatasetError(V2ValidationError):
    """The frozen BTC dataset drifted from the committed raw bundles."""


def _raw(repo_root: Path, attempt_id: str) -> Path:
    return repo_root / _RAW_DIR / attempt_id


def _load_receipt(repo_root: Path, attempt_id: str) -> dict[str, Any]:
    path = _raw(repo_root, attempt_id) / "acquisition_receipt.json"
    obj = json.loads(path.read_bytes())
    if not isinstance(obj, dict):
        raise BtcDatasetError(f"{attempt_id}: acquisition receipt is not a JSON object")
    return obj


def load_attempt(
    repo_root: str | Path, attempt_id: str
) -> tuple[dict[str, Any], pd.DataFrame, str]:
    """Re-derive one attempt's canonical daily frame from its committed raw bytes.

    Re-parses every window strictly, re-derives each window receipt and checks it against
    the committed receipt (body hash + length + open count), assembles the canonical daily
    frame, and returns ``(committed_receipt, frame, content_fingerprint)``.
    """
    root = Path(repo_root)
    receipt = _load_receipt(root, attempt_id)
    plan = build_btc_acquisition_plan()
    if receipt["plan_sha256"] != plan.plan_sha256():
        raise BtcDatasetError(f"{attempt_id}: receipt plan_sha256 != the immutable plan")
    rows_by_window = []
    for window, wr in zip(plan.windows, receipt["windows"], strict=True):
        body = (_raw(root, attempt_id) / window.filename).read_bytes()
        rows = parse_candles_body(body, window)
        local = build_window_receipt(attempt_id, window, body, plan.plan_sha256())
        if (
            local.body_sha256 != wr["body_sha256"]
            or local.body_bytes != wr["body_bytes"]
            or local.parsed_open_count != wr["parsed_open_count"]
        ):
            raise BtcDatasetError(f"{attempt_id} window {window.ordinal}: raw bytes drift receipt")
        rows_by_window.append(rows)
    frame = canonical_daily_frame(rows_by_window)
    return receipt, frame, content_fingerprint(frame)


@dataclass(frozen=True, slots=True)
class CanonicalBtcDataset:
    """The verified canonical BTC daily frame + its shared genesis/audit fingerprint."""

    frame: pd.DataFrame
    content_fingerprint: str
    genesis_receipt: dict[str, Any]
    audit_receipt: dict[str, Any]


def load_canonical_btc_dataset(repo_root: str | Path) -> CanonicalBtcDataset:
    """Load the canonical BTC dataset, re-proving genesis↔audit canonical equality."""
    g_receipt, g_frame, g_fp = load_attempt(repo_root, GENESIS_ATTEMPT_ID)
    a_receipt, a_frame, a_fp = load_attempt(repo_root, AUDIT_ATTEMPT_ID)
    if not g_frame.index.equals(a_frame.index):
        raise BtcDatasetError("genesis/audit timestamp sets differ")
    for col in ("open", "high", "low", "close", "volume"):
        if not g_frame[col].equals(a_frame[col]):
            raise BtcDatasetError(f"genesis/audit {col} values differ")
    if g_fp != a_fp:
        raise BtcDatasetError("genesis/audit content fingerprints differ")
    if g_receipt["workflow_run_id"] == a_receipt["workflow_run_id"]:
        raise BtcDatasetError("genesis/audit are not independent (same workflow run id)")
    return CanonicalBtcDataset(g_frame, g_fp, g_receipt, a_receipt)


# --------------------------------------------------------------------------- #
# frozen artifacts                                                            #
# --------------------------------------------------------------------------- #
def _sha256_of(repo_root: Path, relpath: str) -> str:
    return sha256_bytes((repo_root / relpath).read_bytes())


def build_acquisition_plan_doc() -> dict[str, Any]:
    return build_btc_acquisition_plan().to_canonical()


def build_reacquisition_audit(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    ds = load_canonical_btc_dataset(root)
    return {
        "schema_version": BTC_DATASET_SCHEMA_VERSION,
        "kind": "btc_reacquisition_audit",
        "canonical_candles_identical": True,
        "content_fingerprint": ds.content_fingerprint,
        "genesis": {
            "attempt_id": GENESIS_ATTEMPT_ID,
            "workflow_run_id": ds.genesis_receipt["workflow_run_id"],
            "source_commit": ds.genesis_receipt["source_commit"],
            "receipt_sha256": _sha256_of(
                root, f"{_RAW_DIR}/{GENESIS_ATTEMPT_ID}/acquisition_receipt.json"
            ),
        },
        "audit": {
            "attempt_id": AUDIT_ATTEMPT_ID,
            "workflow_run_id": ds.audit_receipt["workflow_run_id"],
            "source_commit": ds.audit_receipt["source_commit"],
            "receipt_sha256": _sha256_of(
                root, f"{_RAW_DIR}/{AUDIT_ATTEMPT_ID}/acquisition_receipt.json"
            ),
        },
        "independent_run_ids": ds.genesis_receipt["workflow_run_id"]
        != ds.audit_receipt["workflow_run_id"],
        "independent_source_commits": ds.genesis_receipt["source_commit"]
        != ds.audit_receipt["source_commit"],
    }


def build_dataset_manifest(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    ds = load_canonical_btc_dataset(root)
    plan = build_btc_acquisition_plan()
    return {
        "schema_version": BTC_DATASET_SCHEMA_VERSION,
        "kind": "btc_dataset_manifest",
        "symbol": SYMBOL,
        "venue": VENUE,
        "interval_seconds": INTERVAL_SECONDS,
        "base_currency": BASE_CURRENCY,
        "plan_sha256": plan.plan_sha256(),
        "row_count": len(ds.frame),
        "first_open": pd.Timestamp(ds.frame.index[0]).isoformat().replace("+00:00", "Z"),
        "last_open": pd.Timestamp(ds.frame.index[-1]).isoformat().replace("+00:00", "Z"),
        "research_cutoff_last_open": RESEARCH_CUTOFF_LAST_OPEN.isoformat().replace("+00:00", "Z"),
        "columns": ["open", "high", "low", "close", "volume"],
        "content_fingerprint": ds.content_fingerprint,
        "genesis_receipt_sha256": _sha256_of(
            root, f"{_RAW_DIR}/{GENESIS_ATTEMPT_ID}/acquisition_receipt.json"
        ),
        "audit_receipt_sha256": _sha256_of(
            root, f"{_RAW_DIR}/{AUDIT_ATTEMPT_ID}/acquisition_receipt.json"
        ),
    }


def build_quality_report(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    ds = load_canonical_btc_dataset(root)
    frame = ds.frame
    close = frame["close"].to_numpy()
    return {
        "schema_version": BTC_DATASET_SCHEMA_VERSION,
        "kind": "btc_quality_report",
        "expected_daily_opens": EXPECTED_DAILY_OPENS,
        "actual_daily_opens": len(frame),
        "missing_opens": EXPECTED_DAILY_OPENS - len(frame),
        "duplicate_opens": 0,
        "all_finite": True,
        "all_prices_positive": bool((frame[["open", "high", "low", "close"]].to_numpy() > 0).all()),
        "volume_nonnegative": bool((frame["volume"].to_numpy() >= 0).all()),
        "ohlcv_identity_holds": bool(
            (
                (frame["low"] <= frame["open"])
                & (frame["open"] <= frame["high"])
                & (frame["low"] <= frame["close"])
                & (frame["close"] <= frame["high"])
            ).all()
        ),
        "contiguous_daily": True,
        "no_row_at_or_after_cutoff": bool((frame.index <= RESEARCH_CUTOFF_LAST_OPEN).all()),
        "first_open": pd.Timestamp(frame.index[0]).isoformat().replace("+00:00", "Z"),
        "last_open": pd.Timestamp(frame.index[-1]).isoformat().replace("+00:00", "Z"),
        "min_close": float(close.min()),
        "max_close": float(close.max()),
        "content_fingerprint": ds.content_fingerprint,
    }


def build_dataset_lock(repo_root: str | Path) -> dict[str, Any]:
    """The top-level lock binding every frozen BTC artifact by SHA-256."""
    root = Path(repo_root)
    ds = load_canonical_btc_dataset(root)
    return {
        "schema_version": BTC_DATASET_SCHEMA_VERSION,
        "kind": "btc_dataset_lock",
        "symbol": SYMBOL,
        "content_fingerprint": ds.content_fingerprint,
        "row_count": len(ds.frame),
        "acquisition_plan_sha256": _sha256_of(root, ACQUISITION_PLAN_RELPATH),
        "reacquisition_audit_sha256": _sha256_of(root, REACQUISITION_AUDIT_RELPATH),
        "dataset_manifest_sha256": _sha256_of(root, DATASET_MANIFEST_RELPATH),
        "quality_report_sha256": _sha256_of(root, QUALITY_REPORT_RELPATH),
    }


# The build order matters: the lock hashes the other four, so they are written first.
_ARTIFACT_BUILDERS: tuple[tuple[str, Any], ...] = (
    (ACQUISITION_PLAN_RELPATH, lambda root: build_acquisition_plan_doc()),
    (REACQUISITION_AUDIT_RELPATH, build_reacquisition_audit),
    (DATASET_MANIFEST_RELPATH, build_dataset_manifest),
    (QUALITY_REPORT_RELPATH, build_quality_report),
    (DATASET_LOCK_RELPATH, build_dataset_lock),
)


def write_frozen_artifacts(repo_root: str | Path) -> list[str]:
    """Write all frozen BTC dataset artifacts (in dependency order). Returns relpaths."""
    root = Path(repo_root)
    (root / BTC_DATASET_DIR).mkdir(parents=True, exist_ok=True)
    written = []
    for relpath, builder in _ARTIFACT_BUILDERS:
        (root / relpath).write_bytes(canonical_json_bytes(builder(root)))
        written.append(relpath)
    return written


def verify_btc_dataset(repo_root: str | Path) -> None:
    """Every committed BTC artifact reproduces byte-for-byte from the raw bundles."""
    root = Path(repo_root)
    load_canonical_btc_dataset(root)  # re-proves genesis↔audit equality + receipts
    for relpath, builder in _ARTIFACT_BUILDERS:
        committed = (root / relpath).read_bytes()
        if committed != canonical_json_bytes(builder(root)):
            raise BtcDatasetError(f"{relpath} does not reproduce byte-for-byte from raw bytes")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse

    parser = argparse.ArgumentParser(description="V2B BTC dataset freeze (offline)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--write", action="store_true", help="write the frozen artifacts")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    if args.write:
        for rel in write_frozen_artifacts(root):
            print(f"wrote {rel}")
        return 0
    try:
        verify_btc_dataset(root)
    except (OSError, V2ValidationError, BtcAcquisitionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
