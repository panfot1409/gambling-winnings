"""Tests for strict OHLCV schema validation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.data.schema import OHLCV_COLUMNS, SchemaError, frame_interval, validate_ohlcv


def raw_frame(n: int = 6) -> pd.DataFrame:
    """A well-formed raw frame with a timezone-aware ``timestamp`` column."""
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


def test_naive_timestamps_rejected_by_default() -> None:
    frame = raw_frame()
    frame["timestamp"] = frame["timestamp"].dt.tz_localize(None)
    with pytest.raises(SchemaError, match="timezone-naive"):
        validate_ohlcv(frame)


def test_naive_timestamps_require_explicit_utc_opt_in() -> None:
    frame = raw_frame()
    frame["timestamp"] = frame["timestamp"].dt.tz_localize(None)
    validated = validate_ohlcv(frame, assume_utc=True)
    pd.testing.assert_frame_equal(validated, validate_ohlcv(raw_frame()))


def test_naive_datetime_index_rejected_by_default() -> None:
    frame = raw_frame().set_index("timestamp")
    assert isinstance(frame.index, pd.DatetimeIndex)
    frame.index = frame.index.tz_localize(None)
    with pytest.raises(SchemaError, match="timezone-naive"):
        validate_ohlcv(frame)


def test_aware_non_utc_timestamps_convert_without_opt_in() -> None:
    frame = raw_frame()
    frame["timestamp"] = frame["timestamp"].dt.tz_convert("Europe/Berlin")
    validated = validate_ohlcv(frame)
    pd.testing.assert_frame_equal(validated, validate_ohlcv(raw_frame()))


def test_naive_textual_timestamps_rejected_by_default() -> None:
    frame = raw_frame()
    frame["timestamp"] = frame["timestamp"].dt.tz_localize(None).astype(str)
    with pytest.raises(SchemaError, match="timezone-naive"):
        validate_ohlcv(frame)


def test_aware_textual_timestamps_accepted() -> None:
    frame = raw_frame()
    frame["timestamp"] = frame["timestamp"].astype(str)
    validated = validate_ohlcv(frame)
    pd.testing.assert_frame_equal(validated, validate_ohlcv(raw_frame()))


def test_unsorted_rows_rejected_never_sorted() -> None:
    shuffled = raw_frame().sample(frac=1, random_state=1)
    with pytest.raises(SchemaError, match="not sorted"):
        validate_ohlcv(shuffled)


def test_missing_candle_rejected_when_inferring_interval() -> None:
    frame = raw_frame(6).drop(index=3).reset_index(drop=True)
    with pytest.raises(SchemaError, match="irregular candle intervals"):
        validate_ohlcv(frame)


def test_missing_candle_rejected_against_expected_interval() -> None:
    frame = raw_frame(6).drop(index=3).reset_index(drop=True)
    with pytest.raises(SchemaError, match="missing candles or gaps"):
        validate_ohlcv(frame, expected_interval="1D")


def test_wrong_expected_interval_rejected() -> None:
    with pytest.raises(SchemaError, match="expected 0 days 01:00:00"):
        validate_ohlcv(raw_frame(), expected_interval="1h")


def test_matching_expected_interval_accepted() -> None:
    validated = validate_ohlcv(raw_frame(), expected_interval="1D")
    assert len(validated) == 6


def test_non_positive_expected_interval_rejected() -> None:
    with pytest.raises(ValueError, match="expected_interval must be positive"):
        validate_ohlcv(raw_frame(), expected_interval="0s")


def test_single_candle_has_no_interval_to_check() -> None:
    validated = validate_ohlcv(raw_frame(1))
    assert len(validated) == 1
    with pytest.raises(ValueError, match="at least 2"):
        frame_interval(validated)


def test_frame_interval_of_validated_frame() -> None:
    assert frame_interval(validate_ohlcv(raw_frame())) == pd.Timedelta("1D")


def _frame_with_timestamps(values: list[str]) -> pd.DataFrame:
    """A valid frame whose timestamp column is replaced by literal strings."""
    frame = raw_frame(len(values))
    return frame.assign(timestamp=values)


def test_mixed_naive_and_utc_aware_rejected_without_opt_in() -> None:
    frame = _frame_with_timestamps(["2024-01-01T00:00:00+00:00", "2024-01-02T00:00:00"])
    with pytest.raises(
        SchemaError, match=r"timezone-naive timestamp\(s\) at row\(s\) 1"
    ) as excinfo:
        validate_ohlcv(frame)
    assert "assume_utc=True" in str(excinfo.value)


def test_mixed_naive_and_non_utc_aware_rejected_without_opt_in() -> None:
    frame = _frame_with_timestamps(["2024-01-01T02:00:00+02:00", "2024-01-02T00:00:00"])
    with pytest.raises(SchemaError, match=r"timezone-naive timestamp\(s\) at row\(s\) 1"):
        validate_ohlcv(frame)


def test_mixed_naive_and_aware_normalize_deterministically_with_opt_in() -> None:
    # aware 2024-01-01T02:00+02:00 == 2024-01-01T00:00Z; naive -> localized UTC.
    frame = _frame_with_timestamps(["2024-01-01T02:00:00+02:00", "2024-01-02T00:00:00"])
    validated = validate_ohlcv(frame, assume_utc=True)
    expected = pd.DatetimeIndex(
        ["2024-01-01T00:00:00+00:00", "2024-01-02T00:00:00+00:00"], name="timestamp"
    ).as_unit("ns")
    pd.testing.assert_index_equal(validated.index, expected)


def test_variable_aware_offsets_accepted_without_opt_in() -> None:
    # +02:00 and -05:00 offsets are unambiguous; exactly one day apart in UTC.
    frame = _frame_with_timestamps(["2024-01-01T02:00:00+02:00", "2024-01-01T19:00:00-05:00"])
    validated = validate_ohlcv(frame)
    expected = pd.DatetimeIndex(
        ["2024-01-01T00:00:00+00:00", "2024-01-02T00:00:00+00:00"], name="timestamp"
    ).as_unit("ns")
    pd.testing.assert_index_equal(validated.index, expected)


def test_malformed_timestamp_reports_row_information() -> None:
    frame = _frame_with_timestamps(["2024-01-01T00:00:00+00:00", "not-a-date"])
    with pytest.raises(SchemaError, match="row 1: 'not-a-date'"):
        validate_ohlcv(frame)


def test_unexpected_columns_rejected_by_default() -> None:
    frame = raw_frame()
    frame["symbol"] = "ETH-USD"
    with pytest.raises(SchemaError, match=r"unexpected column\(s\): \['symbol'\]"):
        validate_ohlcv(frame)


def test_extra_columns_dropped_only_with_explicit_opt_in() -> None:
    frame = raw_frame()
    frame["symbol"] = "ETH-USD"
    frame["trades"] = 42
    validated = validate_ohlcv(frame, allow_extra_columns=True)
    assert "symbol" not in validated.columns
    assert "trades" not in validated.columns
    pd.testing.assert_frame_equal(validated, validate_ohlcv(raw_frame()))


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


def test_gap_and_value_problems_reported_together() -> None:
    frame = raw_frame(6).drop(index=3).reset_index(drop=True)
    frame.loc[1, "volume"] = -1.0
    with pytest.raises(SchemaError) as excinfo:
        validate_ohlcv(frame)
    assert len(excinfo.value.problems) == 2
