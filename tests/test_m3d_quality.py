"""Prospective quality-audit tests (M3D section 18).

Integrity only: the real committed cohort has zero structural errors; the audit
counts data-diagnostic warnings without ranking, labelling, or selecting; and any
overlap with the frozen M2B dataset is a HARD STOP.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import eth_research
from eth_research.m3d.quality import build_prospective_quality_bytes, verify_prospective_quality
from eth_research.m3d.validation import M3DValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

# Coinbase field order [time, low, high, open, close, volume].
_ROWS_ZERO_VOL = [
    [1783987200, 1771.36, 1895.61, 1774.57, 1890.63, 138211.47],
    [1783900800, 1748.05, 1844.67, 1805.56, 1774.57, 0.0],  # zero-volume day
    [1783814400, 1778.55, 1825.46, 1786.81, 1805.51, 39647.67],
]


def test_real_quality_report_has_zero_errors() -> None:
    report = verify_prospective_quality(REPO_ROOT)
    assert report["total_errors"] == 0
    assert report["row_count"] == 3
    assert all(error["count"] == 0 for error in report["errors"])


def test_overlap_with_m2b_is_a_hard_stop(
    tmp_path: Path, m3d_staged_cohort: Callable[..., Path]
) -> None:
    # Move the M2B final candle forward so prospective rows overlap it.
    m3d_staged_cohort(tmp_path, m2b_last_open="2026-07-13T00:00:00+00:00")
    with pytest.raises(M3DValidationError, match="overlap"):
        build_prospective_quality_bytes(tmp_path)


def test_zero_volume_is_reported_as_a_warning_not_an_error(
    tmp_path: Path, m3d_staged_cohort: Callable[..., Path]
) -> None:
    repo = m3d_staged_cohort(tmp_path, rows=_ROWS_ZERO_VOL)
    (repo / "research/m3d/prospective_quality.json").write_bytes(
        build_prospective_quality_bytes(repo)
    )
    report = verify_prospective_quality(repo)
    assert report["total_errors"] == 0
    warnings = {w["category"]: w for w in report["warnings"]}
    assert warnings["zero_volume"]["count"] == 1
    assert warnings["zero_volume"]["example_timestamps"] == ["2026-07-13T00:00:00Z"]
