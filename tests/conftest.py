"""Shared fixtures for the test suite."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd
import pytest

from eth_research.data.synthetic import make_synthetic_ohlcv


@pytest.fixture
def synthetic_daily() -> pd.DataFrame:
    """400 daily bars of deterministic synthetic ETH-like data."""
    return make_synthetic_ohlcv(n_periods=400, seed=7)


def _build_frame(opens: Sequence[float], closes: Sequence[float]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(closes), freq="1D", tz="UTC", name="timestamp")
    open_array = np.asarray(list(opens), dtype=float)
    close_array = np.asarray(list(closes), dtype=float)
    high = np.maximum(open_array, close_array) * 1.01
    low = np.minimum(open_array, close_array) * 0.99
    return pd.DataFrame(
        {
            "open": open_array,
            "high": high,
            "low": low,
            "close": close_array,
            "volume": np.full(len(close_array), 1_000.0),
        },
        index=index,
    )


@pytest.fixture
def frame_from_bars() -> Callable[[Sequence[tuple[float, float]]], pd.DataFrame]:
    """Factory for a valid OHLCV frame with exactly the given (open, close) bars.

    Lets tests hand-compute expected fills and equity from known prices,
    including overnight gaps (open != previous close).
    """

    def build(bars: Sequence[tuple[float, float]]) -> pd.DataFrame:
        return _build_frame([bar[0] for bar in bars], [bar[1] for bar in bars])

    return build


@pytest.fixture
def frame_from_closes() -> Callable[[Sequence[float]], pd.DataFrame]:
    """Factory for a gapless frame with the given closes (open = previous close)."""

    def build(closes: Sequence[float]) -> pd.DataFrame:
        opens = [closes[0], *closes[:-1]]
        return _build_frame(opens, closes)

    return build
