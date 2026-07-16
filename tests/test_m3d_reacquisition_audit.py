"""Independent reacquisition audit tests (M3D section 14/17).

The real committed genesis and audit attempts must reproduce the same canonical
cohort under distinct provenance; a synthetic attempt whose content differs is a
HARD STOP.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import eth_research
from eth_research.m3d.acquisition_plan import AUDIT_ATTEMPT_ID, GENESIS_ATTEMPT_ID
from eth_research.m3d.reacquisition_audit import (
    build_reacquisition_audit_bytes,
    verify_reacquisition_audit,
)
from eth_research.m3d.validation import M3DValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

# Coinbase field order [time, low, high, open, close, volume]; three candles.
_ROWS = [
    [1783987200, 1771.36, 1895.61, 1774.57, 1890.63, 138211.47661573],
    [1783900800, 1748.05, 1844.67, 1805.56, 1774.57, 106281.79272453],
    [1783814400, 1778.55, 1825.46, 1786.81, 1805.51, 39647.67901761],
]


def test_real_reacquisition_audit_verifies_a_match() -> None:
    mapping = verify_reacquisition_audit(REPO_ROOT)
    assert mapping["canonical_content_match"] is True
    assert mapping["differing_fields"] == 0
    assert mapping["independent_plans"] is True


def test_real_audit_binds_distinct_independent_provenance() -> None:
    mapping = verify_reacquisition_audit(REPO_ROOT)
    genesis, audit = mapping["genesis"], mapping["audit"]
    assert genesis["plan_sha256"] != audit["plan_sha256"]
    assert genesis["source_commit"] != audit["source_commit"]
    assert genesis["workflow_run_id"] != audit["workflow_run_id"]
    assert genesis["canonical_content_fingerprint"] == audit["canonical_content_fingerprint"]


def test_divergent_audit_content_is_a_hard_stop(
    tmp_path: Path, m3d_staged_cohort: Callable[..., Path]
) -> None:
    m3d_staged_cohort(tmp_path, rows=_ROWS, attempt_id=GENESIS_ATTEMPT_ID)
    diverged = [list(row) for row in _ROWS]
    diverged[0][4] = diverged[0][4] + 25.0  # a different close on the audit attempt
    m3d_staged_cohort(tmp_path, rows=diverged, attempt_id=AUDIT_ATTEMPT_ID)
    with pytest.raises(M3DValidationError, match="canonical content differ"):
        build_reacquisition_audit_bytes(tmp_path)
