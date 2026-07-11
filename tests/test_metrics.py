"""Tests for equity-curve metrics, checked against hand-computed values."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from eth_research.backtest import CostModel, run_backtest
from eth_research.metrics import (
    bar_returns,
    cagr,
    max_drawdown,
    periods_per_year_from_interval,
    sharpe_ratio,
    sortino_ratio,
    summarize,
    total_return,
)
from eth_research.strategies import BuyAndHold, MovingAverageCrossover

START = pd.Timestamp("2024-01-01", tz="UTC")


def series(values: list[float]) -> pd.Series[float]:
    return pd.Series(values, dtype=float)


def test_bar_returns_hand_computed() -> None:
    returns = bar_returns(series([1100.0, 990.0]), initial_equity=1000.0)
    assert returns.tolist() == pytest.approx([0.10, -0.10])


def test_first_bar_return_is_a_real_period() -> None:
    # Entry costs on the first bar show up as a real first-bar loss.
    returns = bar_returns(series([980.0, 980.0]), initial_equity=1000.0)
    assert returns.tolist() == pytest.approx([-0.02, 0.0])


def test_total_return_from_equity() -> None:
    assert total_return(series([1100.0, 990.0]), initial_equity=1000.0) == pytest.approx(-0.01)


def test_cagr_over_exactly_one_year_equals_total_return() -> None:
    # 8766 hours = 365.25 days = exactly one year under the 365.25-day convention.
    end = START + pd.Timedelta(hours=8766)
    assert cagr(1000.0, 2000.0, START, end) == pytest.approx(1.0)


def test_cagr_of_doubling_over_two_years() -> None:
    end = START + 2 * pd.Timedelta(hours=8766)
    assert cagr(1000.0, 2000.0, START, end) == pytest.approx(math.sqrt(2.0) - 1.0)


def test_cagr_uses_recorded_times_not_bar_counts() -> None:
    # Same equity ratio, half the elapsed time -> much higher CAGR.
    one_year = cagr(1000.0, 2000.0, START, START + pd.Timedelta(hours=8766))
    half_year = cagr(1000.0, 2000.0, START, START + pd.Timedelta(hours=4383))
    assert half_year == pytest.approx(3.0)  # (2)^2 - 1
    assert half_year > one_year


def test_cagr_rejects_bad_windows_and_equity() -> None:
    with pytest.raises(ValueError, match="after start"):
        cagr(1000.0, 1100.0, START, START)
    with pytest.raises(ValueError, match="terminal equity"):
        cagr(1000.0, 0.0, START, START + pd.Timedelta("1D"))
    with pytest.raises(ValueError, match="initial equity"):
        cagr(0.0, 1000.0, START, START + pd.Timedelta("1D"))


def test_sharpe_known_value() -> None:
    # mean 0.02, sample std 0.01 -> 2.0 per bar, annualized by sqrt(252).
    value = sharpe_ratio(series([0.01, 0.02, 0.03]), periods_per_year=252)
    assert value == pytest.approx(2.0 * math.sqrt(252))


def test_sharpe_subtracts_risk_free_rate() -> None:
    value = sharpe_ratio(series([0.01, 0.02, 0.03]), periods_per_year=252, risk_free_rate=0.02)
    assert value == pytest.approx(0.0)


def test_sharpe_nan_when_volatility_is_zero() -> None:
    assert math.isnan(sharpe_ratio(series([0.01] * 10), periods_per_year=365))


def test_sharpe_nan_for_a_single_bar() -> None:
    assert math.isnan(sharpe_ratio(series([0.01]), periods_per_year=365))


def test_sortino_known_value() -> None:
    # mean 0.005; downside RMS over all 4 bars = sqrt(0.000125).
    value = sortino_ratio(series([0.02, -0.01, 0.03, -0.02]), periods_per_year=1)
    assert value == pytest.approx(0.005 / math.sqrt(0.000125))


def test_sortino_nan_without_downside() -> None:
    assert math.isnan(sortino_ratio(series([0.01, 0.02]), periods_per_year=365))


def test_max_drawdown_known_path() -> None:
    # peak 1200 -> trough 495.
    value = max_drawdown(series([1200.0, 900.0, 990.0, 495.0]), initial_equity=1000.0)
    assert value == pytest.approx(495.0 / 1200.0 - 1.0)


def test_max_drawdown_counts_losses_from_initial_equity() -> None:
    value = max_drawdown(series([900.0, 945.0]), initial_equity=1000.0)
    assert value == pytest.approx(-0.1)


def test_max_drawdown_zero_when_equity_never_falls() -> None:
    assert max_drawdown(series([1100.0, 1200.0]), initial_equity=1000.0) == 0.0


def test_periods_per_year_from_interval() -> None:
    assert periods_per_year_from_interval(pd.Timedelta("1D")) == pytest.approx(365.25)
    assert periods_per_year_from_interval(pd.Timedelta("1h")) == pytest.approx(8766.0)
    with pytest.raises(ValueError, match="positive"):
        periods_per_year_from_interval(pd.Timedelta(0))


def test_non_positive_periods_per_year_rejected() -> None:
    with pytest.raises(ValueError, match="periods_per_year"):
        sharpe_ratio(series([0.01, 0.02]), periods_per_year=0)


def test_invalid_equity_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        total_return(series([]), initial_equity=1000.0)
    with pytest.raises(ValueError, match="non-positive"):
        total_return(series([1000.0, 0.0]), initial_equity=1000.0)
    with pytest.raises(ValueError, match="non-positive"):
        max_drawdown(series([1000.0, -5.0]), initial_equity=1000.0)
    with pytest.raises(ValueError, match="non-finite"):
        total_return(series([1000.0, float("nan")]), initial_equity=1000.0)
    with pytest.raises(ValueError, match="initial equity"):
        bar_returns(series([1000.0]), initial_equity=0.0)


def test_summarize_wires_all_components(synthetic_daily: pd.DataFrame) -> None:
    result = run_backtest(synthetic_daily, MovingAverageCrossover(fast_window=10, slow_window=30))
    summary = summarize(result)

    returns = bar_returns(result.equity, result.initial_cash)
    assert summary.strategy_name == "sma_10_30"
    assert summary.n_periods == 400
    assert summary.start_time == synthetic_daily.index[0]
    assert summary.end_time == synthetic_daily.index[-1] + pd.Timedelta("1D")
    assert summary.periods_per_year == pytest.approx(365.25)
    assert summary.initial_equity == result.initial_cash
    assert summary.terminal_equity == pytest.approx(result.terminal_equity)
    assert summary.total_return == pytest.approx(result.total_return)
    assert summary.cagr == pytest.approx(
        cagr(result.initial_cash, result.terminal_equity, result.start_time, result.end_time)
    )
    assert summary.sharpe == pytest.approx(sharpe_ratio(returns, summary.periods_per_year))
    assert summary.sortino == pytest.approx(sortino_ratio(returns, summary.periods_per_year))
    assert summary.max_drawdown == pytest.approx(max_drawdown(result.equity, result.initial_cash))
    assert summary.total_traded_notional == pytest.approx(result.total_traded_notional)
    assert summary.turnover == pytest.approx(result.turnover)
    assert summary.num_trades == result.num_trades


def test_summarize_accepts_explicit_periods_per_year(synthetic_daily: pd.DataFrame) -> None:
    result = run_backtest(synthetic_daily, MovingAverageCrossover(fast_window=10, slow_window=30))
    summary = summarize(result, periods_per_year=100.0)
    assert summary.periods_per_year == 100.0
    returns = bar_returns(result.equity, result.initial_cash)
    assert summary.sharpe == pytest.approx(sharpe_ratio(returns, 100.0))


def test_summarize_constant_prices_has_undefined_sharpe(
    frame_from_bars: object,
) -> None:
    build = frame_from_bars
    assert callable(build)
    frame = build([(100.0, 100.0)] * 5)
    result = run_backtest(frame, BuyAndHold(), CostModel(fee_rate=0.0, slippage_rate=0.0))
    summary = summarize(result)
    assert summary.total_return == pytest.approx(0.0)
    assert summary.cagr == pytest.approx(0.0)
    assert math.isnan(summary.sharpe)
    assert math.isnan(summary.sortino)
    assert summary.max_drawdown == 0.0


def test_summary_as_dict_round_trips(synthetic_daily: pd.DataFrame) -> None:
    result = run_backtest(synthetic_daily, MovingAverageCrossover(fast_window=10, slow_window=30))
    summary = summarize(result).as_dict()
    assert summary["strategy_name"] == "sma_10_30"
    assert summary["n_periods"] == 400
