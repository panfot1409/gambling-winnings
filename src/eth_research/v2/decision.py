"""The V2A nomination decision: apply the pre-registered rule to the candidate evidence.

Given a :class:`~eth_research.v2.evaluator.ProgramEvaluation` and the pre-registered
:class:`~eth_research.v2.protocol.ResearchProtocol`, this module mechanically assigns each candidate
a V2A-emittable status and nominates **at most one** candidate. It cannot emit anything outside the
constitution's vocabulary, and it never nominates more than one:

* a candidate meeting every enabled criterion is ``research_stage_supported``;
* a candidate failing any is ``research_stage_rejected`` (a valid outcome);
* the single supported candidate with the strictly-highest primary bootstrap point estimate is
  promoted to ``eligible_for_development_gate_review``; a tie for the top, or no supported
  candidate, nominates nobody.

The programme's standing posture is always ``not_sell_ready``. No status here is an out-of-sample,
forward, or live claim.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.constitution import (
    STANDING_POSTURE,
    CommercialEvidenceConstitution,
    require_v2a_emittable_status,
)
from eth_research.v2.evaluator import ProgramEvaluation
from eth_research.v2.protocol import ResearchProtocol
from eth_research.v2.strict import V2ValidationError, canonical_sha256

DECISION_SCHEMA_VERSION: int = 1

SUPPORTED: str = "research_stage_supported"
REJECTED: str = "research_stage_rejected"
NOMINATED: str = "eligible_for_development_gate_review"


class DecisionError(V2ValidationError):
    """The decision was malformed or violated the at-most-one-nomination rule."""


@dataclass(frozen=True, slots=True)
class CandidateOutcome:
    """One candidate's mechanically-derived status and the criteria that produced it."""

    candidate_id: str
    status: str
    criteria: dict[str, bool]
    nominated: bool

    def to_canonical(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "criteria": dict(sorted(self.criteria.items())),
            "nominated": self.nominated,
        }


@dataclass(frozen=True, slots=True)
class ProgramDecision:
    """The committed, hashable programme decision: per-candidate status + at most one nomination."""

    schema_version: int
    protocol_fingerprint: str
    constitution_fingerprint: str
    standing_posture: str
    outcomes: tuple[CandidateOutcome, ...]
    nominated_candidate_id: str | None

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "protocol_fingerprint": self.protocol_fingerprint,
            "constitution_fingerprint": self.constitution_fingerprint,
            "standing_posture": self.standing_posture,
            "outcomes": [o.to_canonical() for o in self.outcomes],
            "nominated_candidate_id": self.nominated_candidate_id,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


def _criteria_for(evaluation: object, protocol: ResearchProtocol) -> dict[str, bool]:
    from eth_research.v2.evaluator import CandidateEvaluation

    assert isinstance(evaluation, CandidateEvaluation)
    c = protocol.criteria
    return {
        "folds_beating_benchmark": evaluation.folds_beating_benchmark
        >= c.min_folds_beating_benchmark,
        "primary_lower_above_zero": (
            evaluation.primary_lower_above_zero if c.bootstrap_lower_bound_above_zero else True
        ),
        "stressed_robustness": (
            evaluation.stressed_lower_above_zero if c.require_stressed_robustness else True
        ),
        "positive_sharpe": (
            evaluation.aggregate_sharpe > 0.0 if c.require_positive_sharpe else True
        ),
    }


def decide(program: ProgramEvaluation, protocol: ResearchProtocol) -> ProgramDecision:
    """Apply the pre-registered rule; return the mechanical programme decision (fail-closed)."""
    if program.protocol_fingerprint != protocol.fingerprint():
        raise DecisionError("evaluation was produced under a different protocol")

    supported: list[tuple[str, float]] = []
    criteria_by_id: dict[str, dict[str, bool]] = {}
    for evaluation in program.evaluations:
        criteria = _criteria_for(evaluation, protocol)
        criteria_by_id[evaluation.candidate_id] = criteria
        if all(criteria.values()):
            supported.append((evaluation.candidate_id, evaluation.primary_point_estimate))

    # Nominate the single supported candidate with the strictly-highest point estimate (else none).
    nominated_id: str | None = None
    if supported:
        top_estimate = max(est for _, est in supported)
        leaders = [cid for cid, est in supported if est == top_estimate]
        if len(leaders) == 1:
            nominated_id = leaders[0]

    outcomes: list[CandidateOutcome] = []
    for evaluation in program.evaluations:
        cid = evaluation.candidate_id
        criteria = criteria_by_id[cid]
        is_supported = all(criteria.values())
        nominated = cid == nominated_id
        if nominated:
            status = NOMINATED
        elif is_supported:
            status = SUPPORTED
        else:
            status = REJECTED
        require_v2a_emittable_status(f"decision.{cid}.status", status)
        outcomes.append(
            CandidateOutcome(
                candidate_id=cid, status=status, criteria=criteria, nominated=nominated
            )
        )

    decision = ProgramDecision(
        schema_version=DECISION_SCHEMA_VERSION,
        protocol_fingerprint=protocol.fingerprint(),
        constitution_fingerprint=CommercialEvidenceConstitution.current().fingerprint(),
        standing_posture=STANDING_POSTURE,
        outcomes=tuple(outcomes),
        nominated_candidate_id=nominated_id,
    )
    _assert_decision_invariants(decision)
    return decision


def _assert_decision_invariants(decision: ProgramDecision) -> None:
    nominations = [o for o in decision.outcomes if o.nominated]
    if len(nominations) > 1:
        raise DecisionError("more than one candidate nominated")
    if nominations and nominations[0].candidate_id != decision.nominated_candidate_id:
        raise DecisionError("nominated flag disagrees with nominated_candidate_id")
    if decision.nominated_candidate_id is not None and not nominations:
        raise DecisionError("nominated_candidate_id set but no outcome carries the nomination")
    if decision.standing_posture != STANDING_POSTURE:
        raise DecisionError(f"standing posture must be {STANDING_POSTURE!r}")
    for outcome in decision.outcomes:
        require_v2a_emittable_status(f"decision.{outcome.candidate_id}.status", outcome.status)
        if outcome.nominated and outcome.status != NOMINATED:
            raise DecisionError(
                f"{outcome.candidate_id} nominated but status is {outcome.status!r}"
            )


def parse_decision(raw: object) -> ProgramDecision:
    """Strictly decode a committed decision artifact and re-assert its invariants."""
    from eth_research.v2.strict import (
        require_bool,
        require_exact_keys,
        require_hex64,
        require_int,
        require_list,
        require_mapping,
        require_nonempty_str,
    )

    obj = require_mapping("decision", raw)
    require_exact_keys(
        "decision",
        obj,
        frozenset(
            {
                "schema_version",
                "protocol_fingerprint",
                "constitution_fingerprint",
                "standing_posture",
                "outcomes",
                "nominated_candidate_id",
            }
        ),
    )

    def _outcome(label: str, value: object) -> CandidateOutcome:
        o = require_mapping(label, value)
        require_exact_keys(label, o, frozenset({"candidate_id", "status", "criteria", "nominated"}))
        crit_obj = require_mapping(f"{label}.criteria", o["criteria"])
        criteria = {
            require_nonempty_str(f"{label}.criteria.key", k): require_bool(
                f"{label}.criteria.{k}", v
            )
            for k, v in crit_obj.items()
        }
        return CandidateOutcome(
            candidate_id=require_nonempty_str(f"{label}.candidate_id", o["candidate_id"]),
            status=require_v2a_emittable_status(f"{label}.status", o["status"]),
            criteria=criteria,
            nominated=require_bool(f"{label}.nominated", o["nominated"]),
        )

    nominated_raw = obj["nominated_candidate_id"]
    nominated_id = (
        None
        if nominated_raw is None
        else require_nonempty_str("decision.nominated_candidate_id", nominated_raw)
    )
    decision = ProgramDecision(
        schema_version=require_int("decision.schema_version", obj["schema_version"]),
        protocol_fingerprint=require_hex64(
            "decision.protocol_fingerprint", obj["protocol_fingerprint"]
        ),
        constitution_fingerprint=require_hex64(
            "decision.constitution_fingerprint", obj["constitution_fingerprint"]
        ),
        standing_posture=require_nonempty_str("decision.standing_posture", obj["standing_posture"]),
        outcomes=tuple(require_list("decision.outcomes", obj["outcomes"], _outcome)),
        nominated_candidate_id=nominated_id,
    )
    _assert_decision_invariants(decision)
    return decision
