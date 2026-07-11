"""Performance metrics for backtest results.

Ratio metrics (Sharpe, Sortino) are annualized with
``sqrt(periods_per_year)``; CAGR compounds over elapsed periods. Crypto
markets trade continuously, so a year is 365.25 days rather than the 252
trading days used for equities.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from eth_research.backtest import BacktestResult

SECONDS_PER_YEAR: float = 365.25 * 24.0 * 3600.0

_VOLATILITY_EPSILON: float = 1e-15
"""Sample deviations below this are numerical noise, not volatility."""


def infer_periods_per_year(index: pd.DatetimeIndex) -> float:
    """Infer bar frequency from the median spacing of ``index``.

    Daily bars give ~365.25; hourly bars give ~8766.
    """
    if len(index) < 2:
        raise ValueError("need at least 2 timestamps to infer the bar frequency")
    deltas = index.to_series().diff().dropna()
    median_seconds = float(deltas.median().total_seconds())
    if median_seconds <= 0:
        raise ValueError("timestamps must be strictly increasing")
    return SECONDS_PER_YEAR / median_seconds


def total_return(returns: pd.Series[float]) -> float:
    """Compound total return of a per-bar simple-return series."""
    _require_returns(returns)
    return float(np.prod(1.0 + returns.to_numpy(dtype=float)) - 1.0)


def cagr(returns: pd.Series[float], periods_per_year: float) -> float:
    """Compound annual growth rate.

    Floors at -100%/year when the capital is wiped out.
    """
    _require_returns(returns)
    _require_periods_per_year(periods_per_year)
    final = float(np.prod(1.0 + returns.to_numpy(dtype=float)))
    if final <= 0.0:
        return -1.0
    years = len(returns) / periods_per_year
    return float(final ** (1.0 / years) - 1.0)


def sharpe_ratio(
    returns: pd.Series[float],
    periods_per_year: float,
    risk_free_rate: float = 0.0,
) -> float:
    """Annualized Sharpe ratio; ``risk_free_rate`` is per bar.

    Returns NaN when volatility is zero (within floating-point noise) or
    undefined (fewer than 2 bars).
    """
    _require_returns(returns)
    _require_periods_per_year(periods_per_year)
    excess = returns - risk_free_rate
    std = float(excess.std(ddof=1))
    if not math.isfinite(std) or std < _VOLATILITY_EPSILON:
        return math.nan
    return float(excess.mean()) / std * math.sqrt(periods_per_year)


def sortino_ratio(
    returns: pd.Series[float],
    periods_per_year: float,
    target_return: float = 0.0,
) -> float:
    """Annualized Sortino ratio; ``target_return`` is per bar.

    The downside deviation is the root mean square of below-target excess
    returns over the full sample. Returns NaN when the sample has no
    downside.
    """
    _require_returns(returns)
    _require_periods_per_year(periods_per_year)
    excess = (returns - target_return).to_numpy(dtype=float)
    downside = np.minimum(excess, 0.0)
    downside_deviation = math.sqrt(float(np.mean(downside**2)))
    if downside_deviation < _VOLATILITY_EPSILON:
        return math.nan
    return float(np.mean(excess)) / downside_deviation * math.sqrt(periods_per_year)


def max_drawdown(returns: pd.Series[float]) -> float:
    """Deepest peak-to-trough equity loss, as a non-positive fraction.

    Starting capital counts as the first peak, so an initial losing streak
    is a drawdown.
    """
    _require_returns(returns)
    equity = (1.0 + returns).cumprod().to_numpy(dtype=float)
    peaks = np.maximum(np.maximum.accumulate(equity), 1.0)
    drawdowns = equity / peaks - 1.0
    return float(drawdowns.min())


@dataclass(frozen=True)
class PerformanceSummary:
    """The standard metric set for one backtest run."""

    strategy_name: str
    n_periods: int
    periods_per_year: float
    total_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    total_turnover: float
    num_trades: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize(
    result: BacktestResult,
    *,
    periods_per_year: float | None = None,
    risk_free_rate: float = 0.0,
) -> PerformanceSummary:
    """Compute the standard metric set for one backtest result.

    When ``periods_per_year`` is omitted it is inferred from the result's
    timestamps.
    """
    returns = result.returns
    if periods_per_year is None:
        index = returns.index
        if not isinstance(index, pd.DatetimeIndex):
            raise TypeError("cannot infer periods_per_year: result index is not a DatetimeIndex")
        periods_per_year = infer_periods_per_year(index)
    return PerformanceSummary(
        strategy_name=result.strategy_name,
        n_periods=len(returns),
        periods_per_year=periods_per_year,
        total_return=total_return(returns),
        cagr=cagr(returns, periods_per_year),
        sharpe=sharpe_ratio(returns, periods_per_year, risk_free_rate=risk_free_rate),
        sortino=sortino_ratio(returns, periods_per_year, target_return=risk_free_rate),
        max_drawdown=max_drawdown(returns),
        total_turnover=result.total_turnover,
        num_trades=result.num_trades,
    )


def _require_returns(returns: pd.Series[float]) -> None:
    if len(returns) == 0:
        raise ValueError("returns series is empty")


def _require_periods_per_year(periods_per_year: float) -> None:
    if periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be positive, got {periods_per_year}")
