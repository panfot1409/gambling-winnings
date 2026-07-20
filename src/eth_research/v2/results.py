"""The immutable V2A research results: evaluation + decision + the provenance that binds them.

A results artifact is a deterministic, hashable record of the one-shot research run: which candidate
set was evaluated, under which protocol and constitution and budget, against which research-train
content, and the mechanical decision that followed. It carries no wall-clock time and no live-only
state, so it reproduces byte-for-byte from the same research-train partition.

It never carries a reserved claim status — every candidate status inside it is validated against the
constitution on build and on parse.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.budget import OneShotResearchBudget
from eth_research.v2.candidates import V2A_CANDIDATES
from eth_research.v2.constitution import (
    CommercialEvidenceConstitution,
    assert_no_reserved_status,
)
from eth_research.v2.decision import ProgramDecision, parse_decision
from eth_research.v2.evaluator import CandidateEvaluation, ProgramEvaluation
from eth_research.v2.protocol import ResearchProtocol
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_exact_keys,
    require_hex64,
    require_int,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_slug,
)

RESULTS_SCHEMA_VERSION: int = 1


class ResultsError(V2ValidationError):
    """A results artifact was malformed or internally inconsistent."""


def _require_finite(label: str, value: object) -> float:
    from eth_research.fractional.validation import require_real

    return require_real(label, value)


@dataclass(frozen=True, slots=True)
class FrozenResearchResults:
    """The committed, hashable one-shot research results."""

    schema_version: int
    run_id: str
    package_version: str
    research_train_fingerprint: str
    protocol_fingerprint: str
    constitution_fingerprint: str
    budget_fingerprint: str
    candidate_fingerprints: dict[str, str]
    evaluation: ProgramEvaluation
    decision: ProgramDecision

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "package_version": self.package_version,
            "research_train_fingerprint": self.research_train_fingerprint,
            "protocol_fingerprint": self.protocol_fingerprint,
            "constitution_fingerprint": self.constitution_fingerprint,
            "budget_fingerprint": self.budget_fingerprint,
            "candidate_fingerprints": dict(sorted(self.candidate_fingerprints.items())),
            "evaluation": self.evaluation.to_canonical(),
            "decision": self.decision.to_canonical(),
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @property
    def nominated_candidate_id(self) -> str | None:
        return self.decision.nominated_candidate_id


def build_results(
    run_id: str,
    evaluation: ProgramEvaluation,
    decision: ProgramDecision,
    *,
    research_train_fingerprint: str,
    package_version: str,
) -> FrozenResearchResults:
    """Assemble the results, binding the current protocol/constitution/budget/candidate ids."""
    protocol = ResearchProtocol.current()
    if evaluation.protocol_fingerprint != protocol.fingerprint():
        raise ResultsError("evaluation protocol fingerprint does not match the current protocol")
    if decision.protocol_fingerprint != protocol.fingerprint():
        raise ResultsError("decision protocol fingerprint does not match the current protocol")

    results = FrozenResearchResults(
        schema_version=RESULTS_SCHEMA_VERSION,
        run_id=require_slug("results.run_id", run_id),
        package_version=require_nonempty_str("results.package_version", package_version),
        research_train_fingerprint=require_nonempty_str(
            "results.research_train_fingerprint", research_train_fingerprint
        ),
        protocol_fingerprint=protocol.fingerprint(),
        constitution_fingerprint=CommercialEvidenceConstitution.current().fingerprint(),
        budget_fingerprint=OneShotResearchBudget.current().fingerprint(),
        candidate_fingerprints={s.candidate_id: s.fingerprint() for s in V2A_CANDIDATES},
        evaluation=evaluation,
        decision=decision,
    )
    _assert_results_invariants(results)
    return results


def _assert_results_invariants(results: FrozenResearchResults) -> None:
    eval_ids = {e.candidate_id for e in results.evaluation.evaluations}
    decision_ids = {o.candidate_id for o in results.decision.outcomes}
    if eval_ids != decision_ids:
        raise ResultsError("evaluation and decision cover different candidate sets")
    if not decision_ids.issubset(set(results.candidate_fingerprints)):
        raise ResultsError("decision references a candidate not in the registered candidate set")
    assert_no_reserved_status(
        "results.decision.status", [o.status for o in results.decision.outcomes]
    )


_RESULTS_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "package_version",
        "research_train_fingerprint",
        "protocol_fingerprint",
        "constitution_fingerprint",
        "budget_fingerprint",
        "candidate_fingerprints",
        "evaluation",
        "decision",
    }
)

_EVAL_KEYS = frozenset(
    {
        "candidate_id",
        "fold_count",
        "folds_beating_benchmark",
        "primary_point_estimate",
        "primary_ci_lower",
        "primary_ci_upper",
        "primary_lower_above_zero",
        "stressed_lower_above_zero",
        "aggregate_sharpe",
    }
)


def _parse_evaluation(raw: object) -> ProgramEvaluation:
    from eth_research.v2.strict import require_bool

    obj = require_mapping("results.evaluation", raw)
    require_exact_keys(
        "results.evaluation",
        obj,
        frozenset({"protocol_fingerprint", "periods_per_year", "evaluations"}),
    )

    def _one(label: str, value: object) -> CandidateEvaluation:
        e = require_mapping(label, value)
        require_exact_keys(label, e, _EVAL_KEYS)
        return CandidateEvaluation(
            candidate_id=require_slug(f"{label}.candidate_id", e["candidate_id"]),
            fold_count=require_int(f"{label}.fold_count", e["fold_count"]),
            folds_beating_benchmark=require_int(
                f"{label}.folds_beating_benchmark", e["folds_beating_benchmark"]
            ),
            primary_point_estimate=_require_finite(
                f"{label}.primary_point_estimate", e["primary_point_estimate"]
            ),
            primary_ci_lower=_require_finite(f"{label}.primary_ci_lower", e["primary_ci_lower"]),
            primary_ci_upper=_require_finite(f"{label}.primary_ci_upper", e["primary_ci_upper"]),
            primary_lower_above_zero=require_bool(
                f"{label}.primary_lower_above_zero", e["primary_lower_above_zero"]
            ),
            stressed_lower_above_zero=require_bool(
                f"{label}.stressed_lower_above_zero", e["stressed_lower_above_zero"]
            ),
            aggregate_sharpe=_require_finite(f"{label}.aggregate_sharpe", e["aggregate_sharpe"]),
        )

    return ProgramEvaluation(
        protocol_fingerprint=require_hex64(
            "results.evaluation.protocol_fingerprint", obj["protocol_fingerprint"]
        ),
        periods_per_year=_require_finite(
            "results.evaluation.periods_per_year", obj["periods_per_year"]
        ),
        evaluations=tuple(require_list("results.evaluation.evaluations", obj["evaluations"], _one)),
    )


def parse_results(raw: object) -> FrozenResearchResults:
    """Strictly decode a committed results artifact and re-assert its invariants and fingerprint."""
    obj = require_mapping("results", raw)
    require_exact_keys("results", obj, _RESULTS_KEYS)
    cf_obj = require_mapping("results.candidate_fingerprints", obj["candidate_fingerprints"])
    candidate_fingerprints = {
        require_slug("results.candidate_fingerprints.key", k): require_hex64(
            f"results.candidate_fingerprints.{k}", v
        )
        for k, v in cf_obj.items()
    }
    results = FrozenResearchResults(
        schema_version=require_int("results.schema_version", obj["schema_version"]),
        run_id=require_slug("results.run_id", obj["run_id"]),
        package_version=require_nonempty_str("results.package_version", obj["package_version"]),
        research_train_fingerprint=require_nonempty_str(
            "results.research_train_fingerprint", obj["research_train_fingerprint"]
        ),
        protocol_fingerprint=require_hex64(
            "results.protocol_fingerprint", obj["protocol_fingerprint"]
        ),
        constitution_fingerprint=require_hex64(
            "results.constitution_fingerprint", obj["constitution_fingerprint"]
        ),
        budget_fingerprint=require_hex64("results.budget_fingerprint", obj["budget_fingerprint"]),
        candidate_fingerprints=candidate_fingerprints,
        evaluation=_parse_evaluation(obj["evaluation"]),
        decision=parse_decision(obj["decision"]),
    )
    _assert_results_invariants(results)
    return results
