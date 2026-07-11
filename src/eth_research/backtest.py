"""Vectorized backtest engine with proportional fees and slippage.

Timing convention
-----------------
Bar returns are close-to-close: ``r_t = close_t / close_{t-1} - 1``. The
target position a strategy computes at bar ``t`` is held during bar ``t + 1``
(one-bar execution lag), so a strategy can never trade on the bar it just
observed. Position changes are charged
``|position change| * (fee_rate + slippage_rate)`` in the bar where the trade
settles. The final position is marked to market, not force-closed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from eth_research.data.schema import validate_ohlcv
from eth_research.strategies.base import Strategy

TRADE_EPSILON: float = 1e-12
"""Position changes at or below this size are not counted as trades."""


@dataclass(frozen=True)
class CostModel:
    """Proportional trading costs per unit of turnover.

    The defaults are deliberately non-zero (10 bps fee + 5 bps slippage);
    pass ``CostModel(fee_rate=0.0, slippage_rate=0.0)`` explicitly for a
    frictionless run.
    """

    fee_rate: float = 0.001
    slippage_rate: float = 0.0005

    def __post_init__(self) -> None:
        for label, rate in (("fee_rate", self.fee_rate), ("slippage_rate", self.slippage_rate)):
            if not 0.0 <= rate < 1.0:
                raise ValueError(f"{label} must be in [0, 1), got {rate}")

    @property
    def rate_per_unit_turnover(self) -> float:
        return self.fee_rate + self.slippage_rate


@dataclass(frozen=True)
class BacktestResult:
    """Per-bar series produced by one backtest run."""

    strategy_name: str
    positions: pd.Series[float]
    """Position actually held during each bar (after the execution lag)."""
    gross_returns: pd.Series[float]
    """Position times asset return, before costs."""
    costs: pd.Series[float]
    """Cost drag per bar."""
    returns: pd.Series[float]
    """Net returns: gross returns minus costs."""
    turnover: pd.Series[float]
    """|Δposition| per bar."""
    equity: pd.Series[float]
    """Cumulative product of (1 + net return); starts at 1.0."""

    @property
    def total_return(self) -> float:
        return float(self.equity.iloc[-1] - 1.0)

    @property
    def total_turnover(self) -> float:
        return float(self.turnover.sum())

    @property
    def num_trades(self) -> int:
        return int((self.turnover > TRADE_EPSILON).sum())


def run_backtest(
    data: pd.DataFrame,
    strategy: Strategy,
    costs: CostModel | None = None,
) -> BacktestResult:
    """Run ``strategy`` over ``data`` and return per-bar results.

    ``data`` is validated against the OHLCV schema first. ``costs`` defaults
    to :class:`CostModel`'s non-zero rates.
    """
    cost_model = costs if costs is not None else CostModel()
    df = validate_ohlcv(data)
    if len(df) < 2:
        raise ValueError(f"backtest needs at least 2 bars, got {len(df)}")

    signal = strategy.target_positions(df)
    _check_signal(signal, df.index, strategy)

    positions = signal.astype(float).shift(1).fillna(0.0).rename("position")
    close = df["close"].astype(float)
    asset_returns = (close / close.shift(1) - 1.0).fillna(0.0)
    turnover = positions.diff().abs().fillna(positions.abs()).rename("turnover")
    gross_returns = (positions * asset_returns).rename("gross_return")
    cost_series = (turnover * cost_model.rate_per_unit_turnover).rename("cost")
    net_returns = (gross_returns - cost_series).rename("return")
    equity = (1.0 + net_returns).cumprod().rename("equity")

    return BacktestResult(
        strategy_name=strategy.name,
        positions=positions,
        gross_returns=gross_returns,
        costs=cost_series,
        returns=net_returns,
        turnover=turnover,
        equity=equity,
    )


def _check_signal(signal: pd.Series[float], index: pd.Index, strategy: Strategy) -> None:
    name = strategy.name
    if not signal.index.equals(index):
        raise ValueError(
            f"strategy {name!r} returned positions whose index does not match the data"
        )
    values = signal.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"strategy {name!r} returned NaN or infinite target positions")
    if values.min() < 0.0 or values.max() > 1.0:
        raise ValueError(
            f"strategy {name!r} returned target positions outside [0, 1]; short selling "
            "and leverage are not supported in this research project"
        )
