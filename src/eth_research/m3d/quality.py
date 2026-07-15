"""Prospective cohort data-quality audit — integrity only, no performance metrics.

The raw bundles are already strictly validated by the reviewed candle parser
(malformed JSON, non-numeric or non-finite values, duplicate/unsorted timestamps,
wrong interval, non-positive price, negative volume, OHLC inconsistency, rows
outside the window, and forming candles are all rejected before a bundle exists),
so a published cohort has **zero** structural errors by construction. This module
records that error inventory as counts, adds the two integrity checks that span
bundles (no overlap with the frozen M2B dataset; primary/audit canonical match is
verified elsewhere), and reports data-diagnostic **warnings** (zero volume,
extreme intraday range, extreme close-to-close move) with counts and a small,
bounded set of example timestamps. Warnings never drop a row, alter a value, rank
periods, label regimes, or select anything, and no report prints every price.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.m3d import _upstream as up
from eth_research.m3d.raw_bundle import build_raw_bundles, combined_canonical_rows
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_json_bytes,
    canonical_sha256,
    load_canonical_json_bytes,
    require_mapping,
    require_str,
)

QUALITY_PATH = "research/m3d/prospective_quality.json"
QUALITY_SCHEMA_VERSION = 1
QUALITY_KIND = "prospective_quality_report"
PRIMARY_ATTEMPT_ID = "coinbase-eth-usd-prospective-genesis-001"

_MAX_EXAMPLES = 5
# Data-diagnostic warning thresholds (integrity signals, never trading signals).
_EXTREME_RANGE_FRACTION = 0.5  # (high - low) / low
_EXTREME_MOVE_FRACTION = 0.5  # |close_t / close_{t-1} - 1|

_ERROR_CATEGORIES = (
    "malformed_response",
    "unexpected_shape",
    "nonnumeric_value",
    "nonfinite_value",
    "duplicate_timestamp",
    "unsorted_timestamp",
    "gap",
    "wrong_interval",
    "nonpositive_price",
    "negative_volume",
    "ohlc_inconsistency",
    "row_outside_plan",
    "forming_candle",
    "overlap_with_m2b",
)


def _build_document(repo_root: str | Path) -> dict[str, Any]:
    from eth_research.m3d import M3D_PACKAGE_VERSION

    bundles = build_raw_bundles(repo_root, PRIMARY_ATTEMPT_ID)
    rows = combined_canonical_rows(bundles)
    if not rows:
        raise M3DValidationError("no prospective rows to audit")

    lock = require_mapping(
        "dataset_lock", up.load_json(repo_root, "research/m2b/dataset_lock.json")
    )
    m2b_last = pd.Timestamp(require_str("last_open_time", lock["last_open_time"]))
    first_open = pd.Timestamp(rows[0][0])

    errors = dict.fromkeys(_ERROR_CATEGORIES, 0)
    # Structural errors are impossible for a parsed bundle; the one cross-dataset
    # error is a prospective row at or before the final M2B candle.
    overlap = [row[0] for row in rows if pd.Timestamp(row[0]) <= m2b_last]
    errors["overlap_with_m2b"] = len(overlap)
    if overlap:
        raise M3DValidationError(f"prospective rows overlap M2B: {overlap[:3]} (HARD STOP)")
    if not first_open > m2b_last:
        raise M3DValidationError(
            "prospective cohort must begin strictly after the final M2B candle"
        )

    zero_volume = [row[0] for row in rows if row[5] == 0.0]
    extreme_range = [
        row[0]
        for row in rows
        if row[3] > 0.0 and (row[1] - row[3]) / row[3] > _EXTREME_RANGE_FRACTION
    ]
    extreme_move = [
        later[0]
        for earlier, later in pairwise(rows)
        if earlier[4] > 0.0 and abs(later[4] / earlier[4] - 1.0) > _EXTREME_MOVE_FRACTION
    ]

    return {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "kind": QUALITY_KIND,
        "package_version": M3D_PACKAGE_VERSION,
        "attempt_id": PRIMARY_ATTEMPT_ID,
        "row_count": len(rows),
        "first_open": rows[0][0],
        "last_open": rows[-1][0],
        "m2b_final_open": up.M2B_LAST_OPEN,
        "errors": [
            {"category": category, "count": errors[category]} for category in _ERROR_CATEGORIES
        ],
        "warnings": [
            _finding("zero_volume", zero_volume),
            _finding("extreme_intraday_range", extreme_range),
            _finding("extreme_close_to_close_move", extreme_move),
        ],
        "total_errors": sum(errors.values()),
    }


def _finding(category: str, timestamps: list[str]) -> dict[str, Any]:
    return {
        "category": category,
        "count": len(timestamps),
        "example_timestamps": list(timestamps[:_MAX_EXAMPLES]),
    }


def build_prospective_quality_bytes(repo_root: str | Path) -> bytes:
    """Deterministically render the prospective quality report bytes."""
    return canonical_json_bytes(_build_document(repo_root))


def prospective_quality_sha256(repo_root: str | Path) -> str:
    return canonical_sha256(_build_document(repo_root))


def verify_prospective_quality(repo_root: str | Path) -> dict[str, Any]:
    """Verify the committed quality report reproduces and reports zero errors."""
    raw, doc = load_canonical_json_bytes(Path(repo_root) / QUALITY_PATH, "prospective_quality")
    mapping = require_mapping("prospective_quality", doc)
    if raw != build_prospective_quality_bytes(repo_root):
        raise M3DValidationError("committed quality report does not match the rebuilt report")
    if mapping["total_errors"] != 0:
        raise M3DValidationError("prospective cohort quality report has structural errors")
    return mapping
