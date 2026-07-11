"""Shared fixtures for the test suite."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd
import pytest

from eth_research.data.synthetic import make_synthetic_ohlcv


@pytest.fixture
def synthetic_daily() -> pd.DataFrame:
    """400 daily bars of deterministic synthetic ETH-like data."""
    return make_synthetic_ohlcv(n_periods=400, seed=7)


@pytest.fixture
def frame_from_closes() -> Callable[[Sequence[float]], pd.DataFrame]:
    """Factory for a valid OHLCV frame with exactly the given close prices.

    Lets tests hand-compute expected results from a known close path.
    """

    def build(closes: Sequence[float]) -> pd.DataFrame:
        index = pd.date_range(
            "2024-01-01", periods=len(closes), freq="1D", tz="UTC", name="timestamp"
        )
        close = pd.Series(list(closes), index=index, dtype=float)
        open_ = close.shift(1).fillna(close.iloc[0])
        high = pd.concat([open_, close], axis=1).max(axis=1) * 1.01
        low = pd.concat([open_, close], axis=1).min(axis=1) * 0.99
        volume = pd.Series(1_000.0, index=index)
        return pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
        )

    return build
