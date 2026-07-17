"""The UTC time convention and the three trading-calendar kinds."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio._time import iso_utc, require_utc_timestamp
from eth_research.portfolio.calendar import (
    Session,
    TradingCalendar,
    synthetic_weekday_calendar,
)


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


# --------------------------------------------------------------------------- #
# _time
# --------------------------------------------------------------------------- #
def test_iso_utc_round_trips_and_rejects_naive() -> None:
    ts = _ts("2026-07-14T13:00:00")
    text = iso_utc(ts)
    assert text == "2026-07-14T13:00:00+00:00"
    assert require_utc_timestamp(text, "t") == ts
    with pytest.raises(CanonicalError):
        iso_utc(pd.Timestamp("2026-07-14T13:00:00"))  # naive


def test_require_utc_timestamp_rejects_noncanonical() -> None:
    for bad in ("2026-07-14T13:00:00Z", "2026-07-14T13:00:00", "not-a-time", 123, "2026-07-14"):
        with pytest.raises(CanonicalError):
            require_utc_timestamp(bad, "t")


# --------------------------------------------------------------------------- #
# calendars
# --------------------------------------------------------------------------- #
def test_continuous_calendar_is_always_open_and_carries_no_sessions() -> None:
    cal = TradingCalendar("c247", "continuous_24_7", (), "synthetic")
    assert cal.is_open(_ts("2026-01-01T00:00:00")) is True
    assert cal.session_containing(_ts("2026-01-01T00:00:00")) is None
    with pytest.raises(CanonicalError):
        TradingCalendar(
            "bad",
            "continuous_24_7",
            (
                Session(
                    "s",
                    "2026-07-14",
                    _ts("2026-07-14T13:00:00"),
                    _ts("2026-07-14T21:00:00"),
                    False,
                    "x",
                ),
            ),
            "synthetic",
        )


def test_session_list_open_and_containment() -> None:
    sessions = (
        Session(
            "d1", "2026-07-14", _ts("2026-07-14T13:00:00"), _ts("2026-07-14T21:00:00"), False, "x"
        ),
        Session(
            "d2", "2026-07-15", _ts("2026-07-15T13:00:00"), _ts("2026-07-15T21:00:00"), False, "x"
        ),
    )
    cal = TradingCalendar("nyse", "session_list", sessions, "x")
    assert cal.is_open(_ts("2026-07-14T15:00:00")) is True
    assert cal.is_open(_ts("2026-07-14T21:00:00")) is False  # half-open [open, close)
    assert cal.is_open(_ts("2026-07-14T22:00:00")) is False
    session = cal.session_containing(_ts("2026-07-15T14:00:00"))
    assert session is not None
    assert session.session_id == "d2"


def test_calendar_rejects_overlap_unsorted_and_duplicate_id() -> None:
    a = Session(
        "a", "2026-07-14", _ts("2026-07-14T13:00:00"), _ts("2026-07-14T21:00:00"), False, "x"
    )
    later = Session(
        "b", "2026-07-15", _ts("2026-07-15T13:00:00"), _ts("2026-07-15T21:00:00"), False, "x"
    )
    overlap = Session(
        "b", "2026-07-14", _ts("2026-07-14T20:00:00"), _ts("2026-07-14T23:00:00"), False, "x"
    )
    dup = Session(
        "a", "2026-07-16", _ts("2026-07-16T13:00:00"), _ts("2026-07-16T21:00:00"), False, "x"
    )
    with pytest.raises(CanonicalError, match="ascending"):
        TradingCalendar("c", "session_list", (later, a), "x")
    with pytest.raises(CanonicalError, match="overlap"):
        TradingCalendar("c", "session_list", (a, overlap), "x")
    with pytest.raises(CanonicalError, match="duplicate"):
        TradingCalendar("c", "session_list", (a, dup), "x")
    with pytest.raises(CanonicalError):  # session open >= close
        Session(
            "z", "2026-07-14", _ts("2026-07-14T21:00:00"), _ts("2026-07-14T13:00:00"), False, "x"
        )


def test_synthetic_weekday_is_deterministic_with_early_close() -> None:
    cal = synthetic_weekday_calendar("nasdaq", "2026-07-13", 7, early_close_dates=("2026-07-15",))
    # 2026-07-13 is a Monday; 7 days -> Mon..Fri = 5 sessions
    assert len(cal.sessions) == 5
    again = synthetic_weekday_calendar("nasdaq", "2026-07-13", 7, early_close_dates=("2026-07-15",))
    assert cal.fingerprint == again.fingerprint
    early = [s for s in cal.sessions if s.early_close]
    assert len(early) == 1
    assert early[0].date == "2026-07-15"
    # the early close is two hours earlier than a normal session
    normal = next(s for s in cal.sessions if not s.early_close)
    normal_span = normal.close - normal.open
    early_span = early[0].close - early[0].open
    assert early_span == normal_span - pd.Timedelta(hours=2)


def test_calendar_round_trips_through_mapping() -> None:
    cal = synthetic_weekday_calendar("nasdaq", "2026-07-13", 5)
    restored = TradingCalendar.from_mapping(cal.canonical())
    assert restored.fingerprint == cal.fingerprint
    assert restored.calendar_id == "nasdaq"
