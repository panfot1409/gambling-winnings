"""V2B §21 — the multiplicity-corrected bootstrap tail and a Monte-Carlo sign-flip diagnostic.

The accepted fold-stratified moving-block bootstrap (:mod:`eth_research.m3c.statistics`) reads its
distribution only at the fixed two-sided 95% percentiles (2.5 / 97.5). The cumulative family-wise
correction needs the **one-sided lower bound at the corrected per-family alpha**
(``0.05 / total_family_count``), a more extreme tail the accepted function does not expose. So this
module *replicates the accepted resampling exactly* — same seed, same per-fold ``floor(n**(1/3))``
block length, same circular padding, same fold order and RNG call sequence — and reads it at any
percentile. :func:`corrected_bootstrap` is proven faithful by reproducing the accepted 95% bounds
bit-for-bit (see ``tests/test_v2b_statistics.py``); it only *adds* the corrected tail. The accepted
module is imported and reused, never modified.

A deterministic seeded Monte-Carlo sign-flip permutation (:func:`mc_sign_flip_p_value`) gives a
second, non-parametric read on whether the pooled paired mean could be a fluke of a mean-zero null.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from eth_research.m3c.statistics import (
    M3C_BOOTSTRAP_RESAMPLES,
    M3C_BOOTSTRAP_SEED,
    FoldPaired,
    StatisticsError,
    block_length,
)
from eth_research.v2.strict import V2ValidationError

STATISTICS_SCHEMA_VERSION: int = 1
#: A deterministic seed for the sign-flip Monte-Carlo, distinct from the bootstrap seed.
MC_SIGN_FLIP_SEED: int = 20260721
MC_SIGN_FLIP_RESAMPLES: int = 20000


class V2BStatisticsError(V2ValidationError):
    """A V2B statistics input or invariant was invalid."""


def _pooled(folds: tuple[FoldPaired, ...]) -> tuple[float, int]:
    total = float(sum(float(f.log_excess.sum()) for f in folds))
    count = int(sum(f.log_excess.size for f in folds))
    if count < 2:
        raise V2BStatisticsError("at least two paired observations are required")
    return total / count, count


def _resample_means(
    folds: tuple[FoldPaired, ...], *, seed: int, resamples: int
) -> tuple[np.ndarray, int, tuple[int, ...]]:
    """Replicate the accepted fold-stratified moving-block resampling and return the pooled means.

    Byte-for-byte the same RNG call sequence as
    :func:`eth_research.m3c.statistics.fold_stratified_block_bootstrap`, so reading the returned
    ``means`` at 2.5 / 97.5 reproduces the accepted interval exactly.
    """
    if len(folds) == 0:
        raise V2BStatisticsError("no folds to bootstrap")
    _point, count = _pooled(folds)
    rng = np.random.default_rng(seed)
    total_sum = np.zeros(resamples, dtype="float64")
    block_lengths: list[int] = []
    for fold in sorted(folds, key=lambda f: f.fold_index):
        x = fold.log_excess
        n = x.size
        length = block_length(n)
        block_lengths.append(length)
        num_blocks = -(-n // length)  # ceil
        extended = np.concatenate([x, x[:length]])
        starts = rng.integers(0, n, size=(resamples, num_blocks))
        idx = starts[:, :, None] + np.arange(length)[None, None, :]
        sampled = extended[idx].reshape(resamples, num_blocks * length)[:, :n]
        total_sum += sampled.sum(axis=1)
    return total_sum / count, count, tuple(block_lengths)


@dataclass(frozen=True, slots=True)
class CorrectedBootstrap:
    """The accepted 95% interval plus the family-wise-corrected one-sided lower bound."""

    point_estimate: float
    ci95_lower: float
    ci95_upper: float
    corrected_alpha: float
    corrected_one_sided_lower: float
    corrected_lower_above_zero: bool
    one_sided_p_value: float
    observation_count: int
    resamples: int

    def to_canonical(self) -> dict[str, object]:
        return {
            "point_estimate": self.point_estimate,
            "ci95_lower": self.ci95_lower,
            "ci95_upper": self.ci95_upper,
            "corrected_alpha": self.corrected_alpha,
            "corrected_one_sided_lower": self.corrected_one_sided_lower,
            "corrected_lower_above_zero": self.corrected_lower_above_zero,
            "one_sided_p_value": self.one_sided_p_value,
            "observation_count": self.observation_count,
            "resamples": self.resamples,
        }


def corrected_bootstrap(
    folds: tuple[FoldPaired, ...],
    *,
    corrected_alpha: float,
    seed: int = M3C_BOOTSTRAP_SEED,
    resamples: int = M3C_BOOTSTRAP_RESAMPLES,
) -> CorrectedBootstrap:
    """Bootstrap the pooled mean paired log-excess; return the 95% interval and the corrected tail.

    ``corrected_alpha`` is the family-wise-corrected one-sided level (e.g.
    :meth:`~eth_research.v2b.multiplicity.ResearchMultiplicityState.corrected_per_family_alpha`).
    ``corrected_one_sided_lower`` is the ``100 * corrected_alpha`` percentile of the resample means;
    the candidate clears the corrected bar iff it is ``> 0``. ``one_sided_p_value`` is the fraction
    of resample means ``<= 0`` (the smallest level at which the lower bound would touch zero).
    """
    if not 0.0 < corrected_alpha < 1.0:
        raise V2BStatisticsError("corrected_alpha must be in (0, 1)")
    point, count = _pooled(folds)
    means, _count, _bl = _resample_means(folds, seed=seed, resamples=resamples)
    ci95_lower = float(np.percentile(means, 2.5, method="linear"))
    ci95_upper = float(np.percentile(means, 97.5, method="linear"))
    corrected_lower = float(np.percentile(means, 100.0 * corrected_alpha, method="linear"))
    p_value = float(np.mean(means <= 0.0))
    return CorrectedBootstrap(
        point_estimate=point,
        ci95_lower=ci95_lower,
        ci95_upper=ci95_upper,
        corrected_alpha=corrected_alpha,
        corrected_one_sided_lower=corrected_lower,
        corrected_lower_above_zero=corrected_lower > 0.0,
        one_sided_p_value=p_value,
        observation_count=count,
        resamples=resamples,
    )


def mc_sign_flip_p_value(
    folds: tuple[FoldPaired, ...],
    *,
    seed: int = MC_SIGN_FLIP_SEED,
    resamples: int = MC_SIGN_FLIP_RESAMPLES,
) -> float:
    """A seeded Monte-Carlo sign-flip permutation p-value for ``H0: pooled mean log-excess <= 0``.

    Under a symmetric mean-zero null, flipping the sign of each fold's whole paired block is
    exchangeable; the MC draws ``resamples`` such flips and returns the fraction of pooled means
    ``>=`` the observed pooled mean (a one-sided upper-tail p-value). A small value means the
    observed edge is unlikely under a no-edge null.
    """
    observed, count = _pooled(folds)
    ordered = sorted(folds, key=lambda f: f.fold_index)
    fold_sums = np.array([float(f.log_excess.sum()) for f in ordered])
    rng = np.random.default_rng(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(resamples, fold_sums.size))
    flipped_means = (signs * fold_sums).sum(axis=1) / count
    # Include the observed configuration for a valid (never-zero) permutation p-value.
    ge = float(np.sum(flipped_means >= observed)) + 1.0
    return ge / (resamples + 1.0)


def to_fold_paired(log_excess_by_fold: dict[int, np.ndarray]) -> tuple[FoldPaired, ...]:
    """Wrap per-fold log-excess arrays as :class:`FoldPaired` (a helper for tests / callers)."""
    out: list[FoldPaired] = []
    for fold_index in sorted(log_excess_by_fold):
        arr = np.asarray(log_excess_by_fold[fold_index], dtype="float64")
        if arr.ndim != 1 or arr.size == 0:
            raise V2BStatisticsError(f"fold {fold_index}: log-excess must be a non-empty 1-D array")
        out.append(FoldPaired(fold_index=fold_index, log_excess=arr))
    if not out:
        raise V2BStatisticsError("no folds")
    return tuple(out)


__all__ = [
    "MC_SIGN_FLIP_RESAMPLES",
    "MC_SIGN_FLIP_SEED",
    "STATISTICS_SCHEMA_VERSION",
    "CorrectedBootstrap",
    "StatisticsError",
    "V2BStatisticsError",
    "corrected_bootstrap",
    "mc_sign_flip_p_value",
    "to_fold_paired",
]
