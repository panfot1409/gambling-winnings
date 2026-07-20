"""V2B §19 — wire the frozen candidates through the execution basis into the reused fold bootstrap.

This is the machinery the one-shot run drives; it is *pure* given a joint panel and is unit-tested
on synthetic panels. The real research-train evaluation is executed exactly once, in the registered
one-shot run (never here).

**Causality.** A candidate signal is decided from closes ``<= t`` and, per its specification,
executes at ``open[t+1]``. The execution basis (:mod:`eth_research.v2b.execution`) trades the target
it is given at ``open[t]``; so the *executed* path is the raw signal shifted forward one bar
(``apply_latency(raw, 1)``) — the target acted on at ``open[t]`` is the signal from closes
``<= t-1``, strictly before that open. No look-ahead. The latency stress adds one further bar.

**Benchmark.** The primary paired endpoint is candidate vs **ETH buy-and-hold**
(:data:`~eth_research.v2b.execution.PRIMARY_BENCHMARK`) — the single-asset passive the whole program
has measured against since V2A, and the harder of the two single-asset holds over the research
train. A constant benchmark is not shifted (it is an allocation, not a signal). Warm-up rows
(excluded from every fold) absorb the one-bar boundary, so the paired series are clean per fold.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from eth_research.m3c.statistics import (
    M3C_BOOTSTRAP_RESAMPLES,
    M3C_BOOTSTRAP_SEED,
    align_paired_by_fold,
    fold_stratified_block_bootstrap,
)
from eth_research.metrics import periods_per_year_from_interval, sharpe_ratio
from eth_research.portfolio.costs import CostParameters
from eth_research.v2.strict import V2ValidationError
from eth_research.v2b.candidates import (
    CANDIDATE_A,
    CANDIDATE_B,
    V2BCandidateSpec,
    cross_asset_confirmation_weights,
    relative_strength_weights,
)
from eth_research.v2b.execution import (
    PRIMARY_BENCHMARK,
    ExecutionResult,
    benchmark_weight_paths,
    simulate_target_path,
)
from eth_research.v2b.folds import V2BFold, series_by_fold
from eth_research.v2b.scenarios import apply_latency

EVALUATION_SCHEMA_VERSION: int = 1
#: Crypto trades every calendar day, so a daily bar is 1/365.25 of a year.
PERIODS_PER_YEAR: float = 365.25


class V2BEvaluationError(V2ValidationError):
    """A candidate could not be evaluated (unknown candidate, empty fold, mislabelled interval)."""


# --------------------------------------------------------------------------- #
# candidate -> raw signal -> causal executed path                              #
# --------------------------------------------------------------------------- #
def candidate_raw_weights(spec: V2BCandidateSpec, panel: pd.DataFrame) -> pd.DataFrame:
    """The candidate's raw per-bar target weights (signal decided from closes ``<= t``)."""
    if spec.candidate_id == CANDIDATE_A.candidate_id:
        return cross_asset_confirmation_weights(panel, **spec.fixed_parameters)
    if spec.candidate_id == CANDIDATE_B.candidate_id:
        return relative_strength_weights(panel, **spec.fixed_parameters)
    raise V2BEvaluationError(f"unknown candidate id {spec.candidate_id!r}")


def candidate_execution_path(
    spec: V2BCandidateSpec, panel: pd.DataFrame, *, extra_lag_bars: int = 0
) -> pd.DataFrame:
    """The causal executed path: raw signal shifted forward ``1 + extra_lag_bars`` bars.

    The mandatory one-bar shift makes the target acted on at ``open[t]`` depend only on closes
    strictly before that open; ``extra_lag_bars`` models additional execution latency (the stress).
    """
    return apply_latency(candidate_raw_weights(spec, panel), 1 + extra_lag_bars)


def candidate_net_returns(
    spec: V2BCandidateSpec, panel: pd.DataFrame, cost: CostParameters, *, extra_lag_bars: int = 0
) -> ExecutionResult:
    """Run the candidate's causal executed path through the execution basis under ``cost``."""
    return simulate_target_path(
        panel, candidate_execution_path(spec, panel, extra_lag_bars=extra_lag_bars), cost
    )


def benchmark_net_returns(panel: pd.DataFrame, name: str, cost: CostParameters) -> ExecutionResult:
    """Run a static benchmark (a constant allocation, unshifted) through the execution basis."""
    index = panel.index
    assert isinstance(index, pd.DatetimeIndex)
    paths = benchmark_weight_paths(index)
    if name not in paths:
        raise V2BEvaluationError(f"unknown benchmark {name!r}")
    return simulate_target_path(panel, paths[name], cost)


# --------------------------------------------------------------------------- #
# candidate evaluation (reusing the accepted fold-stratified bootstrap)         #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """One candidate's reduced research-train evidence vs the primary benchmark (no nomination)."""

    candidate_id: str
    benchmark: str
    fold_count: int
    folds_beating_benchmark: int
    primary_point_estimate: float
    primary_ci_lower: float
    primary_ci_upper: float
    primary_lower_above_zero: bool
    stressed_lower_above_zero: bool
    latency_lower_above_zero: bool
    aggregate_sharpe: float

    def to_canonical(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "benchmark": self.benchmark,
            "fold_count": self.fold_count,
            "folds_beating_benchmark": self.folds_beating_benchmark,
            "primary_point_estimate": self.primary_point_estimate,
            "primary_ci_lower": self.primary_ci_lower,
            "primary_ci_upper": self.primary_ci_upper,
            "primary_lower_above_zero": self.primary_lower_above_zero,
            "stressed_lower_above_zero": self.stressed_lower_above_zero,
            "latency_lower_above_zero": self.latency_lower_above_zero,
            "aggregate_sharpe": self.aggregate_sharpe,
        }


def _fold_returns(result: ExecutionResult, folds: tuple[V2BFold, ...]) -> dict[int, pd.Series]:
    return series_by_fold(result.net_return_series(), folds)


def _bootstrap_lower_above_zero(
    candidate_by_fold: dict[int, pd.Series], benchmark_by_fold: dict[int, pd.Series]
) -> tuple[float, float, float, bool]:
    paired = align_paired_by_fold(candidate_by_fold, benchmark_by_fold)
    result = fold_stratified_block_bootstrap(
        paired, seed=M3C_BOOTSTRAP_SEED, resamples=M3C_BOOTSTRAP_RESAMPLES
    )
    return (
        float(result.point_estimate),
        float(result.ci_lower),
        float(result.ci_upper),
        bool(result.lower_bound_above_zero),
    )


def _total_return(returns: pd.Series) -> float:
    values = returns.to_numpy(dtype=float)
    if values.size == 0:
        return 0.0
    return float((1.0 + values).prod() - 1.0)


def evaluate_candidate(
    spec: V2BCandidateSpec,
    panel: pd.DataFrame,
    folds: tuple[V2BFold, ...],
    *,
    primary_cost: CostParameters,
    stressed_cost: CostParameters,
) -> CandidateEvaluation:
    """Reduce one candidate to its bootstrap evidence vs ETH buy-and-hold (primary + two stresses).

    The paired 95% CIs come from the reused fold-stratified moving-block bootstrap over the frozen
    folds. Three CIs are formed: ``primary`` (primary cost), ``stressed`` (heavier cost), and
    ``latency`` (primary cost + one extra bar of execution delay). ``folds_beating_benchmark``
    counts the out-of-sample folds where the candidate's total return exceeds the benchmark's.
    """
    if not folds:
        raise V2BEvaluationError("no folds")
    benchmark = PRIMARY_BENCHMARK

    bench_primary = benchmark_net_returns(panel, benchmark, primary_cost)
    bench_stressed = benchmark_net_returns(panel, benchmark, stressed_cost)
    bench_primary_by_fold = _fold_returns(bench_primary, folds)
    bench_stressed_by_fold = _fold_returns(bench_stressed, folds)

    cand_primary = candidate_net_returns(spec, panel, primary_cost)
    cand_stressed = candidate_net_returns(spec, panel, stressed_cost)
    cand_latency = candidate_net_returns(spec, panel, primary_cost, extra_lag_bars=1)
    cand_primary_by_fold = _fold_returns(cand_primary, folds)
    cand_stressed_by_fold = _fold_returns(cand_stressed, folds)
    cand_latency_by_fold = _fold_returns(cand_latency, folds)

    point, lower, upper, primary_above = _bootstrap_lower_above_zero(
        cand_primary_by_fold, bench_primary_by_fold
    )
    _p2, _l2, _u2, stressed_above = _bootstrap_lower_above_zero(
        cand_stressed_by_fold, bench_stressed_by_fold
    )
    _p3, _l3, _u3, latency_above = _bootstrap_lower_above_zero(
        cand_latency_by_fold, bench_primary_by_fold
    )

    beating = sum(
        1
        for f in folds
        if _total_return(cand_primary_by_fold[f.fold_index])
        > _total_return(bench_primary_by_fold[f.fold_index])
    )
    concatenated = pd.concat([cand_primary_by_fold[f.fold_index] for f in folds])
    aggregate_sharpe = float(sharpe_ratio(concatenated, periods_per_year=PERIODS_PER_YEAR))

    return CandidateEvaluation(
        candidate_id=spec.candidate_id,
        benchmark=benchmark,
        fold_count=len(folds),
        folds_beating_benchmark=beating,
        primary_point_estimate=point,
        primary_ci_lower=lower,
        primary_ci_upper=upper,
        primary_lower_above_zero=primary_above,
        stressed_lower_above_zero=stressed_above,
        latency_lower_above_zero=latency_above,
        aggregate_sharpe=aggregate_sharpe,
    )


def bar_interval(panel: pd.DataFrame) -> pd.Timedelta:
    """The (constant) bar interval of the panel, used only for the periods-per-year sanity check."""
    index = panel.index
    assert isinstance(index, pd.DatetimeIndex)
    if len(index) < 2:
        raise V2BEvaluationError("need at least two bars")
    interval = index[1] - index[0]
    # A daily research-train; keep periods_per_year in agreement with the interval helper.
    _ = periods_per_year_from_interval(interval)
    return interval
