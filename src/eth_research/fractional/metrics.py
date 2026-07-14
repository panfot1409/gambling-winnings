"""Reconciled performance metrics for a fractional backtest (Milestone 3B, Phase 11).

Performance statistics consume the engine's close-marked equity curve through the
same shared primitives as the binary engine (:mod:`eth_research.metrics`), so a
compatibility run yields identical performance numbers. Fractional-specific
figures — turnover, fees, achieved exposure, partial-fill counts — are derived
from the primitive bar and fill records. Realized volatility is reported here and
is deliberately distinct from any *requested* volatility target: requesting a
target never implies it was achieved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from eth_research.fractional.accounting import DEFAULT_TOLERANCES
from eth_research.fractional.engine import FractionalBacktestResult
from eth_research.metrics import bar_returns, max_drawdown, sharpe_ratio, sortino_ratio


@dataclass(frozen=True)
class FractionalMetrics:
    """Reconciled scalar summary of one fractional backtest."""

    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    num_fills: int
    num_partial_fills: int
    total_traded_notional: float
    turnover: float
    total_fees: float
    average_achieved_exposure: float
    time_in_market: float
    terminal_equity: float
    terminal_liquidation_equity: float


def compute_fractional_metrics(
    result: FractionalBacktestResult,
    *,
    periods_per_year: float,
    risk_free_rate: float = 0.0,
) -> FractionalMetrics:
    """Compute the reconciled metric summary from a fractional result.

    Performance ratios reuse the shared metric primitives on the close-marked
    equity curve; turnover, fees, and exposure come from the fill and bar
    records. ``annualized_return`` compounds the total return over the bar count
    (``periods_per_year`` bars per year).
    """
    if periods_per_year <= 0.0:
        raise ValueError(f"periods_per_year must be positive, got {periods_per_year!r}")
    equity = result.equity
    n = len(equity)
    returns = bar_returns(equity, result.initial_cash)
    terminal = float(equity.iloc[-1])
    total = terminal / result.initial_cash - 1.0
    annualized_return = (terminal / result.initial_cash) ** (periods_per_year / n) - 1.0
    if n >= 2:
        annualized_volatility = float(returns.std(ddof=1)) * math.sqrt(periods_per_year)
    else:
        annualized_volatility = math.nan

    traded_notional = sum(f.fill_notional for f in result.fills)
    fees = sum(f.fee for f in result.fills)
    exposures = [b.achieved_exposure for b in result.bars]
    average_exposure = sum(exposures) / len(exposures)
    in_market = sum(1 for e in exposures if e > DEFAULT_TOLERANCES.weight_tolerance) / len(
        exposures
    )
    partial_fills = sum(1 for b in result.bars if b.partial)

    return FractionalMetrics(
        total_return=total,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sharpe_ratio=sharpe_ratio(returns, periods_per_year, risk_free_rate),
        sortino_ratio=sortino_ratio(returns, periods_per_year, risk_free_rate),
        max_drawdown=max_drawdown(equity, result.initial_cash),
        num_fills=result.num_fills,
        num_partial_fills=partial_fills,
        total_traded_notional=traded_notional,
        turnover=traded_notional / result.initial_cash,
        total_fees=fees,
        average_achieved_exposure=average_exposure,
        time_in_market=in_market,
        terminal_equity=terminal,
        terminal_liquidation_equity=result.terminal_liquidation_equity,
    )
