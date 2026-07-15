"""Maturity / evaluation-prohibition firewall + graph verifier (M3D sections 19-21)."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import eth_research
from eth_research.m3d.maturity import (
    evaluate_maturity,
    require_data_only_operation,
    require_no_evaluation_capability,
)
from eth_research.m3d.validation import M3DValidationError
from eth_research.m3d.verify_m3d_program import (
    _scan_forbidden_fields,
    _scan_prohibited_imports,
    verify_m3d_program,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# graph verifier                                                              #
# --------------------------------------------------------------------------- #
def test_verify_m3d_program_runs_the_full_chain() -> None:
    checks = verify_m3d_program(REPO_ROOT)
    names = [name for name, _ in checks]
    assert len(names) == 25
    assert names[0] == "01_upstream_anchors"
    assert "22_immature_and_unauthorized" in names
    assert "24_no_unexpected_write_workflow" in names


def test_verify_m3d_program_has_no_skip_parameter() -> None:
    # No optional parameter may skip a check.
    params = list(inspect.signature(verify_m3d_program).parameters)
    assert params == ["repo_root"]


def test_no_prohibited_imports_in_the_isolated_package() -> None:
    _scan_prohibited_imports(REPO_ROOT)  # raises on any engine/strategy/eval import


# --------------------------------------------------------------------------- #
# maturity firewall                                                           #
# --------------------------------------------------------------------------- #
def test_cohort_is_immature_and_never_authorized() -> None:
    state = evaluate_maturity(REPO_ROOT)
    assert state.maturity_state == "immature"
    assert state.is_mature is False
    assert state.evaluation_authorized is False
    assert state.remaining_rows == 362


def test_data_only_operation_allowlist_is_fail_closed() -> None:
    for allowed in ("acquire", "transform", "quality_audit", "verify", "replay"):
        assert require_data_only_operation(allowed) == allowed
    for forbidden in ("evaluate", "backtest", "promote", "rank", "declare_candidate"):
        with pytest.raises(M3DValidationError):
            require_data_only_operation(forbidden)
    with pytest.raises(M3DValidationError, match="not on the data-only allowlist"):
        require_data_only_operation("mint_nft")


def test_no_evaluation_capability_on_the_real_repo() -> None:
    facts = require_no_evaluation_capability(REPO_ROOT)
    assert facts["evaluation_ledger_byte_count"] == 0
    assert facts["evaluation_authorized"] is False


def test_a_forbidden_evaluation_artifact_is_rejected(tmp_path: Path) -> None:
    m3d = tmp_path / "research/m3d"
    m3d.mkdir(parents=True)
    (m3d / "prospective_evaluations.jsonl").write_bytes(b"")  # byte-empty ledger present
    (m3d / "candidate_results.json").write_text("{}")  # a smuggled evaluation output
    with pytest.raises(M3DValidationError, match="forbidden evaluation-output"):
        require_no_evaluation_capability(tmp_path)


def test_a_smuggled_performance_field_is_rejected() -> None:
    with pytest.raises(M3DValidationError, match="smuggled evaluation field"):
        _scan_forbidden_fields({"row_count": 3, "diagnostics": {"sharpe_ratio": 1.2}})
    # A clean governance document passes.
    _scan_forbidden_fields({"row_count": 3, "maturity_state": "immature"})
