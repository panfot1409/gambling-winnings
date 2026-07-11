"""Regression tests that guard against look-ahead bias.

These pin the core discipline of the project:

1. a strategy's signal at bar ``t`` cannot depend on bars after ``t``;
2. the engine executes at the next open — a signal derived from a bar's
   close can never fill at that close, capture that bar's move, or capture
   the overnight gap into the execution open;
3. evaluation splits never mix future rows into the past.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd
import pytest

from eth_research.backtest import CostModel, run_backtest
from eth_research.splits import chronological_split
from eth_research.strategies import BuyAndHold, MovingAverageCrossover, Strategy

STRATEGIES = [BuyAndHold(), MovingAverageCrossover(fast_window=10, slow_window=30)]
CUT_POINTS = (40, 150, 399)
ZERO_COST = CostModel(fee_rate=0.0, slippage_rate=0.0)

BarsFactory = Callable[[Sequence[tuple[float, float]]], pd.DataFrame]


class PerfectForesight(Strategy):
    """Cheat probe: signals 1 exactly on bars whose own close beats their open.

    That information exists only at the bar's close, so a correct engine can
    act on it no earlier than the next open.
    """

    @property
    def name(self) -> str:
        return "perfect_foresight"

    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        close = data["close"].astype(float)
        open_ = data["open"].astype(float)
        return (close > open_).astype(float)


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda strategy: strategy.name)
def test_signals_are_prefix_invariant(strategy: Strategy, synthetic_daily: pd.DataFrame) -> None:
    """Signals computed on truncated history equal signals on full history."""
    full = strategy.target_positions(synthetic_daily)
    for cut in CUT_POINTS:
        prefix = strategy.target_positions(synthetic_daily.iloc[:cut])
        pd.testing.assert_series_equal(prefix, full.iloc[:cut], check_exact=True)


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda strategy: strategy.name)
def test_future_perturbation_cannot_change_past_signals(
    strategy: Strategy, synthetic_daily: pd.DataFrame
) -> None:
    """Rewriting bars after the cut must leave signals up to the cut untouched."""
    cut = 200
    perturbed = synthetic_daily.copy()
    perturbed.iloc[cut:, :4] *= 1.5  # scale open/high/low/close; keeps OHLC valid

    base = strategy.target_positions(synthetic_daily)
    after = strategy.target_positions(perturbed)
    pd.testing.assert_series_equal(after.iloc[:cut], base.iloc[:cut], check_exact=True)

    if isinstance(strategy, MovingAverageCrossover):
        # Sanity check that the perturbation was strong enough to matter at all.
        assert not after.iloc[cut:].equals(base.iloc[cut:])


def test_engine_prefix_invariance(synthetic_daily: pd.DataFrame) -> None:
    """Truncating later bars leaves earlier fills and equity bit-identical."""
    cut = 200
    strategy = MovingAverageCrossover(fast_window=10, slow_window=30)
    full = run_backtest(synthetic_daily, strategy)
    truncated = run_backtest(synthetic_daily.iloc[:cut], strategy)

    cutoff_time = synthetic_daily.index[cut]
    full_prefix_fills = tuple(f for f in full.fills if f.timestamp < cutoff_time)
    assert truncated.fills == full_prefix_fills
    pd.testing.assert_series_equal(truncated.equity, full.equity.iloc[:cut], check_exact=True)
    pd.testing.assert_series_equal(truncated.cash, full.cash.iloc[:cut], check_exact=True)


def test_future_price_mutation_cannot_change_past_fills(synthetic_daily: pd.DataFrame) -> None:
    """Rewriting future bars must not change earlier fills or earlier equity."""
    cut = 200
    strategy = MovingAverageCrossover(fast_window=10, slow_window=30)
    perturbed = synthetic_daily.copy()
    perturbed.iloc[cut:, :4] *= 1.5

    base = run_backtest(synthetic_daily, strategy)
    mutated = run_backtest(perturbed, strategy)

    cutoff_time = synthetic_daily.index[cut]
    base_prefix = tuple(f for f in base.fills if f.timestamp < cutoff_time)
    mutated_prefix = tuple(f for f in mutated.fills if f.timestamp < cutoff_time)
    assert mutated_prefix == base_prefix
    pd.testing.assert_series_equal(
        mutated.equity.iloc[:cut], base.equity.iloc[:cut], check_exact=True
    )


def test_same_bar_knowledge_is_worthless_through_the_engine(
    frame_from_bars: BarsFactory,
) -> None:
    """Every bar rallies +50% intrabar, then gaps back down overnight.

    Perfect same-bar foresight would compound +50% per bar. The engine fills
    at the next open, so the run captures exactly one intrabar rally:
    buy at open[1]=100 (12 ETH at initial 1200), equity 12*150 = 1800 at
    every close thereafter -> +50% total, not (1.5^4 - 1).
    """
    bars = [(100.0, 150.0)] * 4
    frame = frame_from_bars(bars)
    result = run_backtest(frame, PerfectForesight(), ZERO_COST, initial_cash=1200.0)

    assert result.num_trades == 1
    fill = result.fills[0]
    assert fill.timestamp == frame.index[1]
    assert fill.reference_price == pytest.approx(100.0)
    assert result.equity.tolist() == pytest.approx([1200.0, 1800.0, 1800.0, 1800.0])
    cheating_return = 1.5**4 - 1.0
    assert result.total_return == pytest.approx(0.5)
    assert result.total_return < cheating_return


def test_signal_from_close_never_fills_at_that_close(frame_from_bars: BarsFactory) -> None:
    """The fill's reference price is the NEXT bar's open, not the signal close."""
    frame = frame_from_bars([(100.0, 300.0), (310.0, 310.0)])
    result = run_backtest(frame, PerfectForesight(), ZERO_COST, initial_cash=1000.0)

    assert result.num_trades == 1
    fill = result.fills[0]
    assert fill.timestamp == frame.index[1]
    assert fill.reference_price == pytest.approx(310.0)  # not close[0] == 300
    # The +200% intrabar move of bar 0 is not captured.
    assert result.total_return == pytest.approx(0.0)


def test_data_driven_strategies_cannot_trade_the_first_open(
    synthetic_daily: pd.DataFrame,
) -> None:
    """No information exists before the first open; only ex-ante entries may fill."""
    result = run_backtest(synthetic_daily, MovingAverageCrossover(fast_window=10, slow_window=30))
    assert all(fill.timestamp > synthetic_daily.index[0] for fill in result.fills)
    assert float(result.quantity.iloc[0]) == 0.0


def test_sma_warmup_is_flat_through_the_engine(synthetic_daily: pd.DataFrame) -> None:
    """Warm-up bars (undefined slow SMA) plus the execution lag stay in cash."""
    result = run_backtest(synthetic_daily, MovingAverageCrossover(fast_window=5, slow_window=10))
    assert (result.quantity.iloc[:10] == 0.0).all()
    assert all(fill.timestamp >= synthetic_daily.index[10] for fill in result.fills)


def test_split_boundaries_are_strictly_ordered(synthetic_daily: pd.DataFrame) -> None:
    """Train strictly precedes validation, which strictly precedes test."""
    splits = chronological_split(synthetic_daily)
    assert splits.train.index.max() < splits.validation.index.min()
    assert splits.validation.index.max() < splits.test.index.min()
