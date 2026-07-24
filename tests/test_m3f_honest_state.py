"""Honest-state derivation + governance state machine (commit 6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eth_research
from eth_research.m3f.honest_state import (
    derive_honest_state,
    render_honest_state_bytes,
    render_honest_state_md,
)
from eth_research.m3f.state_machine import derive_state, verify_state
from eth_research.m3f.validation import M3FValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def test_derive_real_repo_honest_state_holds_invariants() -> None:
    state = derive_honest_state(REPO_ROOT)
    assert state["m3c_candidate_verdict"] == "rejected_for_development_gate_promotion"
    # The cohort row count is the committed accepted state, cross-checked against the
    # acceptance chain rather than pinned to a literal: growth is lawful only through
    # a recorded acceptance, and the cohort must stay strictly below maturity.
    accepted = json.loads((REPO_ROOT / "research/m3e/accepted_base.json").read_text())
    assert state["m3d_cohort_row_count"] == accepted["row_count"]
    assert state["m3d_cohort_row_count"] < state["m3d_maturity_threshold"]
    assert state["m3d_maturity_state"] == "immature"
    assert state["m3d_evaluation_authorized"] is False
    # Every production proposal in the tree must be covered by an acceptance record,
    # and the V2D anchor is what makes such growth lawful at all.
    assert state["m3e_production_proposal_count"] == state["m3e_accepted_proposal_count"]
    assert state["m3e_active"] is (state["m3e_production_proposal_count"] > 0)
    if state["m3e_production_proposal_count"] > 0:
        assert (REPO_ROOT / "governance/v2d/prospective_activation.json").is_file()
        assert (REPO_ROOT / "research/m3e/acceptance_registry.jsonl").is_file()
    assert state["standing_workflow_can_write_contents"] is False
    for facts in state["ledgers"].values():
        assert facts["byte_count"] == 0


def test_honest_state_render_is_deterministic() -> None:
    a = derive_honest_state(REPO_ROOT)
    b = derive_honest_state(REPO_ROOT)
    assert render_honest_state_bytes(a) == render_honest_state_bytes(b)
    assert render_honest_state_md(a) == render_honest_state_md(b)
    assert render_honest_state_bytes(a).endswith(b"\n")


def _valid_honest_state() -> dict[str, object]:
    return {
        "m3c_candidate_verdict": "rejected_for_development_gate_promotion",
        "m3d_cohort_row_count": 3,
        "m3d_maturity_threshold": 365,
        "m3d_maturity_state": "immature",
        "m3d_evaluation_authorized": False,
        "m3e_active": False,
        "m3e_production_proposal_count": 0,
        "standing_workflow_can_write_contents": False,
    }


def test_state_machine_accepts_the_terminal_set() -> None:
    state = verify_state(_valid_honest_state())
    assert "rejected_candidate_terminal" in state.labels
    assert "review_only_ready_inactive" in state.labels
    assert state.is_legal()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("m3c_candidate_verdict", "eligible_for_development_gate_promotion"),
        ("m3d_evaluation_authorized", True),
        ("m3e_production_proposal_count", 1),  # inactive M3E with a proposal
        ("m3e_accepted_proposal_count", 1),  # inactive M3E with an acceptance
        ("standing_workflow_can_write_contents", True),
        ("m3d_cohort_row_count", 400),  # >= threshold but labelled immature
    ],
)
def test_state_machine_refuses_impossible_combinations(key: str, value: object) -> None:
    bad = _valid_honest_state()
    bad[key] = value
    with pytest.raises(M3FValidationError):
        derive_state(bad)


@pytest.mark.parametrize(
    ("proposals", "accepted"),
    [(1, 0), (2, 1), (0, 1)],
)
def test_active_m3e_refuses_proposals_not_covered_by_acceptances(
    proposals: int, accepted: int
) -> None:
    # Under the V2D anchor, growth is lawful ONLY when every committed production
    # proposal is covered by exactly one acceptance record (and vice versa); any
    # mismatch stays as impossible as an unaccepted proposal always was.
    bad = _valid_honest_state()
    bad["m3e_active"] = True
    bad["m3e_production_proposal_count"] = proposals
    bad["m3e_accepted_proposal_count"] = accepted
    with pytest.raises(M3FValidationError):
        derive_state(bad)


def test_active_m3e_with_fully_accepted_growth_is_the_exact_terminal_set() -> None:
    good = _valid_honest_state()
    good["m3e_active"] = True
    good["m3e_production_proposal_count"] = 1
    good["m3e_accepted_proposal_count"] = 1
    state = verify_state(good)
    assert set(state.labels) == {
        "accepted_stack_stable",
        "rejected_candidate_terminal",
        "immature_cohort_unauthorized",
        "reviewed_growth_active",
    }
    # the inactive label can never co-occur with the active one
    assert "review_only_ready_inactive" not in state.labels


def test_state_machine_rejects_bool_as_int_and_int_as_bool() -> None:
    bad = _valid_honest_state()
    bad["m3e_production_proposal_count"] = True  # bool where int expected
    with pytest.raises(M3FValidationError):
        derive_state(bad)
    bad2 = _valid_honest_state()
    bad2["m3e_active"] = 0  # int where bool expected
    with pytest.raises(M3FValidationError):
        derive_state(bad2)
