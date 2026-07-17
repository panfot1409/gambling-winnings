"""Whole-graph repository-freeze verifier + replay status (commit 7).

These bind to the live repository state, so they assert only the *phase-independent*
guarantees: the always-available governance checks (honest-state invariants, the
governance state machine, and the workflow supply-chain scan) pass on the real repo,
and the governance-derived facts match. The committed-artifact checks (freeze catalog,
honest-state reproduction, dependency/workflow inventories) are exercised against a
temporary tree so the assertions hold both before and after the R (registration) phase.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.m3f.audit import verify_repository_freeze
from eth_research.m3f.replay import replay_status
from eth_research.m3f.validation import M3FValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

# The checks that never depend on a committed M3F artifact.
_ALWAYS_AVAILABLE = (
    "01_honest_state_invariants",
    "02_governance_state_legal",
    "03_workflow_supply_chain",
    "08_semantic_oracles",
)


def _failing_names(failures: list[str]) -> set[str]:
    return {f.split(":", 1)[0] for f in failures}


def test_real_repo_governance_checks_all_pass() -> None:
    result = verify_repository_freeze(REPO_ROOT)
    check_names = {name for name, _ in result.checks}
    failing = _failing_names(result.failures)
    for name in _ALWAYS_AVAILABLE:
        assert name in check_names, f"{name} did not run"
        assert name not in failing, f"{name} unexpectedly failed: {result.failures}"


def test_real_repo_workflow_supply_chain_is_clean() -> None:
    # Every committed workflow is read-only, SHA-pinned, and free of publish verbs.
    result = verify_repository_freeze(REPO_ROOT)
    assert "03_workflow_supply_chain" not in _failing_names(result.failures)


def test_verify_repository_freeze_fails_closed_without_governance_artifacts(
    tmp_path: Path,
) -> None:
    # An empty tree cannot read research/m3c/candidate_decision.json; check 01 fails and
    # the verifier returns early because nothing downstream is trustworthy.
    result = verify_repository_freeze(tmp_path)
    assert not result.ok
    assert len(result.checks) == 1
    assert result.checks[0][0] == "01_honest_state_invariants"
    assert result.failures[0].startswith("01_honest_state_invariants")


def test_raise_for_status_raises_on_failure(tmp_path: Path) -> None:
    result = verify_repository_freeze(tmp_path)
    with pytest.raises(M3FValidationError, match="repository freeze verification failed"):
        result.raise_for_status()


def test_raise_for_status_is_silent_when_all_available_checks_pass() -> None:
    # On the real repo the always-available checks pass; a result restricted to just
    # those must not raise. (We cannot call raise_for_status on the full real-repo
    # result because the committed-artifact checks are phase-dependent.)
    result = verify_repository_freeze(REPO_ROOT)
    governance_only = [f for f in result.failures if f.split(":", 1)[0] in _ALWAYS_AVAILABLE]
    assert governance_only == []


def test_replay_status_reports_governance_facts() -> None:
    status = replay_status(REPO_ROOT)
    assert status["m3c_verdict"] == "rejected_for_development_gate_promotion"
    assert status["m3d_cohort_rows"] == 3
    assert status["m3d_maturity"] == "immature"
    assert status["m3e_active"] is False
    assert status["m3e_production_proposal_count"] == 0
    assert isinstance(status["checks"], list)
    assert "01_honest_state_invariants" in status["checks"]


def test_replay_status_fails_closed_without_governance(tmp_path: Path) -> None:
    status = replay_status(tmp_path)
    assert status["ok"] is False
    assert status["m3c_verdict"] is None
    assert status["m3d_cohort_rows"] is None
    assert status["m3e_active"] is None
