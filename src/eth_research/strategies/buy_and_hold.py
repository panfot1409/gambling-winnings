"""Buy-and-hold benchmark strategy."""

from __future__ import annotations

import pandas as pd

from eth_research.strategies.base import Strategy


class BuyAndHold(Strategy):
    """Hold a full position at all times — the passive benchmark.

    Any active strategy has to beat this after costs to be interesting.
    """

    @property
    def name(self) -> str:
        return "buy_and_hold"

    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        return pd.Series(1.0, index=data.index, name="target_position")
