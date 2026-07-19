"""The V2A candidate evaluator: reuse the accepted engine to score candidates on research-train.

The full pipeline (:func:`evaluate_program`) reuses the accepted M3C grid driver
(``compute_m3c_cell_runs``) to run every candidate and the passive benchmark through the reviewed
fractional engine over the walk-forward folds, then reduces each candidate to a
:class:`CandidateEvaluation` using the reviewed fold-stratified bootstrap. The reduction step
(:func:`summarize_candidate`) is pure and is what the decision rule consumes, so it is tested on
synthetic fold returns; the real research-train run happens exactly once, in the registered one-shot
execution.

Nothing here decides status or nominates — that is :mod:`eth_research.v2.decision`. This module only
produces the evidence the rule is applied to.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from eth_research.data.schema import frame_interval
from eth_research.m3c.experiment import M3CCellRun, compute_m3c_cell_runs
from eth_research.m3c.statistics import (
    M3C_BOOTSTRAP_CONFIDENCE,
    align_paired_by_fold,
    fold_stratified_block_bootstrap,
)
from eth_research.metrics import periods_per_year_from_interval, sharpe_ratio
from eth_research.v2.candidates import (
    BENCHMARK_NAME,
    build_all_fractional_strategies,
    build_buy_and_hold_benchmark,
)
from eth_research.v2.protocol import ResearchProtocol
from eth_research.v2.strict import V2ValidationError
from eth_research.walkforward import INITIAL_CASH, WalkForwardProtocol

EVALUATOR_SCHEMA_VERSION: int = 1


class EvaluatorError(V2ValidationError):
    """A candidate evaluation could not be produced (missing cells, empty folds, etc.)."""


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """The reduced research-train evidence for one candidate (no status, no nomination)."""

    candidate_id: str
    fold_count: int
    folds_beating_benchmark: int
    primary_point_estimate: float
    primary_ci_lower: float
    primary_ci_upper: float
    primary_lower_above_zero: bool
    stressed_lower_above_zero: bool
    aggregate_sharpe: float

    def to_canonical(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "fold_count": self.fold_count,
            "folds_beating_benchmark": self.folds_beating_benchmark,
            "primary_point_estimate": self.primary_point_estimate,
            "primary_ci_lower": self.primary_ci_lower,
            "primary_ci_upper": self.primary_ci_upper,
            "primary_lower_above_zero": self.primary_lower_above_zero,
            "stressed_lower_above_zero": self.stressed_lower_above_zero,
            "aggregate_sharpe": self.aggregate_sharpe,
        }


def _total_return(returns: pd.Series) -> float:
    values = returns.to_numpy(dtype=float)
    if values.size == 0:
        return 0.0
    return float(np.prod(1.0 + values) - 1.0)


def _bootstrap_lower_above_zero(
    candidate_by_fold: dict[int, pd.Series],
    benchmark_by_fold: dict[int, pd.Series],
    *,
    seed: int,
    resamples: int,
) -> tuple[float, float, float, bool]:
    paired = align_paired_by_fold(candidate_by_fold, benchmark_by_fold)
    result = fold_stratified_block_bootstrap(paired, seed=seed, resamples=resamples)
    return (
        float(result.point_estimate),
        float(result.ci_lower),
        float(result.ci_upper),
        bool(result.lower_bound_above_zero),
    )


def summarize_candidate(
    candidate_id: str,
    *,
    primary_candidate_by_fold: dict[int, pd.Series],
    primary_benchmark_by_fold: dict[int, pd.Series],
    stressed_candidate_by_fold: dict[int, pd.Series],
    stressed_benchmark_by_fold: dict[int, pd.Series],
    periods_per_year: float,
    protocol: ResearchProtocol,
) -> CandidateEvaluation:
    """Reduce one candidate's per-fold marked returns to its :class:`CandidateEvaluation` (pure)."""
    # The reused fold-stratified bootstrap fixes a 95% (2.5/97.5) interval; the protocol's declared
    # confidence must equal it, or the reported CI bounds would be mislabelled (Sci-C1). We do not
    # reparameterize the accepted engine — we refuse a protocol that disagrees with it.
    if protocol.bootstrap_confidence != M3C_BOOTSTRAP_CONFIDENCE:
        raise EvaluatorError(
            f"protocol bootstrap_confidence {protocol.bootstrap_confidence!r} != the reused "
            f"engine's fixed {M3C_BOOTSTRAP_CONFIDENCE!r}; the interval would be mislabelled"
        )
    folds = sorted(primary_candidate_by_fold)
    if not folds:
        raise EvaluatorError(f"candidate {candidate_id!r} has no evaluated folds")

    beating = sum(
        1
        for f in folds
        if _total_return(primary_candidate_by_fold[f]) > _total_return(primary_benchmark_by_fold[f])
    )

    point, lower, upper, primary_above = _bootstrap_lower_above_zero(
        primary_candidate_by_fold,
        primary_benchmark_by_fold,
        seed=protocol.bootstrap_seed,
        resamples=protocol.bootstrap_resamples,
    )
    _p2, _l2, _u2, stressed_above = _bootstrap_lower_above_zero(
        stressed_candidate_by_fold,
        stressed_benchmark_by_fold,
        seed=protocol.bootstrap_seed,
        resamples=protocol.bootstrap_resamples,
    )

    concatenated = pd.concat([primary_candidate_by_fold[f] for f in folds])
    aggregate_sharpe = float(sharpe_ratio(concatenated, periods_per_year=periods_per_year))

    return CandidateEvaluation(
        candidate_id=candidate_id,
        fold_count=len(folds),
        folds_beating_benchmark=beating,
        primary_point_estimate=point,
        primary_ci_lower=lower,
        primary_ci_upper=upper,
        primary_lower_above_zero=primary_above,
        stressed_lower_above_zero=stressed_above,
        aggregate_sharpe=aggregate_sharpe,
    )


def _returns_by_fold(
    cells: tuple[M3CCellRun, ...], strategy_name: str, scenario_name: str
) -> dict[int, pd.Series]:
    out: dict[int, pd.Series] = {}
    for cell in cells:
        if cell.strategy == strategy_name and cell.cost_scenario == scenario_name:
            out[cell.fold_index] = cell.marked_daily_returns
    return out


@dataclass(frozen=True, slots=True)
class ProgramEvaluation:
    """Every candidate's reduced evidence plus the protocol it was produced under."""

    protocol_fingerprint: str
    periods_per_year: float
    evaluations: tuple[CandidateEvaluation, ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "protocol_fingerprint": self.protocol_fingerprint,
            "periods_per_year": self.periods_per_year,
            "evaluations": [e.to_canonical() for e in self.evaluations],
        }


def evaluate_program(
    research_train: pd.DataFrame, wf_protocol: WalkForwardProtocol, protocol: ResearchProtocol
) -> ProgramEvaluation:
    """Run every candidate + the benchmark through the reused engine and reduce to evidence.

    This is the full research-train pipeline; it is executed exactly once, in the registered
    one-shot run. It never touches a sealed partition — ``research_train`` is already firewalled.
    """
    strategies = (*build_all_fractional_strategies(), build_buy_and_hold_benchmark())
    scenarios = (protocol.primary_cost(), protocol.stressed_cost())
    cells = compute_m3c_cell_runs(
        research_train,
        wf_protocol,
        initial_cash=INITIAL_CASH,
        strategies=strategies,
        scenarios=scenarios,
    )

    # Derive the bar from the reviewed frame helper, which re-checks the index is a >= 2-row
    # DatetimeIndex, rather than indexing the first two rows by hand (Sci-C3).
    interval = frame_interval(research_train)
    ppy = periods_per_year_from_interval(interval)

    primary = protocol.primary_cost_scenario
    stressed = protocol.stressed_cost_scenario
    benchmark_primary = _returns_by_fold(cells, BENCHMARK_NAME, primary)
    benchmark_stressed = _returns_by_fold(cells, BENCHMARK_NAME, stressed)

    evaluations: list[CandidateEvaluation] = []
    for strategy in build_all_fractional_strategies():
        evaluations.append(
            summarize_candidate(
                strategy.name,
                primary_candidate_by_fold=_returns_by_fold(cells, strategy.name, primary),
                primary_benchmark_by_fold=benchmark_primary,
                stressed_candidate_by_fold=_returns_by_fold(cells, strategy.name, stressed),
                stressed_benchmark_by_fold=benchmark_stressed,
                periods_per_year=ppy,
                protocol=protocol,
            )
        )

    return ProgramEvaluation(
        protocol_fingerprint=protocol.fingerprint(),
        periods_per_year=float(ppy),
        evaluations=tuple(evaluations),
    )
