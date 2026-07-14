"""Milestone 3A adversarial regression tests.

Targeted attacks on the evaluator's bug guards: the per-cell reconciliation
that every reported scalar agrees with the engine's accounting must actually
*reject* a corrupted result, not wave it through.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from eth_research.backtest import BacktestResult, run_backtest
from eth_research.costs import cost_scenario
from eth_research.development_evaluation import DevelopmentEvaluationError, _reconcile
from eth_research.strategies import BuyAndHold


def _frame(n: int = 12) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [10.0 + i for i in range(n)],
            "high": [11.0 + i for i in range(n)],
            "low": [9.0 + i for i in range(n)],
            "close": [10.5 + i for i in range(n)],
            "volume": [1.0] * n,
        },
        index=idx,
    )


def _result(frame: pd.DataFrame, initial_cash: float = 10_000.0) -> BacktestResult:
    return run_backtest(
        frame, BuyAndHold(), cost_scenario("base").cost_model(), initial_cash=initial_cash
    )


class TestReconciliationGuard:
    def test_clean_result_reconciles(self) -> None:
        frame = _frame()
        _reconcile(_result(frame), frame, 10_000.0)  # must not raise

    def test_corrupted_equity_is_rejected(self) -> None:
        frame = _frame()
        result = _result(frame)
        tampered = dataclasses.replace(result, equity=result.equity + 1.0)
        with pytest.raises(DevelopmentEvaluationError, match="equity != cash"):
            _reconcile(tampered, frame, 10_000.0)

    def test_wrong_initial_cash_is_rejected(self) -> None:
        frame = _frame()
        result = _result(frame)
        with pytest.raises(DevelopmentEvaluationError, match="initial cash disagrees"):
            _reconcile(result, frame, 9_999.0)

    def test_equity_over_wrong_bars_is_rejected(self) -> None:
        frame = _frame()
        result = _result(frame)
        shifted = result.equity.copy()
        shifted.index = shifted.index + pd.Timedelta(days=1)
        tampered = dataclasses.replace(result, equity=shifted)
        with pytest.raises(DevelopmentEvaluationError, match="does not cover exactly the OOS bars"):
            _reconcile(tampered, frame, 10_000.0)

    def test_corrupted_quantity_breaks_reconciliation(self) -> None:
        frame = _frame()
        result = _result(frame)
        tampered = dataclasses.replace(result, quantity=result.quantity + 0.5)
        with pytest.raises(DevelopmentEvaluationError, match="equity != cash"):
            _reconcile(tampered, frame, 10_000.0)
