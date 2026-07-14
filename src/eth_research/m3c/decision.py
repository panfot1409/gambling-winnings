"""The mechanical, frozen M3C promotion-eligibility decision.

``evaluate_candidate_decision`` reads the committed :class:`M3CResults` and the
frozen promotion rule (docs/M3C_PLAN.md §8) and computes — never paraphrases —
the outcome. The candidate is marked ``eligible_for_development_gate_review`` iff
all seven criteria P1..P7 pass, otherwise ``rejected_for_development_gate_promotion``.
Each criterion is recorded as a strict :class:`CriterionResult` (id, description,
observed value, threshold, pass/fail, source cells), and the serialized decision
also pins that the test, development gate, and final holdout were never accessed,
that no parameter changed, and that exactly one candidate was evaluated.

"Eligible" means only "eligible for an independent development-gate review". It is
not gate authorization, promotion, alpha, or approval to trade. The model
re-checks that the recorded outcome matches the mechanical evaluation of its own
criteria on parse, so a hand-edited outcome is rejected.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research._json import require_canonical_file_bytes
from eth_research.data.provenance import sha256_bytes
from eth_research.m3c.candidate import M3C_CANDIDATE_ID
from eth_research.m3c.results import (
    M3C_EXPERIMENT_FAMILY,
    PRIMARY_COMPARATOR,
    PRIMARY_SCENARIO,
    M3CResults,
)
from eth_research.m3c.validation import (
    canonical_json_bytes,
    require_bool,
    require_exact_keys,
    require_exact_string,
    require_hex64,
    require_mapping,
    require_nonempty_str,
    require_positive_int,
    require_str,
    require_tuple,
    strict_json_loads,
)

M3C_DECISION_SCHEMA_VERSION: int = 1
M3C_DECISION_RELPATH: str = "research/m3c/candidate_decision.json"

OUTCOME_ELIGIBLE: str = "eligible_for_development_gate_review"
OUTCOME_REJECTED: str = "rejected_for_development_gate_promotion"
_OUTCOMES: tuple[str, ...] = (OUTCOME_ELIGIBLE, OUTCOME_REJECTED)

PROMOTION_CRITERIA: tuple[str, ...] = ("P1", "P2", "P3", "P4", "P5", "P6", "P7")

_STRESSED_SCENARIO: str = "causal_proxy_stressed"
_BUY_AND_HOLD: str = "buy_and_hold"


class DecisionError(ValueError):
    """The candidate decision failed strict validation or a mechanical invariant."""


def _cell_key(strategy: str, scenario: str, fold: int) -> str:
    return f"{strategy}::{scenario}::fold{fold}"


@dataclass(frozen=True)
class CriterionResult:
    """One promotion criterion's mechanical evaluation against the committed results."""

    criterion_id: str
    description: str
    observed_value: str
    threshold: str
    passed: bool
    source_cells: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "description": self.description,
            "observed_value": self.observed_value,
            "threshold": self.threshold,
            "passed": self.passed,
            "source_cells": list(self.source_cells),
        }

    @classmethod
    def from_dict(cls, payload: object) -> CriterionResult:
        data = require_mapping("criterion", payload)
        require_exact_keys("criterion", data, _CRITERION_KEYS)
        return cls(
            criterion_id=require_nonempty_str("criterion_id", data["criterion_id"]),
            description=require_nonempty_str("description", data["description"]),
            observed_value=require_str("observed_value", data["observed_value"]),
            threshold=require_nonempty_str("threshold", data["threshold"]),
            passed=require_bool("passed", data["passed"]),
            source_cells=require_tuple("source_cells", data["source_cells"], require_nonempty_str),
        )


_CRITERION_KEYS = frozenset(
    {
        "criterion_id",
        "description",
        "observed_value",
        "threshold",
        "passed",
        "source_cells",
    }
)


@dataclass(frozen=True)
class CandidateDecision:
    """The strict, byte-stable promotion-eligibility decision."""

    decision_schema_version: int
    experiment_id: str
    experiment_family: str
    outcome: str
    results_sha256: str
    protocol_sha256: str
    criteria: tuple[CriterionResult, ...]
    verification_passed: bool
    test_accessed: bool
    development_gate_accessed: bool
    final_holdout_accessed: bool
    parameter_changes: str
    candidate_count: int

    def __post_init__(self) -> None:
        if self.decision_schema_version != M3C_DECISION_SCHEMA_VERSION:
            raise DecisionError("unexpected decision schema version")
        if self.experiment_family != M3C_EXPERIMENT_FAMILY:
            raise DecisionError("wrong experiment family")
        if not self.experiment_id.startswith(M3C_EXPERIMENT_FAMILY):
            raise DecisionError("experiment_id must belong to the family")
        if self.outcome not in _OUTCOMES:
            raise DecisionError(f"outcome must be one of {_OUTCOMES}, got {self.outcome!r}")
        if tuple(c.criterion_id for c in self.criteria) != PROMOTION_CRITERIA:
            raise DecisionError(f"criteria must be exactly {PROMOTION_CRITERIA} in order")
        all_passed = all(c.passed for c in self.criteria)
        expected = OUTCOME_ELIGIBLE if all_passed else OUTCOME_REJECTED
        if self.outcome != expected:
            raise DecisionError(
                "outcome does not match the mechanical evaluation of the criteria "
                f"(all_passed={all_passed} implies {expected!r}, got {self.outcome!r})"
            )
        p6 = next(c for c in self.criteria if c.criterion_id == "P6")
        if p6.passed != self.verification_passed:
            raise DecisionError("P6 pass/fail must equal the recorded verification_passed flag")
        if self.test_accessed or self.development_gate_accessed or self.final_holdout_accessed:
            raise DecisionError("no sealed partition may be recorded as accessed")
        if self.parameter_changes != "none":
            raise DecisionError("parameter_changes must be 'none'")
        if self.candidate_count != 1:
            raise DecisionError("exactly one candidate must be evaluated")
        require_hex64("results_sha256", self.results_sha256)
        require_hex64("protocol_sha256", self.protocol_sha256)

    @property
    def eligible(self) -> bool:
        return self.outcome == OUTCOME_ELIGIBLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_schema_version": self.decision_schema_version,
            "experiment_id": self.experiment_id,
            "experiment_family": self.experiment_family,
            "outcome": self.outcome,
            "results_sha256": self.results_sha256,
            "protocol_sha256": self.protocol_sha256,
            "criteria": [c.to_dict() for c in self.criteria],
            "verification_passed": self.verification_passed,
            "test_accessed": self.test_accessed,
            "development_gate_accessed": self.development_gate_accessed,
            "final_holdout_accessed": self.final_holdout_accessed,
            "parameter_changes": self.parameter_changes,
            "candidate_count": self.candidate_count,
        }

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: object) -> CandidateDecision:
        data = require_mapping("candidate_decision", payload)
        require_exact_keys("candidate_decision", data, _DECISION_KEYS)
        criteria = tuple(CriterionResult.from_dict(c) for c in _require_list(data["criteria"]))
        return cls(
            decision_schema_version=require_positive_int(
                "decision_schema_version", data["decision_schema_version"]
            ),
            experiment_id=require_nonempty_str("experiment_id", data["experiment_id"]),
            experiment_family=require_nonempty_str("experiment_family", data["experiment_family"]),
            outcome=require_nonempty_str("outcome", data["outcome"]),
            results_sha256=require_hex64("results_sha256", data["results_sha256"]),
            protocol_sha256=require_hex64("protocol_sha256", data["protocol_sha256"]),
            criteria=criteria,
            verification_passed=require_bool("verification_passed", data["verification_passed"]),
            test_accessed=require_bool("test_accessed", data["test_accessed"]),
            development_gate_accessed=require_bool(
                "development_gate_accessed", data["development_gate_accessed"]
            ),
            final_holdout_accessed=require_bool(
                "final_holdout_accessed", data["final_holdout_accessed"]
            ),
            parameter_changes=require_exact_string(
                "parameter_changes", data["parameter_changes"], "none"
            ),
            candidate_count=require_positive_int("candidate_count", data["candidate_count"]),
        )

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> CandidateDecision:
        return cls.from_dict(strict_json_loads(raw))


_DECISION_KEYS = frozenset(
    {
        "decision_schema_version",
        "experiment_id",
        "experiment_family",
        "outcome",
        "results_sha256",
        "protocol_sha256",
        "criteria",
        "verification_passed",
        "test_accessed",
        "development_gate_accessed",
        "final_holdout_accessed",
        "parameter_changes",
        "candidate_count",
    }
)


def _require_list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise DecisionError(f"expected a JSON array, got {type(value).__name__}")
    return value


def _evaluate_criteria(
    results: M3CResults, *, verification_passed: bool
) -> tuple[CriterionResult, ...]:
    """Mechanically evaluate P1..P7 from the committed results (§8)."""
    folds = tuple(range(len(results.paired_comparisons)))
    cells = {(c.strategy, c.cost_scenario, c.fold_index): c for c in results.fold_cells}
    base = PRIMARY_SCENARIO
    stressed = _STRESSED_SCENARIO
    cand_base = [cells[(M3C_CANDIDATE_ID, base, f)] for f in folds]
    bnh_base = [cells[(_BUY_AND_HOLD, base, f)] for f in folds]
    cand_stressed = [cells[(M3C_CANDIDATE_ID, stressed, f)] for f in folds]
    cand_causal = [
        cells[(M3C_CANDIDATE_ID, scenario, f)] for scenario in (base, stressed) for f in folds
    ]

    # P1 — primary 95% bootstrap lower bound strictly above zero.
    p1 = CriterionResult(
        criterion_id="P1",
        description="primary 95% bootstrap lower bound > 0 (causal_proxy_base)",
        observed_value=f"ci_lower={results.bootstrap.ci_lower:.6g}",
        threshold="ci_lower > 0",
        passed=results.bootstrap.ci_lower > 0.0,
        source_cells=tuple(_cell_key(M3C_CANDIDATE_ID, base, f) for f in folds),
    )

    # P2 — candidate marked return beats buy-and-hold in at least 3 of 5 base folds.
    wins = sum(1 for pc in results.paired_comparisons if pc.candidate_beats_bnh)
    p2 = CriterionResult(
        criterion_id="P2",
        description="candidate marked total return > buy_and_hold in >= 3 of 5 folds (base)",
        observed_value=f"{wins}/{len(folds)} folds",
        threshold=">= 3 of 5",
        passed=wins >= 3,
        source_cells=tuple(_cell_key(M3C_CANDIDATE_ID, base, f) for f in folds),
    )

    # P3 — candidate fold-median max drawdown no deeper than buy-and-hold's. max_drawdown
    # is stored as a non-positive fraction, so "<= B&H drawdown" as a magnitude means the
    # signed candidate median must be >= the signed B&H median (closer to zero).
    cand_med_dd = statistics.median([c.max_drawdown for c in cand_base])
    bnh_med_dd = statistics.median([c.max_drawdown for c in bnh_base])
    p3 = CriterionResult(
        criterion_id="P3",
        description="candidate fold-median max drawdown no deeper than buy_and_hold (base)",
        observed_value=f"candidate={cand_med_dd:.6g}, buy_and_hold={bnh_med_dd:.6g}",
        threshold="candidate median drawdown >= B&H median drawdown (signed, <=0)",
        passed=cand_med_dd >= bnh_med_dd,
        source_cells=tuple(_cell_key(M3C_CANDIDATE_ID, base, f) for f in folds)
        + tuple(_cell_key(_BUY_AND_HOLD, base, f) for f in folds),
    )

    # P4 — candidate fold-median marked total return positive under the stressed costs.
    cand_stressed_med = statistics.median([c.marked_total_return for c in cand_stressed])
    p4 = CriterionResult(
        criterion_id="P4",
        description="candidate fold-median marked total return > 0 (causal_proxy_stressed)",
        observed_value=f"median={cand_stressed_med:.6g}",
        threshold="> 0",
        passed=cand_stressed_med > 0.0,
        source_cells=tuple(_cell_key(M3C_CANDIDATE_ID, stressed, f) for f in folds),
    )

    # P5 — every candidate causal-scenario fold ends with positive marked equity and no
    # fold return at or below -1 (accounting invariants are reconciled upstream, so a
    # constructed M3CResults already guarantees positive terminal equity for every cell).
    min_equity = min(c.marked_terminal_equity for c in cand_causal)
    no_ruin = all(c.marked_total_return > -1.0 for c in cand_causal)
    p5 = CriterionResult(
        criterion_id="P5",
        description="every candidate causal-scenario fold terminal equity > 0 and return > -1",
        observed_value=f"min_terminal_equity={min_equity:.6g}, no_ruin={str(no_ruin).lower()}",
        threshold="all terminal equity > 0 and all returns > -1",
        passed=min_equity > 0.0 and no_ruin,
        source_cells=tuple(
            _cell_key(M3C_CANDIDATE_ID, scenario, f) for scenario in (base, stressed) for f in folds
        ),
    )

    # P6 — causality/replay/archive/cross-runtime verification (supplied by the orchestrator).
    p6 = CriterionResult(
        criterion_id="P6",
        description="all causality/replay/archive/cross-runtime verification checks pass",
        observed_value=f"verification_passed={str(verification_passed).lower()}",
        threshold="externally verified true",
        passed=verification_passed,
        source_cells=(),
    )

    # P7 — exactly one new candidate, no parameter change, no alternate primary endpoint.
    candidate_count = sum(1 for s in results.strategies if s == M3C_CANDIDATE_ID)
    hashes_present = bool(
        results.protocol_sha256 and results.lineage_sha256 and results.budget_sha256
    )
    primary_ok = (
        results.primary_scenario == PRIMARY_SCENARIO
        and results.primary_comparator == PRIMARY_COMPARATOR
    )
    p7 = CriterionResult(
        criterion_id="P7",
        description="exactly one new candidate; no parameter change; no alternate primary",
        observed_value=(
            f"candidate_count={candidate_count}, "
            f"primary={results.primary_scenario}/{results.primary_comparator}, "
            f"lineage_budget_protocol_bound={str(hashes_present).lower()}"
        ),
        threshold="candidate_count == 1 and canonical primary and lineage/budget/protocol bound",
        passed=candidate_count == 1 and hashes_present and primary_ok,
        source_cells=("strategies", "protocol_sha256", "lineage_sha256", "budget_sha256"),
    )
    return (p1, p2, p3, p4, p5, p6, p7)


def evaluate_candidate_decision(
    results: M3CResults, *, verification_passed: bool = False
) -> CandidateDecision:
    """Mechanically evaluate the frozen promotion rule against committed results.

    ``verification_passed`` carries the outcome of the causality/replay/archive/
    cross-runtime checks (P6) that live outside the results model; it defaults to
    ``False`` so the caller must assert them explicitly. The outcome is eligible
    iff all seven criteria pass, else rejected — computed here, never paraphrased.
    """
    criteria = _evaluate_criteria(results, verification_passed=verification_passed)
    outcome = OUTCOME_ELIGIBLE if all(c.passed for c in criteria) else OUTCOME_REJECTED
    candidate_count = sum(1 for s in results.strategies if s == M3C_CANDIDATE_ID)
    return CandidateDecision(
        decision_schema_version=M3C_DECISION_SCHEMA_VERSION,
        experiment_id=results.experiment_id,
        experiment_family=results.experiment_family,
        outcome=outcome,
        results_sha256=sha256_bytes(results.to_json_bytes()),
        protocol_sha256=results.protocol_sha256,
        criteria=criteria,
        verification_passed=verification_passed,
        test_accessed=False,
        development_gate_accessed=False,
        final_holdout_accessed=False,
        parameter_changes="none",
        candidate_count=candidate_count,
    )


def load_m3c_decision(path: str | Path) -> CandidateDecision:
    """Strictly parse a committed M3C candidate decision file."""
    raw = require_canonical_file_bytes(Path(path).read_bytes(), "m3c decision")
    return CandidateDecision.from_json_bytes(raw)
