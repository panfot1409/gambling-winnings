"""Compatibility oracle: binary-equivalent strategies match the binary engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.fractional.compatibility import (
    CompatibilityError,
    assert_binary_parity,
    binary_parity,
)
from eth_research.fractional.strategies import STRATEGIES_BY_NAME

INITIAL_CASH = 10_000.0
BINARY_EQUIVALENT = ["cash", "buy_and_hold", "donchian_55_20"]
NON_EQUIVALENT = ["vol_target_buy_and_hold_30d_50pct", "vol_target_donchian_55_20_30d_50pct"]


def _frame(n: int = 210, seed: int = 0) -> pd.DataFrame:
    index = pd.date_range("2017-06-01", periods=n, freq="D", tz="UTC")
    t = np.arange(n, dtype="float64")
    close = 150.0 + 70.0 * np.sin((t + 5.0 * seed) / 17.0) + 0.08 * t
    open_ = np.empty(n, dtype="float64")
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    volume = 1_200.0 + 5.0 * t
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


class TestOracle:
    @pytest.mark.parametrize("name", BINARY_EQUIVALENT)
    def test_binary_equivalent_strategies_match_bit_for_bit(self, name: str) -> None:
        report = assert_binary_parity(_frame(), STRATEGIES_BY_NAME[name], initial_cash=INITIAL_CASH)
        assert report.equity_matches
        assert report.quantity_matches
        assert report.cash_matches
        assert report.terminal_liquidation_close

    @pytest.mark.parametrize("seed", [0, 1, 2])
    @pytest.mark.parametrize("cash", [10_000.0, 5_000.0, 250_000.0])
    def test_parity_holds_across_frames_and_capital(self, seed: int, cash: float) -> None:
        report = assert_binary_parity(
            _frame(seed=seed), STRATEGIES_BY_NAME["donchian_55_20"], initial_cash=cash
        )
        assert report.equity_matches
        assert report.quantity_matches

    @pytest.mark.parametrize("name", NON_EQUIVALENT)
    def test_overlay_strategies_have_no_binary_equivalent(self, name: str) -> None:
        with pytest.raises(CompatibilityError, match="no binary equivalent"):
            binary_parity(_frame(), STRATEGIES_BY_NAME[name], initial_cash=INITIAL_CASH)

    def test_report_records_the_terminal_liquidation_diff(self) -> None:
        report = binary_parity(
            _frame(), STRATEGIES_BY_NAME["buy_and_hold"], initial_cash=INITIAL_CASH
        )
        assert report.max_terminal_liquidation_diff <= 1e-9
        assert report.bars == 210
