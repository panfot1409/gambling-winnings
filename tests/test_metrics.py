"""Tests for performance metrics, checked against hand-computed values."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from eth_research.backtest import run_backtest
from eth_research.metrics import (
    cagr,
    infer_periods_per_year,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    summarize,
    total_return,
)
from eth_research.strategies import MovingAverageCrossover


def series(values: list[float]) -> pd.Series[float]:
    return pd.Series(values, dtype=float)


def test_total_return_compounds() -> None:
    assert total_return(series([0.1, -0.1])) == pytest.approx(-0.01)


def test_cagr_equals_total_return_over_exactly_one_year() -> None:
    returns = series([0.01] * 365)
    assert cagr(returns, periods_per_year=365) == pytest.approx(total_return(returns))


def test_cagr_of_doubling_over_two_years() -> None:
    per_bar = 2.0 ** (1.0 / 730.0) - 1.0
    returns = series([per_bar] * 730)
    assert cagr(returns, periods_per_year=365) == pytest.approx(math.sqrt(2.0) - 1.0)


def test_cagr_floors_at_minus_one_when_wiped_out() -> None:
    assert cagr(series([-1.0, 0.0]), periods_per_year=365) == -1.0


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
    # equity: 1.2, 0.9, 0.99, 0.495; peak 1.2 -> trough 0.495.
    value = max_drawdown(series([0.2, -0.25, 0.1, -0.5]))
    assert value == pytest.approx(0.495 / 1.2 - 1.0)


def test_max_drawdown_counts_losses_from_starting_capital() -> None:
    assert max_drawdown(series([-0.1, 0.05])) == pytest.approx(-0.1)


def test_max_drawdown_zero_when_equity_never_falls() -> None:
    assert max_drawdown(series([0.1, 0.2])) == 0.0


def test_infer_periods_per_year_daily() -> None:
    index = pd.date_range("2024-01-01", periods=30, freq="1D", tz="UTC")
    assert infer_periods_per_year(index) == pytest.approx(365.25)


def test_infer_periods_per_year_hourly() -> None:
    index = pd.date_range("2024-01-01", periods=30, freq="1h", tz="UTC")
    assert infer_periods_per_year(index) == pytest.approx(365.25 * 24)


def test_infer_periods_per_year_needs_two_timestamps() -> None:
    index = pd.date_range("2024-01-01", periods=1, freq="1D", tz="UTC")
    with pytest.raises(ValueError, match="at least 2"):
        infer_periods_per_year(index)


def test_empty_returns_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        total_return(series([]))


def test_non_positive_periods_per_year_rejected() -> None:
    with pytest.raises(ValueError, match="periods_per_year"):
        sharpe_ratio(series([0.01, 0.02]), periods_per_year=0)


def test_summarize_wires_all_components(synthetic_daily: pd.DataFrame) -> None:
    result = run_backtest(synthetic_daily, MovingAverageCrossover(fast_window=10, slow_window=30))
    summary = summarize(result)

    assert summary.strategy_name == "sma_10_30"
    assert summary.n_periods == 400
    assert summary.periods_per_year == pytest.approx(365.25)
    assert summary.total_return == pytest.approx(result.total_return)
    assert summary.cagr == pytest.approx(cagr(result.returns, summary.periods_per_year))
    assert summary.sharpe == pytest.approx(sharpe_ratio(result.returns, summary.periods_per_year))
    assert summary.sortino == pytest.approx(sortino_ratio(result.returns, summary.periods_per_year))
    assert summary.max_drawdown == pytest.approx(max_drawdown(result.returns))
    assert summary.total_turnover == pytest.approx(result.total_turnover)
    assert summary.num_trades == result.num_trades


def test_summarize_accepts_explicit_periods_per_year(synthetic_daily: pd.DataFrame) -> None:
    result = run_backtest(synthetic_daily, MovingAverageCrossover(fast_window=10, slow_window=30))
    summary = summarize(result, periods_per_year=100.0)
    assert summary.periods_per_year == 100.0


def test_summary_as_dict_round_trips(synthetic_daily: pd.DataFrame) -> None:
    result = run_backtest(synthetic_daily, MovingAverageCrossover(fast_window=10, slow_window=30))
    summary = summarize(result).as_dict()
    assert summary["strategy_name"] == "sma_10_30"
    assert summary["n_periods"] == 400
