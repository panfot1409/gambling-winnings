"""Strategy interface shared by all trading strategies."""

from __future__ import annotations

import abc

import pandas as pd


class Strategy(abc.ABC):
    """Maps historical OHLCV data to target positions.

    Contract
    --------
    * ``target_positions(data)`` returns one value per input row, aligned to
      ``data.index``.
    * The value at timestamp ``t`` may use information up to and including
      bar ``t`` only — the backtest engine executes it on the *next* bar, so
      strategies never trade on the bar they just observed.
    * Positions are fractions of equity in ``[0, 1]``: ``0`` is flat (cash),
      ``1`` is fully invested. Short selling and leverage are out of scope
      for this research project and are rejected by the engine.
    """

    @property
    def name(self) -> str:
        """Identifier used in results and reports."""
        return type(self).__name__

    @abc.abstractmethod
    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        """Return the target position for each bar of ``data``."""
