"""The deterministic rebalance schedule."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.calendar import synthetic_weekday_calendar
from eth_research.portfolio.schedule import RebalanceSchedule, schedule_from_calendar_opens


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def test_schedule_orders_and_fingerprints() -> None:
    sched = RebalanceSchedule(timestamps=(_ts("2026-07-14T13:00:00"), _ts("2026-07-15T13:00:00")))
    assert len(sched.events()) == 2
    assert len(sched.fingerprint) == 64
    restored = RebalanceSchedule.from_mapping(sched.canonical())
    assert restored.fingerprint == sched.fingerprint


def test_schedule_rejects_empty_and_unsorted() -> None:
    with pytest.raises(CanonicalError, match="at least one"):
        RebalanceSchedule(timestamps=())
    with pytest.raises(CanonicalError, match="ascending"):
        RebalanceSchedule(timestamps=(_ts("2026-07-15T13:00:00"), _ts("2026-07-14T13:00:00")))
    with pytest.raises(CanonicalError, match="ascending"):
        RebalanceSchedule(timestamps=(_ts("2026-07-14T13:00:00"), _ts("2026-07-14T13:00:00")))


def test_schedule_from_calendar_opens() -> None:
    cal = synthetic_weekday_calendar("nasdaq", "2026-07-13", 7)  # Mon..Fri = 5 sessions
    every_session = schedule_from_calendar_opens(cal)
    assert len(every_session.events()) == 5
    every_other = schedule_from_calendar_opens(cal, every=2)
    assert len(every_other.events()) == 3  # sessions 0, 2, 4
    # a continuous calendar has no sessions -> explicit schedule required
    from eth_research.portfolio.calendar import TradingCalendar

    with pytest.raises(CanonicalError, match="no sessions"):
        schedule_from_calendar_opens(TradingCalendar("c", "continuous_24_7", (), "x"))
