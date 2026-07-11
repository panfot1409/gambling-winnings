"""Tests for boundary-safe warm-up context: useful carry-in, zero leakage."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd
import pytest

from eth_research.backtest import CostModel, run_backtest
from eth_research.data.schema import SchemaError
from eth_research.splits import chronological_split
from eth_research.strategies import BuyAndHold, MovingAverageCrossover, Strategy

ZERO_COST = CostModel(fee_rate=0.0, slippage_rate=0.0)

ClosesFactory = Callable[[Sequence[float]], pd.DataFrame]


class AlwaysFlat(Strategy):
    """Test double that never wants a position."""

    @property
    def name(self) -> str:
        return "always_flat"

    def target_positions(self, data: pd.DataFrame) -> pd.Series[float]:
        return pd.Series(0.0, index=data.index, dtype=float)


def test_context_enables_entry_at_first_evaluation_open(
    frame_from_closes: ClosesFactory,
) -> None:
    """A signal from the final context close executes at the first
    evaluation open, with costs charged."""
    frame = frame_from_closes([1.0, 2.0, 3.0, 4.0])
    context, evaluation = frame.iloc[:2], frame.iloc[2:]
    strategy = MovingAverageCrossover(fast_window=1, slow_window=2)
    costs = CostModel(fee_rate=0.01, slippage_rate=0.02)

    with_context = run_backtest(evaluation, strategy, costs, context=context)
    assert with_context.context_bars == 2
    assert with_context.num_trades == 1
    fill = with_context.fills[0]
    assert fill.timestamp == evaluation.index[0]
    assert fill.side == "buy"
    assert fill.reference_price == pytest.approx(2.0)  # first evaluation open
    assert fill.fill_price == pytest.approx(2.0 * 1.02)
    assert fill.fee > 0.0

    # Without context the SMA is still warming up inside the evaluation
    # window and never trades: the carry-in is genuinely useful.
    without_context = run_backtest(evaluation, strategy, costs)
    assert without_context.num_trades == 0


def test_context_rows_contribute_no_pnl(frame_from_closes: ClosesFactory) -> None:
    """A strongly rising context must not move a flat strategy's equity."""
    frame = frame_from_closes([1.0, 10.0, 100.0, 100.0, 100.0])
    context, evaluation = frame.iloc[:3], frame.iloc[3:]

    result = run_backtest(
        evaluation, AlwaysFlat(), ZERO_COST, initial_cash=5_000.0, context=context
    )
    assert result.num_trades == 0
    assert result.equity.tolist() == [5_000.0, 5_000.0]
    assert result.equity.index.equals(evaluation.index)
    assert result.start_time == evaluation.index[0]


def test_context_changes_signals_only_not_accounting(
    frame_from_closes: ClosesFactory,
) -> None:
    """For a data-independent strategy, context must not change anything."""
    frame = frame_from_closes([1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
    context, evaluation = frame.iloc[:3], frame.iloc[3:]

    with_context = run_backtest(evaluation, BuyAndHold(), ZERO_COST, context=context)
    without_context = run_backtest(evaluation, BuyAndHold(), ZERO_COST)

    assert with_context.fills == without_context.fills
    pd.testing.assert_series_equal(with_context.equity, without_context.equity)
    assert with_context.context_bars == 3
    assert without_context.context_bars == 0


def test_no_future_leakage_with_context(synthetic_daily: pd.DataFrame) -> None:
    """With context fixed, rewriting future evaluation bars cannot change
    earlier fills or earlier equity."""
    context = synthetic_daily.iloc[:40]
    evaluation = synthetic_daily.iloc[40:140]
    cut = 50  # position within the evaluation window
    strategy = MovingAverageCrossover(fast_window=10, slow_window=30)

    base = run_backtest(evaluation, strategy, context=context)
    perturbed_eval = evaluation.copy()
    perturbed_eval.iloc[cut:, :4] *= 1.5
    mutated = run_backtest(perturbed_eval, strategy, context=context)

    cutoff_time = evaluation.index[cut]
    base_prefix = tuple(f for f in base.fills if f.timestamp < cutoff_time)
    mutated_prefix = tuple(f for f in mutated.fills if f.timestamp < cutoff_time)
    assert mutated_prefix == base_prefix
    pd.testing.assert_series_equal(
        mutated.equity.iloc[:cut], base.equity.iloc[:cut], check_exact=True
    )


def test_gapped_context_rejected(frame_from_closes: ClosesFactory) -> None:
    frame = frame_from_closes([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    context = frame.iloc[:2]
    evaluation = frame.iloc[3:]  # skips row 2 -> seam gap
    with pytest.raises(SchemaError, match="irregular candle intervals"):
        run_backtest(evaluation, BuyAndHold(), ZERO_COST, context=context)


def test_overlapping_context_rejected(frame_from_closes: ClosesFactory) -> None:
    frame = frame_from_closes([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    context = frame.iloc[:4]
    evaluation = frame.iloc[3:]  # row 3 in both -> duplicate timestamp
    with pytest.raises(SchemaError, match="duplicated timestamp"):
        run_backtest(evaluation, BuyAndHold(), ZERO_COST, context=context)


def test_context_after_evaluation_rejected(frame_from_closes: ClosesFactory) -> None:
    frame = frame_from_closes([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    context = frame.iloc[4:]
    evaluation = frame.iloc[:4]
    with pytest.raises(SchemaError, match="not sorted"):
        run_backtest(evaluation, BuyAndHold(), ZERO_COST, context=context)


def test_empty_context_is_equivalent_to_none(frame_from_closes: ClosesFactory) -> None:
    frame = frame_from_closes([1.0, 2.0, 3.0, 4.0])
    empty = frame.iloc[0:0]
    with_empty = run_backtest(frame, BuyAndHold(), ZERO_COST, context=empty)
    without = run_backtest(frame, BuyAndHold(), ZERO_COST)
    assert with_empty.fills == without.fills
    assert with_empty.context_bars == 0


def test_split_context_helpers(synthetic_daily: pd.DataFrame) -> None:
    splits = chronological_split(synthetic_daily)  # 240 / 80 / 80

    validation_context = splits.validation_context(30)
    pd.testing.assert_frame_equal(validation_context, splits.train.iloc[-30:])

    # Test context may reach back through validation into train.
    test_context = splits.test_context(100)
    expected = pd.concat([splits.train, splits.validation]).iloc[-100:]
    pd.testing.assert_frame_equal(test_context, expected)

    with pytest.raises(ValueError, match="bars must be >= 1"):
        splits.validation_context(0)
    with pytest.raises(ValueError, match="only 240"):
        splits.validation_context(241)


def test_split_context_feeds_engine(synthetic_daily: pd.DataFrame) -> None:
    """validation evaluated with trailing train rows as warm-up context."""
    splits = chronological_split(synthetic_daily)
    strategy = MovingAverageCrossover(fast_window=10, slow_window=30)
    result = run_backtest(splits.validation, strategy, context=splits.validation_context(30))
    assert result.context_bars == 30
    assert result.start_time == splits.validation.index[0]
    assert len(result.equity) == len(splits.validation)


def test_boundaries_reporting(synthetic_daily: pd.DataFrame) -> None:
    splits = chronological_split(synthetic_daily)
    boundaries = splits.boundaries()
    index = synthetic_daily.index
    assert boundaries["train"] == (index[0], index[239])
    assert boundaries["validation"] == (index[240], index[319])
    assert boundaries["test"] == (index[320], index[399])
