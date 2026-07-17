"""The strict canonical bar-frame contract and its content fingerprint."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.bars import bar_frame_fingerprint, validate_bar_frame
from eth_research.portfolio.identity import InstrumentId

INST = InstrumentId(
    asset_class="crypto_spot",
    base_asset="ETH",
    quote_currency="USD",
    venue="synthetic",
    symbol="ETH-USD",
    instrument_type="spot",
    price_unit="USD",
    quantity_unit="ETH",
    calendar_id="continuous_24_7",
)


def _frame(rows: int = 3, *, start: str = "2026-07-14T00:00:00") -> pd.DataFrame:
    opens = pd.date_range(start=start, periods=rows, freq="h", tz="UTC")
    closes = opens + pd.Timedelta(hours=1)
    return pd.DataFrame(
        {
            "open_time": opens,
            "close_time": closes,
            "open": [100.0 + i for i in range(rows)],
            "high": [102.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [101.0 + i for i in range(rows)],
            "volume": [1000.0 + i for i in range(rows)],
        }
    )


def test_valid_frame_returns_canonical_copy_without_mutating_input() -> None:
    frame = _frame()
    original = frame.copy(deep=True)
    canonical = validate_bar_frame(frame, INST)
    assert list(canonical.columns) == [
        "open_time",
        "close_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    assert len(canonical) == 3
    # input untouched
    pd.testing.assert_frame_equal(frame, original)


def test_rejects_extra_column_unless_allowed() -> None:
    frame = _frame()
    frame["oops"] = 1.0
    with pytest.raises(CanonicalError, match="unexpected column"):
        validate_bar_frame(frame, INST)
    # allow_extra drops it
    canonical = validate_bar_frame(frame, INST, allow_extra=True)
    assert "oops" not in canonical.columns


def test_rejects_missing_column() -> None:
    frame = _frame().drop(columns=["volume"])
    with pytest.raises(CanonicalError, match="missing required column"):
        validate_bar_frame(frame, INST)


def test_rejects_unsorted_and_duplicate_open_time() -> None:
    frame = _frame()
    frame.loc[2, "open_time"] = frame.loc[0, "open_time"]  # out of order / duplicate
    with pytest.raises(CanonicalError, match="strictly increasing"):
        validate_bar_frame(frame, INST)


def test_rejects_bad_ohlc_and_volume() -> None:
    bad_close_order = _frame()
    bad_close_order.loc[0, "close_time"] = bad_close_order.loc[0, "open_time"]
    with pytest.raises(CanonicalError, match="before close_time"):
        validate_bar_frame(bad_close_order, INST)

    non_positive = _frame()
    non_positive.loc[0, "low"] = 0.0
    with pytest.raises(CanonicalError):
        validate_bar_frame(non_positive, INST)

    low_too_high = _frame()
    low_too_high.loc[0, "low"] = 100.5  # > min(open, close)=100
    with pytest.raises(CanonicalError, match="low must be"):
        validate_bar_frame(low_too_high, INST)

    high_too_low = _frame()
    high_too_low.loc[0, "high"] = 100.5  # < max(open, close)=101
    with pytest.raises(CanonicalError, match="high must be"):
        validate_bar_frame(high_too_low, INST)

    neg_volume = _frame()
    neg_volume.loc[0, "volume"] = -1.0
    with pytest.raises(CanonicalError):
        validate_bar_frame(neg_volume, INST)


def test_rejects_naive_timestamps() -> None:
    frame = _frame()
    frame["open_time"] = pd.date_range(start="2026-07-14", periods=3, freq="h")  # tz-naive
    with pytest.raises(CanonicalError, match="timezone-aware"):
        validate_bar_frame(frame, INST)


def test_fingerprint_is_stable_and_sensitive() -> None:
    frame = _frame()
    first = bar_frame_fingerprint(frame, INST)
    assert first == bar_frame_fingerprint(_frame(), INST)
    assert len(first) == 64
    changed = _frame()
    old_close = changed.loc[1, "close"]
    assert isinstance(old_close, float)  # narrow pandas Scalar so the arithmetic types
    changed.loc[1, "close"] = old_close + 0.01
    assert bar_frame_fingerprint(changed, INST) != first
