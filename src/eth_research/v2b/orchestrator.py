"""V2B §29 — the fail-closed one-shot evaluation orchestrator.

Ties the frozen machinery into a single mechanical evaluation: for each candidate it forms the
primary/stressed/latency paired 95% bootstrap CIs, the family-wise-corrected one-sided lower bound,
the Monte-Carlo sign-flip p-value, and the parameter-sensitivity stability, assembles the seven
pre-registered nomination gates, and applies the ≤1 nomination rule. It is *pure* given a panel,
folds, cost scenarios, and the corrected per-family alpha, so it is unit-tested on synthetic panels.

The real research-train evaluation is invoked **exactly once**, in the registered one-shot run, via
:func:`run_one_shot` — which reads the real committed universe/scenarios/multiplicity and calls the
same pure :func:`evaluate_program`. Nothing here appends to the registry or publishes; that is the
job of the P driver, which wraps this between a ``started`` and a terminal registry event.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from eth_research.m3c.statistics import FoldPaired, align_paired_by_fold
from eth_research.portfolio.costs import CostParameters
from eth_research.v2.strict import V2ValidationError, canonical_sha256
from eth_research.v2b.candidates import V2B_CANDIDATES, V2BCandidateSpec
from eth_research.v2b.evaluation import (
    CandidateEvaluation,
    benchmark_net_returns,
    candidate_net_returns,
    evaluate_candidate,
)
from eth_research.v2b.execution import PRIMARY_BENCHMARK, build_v2b_universe
from eth_research.v2b.folds import V2BFold, build_oos_folds, series_by_fold
from eth_research.v2b.governance import protocol_fingerprint
from eth_research.v2b.multiplicity import ResearchMultiplicityState
from eth_research.v2b.nomination import (
    CandidateGates,
    NominationDecision,
    build_gates,
    decide_nomination,
)
from eth_research.v2b.scenarios import COST_SCENARIOS, PRIMARY_COST, STRESSED_COST
from eth_research.v2b.sensitivity import SensitivityReport, evaluate_sensitivity
from eth_research.v2b.statistics import (
    CorrectedBootstrap,
    corrected_bootstrap,
    mc_sign_flip_p_value,
)

ORCHESTRATOR_SCHEMA_VERSION: int = 1

# The four terminal verdict strings (exactly one is returned).
VERDICT_NOMINATION = (
    "V2B COMPLETE — ONE GENUINELY NEW CROSS-ASSET RESEARCH CANDIDATE NOMINATED FOR INDEPENDENT "
    "DEVELOPMENT-GATE REVIEW; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY"
)
VERDICT_NO_NOMINATION = (
    "V2B COMPLETE — NO CROSS-ASSET CANDIDATE NOMINATED; CUMULATIVE NEGATIVE EVIDENCE PRESERVED; "
    "ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY"
)


class V2BOrchestratorError(V2ValidationError):
    """The one-shot evaluation could not be produced under the fail-closed contract."""


@dataclass(frozen=True, slots=True)
class CandidateResult:
    """One candidate's full evidence: reduced evaluation, corrected tail, MC, sensitivity, gates."""

    evaluation: CandidateEvaluation
    corrected: CorrectedBootstrap
    mc_p_value: float
    sensitivity: SensitivityReport
    gates: CandidateGates

    def to_canonical(self) -> dict[str, object]:
        return {
            "evaluation": self.evaluation.to_canonical(),
            "corrected_bootstrap": self.corrected.to_canonical(),
            "mc_sign_flip_p_value": self.mc_p_value,
            "sensitivity": self.sensitivity.to_canonical(),
            "gates": self.gates.to_canonical(),
        }


@dataclass(frozen=True, slots=True)
class ProgramResult:
    """Every candidate's full evidence, the nomination decision, and the terminal verdict."""

    corrected_alpha: float
    candidates: tuple[CandidateResult, ...]
    decision: NominationDecision
    verdict: str

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": ORCHESTRATOR_SCHEMA_VERSION,
            "corrected_alpha": self.corrected_alpha,
            "candidates": [c.to_canonical() for c in self.candidates],
            "decision": self.decision.to_canonical(),
            "verdict": self.verdict,
        }

    def result_fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


def _primary_paired(
    spec: V2BCandidateSpec,
    panel: pd.DataFrame,
    folds: tuple[V2BFold, ...],
    primary_cost: CostParameters,
) -> tuple[FoldPaired, ...]:
    """The primary-cost per-fold paired log-excess (candidate vs ETH buy-and-hold)."""
    cand = candidate_net_returns(spec, panel, primary_cost)
    bench = benchmark_net_returns(panel, PRIMARY_BENCHMARK, primary_cost)
    cand_by_fold = series_by_fold(cand.net_return_series(), folds)
    bench_by_fold = series_by_fold(bench.net_return_series(), folds)
    return align_paired_by_fold(cand_by_fold, bench_by_fold)


def evaluate_candidate_full(
    spec: V2BCandidateSpec,
    panel: pd.DataFrame,
    folds: tuple[V2BFold, ...],
    *,
    primary_cost: CostParameters,
    stressed_cost: CostParameters,
    corrected_alpha: float,
) -> CandidateResult:
    """Produce one candidate's full evidence and its seven-gate assembly (pure)."""
    evaluation = evaluate_candidate(
        spec, panel, folds, primary_cost=primary_cost, stressed_cost=stressed_cost
    )
    paired = _primary_paired(spec, panel, folds, primary_cost)
    corrected = corrected_bootstrap(paired, corrected_alpha=corrected_alpha)
    mc_p = mc_sign_flip_p_value(paired)
    sensitivity = evaluate_sensitivity(spec, panel, folds, primary_cost=primary_cost)
    gates = build_gates(
        spec.candidate_id,
        primary_lower_above_zero=evaluation.primary_lower_above_zero,
        stressed_lower_above_zero=evaluation.stressed_lower_above_zero,
        latency_lower_above_zero=evaluation.latency_lower_above_zero,
        folds_beating=evaluation.folds_beating_benchmark,
        fold_count=evaluation.fold_count,
        corrected_lower_above_zero=corrected.corrected_lower_above_zero,
        mc_p_value=mc_p,
        corrected_alpha=corrected_alpha,
        sensitivity_all_above_zero=sensitivity.all_above_zero,
        primary_point_estimate=evaluation.primary_point_estimate,
    )
    return CandidateResult(
        evaluation=evaluation,
        corrected=corrected,
        mc_p_value=mc_p,
        sensitivity=sensitivity,
        gates=gates,
    )


def evaluate_program(
    panel: pd.DataFrame,
    folds: tuple[V2BFold, ...],
    *,
    primary_cost: CostParameters,
    stressed_cost: CostParameters,
    corrected_alpha: float,
    specs: tuple[V2BCandidateSpec, ...] = V2B_CANDIDATES,
) -> ProgramResult:
    """Evaluate every candidate, apply the ≤1 rule, and pick the terminal verdict (pure)."""
    if not specs:
        raise V2BOrchestratorError("no candidates to evaluate")
    candidates = tuple(
        evaluate_candidate_full(
            spec,
            panel,
            folds,
            primary_cost=primary_cost,
            stressed_cost=stressed_cost,
            corrected_alpha=corrected_alpha,
        )
        for spec in specs
    )
    decision = decide_nomination(tuple(c.gates for c in candidates))
    verdict = VERDICT_NOMINATION if decision.nominated_candidate_id else VERDICT_NO_NOMINATION
    return ProgramResult(
        corrected_alpha=corrected_alpha,
        candidates=candidates,
        decision=decision,
        verdict=verdict,
    )


@dataclass(frozen=True, slots=True)
class OneShotOutcome:
    """The one-shot run's protocol fingerprint plus the pure program result."""

    protocol_fingerprint: str
    result: ProgramResult


def run_one_shot(repo_root: str | Path) -> OneShotOutcome:
    """Run the ONE authorized research-train evaluation from committed bytes (invoke once, at P).

    Reads the real firewalled universe, the frozen cost scenarios, and the cumulative multiplicity
    state, then calls the same pure :func:`evaluate_program`. This must be invoked exactly once,
    inside the registered ``started`` → terminal window; it never appends to the registry itself.
    """
    root = Path(repo_root)
    universe = build_v2b_universe(root)
    folds = build_oos_folds(universe.index)
    corrected_alpha = ResearchMultiplicityState.current().corrected_per_family_alpha()
    result = evaluate_program(
        universe.partition.panel,
        folds,
        primary_cost=COST_SCENARIOS[PRIMARY_COST],
        stressed_cost=COST_SCENARIOS[STRESSED_COST],
        corrected_alpha=corrected_alpha,
    )
    return OneShotOutcome(protocol_fingerprint=protocol_fingerprint(root), result=result)
