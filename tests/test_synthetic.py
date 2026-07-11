"""Tests for the deterministic synthetic OHLCV generator."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.data.schema import validate_ohlcv
from eth_research.data.synthetic import make_synthetic_ohlcv


def test_same_seed_is_deterministic() -> None:
    first = make_synthetic_ohlcv(n_periods=50, seed=1)
    second = make_synthetic_ohlcv(n_periods=50, seed=1)
    pd.testing.assert_frame_equal(first, second)


def test_different_seeds_differ() -> None:
    first = make_synthetic_ohlcv(n_periods=50, seed=1)
    second = make_synthetic_ohlcv(n_periods=50, seed=2)
    assert not first["close"].equals(second["close"])


def test_output_is_schema_canonical() -> None:
    frame = make_synthetic_ohlcv(n_periods=25, seed=0)
    assert len(frame) == 25
    pd.testing.assert_frame_equal(validate_ohlcv(frame), frame)


def test_start_and_frequency_are_honored() -> None:
    frame = make_synthetic_ohlcv(n_periods=10, freq="1h", start="2021-06-01")
    index = frame.index
    assert index[0] == pd.Timestamp("2021-06-01", tz="UTC")
    assert (pd.Series(index).diff().dropna() == pd.Timedelta("1h")).all()


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"n_periods": 0}, "n_periods"),
        ({"start_price": 0.0}, "start_price"),
        ({"volatility": -0.1}, "volatility"),
    ],
)
def test_invalid_arguments_rejected(kwargs: dict[str, float], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        make_synthetic_ohlcv(**{"n_periods": 10, **kwargs})  # type: ignore[arg-type]
