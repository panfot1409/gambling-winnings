"""Buy-and-hold benchmark strategy."""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from eth_research.strategies.base import Strategy


class BuyAndHold(Strategy):
    """Hold a full position at all times — the passive benchmark.

    Buy-and-hold is an ex-ante benchmark that requires no observed price
    data: ``initial_target = 1`` means it **enters at the first available
    open** of the evaluated window (paying fee and slippage there) and never
    trades again. Any active strategy has to beat this after costs.
    """

    initial_target: ClassVar[int] = 1

    @property
    def name(self) -> str:
        return "buy_and_hold"

    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        return pd.Series(1.0, index=data.index, name="target_position")
