"""Simple moving-average (SMA) crossover strategy."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from eth_research.strategies.base import Strategy


@dataclass(frozen=True)
class MovingAverageCrossover(Strategy):
    """Long when the fast SMA of close is above the slow SMA, otherwise flat.

    The target at row ``t`` uses closes up to and including bar ``t`` and is
    executed by the engine at the open of bar ``t + 1``. With
    ``fast_window=1`` this degenerates to "price above its SMA". During the
    warm-up period, before both averages have a full window of data, the
    strategy stays flat (``initial_target`` keeps the default 0: it starts
    in cash).
    """

    fast_window: int = 20
    slow_window: int = 50

    def __post_init__(self) -> None:
        if self.fast_window < 1:
            raise ValueError(f"fast_window must be >= 1, got {self.fast_window}")
        if self.slow_window <= self.fast_window:
            raise ValueError(
                f"slow_window ({self.slow_window}) must be greater than "
                f"fast_window ({self.fast_window})"
            )

    @property
    def name(self) -> str:
        return f"sma_{self.fast_window}_{self.slow_window}"

    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        close = data["close"].astype(float)
        fast = close.rolling(self.fast_window).mean()
        slow = close.rolling(self.slow_window).mean()
        # Rolling means are NaN during warm-up; NaN comparisons are False -> flat.
        signal = (fast > slow).astype(float)
        return signal.rename("target_position")
