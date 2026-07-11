"""Tests for the benchmark and SMA crossover strategies."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd
import pytest

from eth_research.strategies import BuyAndHold, MovingAverageCrossover, Strategy

STRATEGIES = [BuyAndHold(), MovingAverageCrossover(fast_window=5, slow_window=10)]


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda strategy: strategy.name)
def test_positions_contract(strategy: Strategy, synthetic_daily: pd.DataFrame) -> None:
    positions = strategy.target_positions(synthetic_daily)
    assert positions.index.equals(synthetic_daily.index)
    assert not positions.isna().any()
    # Milestone 1 restricts targets to exactly binary long/cash.
    assert np.isin(positions.to_numpy(dtype=float), (0.0, 1.0)).all()
    assert strategy.initial_target in (0, 1)


def test_buy_and_hold_is_always_fully_invested(synthetic_daily: pd.DataFrame) -> None:
    strategy = BuyAndHold()
    positions = strategy.target_positions(synthetic_daily)
    assert (positions == 1.0).all()
    assert strategy.name == "buy_and_hold"


def test_buy_and_hold_is_ex_ante() -> None:
    """Buy-and-hold needs no observed data: it targets 1 from the first open."""
    assert BuyAndHold.initial_target == 1


def test_data_driven_strategies_start_in_cash() -> None:
    assert MovingAverageCrossover(fast_window=5, slow_window=10).initial_target == 0


def test_sma_long_in_rising_market(
    frame_from_closes: Callable[[Sequence[float]], pd.DataFrame],
) -> None:
    frame = frame_from_closes([1.0, 2.0, 3.0, 4.0, 5.0])
    positions = MovingAverageCrossover(fast_window=1, slow_window=2).target_positions(frame)
    # Bar 0 is warm-up; afterwards close > mean(close, prev close) iff rising.
    assert positions.tolist() == [0.0, 1.0, 1.0, 1.0, 1.0]


def test_sma_flat_in_falling_market(
    frame_from_closes: Callable[[Sequence[float]], pd.DataFrame],
) -> None:
    frame = frame_from_closes([5.0, 4.0, 3.0, 2.0, 1.0])
    positions = MovingAverageCrossover(fast_window=1, slow_window=2).target_positions(frame)
    assert positions.tolist() == [0.0, 0.0, 0.0, 0.0, 0.0]


def test_sma_crossover_flips_with_the_trend(
    frame_from_closes: Callable[[Sequence[float]], pd.DataFrame],
) -> None:
    closes = [1.0, 1.0, 1.0, 1.0, 10.0, 11.0, 12.0, 1.0, 1.0, 1.0]
    frame = frame_from_closes(closes)
    positions = MovingAverageCrossover(fast_window=1, slow_window=3).target_positions(frame)
    assert positions.tolist() == [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]


def test_sma_stays_flat_during_warmup(synthetic_daily: pd.DataFrame) -> None:
    positions = MovingAverageCrossover(fast_window=5, slow_window=10).target_positions(
        synthetic_daily
    )
    assert (positions.iloc[:9] == 0.0).all()


def test_sma_name_encodes_windows() -> None:
    assert MovingAverageCrossover(fast_window=5, slow_window=20).name == "sma_5_20"


@pytest.mark.parametrize(
    ("fast_window", "slow_window", "match"),
    [
        (0, 5, "fast_window"),
        (5, 5, "slow_window"),
        (10, 5, "slow_window"),
    ],
)
def test_invalid_windows_rejected(fast_window: int, slow_window: int, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        MovingAverageCrossover(fast_window=fast_window, slow_window=slow_window)
