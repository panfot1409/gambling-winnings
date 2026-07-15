"""Fold-seam-aware bootstrap + PSR: determinism, alignment, and oracle agreement."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.m3c.statistics import (
    FoldPaired,
    align_paired_by_fold,
    block_length,
    fold_stratified_block_bootstrap,
    paired_log_excess,
    probabilistic_sharpe_ratio,
    slow_reference_bootstrap,
)

_REJECT = (ValueError, TypeError)


def _folds(sizes: list[int], *, seed: int = 1) -> tuple[FoldPaired, ...]:
    rng = np.random.default_rng(seed)
    return tuple(
        FoldPaired(fold_index=i, log_excess=rng.normal(0.0002, 0.01, size=n))
        for i, n in enumerate(sizes)
    )


def test_block_length_is_floor_cube_root() -> None:
    assert [block_length(n) for n in (1, 8, 27, 30, 225, 226)] == [1, 2, 3, 3, 6, 6]


def test_bootstrap_is_deterministic() -> None:
    folds = _folds([40, 35, 33, 30, 28])
    a = fold_stratified_block_bootstrap(folds, seed=20260714, resamples=3000)
    b = fold_stratified_block_bootstrap(folds, seed=20260714, resamples=3000)
    assert (a.point_estimate, a.ci_lower, a.ci_upper) == (b.point_estimate, b.ci_lower, b.ci_upper)
    assert a.observation_count == sum(f.log_excess.size for f in folds)
    assert a.fold_count == 5


def test_point_estimate_matches_slow_oracle_and_ci_is_close() -> None:
    folds = _folds([50, 44, 40], seed=9)
    fast = fold_stratified_block_bootstrap(folds, seed=7, resamples=6000)
    point, lo, hi = slow_reference_bootstrap(folds, seed=7, resamples=6000)
    assert abs(fast.point_estimate - point) < 1e-12  # pooled mean is exact, not resampled
    assert abs(fast.ci_lower - lo) < 5e-4
    assert abs(fast.ci_upper - hi) < 5e-4


def test_all_positive_and_all_negative_excess_intervals_have_correct_sign() -> None:
    pos = (FoldPaired(0, np.full(30, 0.01)), FoldPaired(1, np.full(30, 0.02)))
    assert fold_stratified_block_bootstrap(pos, resamples=500).ci_lower > 0.0
    neg = (FoldPaired(0, np.full(30, -0.01)), FoldPaired(1, np.full(30, -0.02)))
    assert fold_stratified_block_bootstrap(neg, resamples=500).ci_upper < 0.0


def test_constant_series_collapses_to_a_point() -> None:
    const = (FoldPaired(0, np.full(20, 0.005)),)
    res = fold_stratified_block_bootstrap(const, resamples=500)
    assert res.point_estimate == pytest.approx(0.005)
    assert res.ci_lower == pytest.approx(0.005)
    assert res.ci_upper == pytest.approx(0.005)


def test_no_block_crosses_a_fold_seam() -> None:
    # A block sampled within fold f can only contain fold-f values. Give each fold a
    # unique constant; every resample mean must be the exact pooled mean of the
    # constants (impossible if a block ever mixed two folds' values under the pooled
    # weighting only when counts differ — here equal counts make cross-mixing detectable).
    folds = (FoldPaired(0, np.full(24, 1.0)), FoldPaired(1, np.full(24, 3.0)))
    res = fold_stratified_block_bootstrap(folds, resamples=1000)
    assert res.ci_lower == pytest.approx(2.0)  # each resample is exactly (24*1 + 24*3)/48
    assert res.ci_upper == pytest.approx(2.0)


def test_paired_alignment_rejects_index_mismatch_and_positional_fallback() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="D", tz="UTC")
    other = pd.date_range("2020-02-01", periods=5, freq="D", tz="UTC")
    cand = {0: pd.Series([0.01] * 5, index=idx)}
    bnh_bad = {0: pd.Series([0.01] * 5, index=other)}
    with pytest.raises(_REJECT):
        align_paired_by_fold(cand, bnh_bad)
    bnh_ok = {0: pd.Series([0.005] * 5, index=idx)}
    (fp,) = align_paired_by_fold(cand, bnh_ok)
    assert fp.log_excess.shape == (5,)


def test_paired_alignment_rejects_fold_set_mismatch() -> None:
    idx = pd.date_range("2020-01-01", periods=3, freq="D", tz="UTC")
    with pytest.raises(_REJECT):
        align_paired_by_fold(
            {0: pd.Series([0.0] * 3, index=idx)}, {1: pd.Series([0.0] * 3, index=idx)}
        )


def test_paired_log_excess_rejects_returns_at_or_below_minus_one() -> None:
    with pytest.raises(_REJECT):
        paired_log_excess(np.array([-1.0, 0.0]), np.array([0.0, 0.0]))
    with pytest.raises(_REJECT):
        paired_log_excess(np.array([0.0]), np.array([np.nan]))


def test_psr_is_bounded_and_undefined_variance_is_rejected() -> None:
    rng = np.random.default_rng(3)
    psr = probabilistic_sharpe_ratio(rng.normal(0.01, 0.02, size=300))
    assert 0.0 <= psr.psr <= 1.0
    assert psr.sample_size == 300
    with pytest.raises(_REJECT):
        probabilistic_sharpe_ratio(np.full(50, 0.01))  # zero variance


def test_block_length_matches_exact_integer_floor_cube_root() -> None:
    # An independent exact floor-cbrt (pure integer search) must agree everywhere in a
    # wide range, including every perfect cube and its neighbours, so the committed
    # block-length rule never depends on transcendental cube-root rounding (N-audit).
    def exact_floor_cbrt(n: int) -> int:
        k = 0
        while (k + 1) ** 3 <= n:
            k += 1
        return k

    for n in range(1, 5000):
        assert block_length(n) == max(1, exact_floor_cbrt(n))
    for cube in (8, 27, 64, 125, 216, 343, 1000, 8000, 27000):
        for n in (cube - 1, cube, cube + 1):
            assert block_length(n) == max(1, exact_floor_cbrt(n))
    # The real M3C candidate causal_proxy_base fold sizes (225, 226) both give L = 6.
    assert block_length(225) == 6
    assert block_length(226) == 6
