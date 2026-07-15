"""Prospective segment-chain tests (M3D section 16).

The committed chain is rebuilt byte-for-byte from the real genesis acquisition
and verified from its genesis sentinel. Future-append fixtures exercise the
incremental rules (contiguous one-interval extension; no overlap, gap, duplicate,
or reorder) without materializing a second chronological segment.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import eth_research
from eth_research.m3d.segment import (
    SEGMENTS_KIND,
    SEGMENTS_PATH,
    build_prospective_segments_bytes,
    verify_prospective_segments,
    verify_segment_records,
)
from eth_research.m3d.validation import M3DValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
_COHORT_START = "2026-07-12T00:00:00Z"
_H = "0" * 64


def _z(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _genesis() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": SEGMENTS_KIND,
        "entry_kind": "genesis",
        "package_version": "0.7.0",
        "cohort_start": _COHORT_START,
    }


def _segment(segment_id: str, first_open: str, row_count: int) -> dict[str, object]:
    first = pd.Timestamp(first_open)
    last = first + pd.Timedelta(days=row_count - 1)
    return {
        "schema_version": 1,
        "entry_kind": "segment",
        "segment_id": segment_id,
        "source_plan_hash": _H,
        "attempt_receipt_hash": _H,
        "raw_bundle_fingerprint": _H,
        "canonical_content_fingerprint": _H,
        "first_open": _z(first),
        "last_open": _z(last),
        "row_count": row_count,
        "interval_seconds": 86400,
        "created_at_utc": "2026-07-15T00:00:00Z",
        "package_version": "0.7.0",
        "source_commit": "a" * 40,
        "publication_bundle_hash": _H,
    }


# --------------------------------------------------------------------------- #
# real committed chain                                                        #
# --------------------------------------------------------------------------- #
def test_real_chain_verifies_and_starts_at_cohort_start() -> None:
    records = verify_prospective_segments(REPO_ROOT)
    assert records[0]["entry_kind"] == "genesis"
    assert records[0]["cohort_start"] == _COHORT_START
    segment = records[1]
    assert segment["first_open"] == _COHORT_START
    assert segment["last_open"] == "2026-07-14T00:00:00Z"
    assert segment["row_count"] == 3
    assert segment["interval_seconds"] == 86400
    # The segment binds the reproducible cohort canonical fingerprint.
    assert (
        segment["canonical_content_fingerprint"]
        == "bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507"
    )


def test_real_chain_rebuild_is_byte_stable() -> None:
    committed = (REPO_ROOT / SEGMENTS_PATH).read_bytes()
    assert committed == build_prospective_segments_bytes(REPO_ROOT)


# --------------------------------------------------------------------------- #
# future-append fixtures (rules only, no real second segment)                 #
# --------------------------------------------------------------------------- #
def test_valid_contiguous_future_segment_is_accepted() -> None:
    records = [
        _genesis(),
        _segment("prospective-segment-000", _COHORT_START, 3),  # last open 07-14
        _segment("prospective-segment-001", "2026-07-15T00:00:00Z", 2),  # starts +1 interval
    ]
    assert verify_segment_records(records) is records


def test_future_segment_with_a_gap_is_rejected() -> None:
    records = [
        _genesis(),
        _segment("prospective-segment-000", _COHORT_START, 3),  # last open 07-14
        _segment("prospective-segment-001", "2026-07-16T00:00:00Z", 2),  # one-day gap
    ]
    with pytest.raises(M3DValidationError, match="one interval"):
        verify_segment_records(records)


def test_future_segment_that_overlaps_is_rejected() -> None:
    records = [
        _genesis(),
        _segment("prospective-segment-000", _COHORT_START, 3),  # last open 07-14
        _segment("prospective-segment-001", "2026-07-14T00:00:00Z", 2),  # overlaps last open
    ]
    with pytest.raises(M3DValidationError, match="overlap"):
        verify_segment_records(records)


def test_chain_without_a_genesis_sentinel_is_rejected() -> None:
    records = [_segment("prospective-segment-000", _COHORT_START, 3)]
    with pytest.raises(M3DValidationError, match="genesis sentinel"):
        verify_segment_records(records)


def test_first_segment_not_at_cohort_start_is_rejected() -> None:
    records = [_genesis(), _segment("prospective-segment-000", "2026-07-13T00:00:00Z", 3)]
    with pytest.raises(M3DValidationError, match="fixed cohort start"):
        verify_segment_records(records)
