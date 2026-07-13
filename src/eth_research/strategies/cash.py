"""Cash baseline: always flat — the nominal zero-risk reference."""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from eth_research.strategies.base import Strategy


class Cash(Strategy):
    """Hold cash at all times: target is always 0.

    A nominal zero-risk baseline. It never trades, so it has no fills, no
    turnover, and constant equity; volatility-based ratios are undefined
    (zero variance). It is not a claim that holding cash is optimal — only
    a fixed reference every active strategy is compared against.
    """

    initial_target: ClassVar[int] = 0

    @property
    def name(self) -> str:
        return "cash"

    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        return pd.Series(0.0, index=data.index, name="target_position")
