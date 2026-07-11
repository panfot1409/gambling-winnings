"""Tests for the portfolio backtest engine, against hand-calculated ledgers.

The expected numbers in these tests are worked out by hand from the
documented execution rules (fill at open with directional slippage, fee on
notional, equity marked at close) — not by re-running the engine's own
formulas.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd
import pytest

from eth_research.backtest import CostModel, run_backtest
from eth_research.strategies import BuyAndHold, MovingAverageCrossover, Strategy

ZERO_COST = CostModel(fee_rate=0.0, slippage_rate=0.0)

BarsFactory = Callable[[Sequence[tuple[float, float]]], pd.DataFrame]


class FixedSignal(Strategy):
    """Test double that emits a predetermined binary signal series."""

    def __init__(self, values: Sequence[float]) -> None:
        self._values = list(values)

    @property
    def name(self) -> str:
        return "fixed_signal"

    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        return pd.Series(self._values, index=data.index, dtype=float)


class MisalignedSignal(Strategy):
    """Test double that returns positions on the wrong index."""

    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        return pd.Series(0.0, index=pd.RangeIndex(len(data)), dtype=float)


def test_hand_calculated_ledger_with_costs(frame_from_bars: BarsFactory) -> None:
    """Full cash/ETH reconciliation with 1% fee and 2% slippage, by hand.

    initial cash 1030.20, bars (open, close): (95, 100), (100, 110), (120, 115),
    signals [1, 0, 0] (decided at each close, executed at the next open),
    data-driven start (flat).

    bar 0: no prior signal, initial_target 0    -> no fill, cash 1030.20, equity 1030.20
    bar 1: signal[0]=1 -> buy at open 100: fill 100*1.02 = 102
           quantity = 1030.20 / (102 * 1.01) = 1030.20 / 103.02 = 10 exactly
           gross = 10 * 102 = 1020, fee = 10.20, cash = 1030.20 - 1020 - 10.20 = 0
           equity at close 110: 10 * 110 = 1100
    bar 2: signal[1]=0 -> sell at open 120: fill 120*0.98 = 117.6
           gross = 10 * 117.6 = 1176, fee = 11.76, cash = 0 + 1176 - 11.76 = 1164.24
           equity = 1164.24
    """
    frame = frame_from_bars([(95.0, 100.0), (100.0, 110.0), (120.0, 115.0)])
    costs = CostModel(fee_rate=0.01, slippage_rate=0.02)
    result = run_backtest(frame, FixedSignal([1.0, 0.0, 0.0]), costs, initial_cash=1030.20)

    assert result.num_trades == 2
    buy, sell = result.fills

    assert buy.side == "buy"
    assert buy.timestamp == frame.index[1]
    assert buy.reference_price == pytest.approx(100.0)
    assert buy.fill_price == pytest.approx(102.0)
    assert buy.quantity == pytest.approx(10.0)
    assert buy.gross_notional == pytest.approx(1020.0)
    assert buy.fee == pytest.approx(10.20)
    assert buy.cash_after == pytest.approx(0.0, abs=1e-9)
    assert buy.quantity_after == pytest.approx(10.0)

    assert sell.side == "sell"
    assert sell.timestamp == frame.index[2]
    assert sell.reference_price == pytest.approx(120.0)
    assert sell.fill_price == pytest.approx(117.6)
    assert sell.quantity == pytest.approx(10.0)
    assert sell.gross_notional == pytest.approx(1176.0)
    assert sell.fee == pytest.approx(11.76)
    assert sell.cash_after == pytest.approx(1164.24)
    assert sell.quantity_after == 0.0

    np.testing.assert_allclose(result.cash, [1030.20, 0.0, 1164.24], atol=1e-9)
    np.testing.assert_allclose(result.quantity, [0.0, 10.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(result.equity, [1030.20, 1100.0, 1164.24])
    assert result.terminal_equity == pytest.approx(1164.24)
    assert result.total_return == pytest.approx(1164.24 / 1030.20 - 1.0)
    assert result.total_traded_notional == pytest.approx(1020.0 + 1176.0)
    assert result.turnover == pytest.approx(2196.0 / 1030.20)
    # Flat at the end: liquidation value equals cash equals terminal equity.
    assert result.terminal_liquidation_equity == pytest.approx(1164.24)
    assert result.final_quantity == 0.0


def test_hand_calculated_ledger_frictionless(frame_from_bars: BarsFactory) -> None:
    """initial 1000, bars (100,110), (125,150), (150,150), signals [1,0,0]:
    signal[0]=1 buys 8 ETH at open[1]=125 (equity 8*150 = 1200 at close[1]);
    signal[1]=0 sells at open[2]=150 -> cash 1200."""
    frame = frame_from_bars([(100.0, 110.0), (125.0, 150.0), (150.0, 150.0)])
    result = run_backtest(frame, FixedSignal([1.0, 0.0, 0.0]), ZERO_COST, initial_cash=1000.0)

    assert result.num_trades == 2
    assert result.fills[0].fill_price == pytest.approx(125.0)
    assert result.fills[0].quantity == pytest.approx(8.0)
    assert result.fills[0].fee == 0.0
    assert result.fills[1].fill_price == pytest.approx(150.0)
    np.testing.assert_allclose(result.equity, [1000.0, 1200.0, 1200.0])
    assert result.total_return == pytest.approx(0.2)


def test_directional_slippage_is_exact(frame_from_bars: BarsFactory) -> None:
    """Buys fill above the open, sells below it, by exactly the slippage rate."""
    frame = frame_from_bars([(100.0, 100.0), (100.0, 100.0), (100.0, 100.0)])
    costs = CostModel(fee_rate=0.0, slippage_rate=0.1)
    result = run_backtest(frame, FixedSignal([1.0, 0.0, 0.0]), costs, initial_cash=1000.0)

    buy, sell = result.fills
    assert buy.reference_price == pytest.approx(100.0)
    assert buy.fill_price == pytest.approx(110.0)  # 100 * (1 + 0.1)
    assert sell.reference_price == pytest.approx(100.0)
    assert sell.fill_price == pytest.approx(90.0)  # 100 * (1 - 0.1)
    # Round trip at a flat price loses exactly the slippage both ways.
    assert result.terminal_equity == pytest.approx(1000.0 * 90.0 / 110.0)


def test_overnight_gap_cannot_be_captured(frame_from_bars: BarsFactory) -> None:
    """A signal from close[t] fills at open[t+1]; the gap accrues to cash.

    Price doubles overnight (close 100 -> open 200). The buy decided at
    close[0] pays the gapped-up open, so total return is just the entry
    costs, never +100%.
    """
    frame = frame_from_bars([(100.0, 100.0), (200.0, 200.0)])
    costs = CostModel(fee_rate=0.001, slippage_rate=0.0005)
    result = run_backtest(frame, FixedSignal([1.0, 1.0]), costs, initial_cash=1000.0)

    assert result.num_trades == 1
    fill = result.fills[0]
    assert fill.timestamp == frame.index[1]
    assert fill.reference_price == pytest.approx(200.0)  # the gapped open, not close[0]
    assert fill.fill_price == pytest.approx(200.0 * 1.0005)
    # equity = quantity * 200 where quantity = 1000 / (200 * 1.0005 * 1.001)
    expected_equity = 1000.0 * 200.0 / (200.0 * 1.0005 * 1.001)
    assert result.terminal_equity == pytest.approx(expected_equity)
    assert result.total_return < 0  # only costs, despite the price doubling
    assert result.total_return > -0.01


def test_buy_and_hold_enters_at_first_available_open(frame_from_bars: BarsFactory) -> None:
    """The ex-ante benchmark fills at open[0] without observing any data."""
    frame = frame_from_bars([(100.0, 110.0), (105.0, 120.0)])
    result = run_backtest(frame, BuyAndHold(), ZERO_COST, initial_cash=1000.0)

    assert result.num_trades == 1
    fill = result.fills[0]
    assert fill.timestamp == frame.index[0]
    assert fill.reference_price == pytest.approx(100.0)
    assert fill.quantity == pytest.approx(10.0)
    np.testing.assert_allclose(result.equity, [1100.0, 1200.0])


def test_buy_and_hold_entry_pays_costs_at_first_open(frame_from_bars: BarsFactory) -> None:
    frame = frame_from_bars([(100.0, 100.0), (100.0, 100.0)])
    costs = CostModel(fee_rate=0.01, slippage_rate=0.02)
    result = run_backtest(frame, BuyAndHold(), costs, initial_cash=1030.20)

    fill = result.fills[0]
    assert fill.timestamp == frame.index[0]
    assert fill.fill_price == pytest.approx(102.0)
    assert fill.quantity == pytest.approx(10.0)
    assert fill.fee == pytest.approx(10.20)
    # Marked at close 100 without liquidation: 10 * 100 = 1000.
    assert result.terminal_equity == pytest.approx(1000.0)


def test_data_driven_strategy_starts_in_cash(frame_from_bars: BarsFactory) -> None:
    """initial_target 0: no fill can happen at the first open."""
    frame = frame_from_bars([(100.0, 110.0), (110.0, 120.0), (120.0, 130.0)])
    result = run_backtest(frame, MovingAverageCrossover(fast_window=1, slow_window=2), ZERO_COST)
    assert all(fill.timestamp > frame.index[0] for fill in result.fills)
    assert float(result.quantity.iloc[0]) == 0.0


def test_terminal_position_marked_to_market_not_liquidated(frame_from_bars: BarsFactory) -> None:
    frame = frame_from_bars([(100.0, 100.0), (100.0, 200.0)])
    costs = CostModel(fee_rate=0.01, slippage_rate=0.02)
    result = run_backtest(frame, FixedSignal([1.0, 1.0]), costs, initial_cash=1030.20)

    # One buy, never sold: quantity = 1030.20 / (102 * 1.01) = 10 ETH.
    assert result.num_trades == 1
    assert result.final_quantity == pytest.approx(10.0)
    assert result.terminal_equity == pytest.approx(10.0 * 200.0, rel=1e-9)
    # Hypothetical liquidation at the last close: 10 * 200 * 0.98 * 0.99.
    assert result.terminal_liquidation_equity == pytest.approx(10.0 * 200.0 * 0.98 * 0.99)
    assert result.terminal_liquidation_equity < result.terminal_equity


def test_no_fill_when_target_is_unchanged(frame_from_bars: BarsFactory) -> None:
    frame = frame_from_bars([(100.0, 101.0)] * 5)
    result = run_backtest(frame, BuyAndHold(), ZERO_COST)
    assert result.num_trades == 1  # enters once, never rebalances


def test_accounting_invariants_hold_on_synthetic_data(synthetic_daily: pd.DataFrame) -> None:
    result = run_backtest(synthetic_daily, MovingAverageCrossover(fast_window=10, slow_window=30))

    initial = result.initial_cash
    # Cash never materially negative; quantity never negative.
    assert float(result.cash.min()) >= -1e-9 * initial
    assert (result.cash.to_numpy() >= -1e-9 * initial).all()
    assert (result.quantity.to_numpy() >= 0.0).all()
    for fill in result.fills:
        assert fill.cash_after >= -1e-9 * initial
        assert fill.quantity_after >= 0.0
        assert fill.quantity > 0.0

    # equity == cash + quantity * close, bar by bar.
    recomputed = result.cash + result.quantity * synthetic_daily["close"].astype(float)
    pd.testing.assert_series_equal(result.equity, recomputed.rename("equity"), check_exact=True)
    assert (result.equity.to_numpy() > 0.0).all()

    # No hidden leverage: every buy is funded by the cash held before it.
    cash_before = initial
    for fill in result.fills:
        if fill.side == "buy":
            assert fill.gross_notional + fill.fee <= cash_before + 1e-9 * initial
        cash_before = fill.cash_after

    # Fills alternate buy/sell starting with a buy; count matches ledger.
    sides = [fill.side for fill in result.fills]
    assert sides == (["buy", "sell"] * len(sides))[: len(sides)]
    assert result.num_trades == len(result.fills)
    assert result.total_traded_notional == pytest.approx(
        sum(fill.gross_notional for fill in result.fills)
    )
    assert result.turnover == pytest.approx(result.total_traded_notional / initial)


def test_result_timing_fields(frame_from_bars: BarsFactory) -> None:
    frame = frame_from_bars([(100.0, 101.0)] * 4)
    result = run_backtest(frame, BuyAndHold(), ZERO_COST)
    assert result.bar_interval == pd.Timedelta("1D")
    assert result.start_time == frame.index[0]
    assert result.end_time == frame.index[-1] + pd.Timedelta("1D")
    assert result.equity.index.equals(frame.index)
    assert result.cash.index.equals(frame.index)
    assert result.quantity.index.equals(frame.index)
    assert result.context_bars == 0


def test_rejects_fractional_targets(frame_from_bars: BarsFactory) -> None:
    frame = frame_from_bars([(100.0, 101.0)] * 4)
    with pytest.raises(ValueError, match="other than 0 or 1"):
        run_backtest(frame, FixedSignal([0.0, 0.5, 0.0, 0.0]), ZERO_COST)


def test_rejects_short_targets(frame_from_bars: BarsFactory) -> None:
    frame = frame_from_bars([(100.0, 101.0)] * 4)
    with pytest.raises(ValueError, match="other than 0 or 1"):
        run_backtest(frame, FixedSignal([0.0, -1.0, 0.0, 0.0]), ZERO_COST)


def test_rejects_nan_targets(frame_from_bars: BarsFactory) -> None:
    frame = frame_from_bars([(100.0, 101.0)] * 4)
    with pytest.raises(ValueError, match="NaN"):
        run_backtest(frame, FixedSignal([0.0, float("nan"), 0.0, 0.0]), ZERO_COST)


def test_rejects_misaligned_positions(frame_from_bars: BarsFactory) -> None:
    frame = frame_from_bars([(100.0, 101.0)] * 4)
    with pytest.raises(ValueError, match="does not match"):
        run_backtest(frame, MisalignedSignal(), ZERO_COST)


def test_requires_at_least_two_bars(frame_from_bars: BarsFactory) -> None:
    with pytest.raises(ValueError, match="at least 2 bars"):
        run_backtest(frame_from_bars([(100.0, 101.0)]), BuyAndHold(), ZERO_COST)


@pytest.mark.parametrize("bad_cash", [0.0, -100.0, float("inf"), float("nan")])
def test_rejects_invalid_initial_cash(frame_from_bars: BarsFactory, bad_cash: float) -> None:
    frame = frame_from_bars([(100.0, 101.0)] * 4)
    with pytest.raises(ValueError, match="initial_cash"):
        run_backtest(frame, BuyAndHold(), ZERO_COST, initial_cash=bad_cash)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"fee_rate": -0.1}, "fee_rate"),
        ({"fee_rate": 1.0}, "fee_rate"),
        ({"slippage_rate": -0.1}, "slippage_rate"),
        ({"slippage_rate": 1.0}, "slippage_rate"),
    ],
)
def test_cost_model_rejects_bad_rates(kwargs: dict[str, float], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        CostModel(**kwargs)


def test_default_cost_model_is_not_frictionless(frame_from_bars: BarsFactory) -> None:
    frame = frame_from_bars([(100.0, 101.0)] * 4)
    with_costs = run_backtest(frame, BuyAndHold())
    frictionless = run_backtest(frame, BuyAndHold(), ZERO_COST)
    assert with_costs.fills[0].fee > 0.0
    assert with_costs.terminal_equity < frictionless.terminal_equity
