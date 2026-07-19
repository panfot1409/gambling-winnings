"""V2B §21 — the corrected-alpha bootstrap reconciles with the accepted one and adds the tail."""

from __future__ import annotations

import numpy as np

from eth_research.m3c.statistics import FoldPaired, fold_stratified_block_bootstrap
from eth_research.v2b import statistics as st


def _folds(
    mean: float, sd: float, seed: int, n: int = 300, count: int = 6
) -> tuple[FoldPaired, ...]:
    rng = np.random.default_rng(seed)
    return tuple(FoldPaired(fold_index=i, log_excess=rng.normal(mean, sd, n)) for i in range(count))


def test_corrected_bootstrap_reproduces_the_accepted_95pct_bounds_exactly() -> None:
    folds = _folds(0.001, 0.02, seed=7)
    accepted = fold_stratified_block_bootstrap(folds)
    mine = st.corrected_bootstrap(folds, corrected_alpha=0.005)
    # Same RNG call sequence -> identical resample distribution -> identical percentiles.
    assert mine.ci95_lower == accepted.ci_lower
    assert mine.ci95_upper == accepted.ci_upper
    assert mine.point_estimate == accepted.point_estimate


def test_corrected_tail_is_more_extreme_than_the_95pct_lower() -> None:
    folds = _folds(0.001, 0.02, seed=8)
    mine = st.corrected_bootstrap(folds, corrected_alpha=0.005)
    # A one-sided 0.5% lower bound is below the two-sided 95% (2.5%) lower bound.
    assert mine.corrected_one_sided_lower <= mine.ci95_lower


def test_corrected_lower_above_zero_flags_a_strong_positive_edge() -> None:
    strong = _folds(0.02, 0.005, seed=9)  # mean >> noise
    weak = _folds(0.0, 0.02, seed=9)  # mean-zero
    assert st.corrected_bootstrap(strong, corrected_alpha=0.005).corrected_lower_above_zero
    assert not st.corrected_bootstrap(weak, corrected_alpha=0.005).corrected_lower_above_zero


def test_mc_sign_flip_p_value_is_small_for_a_strong_edge_and_midrange_for_null() -> None:
    strong = _folds(0.05, 0.005, seed=10)
    null = _folds(0.0, 0.02, seed=11)
    p_strong = st.mc_sign_flip_p_value(strong)
    p_null = st.mc_sign_flip_p_value(null)
    assert 0.0 < p_strong <= 0.05
    assert 0.1 < p_null < 0.9  # a mean-zero series is not significant


def test_to_fold_paired_round_trips() -> None:
    arrays = {0: np.array([0.1, 0.2]), 1: np.array([0.3, -0.1, 0.05])}
    folds = st.to_fold_paired(arrays)
    assert tuple(f.fold_index for f in folds) == (0, 1)
    assert folds[1].log_excess.shape == (3,)


def test_corrected_bootstrap_is_deterministic() -> None:
    folds = _folds(0.001, 0.02, seed=12)
    a = st.corrected_bootstrap(folds, corrected_alpha=0.01)
    b = st.corrected_bootstrap(folds, corrected_alpha=0.01)
    assert a.to_canonical() == b.to_canonical()
