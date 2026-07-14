"""Fractional engine: compatibility parity with the binary engine + causality.

Under the ``compatibility_v1`` scenario the three binary-equivalent strategies
must reproduce the binary ``run_backtest`` equity curve to the last bit (the
Phase 12 oracle formalizes this); every fill must be causal (no bar-t close or
future row reaches a fill), and long-only invariants must hold on every bar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.backtest import CostModel, run_backtest
from eth_research.fractional.accounting import DEFAULT_TOLERANCES
from eth_research.fractional.cost_model import (
    CAUSAL_PROXY_BASE,
    COMPATIBILITY_V1,
    CostScenario,
)
from eth_research.fractional.engine import EngineError, run_fractional_backtest
from eth_research.fractional.strategies import STRATEGIES_BY_NAME
from eth_research.strategies.base import Strategy
from eth_research.strategies.buy_and_hold import BuyAndHold
from eth_research.strategies.cash import Cash
from eth_research.strategies.donchian import DonchianChannel

INITIAL_CASH = 10_000.0


def _synthetic_frame(n: int = 200) -> pd.DataFrame:
    index = pd.date_range("2018-01-01", periods=n, freq="D", tz="UTC")
    t = np.arange(n, dtype="float64")
    # A pronounced oscillation (period ~100 bars) so Donchian both enters on an
    # up-break and exits on a down-break, exercising buys and sells.
    close = 130.0 + 60.0 * np.sin(t / 16.0) + 0.05 * t
    open_ = np.empty(n, dtype="float64")
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) * 1.015
    low = np.minimum(open_, close) * 0.985
    volume = 1_000.0 + 8.0 * t
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


class TestCompatibilityParity:
    """compatibility_v1 fractional == binary base scenario, bit-for-bit."""

    @pytest.mark.parametrize(
        ("name", "binary_strategy"),
        [
            ("cash", Cash()),
            ("buy_and_hold", BuyAndHold()),
            ("donchian_55_20", DonchianChannel(entry_window=55, exit_window=20)),
        ],
    )
    def test_equity_curve_matches_binary_engine(self, name: str, binary_strategy: Strategy) -> None:
        frame = _synthetic_frame()
        binary = run_backtest(
            frame,
            binary_strategy,
            CostModel(fee_rate=0.001, slippage_rate=0.0005),
            initial_cash=INITIAL_CASH,
        )
        fractional = run_fractional_backtest(
            frame, STRATEGIES_BY_NAME[name], COMPATIBILITY_V1, initial_cash=INITIAL_CASH
        )
        np.testing.assert_array_equal(fractional.equity.to_numpy(), binary.equity.to_numpy())
        np.testing.assert_array_equal(fractional.quantity.to_numpy(), binary.quantity.to_numpy())
        assert fractional.terminal_liquidation_equity == pytest.approx(
            binary.terminal_liquidation_equity, abs=1e-9
        )

    def test_donchian_actually_trades(self) -> None:
        # Guard against a vacuous parity: the wave must trigger real fills.
        frame = _synthetic_frame()
        fractional = run_fractional_backtest(
            frame,
            STRATEGIES_BY_NAME["donchian_55_20"],
            COMPATIBILITY_V1,
            initial_cash=INITIAL_CASH,
        )
        assert fractional.num_fills >= 2


class TestCausality:
    def test_future_rows_never_affect_earlier_bars(self) -> None:
        frame = _synthetic_frame()
        cut = 90
        mutated = frame.copy()
        # Corrupt every row from `cut` onward (open/high/low/close/volume).
        mutated.iloc[cut:] = mutated.iloc[cut:] * 3.0
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
        # Bars strictly before the cut used only data through their own t-1 and
        # open[t], so their equity cannot have moved.
        np.testing.assert_array_equal(base.equity.to_numpy()[:cut], after.equity.to_numpy()[:cut])


class TestLongOnlyInvariants:
    @pytest.mark.parametrize("scenario", [COMPATIBILITY_V1, CAUSAL_PROXY_BASE])
    @pytest.mark.parametrize("name", list(STRATEGIES_BY_NAME))
    def test_no_negative_cash_or_eth_and_bounded_exposure(
        self, name: str, scenario: CostScenario
    ) -> None:
        frame = _synthetic_frame()
        result = run_fractional_backtest(
            frame,
            STRATEGIES_BY_NAME[name],
            scenario,
            initial_cash=INITIAL_CASH,
        )
        tol = DEFAULT_TOLERANCES
        for bar in result.bars:
            assert bar.cash_after >= -tol.cash_tolerance
            assert bar.quantity_after >= -tol.quantity_tolerance
            assert -tol.weight_tolerance <= bar.achieved_exposure <= 1.0 + tol.weight_tolerance
            assert bar.equity > 0.0

    def test_vol_target_produces_fractional_exposure(self) -> None:
        # The volatility-targeted strategy must scale below full investment on
        # some bar (otherwise the overlay is inert on this data).
        frame = _synthetic_frame()
        result = run_fractional_backtest(
            frame,
            STRATEGIES_BY_NAME["vol_target_buy_and_hold_30d_50pct"],
            COMPATIBILITY_V1,
            initial_cash=INITIAL_CASH,
        )
        exposures = [b.executable_target for b in result.bars]
        assert any(0.0 < e < 1.0 for e in exposures)


class TestValidation:
    def test_empty_frame_is_rejected(self) -> None:
        empty = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="UTC"),
        )
        with pytest.raises(EngineError, match="empty"):
            run_fractional_backtest(
                empty, STRATEGIES_BY_NAME["cash"], COMPATIBILITY_V1, initial_cash=INITIAL_CASH
            )

    def test_non_positive_initial_cash_is_rejected(self) -> None:
        with pytest.raises(EngineError, match="initial_cash"):
            run_fractional_backtest(
                _synthetic_frame(),
                STRATEGIES_BY_NAME["cash"],
                COMPATIBILITY_V1,
                initial_cash=0.0,
            )

    def test_context_not_strictly_before_frame_is_rejected(self) -> None:
        # Defense in depth: a context overlapping/following the frame could leak a
        # future row into signal/liquidity/volatility estimation and is refused.
        frame = _synthetic_frame(n=80)
        bad_context = frame.iloc[-10:]  # overlaps the frame in time
        with pytest.raises(EngineError, match="context must be strictly before"):
            run_fractional_backtest(
                frame,
                STRATEGIES_BY_NAME["cash"],
                COMPATIBILITY_V1,
                initial_cash=INITIAL_CASH,
                context=bad_context,
            )
