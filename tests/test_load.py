"""Tests for CSV and Parquet loading under strict validation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from eth_research.data.load import load_ohlcv
from eth_research.data.schema import SchemaError, validate_ohlcv
from eth_research.data.synthetic import make_synthetic_ohlcv


@pytest.fixture
def canonical() -> pd.DataFrame:
    return make_synthetic_ohlcv(n_periods=50, seed=3)


def test_csv_roundtrip(tmp_path: Path, canonical: pd.DataFrame) -> None:
    path = tmp_path / "eth.csv"
    canonical.reset_index().to_csv(path, index=False)
    loaded = load_ohlcv(path)
    pd.testing.assert_frame_equal(loaded, canonical, check_freq=False)


def test_parquet_roundtrip(tmp_path: Path, canonical: pd.DataFrame) -> None:
    path = tmp_path / "eth.parquet"
    canonical.to_parquet(path)
    loaded = load_ohlcv(path)
    pd.testing.assert_frame_equal(loaded, canonical, check_freq=False)


def test_pq_extension_is_treated_as_parquet(tmp_path: Path, canonical: pd.DataFrame) -> None:
    path = tmp_path / "eth.pq"
    canonical.to_parquet(path)
    loaded = load_ohlcv(path)
    pd.testing.assert_frame_equal(loaded, canonical, check_freq=False)


def test_epoch_milliseconds_are_unambiguous_utc(tmp_path: Path, canonical: pd.DataFrame) -> None:
    frame = canonical.reset_index()
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    frame["timestamp"] = (frame["timestamp"] - epoch) // pd.Timedelta(milliseconds=1)
    path = tmp_path / "eth.csv"
    frame.to_csv(path, index=False)
    # No assume_utc needed: epoch timestamps carry no timezone ambiguity.
    loaded = load_ohlcv(path, timestamp_unit="ms")
    pd.testing.assert_frame_equal(loaded, canonical, check_freq=False)


def test_naive_file_rejected_without_opt_in(tmp_path: Path, canonical: pd.DataFrame) -> None:
    frame = canonical.reset_index()
    frame["timestamp"] = frame["timestamp"].dt.tz_localize(None)
    path = tmp_path / "eth.csv"
    frame.to_csv(path, index=False)
    with pytest.raises(SchemaError, match="timezone-naive"):
        load_ohlcv(path)
    loaded = load_ohlcv(path, assume_utc=True)
    pd.testing.assert_frame_equal(loaded, canonical, check_freq=False)


def test_unsorted_file_rejected(tmp_path: Path, canonical: pd.DataFrame) -> None:
    path = tmp_path / "eth.csv"
    canonical.reset_index().sample(frac=1, random_state=2).to_csv(path, index=False)
    with pytest.raises(SchemaError, match="not sorted"):
        load_ohlcv(path)


def test_gapped_file_rejected(tmp_path: Path, canonical: pd.DataFrame) -> None:
    path = tmp_path / "eth.csv"
    canonical.reset_index().drop(index=10).to_csv(path, index=False)
    with pytest.raises(SchemaError, match="irregular candle intervals"):
        load_ohlcv(path)
    with pytest.raises(SchemaError, match="missing candles or gaps"):
        load_ohlcv(path, expected_interval="1D")


def test_expected_interval_passthrough(tmp_path: Path, canonical: pd.DataFrame) -> None:
    path = tmp_path / "eth.csv"
    canonical.reset_index().to_csv(path, index=False)
    loaded = load_ohlcv(path, expected_interval="1D")
    pd.testing.assert_frame_equal(loaded, canonical, check_freq=False)
    with pytest.raises(SchemaError, match="expected 0 days 01:00:00"):
        load_ohlcv(path, expected_interval="1h")


def test_loader_and_validator_agree_on_mixed_timestamps(tmp_path: Path) -> None:
    """The loader must apply exactly the direct validator's timestamp rules."""
    path = tmp_path / "eth.csv"
    path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01T00:00:00+00:00,100,103,97,101,10\n"
        "2024-01-02T00:00:00,101,104,98,102,10\n"  # naive row
    )
    raw = pd.read_csv(path)

    with pytest.raises(SchemaError, match=r"timezone-naive timestamp\(s\) at row\(s\) 1"):
        load_ohlcv(path)
    with pytest.raises(SchemaError, match=r"timezone-naive timestamp\(s\) at row\(s\) 1"):
        validate_ohlcv(raw)

    loaded = load_ohlcv(path, assume_utc=True)
    validated = validate_ohlcv(raw, assume_utc=True)
    pd.testing.assert_frame_equal(loaded, validated)
    assert str(loaded.index.dtype) == "datetime64[ns, UTC]"


def test_loader_accepts_variable_aware_offsets(tmp_path: Path) -> None:
    path = tmp_path / "eth.csv"
    path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01T02:00:00+02:00,100,103,97,101,10\n"
        "2024-01-01T19:00:00-05:00,101,104,98,102,10\n"
    )
    loaded = load_ohlcv(path)
    expected = pd.DatetimeIndex(
        ["2024-01-01T00:00:00+00:00", "2024-01-02T00:00:00+00:00"], name="timestamp"
    ).as_unit("ns")
    pd.testing.assert_index_equal(loaded.index, expected)


def test_loader_rejects_unexpected_columns(tmp_path: Path, canonical: pd.DataFrame) -> None:
    path = tmp_path / "eth.csv"
    canonical.reset_index().assign(symbol="ETH-USD").to_csv(path, index=False)
    with pytest.raises(SchemaError, match=r"unexpected column\(s\): \['symbol'\]"):
        load_ohlcv(path)
    loaded = load_ohlcv(path, allow_extra_columns=True)
    pd.testing.assert_frame_equal(loaded, canonical, check_freq=False)


def test_unsupported_extension_rejected(tmp_path: Path) -> None:
    path = tmp_path / "eth.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="unsupported data file extension"):
        load_ohlcv(path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_ohlcv(tmp_path / "does-not-exist.csv")


def test_invalid_content_raises_schema_error(tmp_path: Path, canonical: pd.DataFrame) -> None:
    path = tmp_path / "eth.csv"
    canonical.reset_index().drop(columns=["close"]).to_csv(path, index=False)
    with pytest.raises(SchemaError, match="missing required"):
        load_ohlcv(path)


def test_csv_floats_load_with_round_trip_precision(tmp_path: Path) -> None:
    """CSV values must load as exactly the doubles the file denotes.

    pandas' default CSV float parser can be off by multiple ulps; the
    canonical dataset builder already parses with round-trip precision, so
    ``load_ohlcv`` reading the same file must produce bit-identical values
    (Milestone 1 correctness fix, found during the Milestone 2B red-team).
    """
    tricky = "0.0007973654593590796"
    exact = float(tricky)
    path = tmp_path / "eth.csv"
    path.write_text(
        "timestamp,open,high,low,close,volume\n"
        f"2024-01-01T00:00:00+00:00,{tricky},{tricky},{tricky},{tricky},1.0\n"
        f"2024-01-02T00:00:00+00:00,{tricky},{tricky},{tricky},{tricky},1.0\n",
        encoding="utf-8",
    )
    loaded = load_ohlcv(path)
    assert float(loaded["open"].iloc[0]) == exact
    assert float(loaded["close"].iloc[1]) == exact
