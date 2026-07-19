"""V2B §22 — the stringent, multiplicity-corrected nomination rule (at most one candidate).

A candidate is *eligible* only if it clears **every** pre-registered gate; among the eligible set at
most one is nominated (the highest primary point estimate; an exact tie nominates none). The rule is
a pure function of the gathered evidence, so it is unit-tested on synthetic gate inputs and applied
mechanically — never re-tuned after seeing a result — in the one-shot run.

The seven gates, all required:

1. primary paired 95% lower bound > 0 (accepted bootstrap, primary cost);
2. stressed-cost 95% lower bound > 0;
3. latency-stressed 95% lower bound > 0 (one extra bar of execution delay);
4. a strict majority of out-of-sample folds beat the benchmark;
5. **the family-wise-corrected one-sided lower bound > 0** (``0.05 / total_family_count``);
6. the Monte-Carlo sign-flip p-value is at or below the corrected per-family alpha;
7. every frozen parameter-neighborhood tuple keeps a primary 95% lower bound > 0 (robust, not
   fragile).

No gate makes a claim of edge on its own; nomination only forwards a candidate to an independent
development-gate review, and never asserts validation, deployment readiness, or sell-ready status.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.strict import V2ValidationError

NOMINATION_SCHEMA_VERSION: int = 1
TIE_BEHAVIOR: str = "highest_primary_point_estimate_else_none"


class V2BNominationError(V2ValidationError):
    """A nomination-gate input was malformed."""


@dataclass(frozen=True, slots=True)
class CandidateGates:
    """Every pre-registered gate outcome for one candidate, plus its primary point estimate."""

    candidate_id: str
    primary_lower_above_zero: bool
    stressed_lower_above_zero: bool
    latency_lower_above_zero: bool
    strict_fold_majority: bool
    corrected_lower_above_zero: bool
    mc_supports: bool
    sensitivity_all_above_zero: bool
    primary_point_estimate: float

    def gate_flags(self) -> dict[str, bool]:
        return {
            "primary_lower_above_zero": self.primary_lower_above_zero,
            "stressed_lower_above_zero": self.stressed_lower_above_zero,
            "latency_lower_above_zero": self.latency_lower_above_zero,
            "strict_fold_majority": self.strict_fold_majority,
            "corrected_lower_above_zero": self.corrected_lower_above_zero,
            "mc_supports": self.mc_supports,
            "sensitivity_all_above_zero": self.sensitivity_all_above_zero,
        }

    @property
    def eligible(self) -> bool:
        """Eligible iff every gate is satisfied."""
        return all(self.gate_flags().values())

    def to_canonical(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "gates": self.gate_flags(),
            "eligible": self.eligible,
            "primary_point_estimate": self.primary_point_estimate,
        }


def strict_fold_majority(folds_beating: int, fold_count: int) -> bool:
    """A strict majority: more than half the out-of-sample folds beat the benchmark."""
    if fold_count <= 0:
        raise V2BNominationError("fold_count must be positive")
    return folds_beating > fold_count / 2.0


def build_gates(
    candidate_id: str,
    *,
    primary_lower_above_zero: bool,
    stressed_lower_above_zero: bool,
    latency_lower_above_zero: bool,
    folds_beating: int,
    fold_count: int,
    corrected_lower_above_zero: bool,
    mc_p_value: float,
    corrected_alpha: float,
    sensitivity_all_above_zero: bool,
    primary_point_estimate: float,
) -> CandidateGates:
    """Assemble one candidate's gates (mc supports iff ``mc_p_value <= corrected_alpha``)."""
    return CandidateGates(
        candidate_id=candidate_id,
        primary_lower_above_zero=primary_lower_above_zero,
        stressed_lower_above_zero=stressed_lower_above_zero,
        latency_lower_above_zero=latency_lower_above_zero,
        strict_fold_majority=strict_fold_majority(folds_beating, fold_count),
        corrected_lower_above_zero=corrected_lower_above_zero,
        mc_supports=mc_p_value <= corrected_alpha,
        sensitivity_all_above_zero=sensitivity_all_above_zero,
        primary_point_estimate=primary_point_estimate,
    )


@dataclass(frozen=True, slots=True)
class NominationDecision:
    """The terminal nomination outcome (at most one candidate) and the per-candidate gate record."""

    nominated_candidate_id: str | None
    eligible_candidate_ids: tuple[str, ...]
    reason: str
    gates: tuple[CandidateGates, ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": NOMINATION_SCHEMA_VERSION,
            "tie_behavior": TIE_BEHAVIOR,
            "nominated_candidate_id": self.nominated_candidate_id,
            "eligible_candidate_ids": list(self.eligible_candidate_ids),
            "reason": self.reason,
            "gates": [g.to_canonical() for g in self.gates],
        }


def decide_nomination(gates: tuple[CandidateGates, ...]) -> NominationDecision:
    """Apply the ≤1 rule: nominate the single eligible candidate with the highest point estimate.

    None eligible → no nomination. Two-or-more eligible → the strictly-highest primary point
    estimate wins; an exact tie for the top nominates none (per ``TIE_BEHAVIOR``).
    """
    if not gates:
        raise V2BNominationError("no candidate gates provided")
    ids = [g.candidate_id for g in gates]
    if len(set(ids)) != len(ids):
        raise V2BNominationError("duplicate candidate ids in the gate set")
    eligible = tuple(g for g in gates if g.eligible)
    eligible_ids = tuple(g.candidate_id for g in eligible)
    if not eligible:
        return NominationDecision(None, eligible_ids, "no candidate cleared every gate", gates)
    ranked = sorted(eligible, key=lambda g: g.primary_point_estimate, reverse=True)
    if len(ranked) >= 2 and ranked[0].primary_point_estimate == ranked[1].primary_point_estimate:
        return NominationDecision(
            None, eligible_ids, "exact tie for the highest primary point estimate", gates
        )
    top = ranked[0]
    return NominationDecision(
        top.candidate_id,
        eligible_ids,
        f"{top.candidate_id} cleared every gate with the highest primary point estimate",
        gates,
    )
