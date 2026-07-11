"""Tests for OHLCV schema validation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.data.schema import OHLCV_COLUMNS, SchemaError, validate_ohlcv


def raw_frame(n: int = 6) -> pd.DataFrame:
    """A well-formed raw frame with a ``timestamp`` column."""
    timestamps = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
    open_ = np.linspace(100.0, 105.0, n) if n > 0 else np.array([], dtype=float)
    close = open_ + 0.5
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_,
            "high": close * 1.02,
            "low": open_ * 0.98,
            "close": close,
            "volume": np.full(n, 10.0),
        }
    )


def test_valid_frame_normalizes() -> None:
    validated = validate_ohlcv(raw_frame())

    assert tuple(validated.columns) == OHLCV_COLUMNS
    assert isinstance(validated.index, pd.DatetimeIndex)
    assert validated.index.name == "timestamp"
    assert str(validated.index.tz) == "UTC"
    assert validated.index.is_monotonic_increasing
    assert validated.index.is_unique
    assert all(dtype == np.float64 for dtype in validated.dtypes)
    assert len(validated) == 6


def test_input_frame_is_not_modified() -> None:
    frame = raw_frame()
    original = frame.copy()
    validate_ohlcv(frame)
    pd.testing.assert_frame_equal(frame, original)


def test_accepts_datetime_index_instead_of_column() -> None:
    from_column = validate_ohlcv(raw_frame())
    from_index = validate_ohlcv(raw_frame().set_index("timestamp"))
    pd.testing.assert_frame_equal(from_index, from_column)


def test_naive_timestamps_are_assumed_utc() -> None:
    frame = raw_frame()
    frame["timestamp"] = frame["timestamp"].dt.tz_localize(None)
    validated = validate_ohlcv(frame)
    pd.testing.assert_frame_equal(validated, validate_ohlcv(raw_frame()))


def test_extra_columns_are_dropped() -> None:
    frame = raw_frame()
    frame["trades"] = 42
    validated = validate_ohlcv(frame)
    assert "trades" not in validated.columns


def test_missing_column_rejected() -> None:
    frame = raw_frame().drop(columns=["close"])
    with pytest.raises(SchemaError, match="missing required"):
        validate_ohlcv(frame)


def test_duplicated_column_names_rejected() -> None:
    frame = raw_frame()
    frame = pd.concat([frame, frame[["close"]]], axis=1)
    with pytest.raises(SchemaError, match="duplicated column"):
        validate_ohlcv(frame)


def test_numeric_timestamps_rejected() -> None:
    frame = raw_frame()
    frame["timestamp"] = np.arange(len(frame))
    with pytest.raises(SchemaError, match="numeric"):
        validate_ohlcv(frame)


def test_unparseable_timestamps_rejected() -> None:
    frame = raw_frame()
    frame["timestamp"] = ["not-a-date"] * len(frame)
    with pytest.raises(SchemaError, match="cannot parse"):
        validate_ohlcv(frame)


def test_missing_timestamp_rejected() -> None:
    frame = raw_frame()
    frame.loc[2, "timestamp"] = None
    with pytest.raises(SchemaError, match="missing timestamp"):
        validate_ohlcv(frame)


def test_nan_price_rejected() -> None:
    frame = raw_frame()
    frame.loc[2, "close"] = np.nan
    with pytest.raises(SchemaError, match="non-finite"):
        validate_ohlcv(frame)


def test_non_numeric_price_rejected() -> None:
    frame = raw_frame()
    frame["close"] = ["oops"] * len(frame)
    with pytest.raises(SchemaError, match="must be numeric"):
        validate_ohlcv(frame)


def test_non_positive_price_rejected() -> None:
    frame = raw_frame()
    frame.loc[0, "open"] = 0.0
    with pytest.raises(SchemaError, match="non-positive prices"):
        validate_ohlcv(frame)


def test_negative_volume_rejected() -> None:
    frame = raw_frame()
    frame.loc[1, "volume"] = -5.0
    with pytest.raises(SchemaError, match="volume"):
        validate_ohlcv(frame)


def test_high_below_open_close_rejected() -> None:
    frame = raw_frame()
    frame.loc[3, "high"] = 1.0
    with pytest.raises(SchemaError, match=r"high < max\(open, close\)"):
        validate_ohlcv(frame)


def test_low_above_open_close_rejected() -> None:
    frame = raw_frame()
    frame.loc[3, "low"] = 1e6
    with pytest.raises(SchemaError, match=r"low > min\(open, close\)"):
        validate_ohlcv(frame)


def test_duplicate_timestamps_rejected() -> None:
    frame = raw_frame()
    frame.loc[3, "timestamp"] = frame.loc[2, "timestamp"]
    with pytest.raises(SchemaError, match="duplicated timestamp"):
        validate_ohlcv(frame)


def test_unsorted_rows_are_sorted_by_default() -> None:
    shuffled = raw_frame().sample(frac=1, random_state=1)
    validated = validate_ohlcv(shuffled)
    pd.testing.assert_frame_equal(validated, validate_ohlcv(raw_frame()))


def test_unsorted_rows_rejected_when_sort_disabled() -> None:
    shuffled = raw_frame().sample(frac=1, random_state=1)
    with pytest.raises(SchemaError, match="not sorted"):
        validate_ohlcv(shuffled, sort=False)


def test_empty_frame_rejected() -> None:
    with pytest.raises(SchemaError, match="empty"):
        validate_ohlcv(raw_frame(0))


def test_all_content_problems_reported_together() -> None:
    frame = raw_frame()
    frame.loc[3, "timestamp"] = frame.loc[2, "timestamp"]
    frame.loc[1, "volume"] = -1.0
    with pytest.raises(SchemaError) as excinfo:
        validate_ohlcv(frame)
    assert len(excinfo.value.problems) == 2
