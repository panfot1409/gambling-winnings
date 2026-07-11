"""Performance metrics computed from the reconciled equity curve.

All metrics consume the engine's close-marked equity series together with
the initial cash committed at the first evaluated open. Nothing here
guesses timing: CAGR uses the engine's recorded evaluation start and end
times, and Sharpe/Sortino annualize only from the validated regular candle
interval or an explicit ``periods_per_year``. A year is 365.25 days
(31,557,600 seconds) — crypto trades continuously.

The first bar's return, ``equity[0] / initial_equity - 1``, represents a
real evaluation period: capital is committed (in cash or filled at the
first open) from the first bar's open through its close. No artificial
initialization return is added.

Invalid equity — empty, non-finite, or non-positive values — is rejected
rather than producing plausible-looking numbers.
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


def periods_per_year_from_interval(interval: pd.Timedelta) -> float:
    """Bars per 365.25-day year for a validated regular candle interval.

    Daily bars give 365.25; hourly bars give 8766.
    """
    seconds = interval.total_seconds()
    if seconds <= 0:
        raise ValueError(f"interval must be positive, got {interval}")
    return SECONDS_PER_YEAR / seconds


def bar_returns(equity: pd.Series[float], initial_equity: float) -> pd.Series[float]:
    """Per-bar simple returns of the equity curve.

    The first return covers the first evaluated bar (initial equity at its
    open to marked equity at its close).
    """
    _validate_equity(equity, initial_equity)
    values = equity.to_numpy(dtype=float)
    previous = np.concatenate(([initial_equity], values[:-1]))
    return pd.Series(values / previous - 1.0, index=equity.index, name="return")


def total_return(equity: pd.Series[float], initial_equity: float) -> float:
    """``terminal equity / initial equity - 1``."""
    _validate_equity(equity, initial_equity)
    return float(equity.iloc[-1]) / initial_equity - 1.0


def cagr(
    initial_equity: float,
    terminal_equity: float,
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
) -> float:
    """Compound annual growth rate over the recorded evaluation window.

    ``start_time``/``end_time`` are the engine's recorded first-open and
    last-close times; elapsed time is converted to years of 365.25 days.
    """
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError(f"initial equity must be positive and finite, got {initial_equity}")
    if not math.isfinite(terminal_equity) or terminal_equity <= 0:
        raise ValueError(f"terminal equity must be positive and finite, got {terminal_equity}")
    elapsed_seconds = (end_time - start_time).total_seconds()
    if elapsed_seconds <= 0:
        raise ValueError(f"end_time must be after start_time, got {start_time} .. {end_time}")
    years = elapsed_seconds / SECONDS_PER_YEAR
    return float((terminal_equity / initial_equity) ** (1.0 / years) - 1.0)


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


def max_drawdown(equity: pd.Series[float], initial_equity: float) -> float:
    """Deepest peak-to-trough loss on the equity curve, as a fraction <= 0.

    Initial equity counts as the first peak, so losses from the very start
    (including entry costs) register as drawdown. Equity is close-marked,
    so intrabar troughs are not visible.
    """
    _validate_equity(equity, initial_equity)
    path = np.concatenate(([initial_equity], equity.to_numpy(dtype=float)))
    peaks = np.maximum.accumulate(path)
    drawdowns = path / peaks - 1.0
    return float(drawdowns.min())


@dataclass(frozen=True)
class PerformanceSummary:
    """The standard metric set for one backtest run."""

    strategy_name: str
    n_periods: int
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    periods_per_year: float
    initial_equity: float
    terminal_equity: float
    total_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    total_traded_notional: float
    turnover: float
    num_trades: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize(
    result: BacktestResult,
    *,
    periods_per_year: float | None = None,
    risk_free_rate: float = 0.0,
) -> PerformanceSummary:
    """Compute the standard metric set from a reconciled backtest result.

    ``periods_per_year`` defaults to the validated regular candle interval
    recorded by the engine (``result.bar_interval``).
    """
    if periods_per_year is None:
        periods_per_year = periods_per_year_from_interval(result.bar_interval)
    _require_periods_per_year(periods_per_year)
    returns = bar_returns(result.equity, result.initial_cash)
    return PerformanceSummary(
        strategy_name=result.strategy_name,
        n_periods=len(result.equity),
        start_time=result.start_time,
        end_time=result.end_time,
        periods_per_year=periods_per_year,
        initial_equity=result.initial_cash,
        terminal_equity=result.terminal_equity,
        total_return=total_return(result.equity, result.initial_cash),
        cagr=cagr(result.initial_cash, result.terminal_equity, result.start_time, result.end_time),
        sharpe=sharpe_ratio(returns, periods_per_year, risk_free_rate=risk_free_rate),
        sortino=sortino_ratio(returns, periods_per_year, target_return=risk_free_rate),
        max_drawdown=max_drawdown(result.equity, result.initial_cash),
        total_traded_notional=result.total_traded_notional,
        turnover=result.turnover,
        num_trades=result.num_trades,
    )


def _require_returns(returns: pd.Series[float]) -> None:
    if len(returns) == 0:
        raise ValueError("returns series is empty")


def _require_periods_per_year(periods_per_year: float) -> None:
    if periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be positive, got {periods_per_year}")


def _validate_equity(equity: pd.Series[float], initial_equity: float) -> None:
    if len(equity) == 0:
        raise ValueError("equity series is empty")
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError(f"initial equity must be positive and finite, got {initial_equity}")
    values = equity.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("equity contains non-finite values")
    if (values <= 0).any():
        raise ValueError(
            "equity contains non-positive values; refusing to compute metrics on an "
            "invalid equity curve"
        )
