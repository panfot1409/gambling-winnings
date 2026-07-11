"""Tests for the vectorized backtest engine."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd
import pytest

from eth_research.backtest import CostModel, run_backtest
from eth_research.strategies import BuyAndHold, Strategy

ZERO_COST = CostModel(fee_rate=0.0, slippage_rate=0.0)

FrameFactory = Callable[[Sequence[float]], pd.DataFrame]


class FixedSignal(Strategy):
    """Test double that emits a predetermined signal series."""

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
        return pd.Series(0.5, index=pd.RangeIndex(len(data)), dtype=float)


def test_frictionless_buy_and_hold_matches_price_path(frame_from_closes: FrameFactory) -> None:
    closes = [100.0, 110.0, 99.0, 108.9]
    frame = frame_from_closes(closes)
    result = run_backtest(frame, BuyAndHold(), ZERO_COST)

    expected_equity = frame["close"] / closes[0]
    np.testing.assert_allclose(result.equity, expected_equity)
    assert result.total_return == pytest.approx(closes[-1] / closes[0] - 1.0)
    assert result.positions.tolist() == [0.0, 1.0, 1.0, 1.0]
    assert result.num_trades == 1
    assert result.total_turnover == pytest.approx(1.0)


def test_buy_and_hold_pays_the_entry_cost_once(frame_from_closes: FrameFactory) -> None:
    frame = frame_from_closes([100.0, 110.0, 99.0, 108.9])
    result = run_backtest(frame, BuyAndHold(), CostModel(fee_rate=0.001, slippage_rate=0.0005))

    # Entry happens on bar 1: its +10% return is reduced by the 15 bps cost.
    expected_final = (1.0 + 0.10 - 0.0015) * (1.0 - 0.10) * (1.0 + 0.10)
    assert float(result.equity.iloc[-1]) == pytest.approx(expected_final)
    assert result.num_trades == 1


def test_engine_matches_bar_by_bar_reference(frame_from_closes: FrameFactory) -> None:
    closes = [100.0, 110.0, 99.0, 108.9, 119.79]
    signal = [1.0, 1.0, 0.0, 1.0, 1.0]
    cost_rate = 0.002 + 0.001
    frame = frame_from_closes(closes)
    result = run_backtest(
        frame, FixedSignal(signal), CostModel(fee_rate=0.002, slippage_rate=0.001)
    )

    # Independent scalar-loop oracle for the vectorized engine.
    held = 0.0
    equity = 1.0
    previous_close = closes[0]
    expected_positions: list[float] = []
    expected_returns: list[float] = []
    expected_equity: list[float] = []
    for t, close in enumerate(closes):
        target = signal[t - 1] if t > 0 else 0.0
        bar_return = close / previous_close - 1.0
        net = target * bar_return - abs(target - held) * cost_rate
        equity *= 1.0 + net
        expected_positions.append(target)
        expected_returns.append(net)
        expected_equity.append(equity)
        held = target
        previous_close = close

    np.testing.assert_allclose(result.positions, expected_positions)
    np.testing.assert_allclose(result.returns, expected_returns)
    np.testing.assert_allclose(result.equity, expected_equity)


def test_turnover_and_trade_count(frame_from_closes: FrameFactory) -> None:
    frame = frame_from_closes([100.0, 101.0, 102.0, 103.0, 104.0])
    result = run_backtest(frame, FixedSignal([1.0, 1.0, 0.5, 0.5, 0.0]), ZERO_COST)

    np.testing.assert_allclose(result.turnover, [0.0, 1.0, 0.0, 0.5, 0.0])
    assert result.total_turnover == pytest.approx(1.5)
    assert result.num_trades == 2


def test_default_cost_model_is_not_frictionless(frame_from_closes: FrameFactory) -> None:
    frame = frame_from_closes([100.0, 110.0, 99.0, 108.9])
    with_default_costs = run_backtest(frame, BuyAndHold())
    frictionless = run_backtest(frame, BuyAndHold(), ZERO_COST)
    assert with_default_costs.total_return < frictionless.total_return


def test_equity_starts_at_one(frame_from_closes: FrameFactory) -> None:
    frame = frame_from_closes([100.0, 110.0, 99.0, 108.9])
    result = run_backtest(frame, BuyAndHold(), ZERO_COST)
    assert float(result.equity.iloc[0]) == pytest.approx(1.0)


def test_leveraged_positions_rejected(frame_from_closes: FrameFactory) -> None:
    frame = frame_from_closes([100.0, 110.0, 99.0, 108.9])
    with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
        run_backtest(frame, FixedSignal([0.0, 1.5, 0.0, 0.0]), ZERO_COST)


def test_short_positions_rejected(frame_from_closes: FrameFactory) -> None:
    frame = frame_from_closes([100.0, 110.0, 99.0, 108.9])
    with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
        run_backtest(frame, FixedSignal([0.0, -0.5, 0.0, 0.0]), ZERO_COST)


def test_nan_positions_rejected(frame_from_closes: FrameFactory) -> None:
    frame = frame_from_closes([100.0, 110.0, 99.0, 108.9])
    with pytest.raises(ValueError, match="NaN"):
        run_backtest(frame, FixedSignal([0.0, float("nan"), 0.0, 0.0]), ZERO_COST)


def test_misaligned_positions_rejected(frame_from_closes: FrameFactory) -> None:
    frame = frame_from_closes([100.0, 110.0, 99.0, 108.9])
    with pytest.raises(ValueError, match="does not match"):
        run_backtest(frame, MisalignedSignal(), ZERO_COST)


def test_requires_at_least_two_bars(frame_from_closes: FrameFactory) -> None:
    with pytest.raises(ValueError, match="at least 2 bars"):
        run_backtest(frame_from_closes([100.0]), BuyAndHold(), ZERO_COST)


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
