"""Strategy interface shared by all trading strategies."""

from __future__ import annotations

import abc
from typing import ClassVar

import pandas as pd


class Strategy(abc.ABC):
    """Maps historical OHLCV data to binary target positions.

    Contract
    --------
    * ``target_positions(data)`` returns one value per input row, aligned to
      ``data.index``, restricted to exactly ``0.0`` (hold cash) or ``1.0``
      (hold ETH). Fractional weights are not supported in Milestone 1
      because the engine implements exact rebalancing only for the
      long/cash case.
    * The value at row ``t`` is the target decided **after observing the
      close of bar** ``t``; the engine executes it at the **open of bar**
      ``t + 1``. A strategy must never use rows after ``t`` to compute the
      value at ``t``.
    * ``initial_target`` is the ex-ante position established at the very
      first evaluated open when no earlier observations (warm-up context)
      exist. It must not depend on observed prices: buy-and-hold sets it to
      1, data-driven strategies keep the default 0 (start in cash).
    * Short selling and leverage are out of scope for this research project
      and are rejected by the engine.
    """

    initial_target: ClassVar[int] = 0
    """Ex-ante target at the first evaluated open; must be 0 or 1."""

    @property
    def name(self) -> str:
        """Identifier used in results and reports."""
        return type(self).__name__

    @abc.abstractmethod
    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        """Return the binary target position for each bar of ``data``."""
