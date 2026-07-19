"""The frozen canonical BTC dataset reproduces from the committed raw bundles."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.v2b import btc_dataset as bd
from eth_research.v2b.acquisition import (
    RESEARCH_CUTOFF_LAST_OPEN,
    WINDOW_END_EXCLUSIVE,
    WINDOW_START,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def test_committed_artifacts_reproduce_and_verify() -> None:
    bd.verify_btc_dataset(REPO_ROOT)  # re-derives everything + byte-compares


def test_canonical_dataset_bounds_and_firewall() -> None:
    ds = bd.load_canonical_btc_dataset(REPO_ROOT)
    assert len(ds.frame) == 2221
    assert ds.frame.index[0] == WINDOW_START
    assert ds.frame.index[-1] == RESEARCH_CUTOFF_LAST_OPEN
    # Firewall: not one BTC row at or after the research cutoff / window end.
    assert bool((ds.frame.index <= RESEARCH_CUTOFF_LAST_OPEN).all())
    assert bool((ds.frame.index < WINDOW_END_EXCLUSIVE).all())
    assert ds.frame.index[-1] < WINDOW_END_EXCLUSIVE


def test_reacquisition_audit_proves_independent_canonical_equality() -> None:
    audit = json.loads((REPO_ROOT / bd.REACQUISITION_AUDIT_RELPATH).read_bytes())
    assert audit["canonical_candles_identical"] is True
    assert audit["independent_run_ids"] is True
    assert audit["independent_source_commits"] is True
    assert audit["genesis"]["workflow_run_id"] != audit["audit"]["workflow_run_id"]
    ds = bd.load_canonical_btc_dataset(REPO_ROOT)
    assert audit["content_fingerprint"] == ds.content_fingerprint


def test_quality_report_is_clean() -> None:
    q = json.loads((REPO_ROOT / bd.QUALITY_REPORT_RELPATH).read_bytes())
    assert q["actual_daily_opens"] == q["expected_daily_opens"] == 2221
    assert q["missing_opens"] == 0
    assert q["duplicate_opens"] == 0
    assert q["all_finite"] is True
    assert q["all_prices_positive"] is True
    assert q["volume_nonnegative"] is True
    assert q["ohlcv_identity_holds"] is True
    assert q["contiguous_daily"] is True
    assert q["no_row_at_or_after_cutoff"] is True
    assert q["min_close"] > 0.0


def test_dataset_lock_binds_sub_artifacts() -> None:
    from eth_research.v2.strict import sha256_bytes

    lock = json.loads((REPO_ROOT / bd.DATASET_LOCK_RELPATH).read_bytes())
    for field, relpath in (
        ("acquisition_plan_sha256", bd.ACQUISITION_PLAN_RELPATH),
        ("reacquisition_audit_sha256", bd.REACQUISITION_AUDIT_RELPATH),
        ("dataset_manifest_sha256", bd.DATASET_MANIFEST_RELPATH),
        ("quality_report_sha256", bd.QUALITY_REPORT_RELPATH),
    ):
        assert lock[field] == sha256_bytes((REPO_ROOT / relpath).read_bytes())
    assert lock["row_count"] == 2221


def test_verify_detects_raw_body_tamper(tmp_path: Path) -> None:
    # Copy the working-tree BTC artifacts (raw bundles + frozen dataset) into a scratch root.
    root = tmp_path / "repo"
    (root / "research/v2b").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "research/v2b/raw", root / "research/v2b/raw")
    shutil.copytree(REPO_ROOT / "research/v2b/btc", root / "research/v2b/btc")
    bd.verify_btc_dataset(root)  # untouched copy verifies
    # Tamper one genesis raw body's volume (keeps OHLCV valid, changes the bytes) -> the
    # re-derived window receipt no longer matches the committed receipt -> verify fails.
    target = (
        root / "research/v2b/raw/coinbase/coinbase-btc-usd-research-genesis-001/candles_000.json"
    )
    raw = json.loads(target.read_bytes())
    raw[0][5] = raw[0][5] + 1.0  # bump one volume
    target.write_bytes(json.dumps(raw).encode())
    with pytest.raises(bd.BtcDatasetError):
        bd.verify_btc_dataset(root)
