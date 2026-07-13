"""Deterministic moving-block bootstrap for paired daily OOS excess returns.

Quantifies the sampling variability of one in-sample research-train
diagnostic: the arithmetic mean daily *paired excess return* of a candidate
versus buy-and-hold over the pooled reset-OOS observations. It is **not** a
profitability proof, its interval is **not** annualized, and it does not
remove uncertainty — it only describes how the mean would vary under
resampling of the observed blocks.

Everything is pinned (``moving-block-bootstrap-v1``): seed 20260713, block
length 30, 5000 resamples, 95% interval, statistic = arithmetic mean,
non-circular, sampling with replacement, ``numpy.random.Generator(PCG64)``.
Given the same input series the output bytes are identical run to run.
Missing, duplicate, shifted, or non-finite observations are rejected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from eth_research.data.provenance import require_int
from eth_research.data.validation import require_finite_float
from eth_research.walkforward import (
    BOOTSTRAP_ALGORITHM,
    BOOTSTRAP_BLOCK_LENGTH,
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
)

RNG_ALGORITHM: str = "numpy.random.Generator(PCG64)"
PERCENTILE_METHOD: str = "linear"
STATISTIC: str = "arithmetic_mean_daily_paired_excess_return"


class BootstrapError(RuntimeError):
    """The bootstrap inputs are malformed or the configuration is off-spec."""


@dataclass(frozen=True)
class BootstrapConfig:
    """The pinned block-bootstrap configuration."""

    algorithm: str = BOOTSTRAP_ALGORITHM
    seed: int = BOOTSTRAP_SEED
    block_length: int = BOOTSTRAP_BLOCK_LENGTH
    resamples: int = BOOTSTRAP_RESAMPLES
    confidence: float = BOOTSTRAP_CONFIDENCE
    rng_algorithm: str = RNG_ALGORITHM
    percentile_method: str = PERCENTILE_METHOD
    statistic: str = STATISTIC

    def __post_init__(self) -> None:
        if self.algorithm != BOOTSTRAP_ALGORITHM:
            raise ValueError(f"algorithm is pinned to {BOOTSTRAP_ALGORITHM!r}")
        require_int("seed", self.seed)
        if self.block_length < 1:
            raise ValueError("block_length must be >= 1")
        if self.resamples < 1:
            raise ValueError("resamples must be >= 1")
        if not 0.0 < require_finite_float("confidence", self.confidence) < 1.0:
            raise ValueError("confidence must be in (0, 1)")
        if self.rng_algorithm != RNG_ALGORITHM:
            raise ValueError(f"rng_algorithm is pinned to {RNG_ALGORITHM!r}")
        if self.percentile_method != PERCENTILE_METHOD:
            raise ValueError(f"percentile_method is pinned to {PERCENTILE_METHOD!r}")
        if self.statistic != STATISTIC:
            raise ValueError(f"statistic is pinned to {STATISTIC!r}")


@dataclass(frozen=True)
class BootstrapInterval:
    """The point estimate and confidence interval of the paired-excess mean."""

    observation_count: int
    point_estimate: float
    ci_lower: float
    ci_median: float
    ci_upper: float
    config: BootstrapConfig

    def __post_init__(self) -> None:
        require_int("observation_count", self.observation_count)
        for label in ("point_estimate", "ci_lower", "ci_median", "ci_upper"):
            require_finite_float(label, getattr(self, label))
        if not self.ci_lower <= self.ci_median <= self.ci_upper:
            raise ValueError("confidence bounds must be ordered lower <= median <= upper")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "observation_count": self.observation_count,
            "point_estimate": self.point_estimate,
            "ci_lower": self.ci_lower,
            "ci_median": self.ci_median,
            "ci_upper": self.ci_upper,
            "algorithm": self.config.algorithm,
            "seed": self.config.seed,
            "block_length": self.config.block_length,
            "resamples": self.config.resamples,
            "confidence": self.config.confidence,
            "rng_algorithm": self.config.rng_algorithm,
            "percentile_method": self.config.percentile_method,
            "statistic": self.config.statistic,
        }


def paired_excess_returns(
    candidate: pd.Series[float], buy_and_hold: pd.Series[float]
) -> pd.Series[float]:
    """Align two daily OOS return series by timestamp and difference them.

    Both series must share exactly the same strictly-increasing, unique,
    timezone-aware index; a missing, duplicate, shifted, or non-finite
    observation is rejected, never dropped or filled.
    """
    for label, series in (("candidate", candidate), ("buy_and_hold", buy_and_hold)):
        if not isinstance(series.index, pd.DatetimeIndex) or series.index.tz is None:
            raise BootstrapError(f"{label} returns must have a timezone-aware DatetimeIndex")
        if not series.index.is_unique:
            raise BootstrapError(f"{label} returns have duplicate timestamps")
        if not series.index.is_monotonic_increasing:
            raise BootstrapError(f"{label} returns are not strictly time-ordered")
        if not np.isfinite(series.to_numpy(dtype=float)).all():
            raise BootstrapError(f"{label} returns contain non-finite values")
    if len(candidate) != len(buy_and_hold) or not candidate.index.equals(buy_and_hold.index):
        raise BootstrapError(
            "candidate and buy-and-hold returns are not aligned on identical timestamps"
        )
    excess = candidate.to_numpy(dtype=float) - buy_and_hold.to_numpy(dtype=float)
    return pd.Series(excess, index=candidate.index, name="paired_excess_return")


def moving_block_bootstrap(
    paired_excess: pd.Series[float], config: BootstrapConfig | None = None
) -> BootstrapInterval:
    """Non-circular moving-block bootstrap of the mean paired excess return.

    Blocks of ``block_length`` consecutive observations are drawn with
    replacement from the ``n - block_length + 1`` possible start positions,
    concatenated to length ``n`` and truncated; the mean is computed on each
    of ``resamples`` resamples. The interval is the pinned lower/median/upper
    percentiles of those means; the point estimate is the mean of the
    original series.
    """
    cfg = config if config is not None else BootstrapConfig()
    values = paired_excess.to_numpy(dtype=float)
    n = len(values)
    if n == 0:
        raise BootstrapError("cannot bootstrap an empty series")
    if not np.isfinite(values).all():
        raise BootstrapError("paired excess series contains non-finite values")
    if cfg.block_length > n:
        raise BootstrapError(
            f"block_length {cfg.block_length} exceeds the sample size {n}; a block cannot be drawn"
        )

    rng = np.random.Generator(np.random.PCG64(cfg.seed))
    max_start = n - cfg.block_length + 1
    blocks_needed = (n + cfg.block_length - 1) // cfg.block_length
    # Precompute an index matrix of block offsets for vectorized gathering.
    offsets = np.arange(cfg.block_length)
    means = np.empty(cfg.resamples, dtype=float)
    for i in range(cfg.resamples):
        starts = rng.integers(0, max_start, size=blocks_needed)
        # positions[b, j] = starts[b] + j; flatten and truncate to n.
        positions = (starts[:, None] + offsets[None, :]).reshape(-1)[:n]
        means[i] = float(values[positions].mean())

    lower_pct = (1.0 - cfg.confidence) / 2.0 * 100.0
    upper_pct = (1.0 + cfg.confidence) / 2.0 * 100.0
    # method is pinned to "linear" (validated on the config); the literal
    # keeps numpy's typed overload happy.
    assert cfg.percentile_method == "linear"
    ci_lower = float(np.percentile(means, lower_pct, method="linear"))
    ci_median = float(np.percentile(means, 50.0, method="linear"))
    ci_upper = float(np.percentile(means, upper_pct, method="linear"))
    return BootstrapInterval(
        observation_count=n,
        point_estimate=float(values.mean()),
        ci_lower=ci_lower,
        ci_median=ci_median,
        ci_upper=ci_upper,
        config=cfg,
    )


def bootstrap_bytes(interval: BootstrapInterval) -> bytes:
    """Deterministic serialization of a bootstrap interval (for hashing)."""
    text = json.dumps(
        interval.to_json_dict(), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
    )
    return (text + "\n").encode("utf-8")
