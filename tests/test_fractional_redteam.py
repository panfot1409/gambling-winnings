"""Engine-level look-ahead + robustness red team (Milestone 3B, Phase 13).

Adversarial checks that no current-bar or future value reaches a fill, that the
lagged-liquidity estimate genuinely uses only the past, and that the engine stays
long-only and reconciled under degenerate market data. These run before the
protocol is frozen; any surviving finding is logged in docs/M3B_BUG_LOG.md.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from eth_research.fractional.cost_model import CAUSAL_PROXY_BASE, COMPATIBILITY_V1
from eth_research.fractional.engine import BarRecord, run_fractional_backtest
from eth_research.fractional.reconciliation import reconcile_result
from eth_research.fractional.strategies import STRATEGIES_BY_NAME

INITIAL_CASH = 10_000.0


def _frame(n: int = 180, volume: float | None = None) -> pd.DataFrame:
    index = pd.date_range("2019-03-01", periods=n, freq="D", tz="UTC")
    t = np.arange(n, dtype="float64")
    close = 150.0 + 55.0 * np.sin(t / 16.0) + 0.08 * t
    open_ = np.empty(n, dtype="float64")
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) * 1.015
    low = np.minimum(open_, close) * 0.985
    vol = np.full(n, volume, dtype="float64") if volume is not None else 1_000.0 + 6.0 * t
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=index,
    )


def _fill_signature(bar: BarRecord) -> tuple[object, ...]:
    return (bar.side, bar.executed_quantity, bar.cash_after, bar.quantity_after, bar.fill_price)


class TestLookAhead:
    def test_future_rows_never_change_past_or_current_fills(self) -> None:
        frame = _frame()
        cut = 100
        mutated = frame.copy()
        mutated.iloc[cut + 1 :] = mutated.iloc[cut + 1 :] * 2.5  # strictly future rows
        base = run_fractional_backtest(
            frame,
            STRATEGIES_BY_NAME["donchian_55_20"],
            CAUSAL_PROXY_BASE,
            initial_cash=INITIAL_CASH,
        )
        after = run_fractional_backtest(
            mutated,
            STRATEGIES_BY_NAME["donchian_55_20"],
            CAUSAL_PROXY_BASE,
            initial_cash=INITIAL_CASH,
        )
        for i in range(cut + 1):
            assert _fill_signature(base.bars[i]) == _fill_signature(after.bars[i])
            assert base.bars[i].equity == after.bars[i].equity

    def test_current_and_future_volume_never_reaches_the_fill(self) -> None:
        # Volume from bar k onward is corrupted; the fill and liquidity used at
        # every bar <= k must be untouched (each reads volume only through t-1).
        frame = _frame()
        k = 120
        mutated = frame.copy()
        vol = mutated["volume"].to_numpy().copy()
        vol[k:] *= 50.0
        mutated["volume"] = vol
        base = run_fractional_backtest(
            frame, STRATEGIES_BY_NAME["buy_and_hold"], CAUSAL_PROXY_BASE, initial_cash=INITIAL_CASH
        )
        after = run_fractional_backtest(
            mutated,
            STRATEGIES_BY_NAME["buy_and_hold"],
            CAUSAL_PROXY_BASE,
            initial_cash=INITIAL_CASH,
        )
        for i in range(k + 1):
            assert _fill_signature(base.bars[i]) == _fill_signature(after.bars[i])
            assert base.bars[i].participation_cap == after.bars[i].participation_cap
            assert base.bars[i].lagged_dollar_volume == after.bars[i].lagged_dollar_volume

    def test_current_bar_close_marks_but_never_moves_the_fill(self) -> None:
        # Corrupting only close[k] (down, keeping OHLC valid) must change bar k's
        # mark-to-market equity but not the fill decided at open[k].
        frame = _frame()
        k = 90
        mutated = frame.copy()
        close = mutated["close"].to_numpy().copy()
        close[k] *= 0.6
        mutated["close"] = close
        base = run_fractional_backtest(
            frame, STRATEGIES_BY_NAME["buy_and_hold"], CAUSAL_PROXY_BASE, initial_cash=INITIAL_CASH
        )
        after = run_fractional_backtest(
            mutated,
            STRATEGIES_BY_NAME["buy_and_hold"],
            CAUSAL_PROXY_BASE,
            initial_cash=INITIAL_CASH,
        )
        assert _fill_signature(base.bars[k]) == _fill_signature(after.bars[k])
        assert base.bars[k].equity != after.bars[k].equity  # the mark moved

    def test_past_volume_actually_drives_the_estimate(self) -> None:
        # Negative control: corrupting PAST volume must change a later liquidity
        # estimate, proving the estimator is not inert.
        frame = _frame()
        k = 120
        mutated = frame.copy()
        vol = mutated["volume"].to_numpy().copy()
        vol[:k] *= 100.0  # shift the whole lagged window
        mutated["volume"] = vol
        base = run_fractional_backtest(
            frame, STRATEGIES_BY_NAME["buy_and_hold"], CAUSAL_PROXY_BASE, initial_cash=INITIAL_CASH
        )
        after = run_fractional_backtest(
            mutated,
            STRATEGIES_BY_NAME["buy_and_hold"],
            CAUSAL_PROXY_BASE,
            initial_cash=INITIAL_CASH,
        )
        assert base.bars[k].lagged_dollar_volume != after.bars[k].lagged_dollar_volume


class TestDegenerateData:
    def test_zero_volume_yields_no_fills_under_a_participation_constraint(self) -> None:
        # No liquidity + a participation-constrained scenario -> no fills, no
        # infinite impact, and a clean reconciliation.
        frame = _frame(volume=0.0)
        result = run_fractional_backtest(
            frame, STRATEGIES_BY_NAME["buy_and_hold"], CAUSAL_PROXY_BASE, initial_cash=INITIAL_CASH
        )
        assert result.num_fills == 0
        assert result.terminal_equity == pytest.approx(INITIAL_CASH, abs=1e-9)
        reconcile_result(result, CAUSAL_PROXY_BASE)

    def test_single_volume_outlier_does_not_destabilize(self) -> None:
        frame = _frame()
        vol = frame["volume"].to_numpy().copy()
        vol[80] = 1e15  # one absurd bar
        frame["volume"] = vol
        result = run_fractional_backtest(
            frame,
            STRATEGIES_BY_NAME["donchian_55_20"],
            CAUSAL_PROXY_BASE,
            initial_cash=INITIAL_CASH,
        )
        reconcile_result(result, CAUSAL_PROXY_BASE)  # median is robust; still reconciles

    def test_price_gap_keeps_long_only_and_reconciled(self) -> None:
        frame = _frame()
        close = frame["close"].to_numpy().copy()
        close[100:] *= 0.4  # a 60% overnight crash sustained thereafter
        frame["close"] = close
        frame["low"] = np.minimum(frame["open"].to_numpy(), close) * 0.985
        result = run_fractional_backtest(
            frame, STRATEGIES_BY_NAME["buy_and_hold"], COMPATIBILITY_V1, initial_cash=INITIAL_CASH
        )
        for bar in result.bars:
            assert bar.cash_after >= -1e-6
            assert bar.quantity_after >= -1e-12
        reconcile_result(result, COMPATIBILITY_V1)


class TestMetamorphic:
    def test_higher_fee_never_lowers_total_fees(self) -> None:
        # Isolated cost bump (same cap, same liquidity): total fees paid are
        # non-decreasing in the fee rate. fee = cash*rate/(1+rate) is increasing.
        full = _frame(n=220, volume=1e12)
        context = full.iloc[:40]
        frame = full.iloc[40:]
        base = run_fractional_backtest(
            frame,
            STRATEGIES_BY_NAME["buy_and_hold"],
            CAUSAL_PROXY_BASE,
            initial_cash=INITIAL_CASH,
            context=context,
        )
        higher_fee = dataclasses.replace(
            CAUSAL_PROXY_BASE, fee_rate=CAUSAL_PROXY_BASE.fee_rate + 0.002
        )
        bumped = run_fractional_backtest(
            frame,
            STRATEGIES_BY_NAME["buy_and_hold"],
            higher_fee,
            initial_cash=INITIAL_CASH,
            context=context,
        )
        base_fees = sum(f.fee for f in base.fills)
        bumped_fees = sum(f.fee for f in bumped.fills)
        assert base.num_fills == 1  # invests at bar 0 (context supplies liquidity)
        assert bumped_fees >= base_fees - 1e-12
