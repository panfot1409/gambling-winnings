"""Bar-by-bar portfolio backtest engine with explicit fills at the open.

Causal event order for each evaluated bar ``t`` (timestamps are candle
**open times**):

1. At ``open[t]`` the engine executes the target decided strictly from data
   through ``close[t-1]`` — for the very first evaluated bar, the
   strategy's ex-ante ``initial_target``, which uses no observed data.
2. Buys fill at ``open[t] * (1 + slippage_rate)``; sells fill at
   ``open[t] * (1 - slippage_rate)``. The fee is
   ``fill_price * quantity * fee_rate`` (absolute fill notional times the
   fee rate) and is paid from cash.
3. Portfolio equity is marked at ``close[t]`` as
   ``cash + quantity * close[t]``.
4. Only after ``close[t]`` does the strategy's target for ``open[t + 1]``
   become available.

A signal derived from ``close[t]`` therefore never fills at ``close[t]``
and never captures the ``close[t] -> open[t + 1]`` gap: that gap accrues to
whatever was already held overnight.

Accounting is exact long/cash bookkeeping — cash balance and ETH quantity,
no borrowing, no shorting, no fractional target weights (targets are
binary ``{0, 1}`` in Milestone 1). Buys convert the entire cash balance
into ETH net of fee; sells convert the entire ETH position back to cash.
Every executed trade is recorded in an immutable fill ledger.

Terminal policy: the final position is **marked to market at the last
close and never force-liquidated**; the hypothetical value of selling at
the last close (with sell slippage and fee) is reported separately as
``terminal_liquidation_equity``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from eth_research.data.schema import frame_interval, validate_ohlcv
from eth_research.strategies.base import Strategy

CASH_TOLERANCE_FRACTION: float = 1e-9
"""Cash may dip below zero by at most this fraction of initial cash (float rounding)."""


class AccountingError(RuntimeError):
    """An internal accounting invariant was violated (engine bug guard)."""


@dataclass(frozen=True)
class CostModel:
    """Trading costs: proportional fee on fill notional, directional slippage.

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


@dataclass(frozen=True)
class Fill:
    """One executed trade, recorded at the moment of execution."""

    timestamp: pd.Timestamp
    """Open time of the bar at which the fill executed."""
    side: Literal["buy", "sell"]
    reference_price: float
    """Unslipped open price of the execution bar."""
    fill_price: float
    """``reference_price * (1 + slippage_rate)`` for buys, ``* (1 - slippage_rate)`` for sells."""
    quantity: float
    """ETH quantity traded; always positive."""
    gross_notional: float
    """``fill_price * quantity``."""
    fee: float
    """``gross_notional * fee_rate``, paid from cash."""
    cash_after: float
    quantity_after: float


@dataclass(frozen=True)
class BacktestResult:
    """Reconciled per-bar account state plus the immutable fill ledger."""

    strategy_name: str
    initial_cash: float
    costs: CostModel
    fills: tuple[Fill, ...]
    cash: pd.Series[float]
    """Cash balance during each bar, after any fill at that bar's open."""
    quantity: pd.Series[float]
    """ETH quantity held during each bar, after any fill at that bar's open."""
    equity: pd.Series[float]
    """``cash + quantity * close``, marked at each bar close."""
    bar_interval: pd.Timedelta
    start_time: pd.Timestamp
    """Open time of the first evaluated bar (capital committed here)."""
    end_time: pd.Timestamp
    """Close time of the last evaluated bar: last open time + interval."""
    context_bars: int
    """Warm-up rows preceding the evaluation (signal context only, no P&L)."""
    terminal_liquidation_equity: float
    """Hypothetical: cash + quantity * last close * (1 - slippage) * (1 - fee)."""

    @property
    def terminal_equity(self) -> float:
        """Mark-to-market equity at the final close (positions not liquidated)."""
        return float(self.equity.iloc[-1])

    @property
    def total_return(self) -> float:
        """``terminal_equity / initial_cash - 1``."""
        return self.terminal_equity / self.initial_cash - 1.0

    @property
    def num_trades(self) -> int:
        """Number of actually executed fills."""
        return len(self.fills)

    @property
    def total_traded_notional(self) -> float:
        """Sum of ``fill_price * quantity`` over all fills."""
        return float(sum(fill.gross_notional for fill in self.fills))

    @property
    def turnover(self) -> float:
        """``total_traded_notional / initial_cash``.

        Total traded notional (at actual fill prices) divided by the
        capital committed at the start of the evaluation.
        """
        return self.total_traded_notional / self.initial_cash

    @property
    def final_quantity(self) -> float:
        """ETH quantity still held after the final bar."""
        return float(self.quantity.iloc[-1])


def run_backtest(
    data: pd.DataFrame,
    strategy: Strategy,
    costs: CostModel | None = None,
    *,
    initial_cash: float = 10_000.0,
) -> BacktestResult:
    """Run ``strategy`` over ``data`` with exact long/cash accounting.

    ``data`` is validated against the strict OHLCV schema (regular
    interval, UTC, sorted). ``costs`` defaults to :class:`CostModel`'s
    non-zero rates. ``initial_cash`` is the cash committed at the open of
    the first evaluated bar.
    """
    cost_model = costs if costs is not None else CostModel()
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError(f"initial_cash must be positive and finite, got {initial_cash}")
    df = validate_ohlcv(data)
    if len(df) < 2:
        raise ValueError(f"backtest needs at least 2 bars, got {len(df)}")
    if strategy.initial_target not in (0, 1):
        raise ValueError(
            f"strategy {strategy.name!r} has initial_target "
            f"{strategy.initial_target}; it must be 0 or 1"
        )

    signal = strategy.target_positions(df)
    _check_signal(signal, df.index, strategy)

    return _simulate(df, strategy, signal, cost_model, initial_cash, context_bars=0)


def _simulate(
    df: pd.DataFrame,
    strategy: Strategy,
    signal: pd.Series[float],
    cost_model: CostModel,
    initial_cash: float,
    *,
    context_bars: int,
) -> BacktestResult:
    opens = df["open"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    targets = signal.to_numpy(dtype=float)
    index = df.index
    n = len(df)

    cash = float(initial_cash)
    quantity = 0.0
    fills: list[Fill] = []
    cash_by_bar: list[float] = []
    quantity_by_bar: list[float] = []
    equity_by_bar: list[float] = []

    for t in range(n):
        # Target decided from information through close[t-1] only; the very
        # first open uses the strategy's ex-ante initial_target.
        target = float(strategy.initial_target) if t == 0 else float(targets[t - 1])
        open_price = float(opens[t])

        if target == 1.0 and quantity == 0.0:
            fill_price = open_price * (1.0 + cost_model.slippage_rate)
            traded = cash / (fill_price * (1.0 + cost_model.fee_rate))
            gross = traded * fill_price
            fee = gross * cost_model.fee_rate
            cash = cash - gross - fee
            quantity = traded
            fills.append(
                Fill(
                    timestamp=index[t],
                    side="buy",
                    reference_price=open_price,
                    fill_price=fill_price,
                    quantity=traded,
                    gross_notional=gross,
                    fee=fee,
                    cash_after=cash,
                    quantity_after=quantity,
                )
            )
        elif target == 0.0 and quantity > 0.0:
            fill_price = open_price * (1.0 - cost_model.slippage_rate)
            traded = quantity
            gross = traded * fill_price
            fee = gross * cost_model.fee_rate
            cash = cash + gross - fee
            quantity = 0.0
            fills.append(
                Fill(
                    timestamp=index[t],
                    side="sell",
                    reference_price=open_price,
                    fill_price=fill_price,
                    quantity=traded,
                    gross_notional=gross,
                    fee=fee,
                    cash_after=cash,
                    quantity_after=quantity,
                )
            )

        if cash < -CASH_TOLERANCE_FRACTION * initial_cash or quantity < 0.0:
            raise AccountingError(
                f"accounting invariant violated at {index[t]}: cash={cash}, quantity={quantity}"
            )

        cash_by_bar.append(cash)
        quantity_by_bar.append(quantity)
        equity_by_bar.append(cash + quantity * float(closes[t]))

    final_close = float(closes[-1])
    if quantity > 0.0:
        liquidation = cash + quantity * final_close * (1.0 - cost_model.slippage_rate) * (
            1.0 - cost_model.fee_rate
        )
    else:
        liquidation = cash

    interval = frame_interval(df)
    return BacktestResult(
        strategy_name=strategy.name,
        initial_cash=float(initial_cash),
        costs=cost_model,
        fills=tuple(fills),
        cash=pd.Series(cash_by_bar, index=index, name="cash"),
        quantity=pd.Series(quantity_by_bar, index=index, name="quantity"),
        equity=pd.Series(equity_by_bar, index=index, name="equity"),
        bar_interval=interval,
        start_time=index[0],
        end_time=index[-1] + interval,
        context_bars=context_bars,
        terminal_liquidation_equity=float(liquidation),
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
    if not np.isin(values, (0.0, 1.0)).all():
        raise ValueError(
            f"strategy {name!r} returned targets other than 0 or 1; Milestone 1 supports "
            "long/cash only — fractional weights, short selling, and leverage are not implemented"
        )
