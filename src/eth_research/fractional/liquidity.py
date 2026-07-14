"""Causal lagged-liquidity estimator (Milestone 3B, Phase 7).

At the execution open of bar ``t`` the estimator uses **only** candles through
``t-1``: it slices ``frame.index < as_of`` itself, so the current bar's volume
and close can never leak into the estimate that prices the current bar's fill.
The statistic is the median of the last ``lookback`` lagged daily dollar volumes
(``close * volume``); the median of lagged base volumes is reported alongside.

The estimate at ``open[t]`` is prefix-invariant: appending or mutating any row at
or after ``t`` cannot change it (enforced by the strict ``< as_of`` slice and by
dedicated prefix-invariance / future-mutation tests). Non-finite volume or close
in the contributing window fails loudly — it never silently disables a cap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

LIQUIDITY_LOOKBACK: int = 30
LIQUIDITY_MIN_OBSERVATIONS: int = 30


class LiquidityError(Exception):
    """The liquidity window was malformed (non-finite value, unsorted index)."""


@dataclass(frozen=True)
class LiquidityEstimate:
    """A causal lagged-liquidity estimate as of one execution open.

    ``dollar_volume_stat`` / ``base_volume_stat`` are ``None`` when the warm-up
    is insufficient. ``sufficient`` is ``True`` only when at least
    ``min_observations`` lagged bars contributed; ``reason`` gives a typed cause
    otherwise. Every contributing timestamp is strictly before ``as_of``.
    """

    as_of: pd.Timestamp
    oldest_contributing: pd.Timestamp | None
    newest_contributing: pd.Timestamp | None
    observation_count: int
    base_volume_stat: float | None
    dollar_volume_stat: float | None
    sufficient: bool
    reason: str | None

    @property
    def available(self) -> bool:
        """True when a strictly positive dollar-volume estimate is usable."""
        return (
            self.sufficient
            and self.dollar_volume_stat is not None
            and self.dollar_volume_stat > 0.0
        )


def estimate_liquidity(
    frame: pd.DataFrame,
    as_of: pd.Timestamp,
    *,
    lookback: int = LIQUIDITY_LOOKBACK,
    min_observations: int = LIQUIDITY_MIN_OBSERVATIONS,
) -> LiquidityEstimate:
    """Median lagged daily dollar volume as of the execution open ``as_of``.

    Uses only rows with ``index < as_of`` (i.e. through ``t-1``); the newest
    ``lookback`` of those rows form the window. ``close`` and ``volume`` of the
    current or any future bar are never read.
    """
    if lookback <= 0 or min_observations <= 0:
        raise LiquidityError("lookback and min_observations must be positive")
    if "close" not in frame.columns or "volume" not in frame.columns:
        raise LiquidityError("frame must carry 'close' and 'volume' columns")

    lagged = frame.loc[frame.index < as_of]
    if not lagged.index.is_monotonic_increasing:
        raise LiquidityError("liquidity history index is not monotonically increasing")

    window = lagged.tail(lookback)
    count = len(window)
    if count < min_observations:
        return LiquidityEstimate(
            as_of=as_of,
            oldest_contributing=None,
            newest_contributing=None,
            observation_count=count,
            base_volume_stat=None,
            dollar_volume_stat=None,
            sufficient=False,
            reason="insufficient_liquidity_history",
        )

    close = window["close"].to_numpy(dtype="float64")
    volume = window["volume"].to_numpy(dtype="float64")
    if not np.isfinite(close).all() or not np.isfinite(volume).all():
        raise LiquidityError("non-finite close or volume in the liquidity window")
    if (volume < 0.0).any():
        raise LiquidityError("negative volume in the liquidity window")

    dollar_volume = close * volume
    dollar_stat = float(np.median(dollar_volume))
    base_stat = float(np.median(volume))
    newest = window.index[-1]
    if newest >= as_of:  # pragma: no cover - guarded by the < as_of slice
        raise LiquidityError("liquidity window newest timestamp is not before as_of")

    return LiquidityEstimate(
        as_of=as_of,
        oldest_contributing=window.index[0],
        newest_contributing=newest,
        observation_count=count,
        base_volume_stat=base_stat,
        dollar_volume_stat=dollar_stat,
        sufficient=True,
        reason=None,
    )
