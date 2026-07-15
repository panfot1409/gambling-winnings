"""Fold-seam-aware paired inference for the M3C primary endpoint.

Primary statistic: the mean, across every candidate OOS day under ``causal_proxy_base``,
of the paired daily log-return excess over buy-and-hold,
``log1p(candidate_net) - log1p(bnh_net)`` (any net return <= -1 is rejected before
the log). Observations are aligned exactly by (fold, timestamp) — never positionally
after discarding the index.

Primary interval: a fold-stratified moving-block bootstrap. Blocks are drawn **within
a fold only**, so a block never crosses an independently-reset fold seam; each fold's
observation count is preserved; the resampled fold contributions are pooled only for
the mean (no stitched equity curve, CAGR, or drawdown is ever bootstrapped). All
bootstrap constants are fixed a-priori, independent of any observed strategy result:

* block length per fold = floor(n**(1/3)) (a committed integer rule of the fold length);
* deterministic RNG seed = 20260714;
* 20,000 resamples;
* two-sided 95% percentile interval.

A slow, obviously-correct reference bootstrap is provided for tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

M3C_BOOTSTRAP_SEED: int = 20260714
M3C_BOOTSTRAP_RESAMPLES: int = 20000
M3C_BOOTSTRAP_CONFIDENCE: float = 0.95
M3C_BOOTSTRAP_ALGORITHM: str = "fold-stratified-moving-block-v1"
_LOWER_PCT: float = 2.5
_UPPER_PCT: float = 97.5


class StatisticsError(ValueError):
    """A paired-inference input violated the strict alignment/domain contract."""


def _integer_cube_root(n: int) -> int:
    """Exact floor of the real cube root of ``n >= 0`` using integer arithmetic only.

    A float cube root (``n ** (1/3)``) is not correctly rounded and can land on the
    wrong side of an integer for perfect (or near-perfect) cubes; this seeds from the
    float estimate and then corrects deterministically, so the block-length rule never
    depends on transcendental rounding.
    """
    if n < 0:
        raise StatisticsError("cube root of a negative count is undefined")
    if n == 0:
        return 0
    k: int = round(n ** (1.0 / 3.0))
    while k * k * k > n:
        k -= 1
    while (k + 1) ** 3 <= n:
        k += 1
    return k


def block_length(n: int) -> int:
    """The committed a-priori block length: exact ``floor(n**(1/3))``, at least 1."""
    if n <= 0:
        raise StatisticsError("fold observation count must be positive")
    return max(1, _integer_cube_root(n))


def paired_log_excess(candidate_net: np.ndarray, bnh_net: np.ndarray) -> np.ndarray:
    """``log1p(candidate) - log1p(bnh)`` after rejecting any net return <= -1."""
    cand = np.asarray(candidate_net, dtype="float64")
    bnh = np.asarray(bnh_net, dtype="float64")
    if cand.shape != bnh.shape or cand.ndim != 1:
        raise StatisticsError("candidate and buy-and-hold return arrays must be 1-D and aligned")
    if not (np.isfinite(cand).all() and np.isfinite(bnh).all()):
        raise StatisticsError("non-finite net return")
    if (cand <= -1.0).any() or (bnh <= -1.0).any():
        raise StatisticsError("net return <= -1 cannot be log-transformed")
    return np.log1p(cand) - np.log1p(bnh)


@dataclass(frozen=True)
class FoldPaired:
    """One fold's exactly-aligned paired daily log-excess series."""

    fold_index: int
    log_excess: np.ndarray  # shape (n,), n == fold OOS day count


def align_paired_by_fold(
    candidate_returns_by_fold: dict[int, pd.Series],
    bnh_returns_by_fold: dict[int, pd.Series],
) -> tuple[FoldPaired, ...]:
    """Pair candidate vs buy-and-hold daily returns fold-by-fold on the exact index.

    Both maps are keyed by fold index; within a fold the two series must carry the
    identical timestamp index (a mismatch is a strict error, never a positional
    fallback).
    """
    if set(candidate_returns_by_fold) != set(bnh_returns_by_fold):
        raise StatisticsError("candidate and buy-and-hold folds do not match")
    out: list[FoldPaired] = []
    for fold_index in sorted(candidate_returns_by_fold):
        cand = candidate_returns_by_fold[fold_index]
        bnh = bnh_returns_by_fold[fold_index]
        if not cand.index.equals(bnh.index):
            raise StatisticsError(f"fold {fold_index}: candidate/B&H timestamps differ")
        if len(cand) == 0:
            raise StatisticsError(f"fold {fold_index}: no paired observations")
        out.append(
            FoldPaired(
                fold_index=fold_index,
                log_excess=paired_log_excess(cand.to_numpy(), bnh.to_numpy()),
            )
        )
    return tuple(out)


@dataclass(frozen=True)
class BootstrapResult:
    """The primary mean paired log-excess and its two-sided 95% percentile interval."""

    algorithm: str
    seed: int
    resamples: int
    confidence: float
    observation_count: int
    fold_count: int
    block_lengths: tuple[int, ...]
    point_estimate: float
    ci_lower: float
    ci_upper: float

    @property
    def lower_bound_above_zero(self) -> bool:
        return self.ci_lower > 0.0


def _pooled_mean(folds: tuple[FoldPaired, ...]) -> tuple[float, int]:
    total = float(sum(float(f.log_excess.sum()) for f in folds))
    count = int(sum(f.log_excess.size for f in folds))
    if count < 2:
        raise StatisticsError("at least two paired observations are required")
    return total / count, count


def fold_stratified_block_bootstrap(
    folds: tuple[FoldPaired, ...],
    *,
    seed: int = M3C_BOOTSTRAP_SEED,
    resamples: int = M3C_BOOTSTRAP_RESAMPLES,
) -> BootstrapResult:
    """Deterministic fold-stratified moving-block bootstrap of the pooled mean.

    Blocks are drawn within each fold (circular moving blocks), so no block crosses a
    fold seam; each fold keeps its observation count; folds are visited in a fixed
    order so the RNG call sequence — and therefore the interval — is byte-reproducible.
    """
    if len(folds) == 0:
        raise StatisticsError("no folds to bootstrap")
    point, count = _pooled_mean(folds)
    rng = np.random.default_rng(seed)
    total_sum = np.zeros(resamples, dtype="float64")
    block_lengths: list[int] = []
    for fold in sorted(folds, key=lambda f: f.fold_index):
        x = fold.log_excess
        n = x.size
        length = block_length(n)
        block_lengths.append(length)
        num_blocks = -(-n // length)  # ceil
        extended = np.concatenate([x, x[:length]])  # circular pad for wrap-around blocks
        starts = rng.integers(0, n, size=(resamples, num_blocks))
        idx = starts[:, :, None] + np.arange(length)[None, None, :]
        sampled = extended[idx].reshape(resamples, num_blocks * length)[:, :n]
        total_sum += sampled.sum(axis=1)
    means = total_sum / count
    return BootstrapResult(
        algorithm=M3C_BOOTSTRAP_ALGORITHM,
        seed=seed,
        resamples=resamples,
        confidence=M3C_BOOTSTRAP_CONFIDENCE,
        observation_count=count,
        fold_count=len(folds),
        block_lengths=tuple(block_lengths),
        point_estimate=point,
        # Pin the interpolation method explicitly (do not rely on the library default).
        ci_lower=float(np.percentile(means, _LOWER_PCT, method="linear")),
        ci_upper=float(np.percentile(means, _UPPER_PCT, method="linear")),
    )


def slow_reference_bootstrap(
    folds: tuple[FoldPaired, ...], *, seed: int, resamples: int
) -> tuple[float, float, float]:
    """A deliberately naive, obviously-correct reference for small-fixture tests."""
    rng = np.random.default_rng(seed)
    point, count = _pooled_mean(folds)
    means = []
    ordered = sorted(folds, key=lambda f: f.fold_index)
    for _ in range(resamples):
        acc = 0.0
        for fold in ordered:
            x = fold.log_excess
            n = x.size
            length = block_length(n)
            num_blocks = -(-n // length)
            pieces: list[float] = []
            for _b in range(num_blocks):
                start = int(rng.integers(0, n))
                pieces.extend(float(x[(start + k) % n]) for k in range(length))
            acc += float(np.sum(pieces[:n]))
        means.append(acc / count)
    arr = np.array(means)
    return (
        point,
        float(np.percentile(arr, _LOWER_PCT, method="linear")),
        float(np.percentile(arr, _UPPER_PCT, method="linear")),
    )


@dataclass(frozen=True)
class ProbabilisticSharpe:
    """Bailey & Lopez de Prado (2012) PSR of the paired log-excess vs SR* = 0.

    A **secondary, fragile** diagnostic only (five folds + adaptive history); it never
    affects the promotion decision. ``psr`` is the probability the true Sharpe of the
    daily paired excess exceeds the benchmark ``sr_star`` under the non-normal estimator.
    """

    observed_sharpe: float
    benchmark_sharpe: float
    sample_size: int
    skewness: float
    kurtosis: float
    psr: float


def probabilistic_sharpe_ratio(values: np.ndarray, *, sr_star: float = 0.0) -> ProbabilisticSharpe:
    """PSR of a per-observation series (here the daily paired log-excess)."""
    x = np.asarray(values, dtype="float64")
    if x.ndim != 1 or x.size < 3:
        raise StatisticsError("PSR requires at least three observations")
    if not np.isfinite(x).all():
        raise StatisticsError("non-finite value in PSR series")
    n = x.size
    mean = float(x.mean())
    std = float(x.std(ddof=1))
    if std == 0.0:
        raise StatisticsError("PSR is undefined for a zero-variance series")
    sr = mean / std
    centered = (x - mean) / std
    skew = float((centered**3).mean())  # standardized (non-bias-corrected) moments
    kurt = float((centered**4).mean())
    denom = float(np.sqrt(max(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2, 1e-12)))
    z = (sr - sr_star) * np.sqrt(n - 1.0) / denom
    psr = float(0.5 * (1.0 + _erf(z / np.sqrt(2.0))))
    return ProbabilisticSharpe(
        observed_sharpe=sr,
        benchmark_sharpe=sr_star,
        sample_size=n,
        skewness=skew,
        kurtosis=kurt,
        psr=psr,
    )


def _erf(x: float) -> float:
    """math.erf without importing math into the module namespace for one call."""
    import math

    return math.erf(x)
