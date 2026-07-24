"""Read-only repository-governance state machine for Milestone 3F.

M3F only *derives and verifies* the current governance state; it executes no
transition. The point is to make impossible states structurally detectable: a rejected
candidate that is also promoted, an immature cohort that is also evaluation-authorized,
an inactive publisher that also has a production proposal, a "sealed/untouched" claim
against a nonempty ledger, or an "inactive" claim against a write-capable workflow are
all refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_research.m3f.validation import (
    M3FValidationError,
    require_bool,
    require_int,
    require_mapping,
    require_str,
)

VALID_STATES = frozenset(
    {
        "accepted_stack_stable",
        "rejected_candidate_terminal",
        "immature_cohort_unauthorized",
        "review_only_ready_inactive",
        "reviewed_growth_active",
    }
)


@dataclass(frozen=True)
class GovernanceState:
    labels: frozenset[str]

    def is_legal(self) -> bool:
        return self.labels <= VALID_STATES and bool(self.labels)


def derive_state(honest_state: dict[str, Any]) -> GovernanceState:
    """Derive the governance-state label set from an honest-state mapping, refusing
    any structurally impossible combination."""
    s = require_mapping(honest_state, "honest_state")
    verdict = require_str(s.get("m3c_candidate_verdict"), "m3c_candidate_verdict")
    rows = require_int(s.get("m3d_cohort_row_count"), "m3d_cohort_row_count")
    threshold = require_int(s.get("m3d_maturity_threshold"), "m3d_maturity_threshold")
    maturity = require_str(s.get("m3d_maturity_state"), "m3d_maturity_state")
    authorized = require_bool(s.get("m3d_evaluation_authorized"), "m3d_evaluation_authorized")
    active = require_bool(s.get("m3e_active"), "m3e_active")
    proposals = require_int(s.get("m3e_production_proposal_count"), "m3e_production_proposal_count")
    can_write = require_bool(
        s.get("standing_workflow_can_write_contents"), "standing_workflow_can_write_contents"
    )

    labels: set[str] = {"accepted_stack_stable"}

    # rejected candidate is terminal — never "promoted".
    if verdict == "rejected_for_development_gate_promotion":
        labels.add("rejected_candidate_terminal")
    elif verdict.startswith("eligible") or "promot" in verdict:
        raise M3FValidationError(f"impossible: rejected candidate reported as {verdict!r}")

    # immature cohort must be unauthorized; maturity is count vs threshold.
    computed_mature = rows >= threshold
    if maturity == "immature":
        if computed_mature:
            raise M3FValidationError("impossible: immature label but row_count >= threshold")
        if authorized:
            raise M3FValidationError("impossible: immature cohort is evaluation_authorized")
        labels.add("immature_cohort_unauthorized")
    elif maturity == "mature" and rows < threshold:
        raise M3FValidationError("impossible: mature label but row_count < threshold")

    # review-only ready + inactive: no proposal, no write-capable workflow.
    # V2D-anchored active growth: every production proposal must be covered by an
    # acceptance record (an uncovered proposal stays exactly as impossible as it
    # was pre-acceptance), and no unauthorized workflow may hold a write grant.
    accepted = require_int(s.get("m3e_accepted_proposal_count", 0), "m3e_accepted_proposal_count")
    if not active:
        if proposals != 0:
            raise M3FValidationError("impossible: inactive M3E but a production proposal exists")
        if can_write:
            raise M3FValidationError("impossible: inactive M3E but a write-capable workflow exists")
        if accepted != 0:
            raise M3FValidationError("impossible: inactive M3E but an acceptance record exists")
        labels.add("review_only_ready_inactive")
    else:
        if proposals != accepted:
            raise M3FValidationError(
                "impossible: active M3E with production proposal(s) not covered by "
                "acceptance records"
            )
        if can_write:
            raise M3FValidationError("impossible: unauthorized write-capable workflow under V2D")
        labels.add("reviewed_growth_active")

    state = GovernanceState(frozenset(labels))
    if not state.is_legal():
        raise M3FValidationError(f"derived an illegal state: {sorted(state.labels)}")
    return state


def verify_state(honest_state: dict[str, Any]) -> GovernanceState:
    """Derive + assert the state is legal; raises on any impossible combination.

    The expected terminal set is exact for each lawful mode: the accepted
    pre-V2D posture (``review_only_ready_inactive``) or the V2D-anchored,
    fully-accepted growth posture (``reviewed_growth_active``) — never a
    mixture, never anything else.
    """
    state = derive_state(honest_state)
    active = require_bool(
        require_mapping(honest_state, "honest_state").get("m3e_active"), "m3e_active"
    )
    expected = {
        "accepted_stack_stable",
        "rejected_candidate_terminal",
        "immature_cohort_unauthorized",
        "reviewed_growth_active" if active else "review_only_ready_inactive",
    }
    if set(state.labels) != expected:
        raise M3FValidationError(
            f"governance state is not the accepted terminal set: {state.labels}"
        )
    return state
