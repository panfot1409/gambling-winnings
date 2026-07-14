"""Metrics + reconciliation: every reported number re-derives from primitives."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from eth_research.fractional.cost_model import (
    CAUSAL_PROXY_BASE,
    CAUSAL_PROXY_STRESSED,
    COMPATIBILITY_V1,
    CostScenario,
)
from eth_research.fractional.engine import run_fractional_backtest
from eth_research.fractional.metrics import compute_fractional_metrics
from eth_research.fractional.reconciliation import ReconciliationError, reconcile_result
from eth_research.fractional.strategies import STRATEGIES_BY_NAME, build_strategies

PERIODS_PER_YEAR = 365.25
INITIAL_CASH = 10_000.0


def _frame(n: int = 160) -> pd.DataFrame:
    index = pd.date_range("2019-01-01", periods=n, freq="D", tz="UTC")
    t = np.arange(n, dtype="float64")
    close = 140.0 + 55.0 * np.sin(t / 15.0) + 0.1 * t
    open_ = np.empty(n, dtype="float64")
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) * 1.02
    low = np.minimum(open_, close) * 0.98
    volume = 900.0 + 6.0 * t
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


SCENARIOS = [COMPATIBILITY_V1, CAUSAL_PROXY_BASE, CAUSAL_PROXY_STRESSED]


class TestReconciliation:
    @pytest.mark.parametrize("scenario", SCENARIOS)
    @pytest.mark.parametrize("strategy", build_strategies(), ids=lambda s: s.name)
    def test_every_run_reconciles(self, strategy: object, scenario: CostScenario) -> None:
        result = run_fractional_backtest(
            _frame(),
            strategy,  # type: ignore[arg-type]
            scenario,
            initial_cash=INITIAL_CASH,
        )
        report = reconcile_result(result, scenario)
        assert report.bars_checked == len(result.bars)
        assert report.max_equity_residual <= 1e-6
        assert "cost_decomposition" in report.checks

    def test_tampered_cash_series_is_caught(self) -> None:
        result = run_fractional_backtest(
            _frame(),
            STRATEGIES_BY_NAME["buy_and_hold"],
            COMPATIBILITY_V1,
            initial_cash=INITIAL_CASH,
        )
        tampered = dataclasses.replace(result, cash=result.cash + 1.0)
        with pytest.raises(ReconciliationError, match="cash/quantity series"):
            reconcile_result(tampered, COMPATIBILITY_V1)

    def test_tampered_equity_series_is_caught(self) -> None:
        result = run_fractional_backtest(
            _frame(),
            STRATEGIES_BY_NAME["buy_and_hold"],
            COMPATIBILITY_V1,
            initial_cash=INITIAL_CASH,
        )
        bumped = result.equity.copy()
        bumped.iloc[-1] = bumped.iloc[-1] + 5.0
        tampered = dataclasses.replace(result, equity=bumped)
        with pytest.raises(ReconciliationError, match="equity"):
            reconcile_result(tampered, COMPATIBILITY_V1)


class TestMetrics:
    def test_cash_strategy_is_flat(self) -> None:
        result = run_fractional_backtest(
            _frame(), STRATEGIES_BY_NAME["cash"], COMPATIBILITY_V1, initial_cash=INITIAL_CASH
        )
        m = compute_fractional_metrics(result, periods_per_year=PERIODS_PER_YEAR)
        assert m.total_return == pytest.approx(0.0, abs=1e-12)
        assert m.num_fills == 0
        assert m.turnover == 0.0
        assert m.total_fees == 0.0
        assert m.average_achieved_exposure == pytest.approx(0.0, abs=1e-12)
        assert m.time_in_market == 0.0

    def test_buy_and_hold_is_fully_invested(self) -> None:
        result = run_fractional_backtest(
            _frame(),
            STRATEGIES_BY_NAME["buy_and_hold"],
            COMPATIBILITY_V1,
            initial_cash=INITIAL_CASH,
        )
        m = compute_fractional_metrics(result, periods_per_year=PERIODS_PER_YEAR)
        assert m.num_fills == 1
        assert m.total_return == pytest.approx(result.total_return, rel=1e-12)
        assert m.average_achieved_exposure > 0.99  # essentially always in ETH
        assert m.time_in_market == 1.0

    def test_metrics_reconcile_with_the_report(self) -> None:
        result = run_fractional_backtest(
            _frame(),
            STRATEGIES_BY_NAME["donchian_55_20"],
            CAUSAL_PROXY_BASE,
            initial_cash=INITIAL_CASH,
        )
        m = compute_fractional_metrics(result, periods_per_year=PERIODS_PER_YEAR)
        report = reconcile_result(result, CAUSAL_PROXY_BASE)
        assert m.total_fees == pytest.approx(report.total_fees, abs=1e-9)
        assert m.total_traded_notional == pytest.approx(report.total_traded_notional, abs=1e-6)
