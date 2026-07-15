"""Raw-bundle transformation + transformation-evidence tests (M3D section 15).

These verify the real committed prospective acquisition (genesis + audit) as the
primary evidence: the retained raw bytes re-derive, byte-for-byte, into canonical
chronological OHLCV rows via the reviewed Coinbase adapter, and the two
independent attempts yield identical canonical content. Synthetic cases cover
determinism and receipt-binding rejection.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import eth_research
from eth_research.m3d.raw_bundle import (
    build_raw_bundles,
    cohort_canonical_fingerprint,
    combined_canonical_rows,
)
from eth_research.m3d.validation import M3DValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
GENESIS = "coinbase-eth-usd-prospective-genesis-001"
AUDIT = "coinbase-eth-usd-prospective-audit-002"
_GENESIS_FINGERPRINT = "bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507"


# --------------------------------------------------------------------------- #
# real committed acquisition                                                  #
# --------------------------------------------------------------------------- #
def test_real_genesis_transforms_to_three_completed_candles() -> None:
    bundles = build_raw_bundles(REPO_ROOT, GENESIS)
    rows = combined_canonical_rows(bundles)
    assert len(bundles) == 1
    assert [r[0] for r in rows] == [
        "2026-07-12T00:00:00Z",
        "2026-07-13T00:00:00Z",
        "2026-07-14T00:00:00Z",
    ]
    # Coinbase [time, low, high, open, close, volume] -> canonical
    # [ts, open, high, low, close, volume]; the 07-12 candle is the fixed start.
    assert rows[0] == ["2026-07-12T00:00:00Z", 1786.81, 1825.46, 1778.55, 1805.51, 39647.67901761]


def test_real_genesis_fingerprint_is_stable_and_deterministic() -> None:
    a = cohort_canonical_fingerprint(build_raw_bundles(REPO_ROOT, GENESIS))
    b = cohort_canonical_fingerprint(build_raw_bundles(REPO_ROOT, GENESIS))
    assert a == b == _GENESIS_FINGERPRINT


def test_real_audit_reacquisition_matches_genesis_canonically() -> None:
    genesis = combined_canonical_rows(build_raw_bundles(REPO_ROOT, GENESIS))
    audit = combined_canonical_rows(build_raw_bundles(REPO_ROOT, AUDIT))
    assert genesis == audit
    assert cohort_canonical_fingerprint(build_raw_bundles(REPO_ROOT, AUDIT)) == _GENESIS_FINGERPRINT


def test_real_bundle_rederives_row_count_and_bounds_from_receipt() -> None:
    (bundle,) = build_raw_bundles(REPO_ROOT, GENESIS)
    assert bundle.row_count == 3
    assert bundle.first_open == "2026-07-12T00:00:00Z"
    assert bundle.last_open == "2026-07-14T00:00:00Z"
    # start_param/end_param are the inclusive Coinbase request opens (provenance).
    assert bundle.start_param == "2026-07-12T00:00:00Z"
    assert bundle.end_param == "2026-07-14T00:00:00Z"


# --------------------------------------------------------------------------- #
# synthetic determinism + receipt binding                                     #
# --------------------------------------------------------------------------- #
def test_synthetic_bundle_is_deterministic(
    tmp_path: Path, m3d_staged_cohort: Callable[..., Path]
) -> None:
    repo = m3d_staged_cohort(tmp_path)
    a = cohort_canonical_fingerprint(build_raw_bundles(repo, GENESIS))
    b = cohort_canonical_fingerprint(build_raw_bundles(repo, GENESIS))
    assert a == b


def test_bundle_rejects_raw_bytes_that_no_longer_match_the_receipt(
    tmp_path: Path, m3d_staged_cohort: Callable[..., Path]
) -> None:
    repo = m3d_staged_cohort(tmp_path)
    raw = repo / "research/m3d/raw/coinbase" / GENESIS
    body = next(p for p in raw.iterdir() if p.name.startswith("coinbase-eth-usd-1d"))
    rows = json.loads(body.read_bytes())
    rows[0][4] = rows[0][4] + 1.0  # perturb a close price after the receipt was written
    body.write_bytes(json.dumps(rows).encode())
    with pytest.raises(M3DValidationError, match="SHA-256 does not match the receipt"):
        build_raw_bundles(repo, GENESIS)
