"""Regression tests that guard against look-ahead bias.

These pin the core discipline of the project:

1. a strategy's signal at bar ``t`` cannot depend on bars after ``t``;
2. the engine defers execution by one bar, so even a strategy that "knows"
   the current bar's return as it closes cannot capture it;
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

FrameFactory = Callable[[Sequence[float]], pd.DataFrame]


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


def test_engine_defers_execution_by_one_bar(frame_from_closes: FrameFactory) -> None:
    """Same-bar knowledge must be worthless once the execution lag applies."""

    class PerfectForesight(Strategy):
        """Signals 1 exactly on bars whose own return is positive.

        That information exists only at the bar's close, so a correct engine
        can only act on it one bar later.
        """

        def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
            close = data["close"].astype(float)
            bar_return = close / close.shift(1) - 1.0
            return (bar_return > 0).astype(float)

    closes = [100.0, 150.0, 100.0, 150.0, 100.0, 150.0, 100.0]
    frame = frame_from_closes(closes)
    result = run_backtest(frame, PerfectForesight(), CostModel(fee_rate=0.0, slippage_rate=0.0))

    # Applying the signal on the same bar (cheating) would capture all three
    # +50% bars; the lagged engine instead always enters right before a -33%
    # bar and must lose money.
    cheating_return = 1.5**3 - 1.0
    assert result.total_return < 0 < cheating_return
    assert float(result.equity.iloc[-1]) == pytest.approx((2.0 / 3.0) ** 3)


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda strategy: strategy.name)
def test_first_bar_is_never_traded(strategy: Strategy, synthetic_daily: pd.DataFrame) -> None:
    """No information exists before the first bar, so it must be flat."""
    result = run_backtest(synthetic_daily, strategy)
    assert float(result.positions.iloc[0]) == 0.0


def test_sma_warmup_is_flat_through_the_engine(synthetic_daily: pd.DataFrame) -> None:
    """Warm-up bars (undefined slow SMA) plus the execution lag stay flat."""
    result = run_backtest(synthetic_daily, MovingAverageCrossover(fast_window=5, slow_window=10))
    assert (result.positions.iloc[:10] == 0.0).all()


def test_split_boundaries_are_strictly_ordered(synthetic_daily: pd.DataFrame) -> None:
    """Train strictly precedes validation, which strictly precedes test."""
    splits = chronological_split(synthetic_daily)
    assert splits.train.index.max() < splits.validation.index.min()
    assert splits.validation.index.max() < splits.test.index.min()
