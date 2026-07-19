"""V2B §20 — a small, frozen parameter-sensitivity neighborhood and its stability summary.

A candidate whose edge (if any) evaporates under a one-notch change to its pre-registered parameters
is fragile, not robust — and fragility is a reason to withhold nomination, never to search for a
better setting. So each candidate carries a **frozen** neighborhood (defined here, before the run)
of nearby parameter tuples, and :func:`evaluate_sensitivity` reports how many of them keep a primary
paired 95% lower bound above zero. The registered (center) parameters are always included; nothing
here is optimized or selected — the neighborhood is scored, not searched.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from eth_research.m3c.statistics import align_paired_by_fold, fold_stratified_block_bootstrap
from eth_research.portfolio.costs import CostParameters
from eth_research.v2.strict import V2ValidationError
from eth_research.v2b.candidates import CANDIDATE_A, CANDIDATE_B, V2BCandidateSpec
from eth_research.v2b.evaluation import (
    benchmark_net_returns,
    candidate_net_returns,
)
from eth_research.v2b.execution import PRIMARY_BENCHMARK
from eth_research.v2b.folds import V2BFold, series_by_fold

SENSITIVITY_SCHEMA_VERSION: int = 1


class V2BSensitivityError(V2ValidationError):
    """A sensitivity neighborhood could not be built or scored."""


def _grid(center: int, deltas: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(center + d for d in deltas)


def sensitivity_neighborhood(spec: V2BCandidateSpec) -> tuple[dict[str, int], ...]:
    """The frozen nearby parameter tuples for ``spec`` (always includes the center; all positive).

    Candidate A perturbs each horizon by ``{-20, 0, +20}`` (a 3x3 grid, 9 tuples); Candidate B
    perturbs its single lookback by ``{-18, 0, +18}`` (3 tuples). The deltas are ~20% of the frozen
    values and fixed here before the run.
    """
    if spec.candidate_id == CANDIDATE_A.candidate_id:
        eth = _grid(spec.fixed_parameters["eth_horizon"], (-20, 0, 20))
        btc = _grid(spec.fixed_parameters["btc_horizon"], (-20, 0, 20))
        tuples = [{"eth_horizon": e, "btc_horizon": b} for e in eth for b in btc]
    elif spec.candidate_id == CANDIDATE_B.candidate_id:
        look = _grid(spec.fixed_parameters["lookback"], (-18, 0, 18))
        tuples = [{"lookback": v} for v in look]
    else:
        raise V2BSensitivityError(f"unknown candidate id {spec.candidate_id!r}")
    for params in tuples:
        if any(v <= 0 for v in params.values()):
            raise V2BSensitivityError("sensitivity neighborhood produced a non-positive parameter")
    return tuple(tuples)


@dataclass(frozen=True, slots=True)
class SensitivityReport:
    """How stable a candidate's primary edge is across its frozen parameter neighborhood."""

    candidate_id: str
    neighbor_count: int
    neighbors_lower_above_zero: int
    fraction_lower_above_zero: float
    min_primary_ci_lower: float
    all_above_zero: bool

    def to_canonical(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "neighbor_count": self.neighbor_count,
            "neighbors_lower_above_zero": self.neighbors_lower_above_zero,
            "fraction_lower_above_zero": self.fraction_lower_above_zero,
            "min_primary_ci_lower": self.min_primary_ci_lower,
            "all_above_zero": self.all_above_zero,
        }


def _primary_lower(
    spec: V2BCandidateSpec,
    panel: pd.DataFrame,
    folds: tuple[V2BFold, ...],
    benchmark_by_fold: dict[int, pd.Series],
    primary_cost: CostParameters,
) -> float:
    cand = candidate_net_returns(spec, panel, primary_cost)
    cand_by_fold = series_by_fold(cand.net_return_series(), folds)
    paired = align_paired_by_fold(cand_by_fold, benchmark_by_fold)
    return float(fold_stratified_block_bootstrap(paired).ci_lower)


def evaluate_sensitivity(
    spec: V2BCandidateSpec,
    panel: pd.DataFrame,
    folds: tuple[V2BFold, ...],
    *,
    primary_cost: CostParameters,
) -> SensitivityReport:
    """Score the frozen neighborhood: how many nearby parameter tuples keep a primary 95% lower > 0.

    The benchmark (ETH buy-and-hold) is computed once; each neighbor re-runs only the candidate. A
    candidate is stable iff every neighbor's primary paired 95% lower bound is above zero.
    """
    if not folds:
        raise V2BSensitivityError("no folds")
    bench = benchmark_net_returns(panel, PRIMARY_BENCHMARK, primary_cost)
    bench_by_fold = series_by_fold(bench.net_return_series(), folds)
    lowers: list[float] = []
    for params in sensitivity_neighborhood(spec):
        neighbor = replace(spec, fixed_parameters=dict(params))
        lowers.append(_primary_lower(neighbor, panel, folds, bench_by_fold, primary_cost))
    above = sum(1 for low in lowers if low > 0.0)
    return SensitivityReport(
        candidate_id=spec.candidate_id,
        neighbor_count=len(lowers),
        neighbors_lower_above_zero=above,
        fraction_lower_above_zero=above / len(lowers),
        min_primary_ci_lower=min(lowers),
        all_above_zero=above == len(lowers),
    )
