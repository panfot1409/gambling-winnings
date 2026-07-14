"""Donchian-channel breakout: a fixed, long-only, stateful exploratory baseline.

Not a promoted candidate — a declared, never-tuned exploratory baseline for
the Milestone 3A research-train walk-forward.

Signal, evaluated at the close of bar ``t`` (timestamps are candle open
times), with the **current bar excluded** from every channel:

* **entry** — ``close[t] > max(high over the previous ``entry_window``
  completed candles)``: go long (target 1);
* **exit** — ``close[t] < min(low over the previous ``exit_window``
  completed candles)``: go flat (target 0);
* otherwise retain the previous target (stateful).

Strict causality: the target decided at close ``t`` is executed by the
engine no earlier than open ``t+1``. Equality never triggers (strict
``>`` / ``<``). The strategy is flat until ``entry_window`` prior candles
exist. Targets are binary ``{0, 1}`` — no shorting, leverage, fractional
sizing, pyramiding, stops, take-profit, volatility targeting, or parameter
search.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from eth_research.strategies.base import Strategy


@dataclass(frozen=True)
class DonchianChannel(Strategy):
    """Long/flat Donchian-channel breakout with the current bar excluded."""

    entry_window: int = 55
    exit_window: int = 20

    def __post_init__(self) -> None:
        if self.entry_window < 1:
            raise ValueError(f"entry_window must be >= 1, got {self.entry_window}")
        if self.exit_window < 1:
            raise ValueError(f"exit_window must be >= 1, got {self.exit_window}")

    @property
    def name(self) -> str:
        return f"donchian_{self.entry_window}_{self.exit_window}"

    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        close = data["close"].astype(float).to_numpy()
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        # Channels over the *previous* N completed candles: rolling(N) ends
        # at the current bar, then shift(1) drops it, so the current high and
        # low never enter their own breakout test (the look-ahead guard).
        entry_level = high.rolling(self.entry_window).max().shift(1).to_numpy()
        exit_level = low.rolling(self.exit_window).min().shift(1).to_numpy()

        n = len(close)
        target = np.zeros(n, dtype=float)
        state = 0.0
        for position in range(n):
            # Flat until entry_window prior candles exist (entry_level is
            # finite only then). NaN comparisons are False, so the state is
            # retained through the warm-up regardless.
            if position >= self.entry_window and np.isfinite(entry_level[position]):
                if close[position] > entry_level[position]:
                    state = 1.0
                elif np.isfinite(exit_level[position]) and close[position] < exit_level[position]:
                    state = 0.0
            else:
                state = 0.0
            target[position] = state
        return pd.Series(target, index=data.index, name="target_position")
