"""Fold-aware bootstraps for paired daily OOS excess returns (M3A closure R4).

The historical ``moving-block-bootstrap-v1`` sampled blocks over one
concatenation of the five independently reset walk-forward folds, so ~10.6% of
block starts (116/1097 at block length 30) spanned a reset seam — treating
independently reset portfolio paths as one continuous return process. That v1
method and its intervals are preserved unchanged for run-001/run-002; this
module adds two fold-aware methods used from run-003 onward:

* ``fold-stratified-moving-block-bootstrap-v2`` (**primary**): blocks are drawn
  strictly within a fold, so no block ever crosses a reset seam; each fold
  contributes its original observation count; the statistic stays the
  observation-weighted arithmetic mean daily paired excess.
* ``hierarchical-fold-block-bootstrap-v1`` (**sensitivity only**): resample the
  folds as clusters with replacement, then blocks within each selected fold, on
  a domain-separated RNG stream. Five clusters give only weak fold-level
  inference.

Neither establishes alpha or live profitability; both are descriptive,
unadjusted, in-sample research diagnostics. Everything is pinned and
deterministic: given the same per-fold inputs the output bytes are identical.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from eth_research.bootstrap import (
    PERCENTILE_METHOD,
    RNG_ALGORITHM,
    STATISTIC,
    BootstrapError,
)
from eth_research.data.provenance import require_int
from eth_research.data.validation import require_finite_float
from eth_research.walkforward import (
    BOOTSTRAP_BLOCK_LENGTH,
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
)

FOLD_STRATIFIED_ALGORITHM: str = "fold-stratified-moving-block-bootstrap-v2"
HIERARCHICAL_ALGORITHM: str = "hierarchical-fold-block-bootstrap-v1"
_HIERARCHICAL_SEED_OFFSET: int = 1  # domain-separates the sensitivity RNG stream


@dataclass(frozen=True)
class FoldAwareBootstrapConfig:
    """Pinned configuration for both fold-aware bootstraps."""

    seed: int = BOOTSTRAP_SEED
    block_length: int = BOOTSTRAP_BLOCK_LENGTH
    resamples: int = BOOTSTRAP_RESAMPLES
    confidence: float = BOOTSTRAP_CONFIDENCE
    primary_algorithm: str = FOLD_STRATIFIED_ALGORITHM
    sensitivity_algorithm: str = HIERARCHICAL_ALGORITHM
    rng_algorithm: str = RNG_ALGORITHM
    percentile_method: str = PERCENTILE_METHOD
    statistic: str = STATISTIC

    def __post_init__(self) -> None:
        require_int("seed", self.seed)
        if self.block_length < 1:
            raise ValueError("block_length must be >= 1")
        if self.resamples < 1:
            raise ValueError("resamples must be >= 1")
        if not 0.0 < require_finite_float("confidence", self.confidence) < 1.0:
            raise ValueError("confidence must be in (0, 1)")
        if self.primary_algorithm != FOLD_STRATIFIED_ALGORITHM:
            raise ValueError(f"primary_algorithm is pinned to {FOLD_STRATIFIED_ALGORITHM!r}")
        if self.sensitivity_algorithm != HIERARCHICAL_ALGORITHM:
            raise ValueError(f"sensitivity_algorithm is pinned to {HIERARCHICAL_ALGORITHM!r}")
        if self.rng_algorithm != RNG_ALGORITHM:
            raise ValueError(f"rng_algorithm is pinned to {RNG_ALGORITHM!r}")
        if self.percentile_method != PERCENTILE_METHOD:
            raise ValueError(f"percentile_method is pinned to {PERCENTILE_METHOD!r}")
        if self.statistic != STATISTIC:
            raise ValueError(f"statistic is pinned to {STATISTIC!r}")

    @property
    def hierarchical_seed(self) -> int:
        return self.seed + _HIERARCHICAL_SEED_OFFSET


@dataclass(frozen=True)
class FoldAwareInterval:
    """A fold-aware bootstrap interval; carries its exact algorithm identity."""

    algorithm: str
    observation_count: int
    fold_observation_counts: tuple[int, ...]
    point_estimate: float
    ci_lower: float
    ci_median: float
    ci_upper: float
    seed: int
    block_length: int
    resamples: int
    confidence: float

    def __post_init__(self) -> None:
        if self.algorithm not in (FOLD_STRATIFIED_ALGORITHM, HIERARCHICAL_ALGORITHM):
            raise ValueError(f"unknown fold-aware algorithm {self.algorithm!r}")
        require_int("observation_count", self.observation_count)
        if self.observation_count != sum(self.fold_observation_counts):
            raise ValueError("observation_count must equal the sum of fold observation counts")
        for label in ("point_estimate", "ci_lower", "ci_median", "ci_upper"):
            require_finite_float(label, getattr(self, label))
        if not self.ci_lower <= self.ci_median <= self.ci_upper:
            raise ValueError("confidence bounds must be ordered lower <= median <= upper")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "observation_count": self.observation_count,
            "fold_observation_counts": list(self.fold_observation_counts),
            "point_estimate": self.point_estimate,
            "ci_lower": self.ci_lower,
            "ci_median": self.ci_median,
            "ci_upper": self.ci_upper,
            "seed": self.seed,
            "block_length": self.block_length,
            "resamples": self.resamples,
            "confidence": self.confidence,
            "rng_algorithm": RNG_ALGORITHM,
            "percentile_method": PERCENTILE_METHOD,
            "statistic": STATISTIC,
        }


def _validate_folds(
    fold_excess: tuple[pd.Series[float], ...], block_length: int
) -> list[np.ndarray]:
    if not isinstance(fold_excess, tuple) or len(fold_excess) == 0:
        raise BootstrapError("fold_excess must be a non-empty tuple of per-fold series")
    arrays: list[np.ndarray] = []
    for index, series in enumerate(fold_excess):
        if not isinstance(series, pd.Series):
            raise BootstrapError(f"fold {index} is not a pandas Series")
        values = series.to_numpy(dtype=float)
        if len(values) == 0:
            raise BootstrapError(f"fold {index} is empty")
        if not np.isfinite(values).all():
            raise BootstrapError(f"fold {index} contains non-finite values")
        arrays.append(values)
    smallest = min(len(a) for a in arrays)
    if block_length > smallest:
        raise BootstrapError(
            f"block_length {block_length} exceeds the smallest fold length {smallest}; a block "
            "would have to cross a reset seam"
        )
    return arrays


def _resample_within(values: np.ndarray, block_length: int, rng: np.random.Generator) -> np.ndarray:
    """One within-fold moving-block resample, non-circular, truncated to len."""
    n = len(values)
    max_start = n - block_length + 1
    blocks_needed = (n + block_length - 1) // block_length
    offsets = np.arange(block_length)
    starts = rng.integers(0, max_start, size=blocks_needed)
    positions = (starts[:, None] + offsets[None, :]).reshape(-1)[:n]
    return np.asarray(values[positions], dtype=float)


def _interval(
    algorithm: str,
    arrays: list[np.ndarray],
    means: np.ndarray,
    config: FoldAwareBootstrapConfig,
) -> FoldAwareInterval:
    pooled = np.concatenate(arrays)
    lower_pct = (1.0 - config.confidence) / 2.0 * 100.0
    upper_pct = (1.0 + config.confidence) / 2.0 * 100.0
    return FoldAwareInterval(
        algorithm=algorithm,
        observation_count=len(pooled),
        fold_observation_counts=tuple(len(a) for a in arrays),
        point_estimate=float(pooled.mean()),
        ci_lower=float(np.percentile(means, lower_pct, method="linear")),
        ci_median=float(np.percentile(means, 50.0, method="linear")),
        ci_upper=float(np.percentile(means, upper_pct, method="linear")),
        seed=config.seed,
        block_length=config.block_length,
        resamples=config.resamples,
        confidence=config.confidence,
    )


def fold_stratified_moving_block_bootstrap(
    fold_excess: tuple[pd.Series[float], ...],
    config: FoldAwareBootstrapConfig | None = None,
) -> FoldAwareInterval:
    """Primary bootstrap: blocks are drawn strictly within each fold.

    Each resample replaces every fold with a within-fold moving-block resample of
    its own length, concatenates them, and takes the observation-weighted mean.
    No sampled block can span two independently reset folds.
    """
    cfg = config if config is not None else FoldAwareBootstrapConfig()
    arrays = _validate_folds(fold_excess, cfg.block_length)
    rng = np.random.Generator(np.random.PCG64(cfg.seed))
    means = np.empty(cfg.resamples, dtype=float)
    for i in range(cfg.resamples):
        resampled = np.concatenate([_resample_within(a, cfg.block_length, rng) for a in arrays])
        means[i] = float(resampled.mean())
    return _interval(FOLD_STRATIFIED_ALGORITHM, arrays, means, cfg)


def hierarchical_fold_block_bootstrap(
    fold_excess: tuple[pd.Series[float], ...],
    config: FoldAwareBootstrapConfig | None = None,
) -> FoldAwareInterval:
    """Sensitivity bootstrap: resample folds as clusters, then blocks within.

    Each resample chooses ``k`` folds (with replacement) from the ``k`` folds,
    replaces each chosen fold with a within-fold moving-block resample, and takes
    the mean of the concatenation. The RNG stream is domain-separated from the
    primary method. With only five clusters this gives weak fold-level inference
    and is reported as sensitivity only.
    """
    cfg = config if config is not None else FoldAwareBootstrapConfig()
    arrays = _validate_folds(fold_excess, cfg.block_length)
    rng = np.random.Generator(np.random.PCG64(cfg.hierarchical_seed))
    k = len(arrays)
    means = np.empty(cfg.resamples, dtype=float)
    for i in range(cfg.resamples):
        chosen = rng.integers(0, k, size=k)
        resampled = np.concatenate(
            [_resample_within(arrays[j], cfg.block_length, rng) for j in chosen]
        )
        means[i] = float(resampled.mean())
    return _interval(HIERARCHICAL_ALGORITHM, arrays, means, cfg)


def fold_aware_bootstrap_bytes(interval: FoldAwareInterval) -> bytes:
    """Deterministic serialization of a fold-aware interval (for hashing)."""
    text = json.dumps(
        interval.to_json_dict(), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
    )
    return (text + "\n").encode("utf-8")
