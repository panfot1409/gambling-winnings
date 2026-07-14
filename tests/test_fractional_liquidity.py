"""Causal lagged-liquidity estimator: causality is the load-bearing property.

The estimate at ``open[t]`` must use only rows through ``t-1`` and must be
invariant to any change at or after ``t`` (no same-bar volume/close leakage).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.fractional.liquidity import (
    LiquidityError,
    estimate_liquidity,
)


def _frame(closes: list[float], volumes: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame({"close": closes, "volume": volumes}, index=index)


class TestHandCalculated:
    def test_constant_dollar_volume_median(self) -> None:
        # close*volume = 1000 for every bar -> median 1000, base median 10.
        frame = _frame([100.0] * 40, [10.0] * 40)
        est = estimate_liquidity(frame, frame.index[35])
        assert est.sufficient
        assert est.observation_count == 30
        assert est.dollar_volume_stat == pytest.approx(1000.0)
        assert est.base_volume_stat == pytest.approx(10.0)
        assert est.available

    def test_window_is_the_thirty_rows_before_as_of(self) -> None:
        frame = _frame([100.0] * 40, [float(i) for i in range(40)])
        as_of = frame.index[35]
        est = estimate_liquidity(frame, as_of)
        # Contributing rows are indices 5..34 (30 rows strictly before 35).
        assert est.oldest_contributing == frame.index[5]
        assert est.newest_contributing == frame.index[34]
        assert est.newest_contributing < as_of
        # median of volumes 5..34 = mean of the 15th/16th order stats (19,20) -> 19.5
        assert est.base_volume_stat == pytest.approx(19.5)


class TestCausality:
    def test_current_and_future_rows_never_affect_the_estimate(self) -> None:
        base = _frame([100.0] * 40, [10.0] * 40)
        as_of = base.index[35]
        reference = estimate_liquidity(base, as_of)

        mutated = base.copy()
        # Blow up the current bar (35) and every future bar; the estimate as of
        # open[35] must not move one bit.
        future = mutated.index >= as_of
        mutated.loc[future, "volume"] = 1e12
        mutated.loc[future, "close"] = 9e9
        after = estimate_liquidity(mutated, as_of)
        assert after == reference

    def test_appending_future_rows_is_prefix_invariant(self) -> None:
        base = _frame([100.0] * 40, [10.0] * 40)
        as_of = base.index[35]
        reference = estimate_liquidity(base, as_of)
        extra = _frame([500.0] * 10, [777.0] * 10, start="2020-02-10")
        appended = pd.concat([base, extra])
        assert estimate_liquidity(appended, as_of) == reference


class TestWarmupAndValidation:
    def test_insufficient_history_is_reported_not_raised(self) -> None:
        frame = _frame([100.0] * 20, [10.0] * 20)
        est = estimate_liquidity(frame, frame.index[19])  # only 19 lagged rows
        assert not est.sufficient
        assert est.reason == "insufficient_liquidity_history"
        assert est.dollar_volume_stat is None
        assert not est.available

    def test_non_finite_volume_fails_loudly(self) -> None:
        vols = [10.0] * 40
        vols[20] = np.inf
        frame = _frame([100.0] * 40, vols)
        with pytest.raises(LiquidityError, match="non-finite"):
            estimate_liquidity(frame, frame.index[35])

    def test_nan_close_fails_loudly(self) -> None:
        closes = [100.0] * 40
        closes[10] = np.nan
        frame = _frame(closes, [10.0] * 40)
        with pytest.raises(LiquidityError, match="non-finite"):
            estimate_liquidity(frame, frame.index[35])

    def test_negative_volume_fails_loudly(self) -> None:
        vols = [10.0] * 40
        vols[25] = -5.0
        frame = _frame([100.0] * 40, vols)
        with pytest.raises(LiquidityError, match="negative volume"):
            estimate_liquidity(frame, frame.index[35])

    def test_zero_volume_run_is_available_false(self) -> None:
        frame = _frame([100.0] * 40, [0.0] * 40)
        est = estimate_liquidity(frame, frame.index[35])
        assert est.sufficient  # 30 observations exist
        assert est.dollar_volume_stat == 0.0
        assert not est.available  # but zero liquidity is not usable

    def test_unsorted_index_is_rejected(self) -> None:
        frame = _frame([100.0] * 40, [10.0] * 40)
        shuffled = frame.iloc[[1, 0, *range(2, 40)]]
        with pytest.raises(LiquidityError, match="monotonic"):
            estimate_liquidity(shuffled, shuffled.index[35])

    def test_single_outlier_does_not_dominate_the_median(self) -> None:
        vols = [10.0] * 40
        vols[15] = 1e9  # one extreme bar
        frame = _frame([100.0] * 40, vols)
        est = estimate_liquidity(frame, frame.index[35])
        # median is robust: still 1000 despite the outlier in the window.
        assert est.dollar_volume_stat == pytest.approx(1000.0)
