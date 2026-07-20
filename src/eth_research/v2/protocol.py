"""The pre-registered V2A research protocol: folds, costs, statistics, and the nomination rule.

Everything a one-shot evaluation needs is fixed here, before any candidate is run, so the outcome
cannot be reverse-engineered from the rules. The protocol reuses the accepted walk-forward,
cost-model, and bootstrap machinery (no accepted engine is modified) and pins:

* the expanding-window walk-forward over the 2221-row research-train partition (5 OOS folds);
* the cost scenarios — a base causal-proxy scenario for the primary read and a stressed scenario for
  the robustness (sensitivity) read, both drawn from the reviewed fractional cost model;
* the fold-stratified moving-block bootstrap parameters (seed, resamples, confidence);
* the nomination rule (``NominationCriteria``): what a candidate must satisfy to be
  ``research_stage_supported`` and, if it is the single best qualifier, nominated
  ``eligible_for_development_gate_review``.

A candidate that does not meet the rule is ``research_stage_rejected`` — a valid, honest outcome.
Neither status is an out-of-sample, forward, or live claim.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.fractional.cost_model import SCENARIOS_BY_NAME as _COST_BY_NAME
from eth_research.fractional.cost_model import CostScenario
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_exact_keys,
    require_mapping,
    require_nonempty_str,
    require_positive_int,
)
from eth_research.walkforward import OOS_FOLD_COUNT, RESEARCH_TRAIN_ROWS

PROTOCOL_SCHEMA_VERSION: int = 1

# Cost scenarios (names resolved from the reviewed fractional cost model). The primary read uses the
# base causal proxy; the robustness read additionally requires the stressed scenario.
PRIMARY_COST_SCENARIO: str = "causal_proxy_base"
STRESSED_COST_SCENARIO: str = "causal_proxy_stressed"

# Fold-stratified moving-block bootstrap parameters for V2A (its own pre-registered seed).
V2A_BOOTSTRAP_SEED: int = 20260719
V2A_BOOTSTRAP_RESAMPLES: int = 20000
V2A_BOOTSTRAP_CONFIDENCE: float = 0.95

# Benchmark every candidate is compared against: passive buy-and-hold (no overlays).
BENCHMARK_NAME: str = "buy_and_hold"


class ProtocolError(V2ValidationError):
    """The pre-registered protocol was malformed or drifted from its fixed definition."""


@dataclass(frozen=True, slots=True)
class NominationCriteria:
    """The pre-registered bar a candidate must clear to be research-stage supported / nominated.

    * ``min_folds_beating_benchmark`` — the candidate's net return must beat the benchmark in at
      least this many of the OOS folds;
    * ``bootstrap_lower_bound_above_zero`` — the fold-stratified bootstrap of paired log-excess
      return (candidate net vs benchmark net) must have its confidence lower bound strictly above 0;
    * ``require_stressed_robustness`` — the bootstrap lower-bound criterion must also hold under the
      stressed cost scenario;
    * ``require_positive_sharpe`` — the candidate's annualized Sharpe on research-train must be > 0.

    A candidate must satisfy all enabled criteria to be ``research_stage_supported``. Among the
    supported candidates, the single one with the highest primary bootstrap point estimate is
    nominated ``eligible_for_development_gate_review``; ties (or none supported) nominate nobody.
    """

    min_folds_beating_benchmark: int
    bootstrap_lower_bound_above_zero: bool
    require_stressed_robustness: bool
    require_positive_sharpe: bool


NOMINATION_CRITERIA = NominationCriteria(
    min_folds_beating_benchmark=3,
    bootstrap_lower_bound_above_zero=True,
    require_stressed_robustness=True,
    require_positive_sharpe=True,
)


@dataclass(frozen=True, slots=True)
class ResearchProtocol:
    """The committed, hashable pre-registration of the V2A one-shot research evaluation."""

    schema_version: int
    research_train_rows: int
    oos_fold_count: int
    primary_cost_scenario: str
    stressed_cost_scenario: str
    bootstrap_seed: int
    bootstrap_resamples: int
    bootstrap_confidence: float
    benchmark_name: str
    criteria: NominationCriteria
    primary_hypothesis: str

    @staticmethod
    def current() -> ResearchProtocol:
        return ResearchProtocol(
            schema_version=PROTOCOL_SCHEMA_VERSION,
            research_train_rows=RESEARCH_TRAIN_ROWS,
            oos_fold_count=OOS_FOLD_COUNT,
            primary_cost_scenario=PRIMARY_COST_SCENARIO,
            stressed_cost_scenario=STRESSED_COST_SCENARIO,
            bootstrap_seed=V2A_BOOTSTRAP_SEED,
            bootstrap_resamples=V2A_BOOTSTRAP_RESAMPLES,
            bootstrap_confidence=V2A_BOOTSTRAP_CONFIDENCE,
            benchmark_name=BENCHMARK_NAME,
            criteria=NOMINATION_CRITERIA,
            primary_hypothesis=(
                "On the authorized research-train partition, after reviewed execution costs, a "
                "candidate family delivers paired log-excess return over passive buy-and-hold "
                "whose fold-stratified bootstrap lower bound is above zero and is robust to a "
                "stressed cost scenario. This is a research-stage signal only; it is not an "
                "out-of-sample, forward, or live claim."
            ),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "research_train_rows": self.research_train_rows,
            "oos_fold_count": self.oos_fold_count,
            "primary_cost_scenario": self.primary_cost_scenario,
            "stressed_cost_scenario": self.stressed_cost_scenario,
            "bootstrap_seed": self.bootstrap_seed,
            "bootstrap_resamples": self.bootstrap_resamples,
            "bootstrap_confidence": self.bootstrap_confidence,
            "benchmark_name": self.benchmark_name,
            "criteria": {
                "min_folds_beating_benchmark": self.criteria.min_folds_beating_benchmark,
                "bootstrap_lower_bound_above_zero": self.criteria.bootstrap_lower_bound_above_zero,
                "require_stressed_robustness": self.criteria.require_stressed_robustness,
                "require_positive_sharpe": self.criteria.require_positive_sharpe,
            },
            "primary_hypothesis": self.primary_hypothesis,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    def primary_cost(self) -> CostScenario:
        return _resolve_cost(self.primary_cost_scenario)

    def stressed_cost(self) -> CostScenario:
        return _resolve_cost(self.stressed_cost_scenario)


def _resolve_cost(name: str) -> CostScenario:
    scenario = _COST_BY_NAME.get(name)
    if scenario is None:
        raise ProtocolError(f"unknown cost scenario {name!r}")
    return scenario


_PROTOCOL_KEYS = frozenset(
    {
        "schema_version",
        "research_train_rows",
        "oos_fold_count",
        "primary_cost_scenario",
        "stressed_cost_scenario",
        "bootstrap_seed",
        "bootstrap_resamples",
        "bootstrap_confidence",
        "benchmark_name",
        "criteria",
        "primary_hypothesis",
    }
)


def parse_protocol(raw: object) -> ResearchProtocol:
    """Strictly decode a committed protocol artifact and re-assert the fixed pre-registration."""
    obj = require_mapping("protocol", raw)
    require_exact_keys("protocol", obj, _PROTOCOL_KEYS)
    # Structural checks on the two fields most likely to be tampered; the fingerprint pins the rest.
    require_positive_int("protocol.research_train_rows", obj["research_train_rows"])
    require_positive_int("protocol.oos_fold_count", obj["oos_fold_count"])
    require_nonempty_str("protocol.primary_hypothesis", obj["primary_hypothesis"])
    current = ResearchProtocol.current()
    if canonical_sha256(obj) != current.fingerprint():
        raise ProtocolError("protocol content drifted from the fixed V2A pre-registration")
    return current
