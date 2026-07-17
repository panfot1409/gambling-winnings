"""Universe membership and survivorship: causal ``active_at`` and per-instrument non-overlap."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import (
    MEMBERSHIP_REASONS,
    MembershipInterval,
    MembershipSchedule,
)


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _inst(symbol: str, base: str) -> InstrumentId:
    return InstrumentId(
        asset_class="crypto_spot",
        base_asset=base,
        quote_currency="USD",
        venue="synthetic",
        symbol=symbol,
        instrument_type="spot",
        price_unit="USD",
        quantity_unit=base,
        calendar_id="continuous_24_7",
    )


A = _inst("A-USD", "AAA")
B = _inst("B-USD", "BBB")


def _interval(
    instrument: InstrumentId,
    start: str,
    end: str | None,
    knowledge: str,
    reason: str = "listing",
) -> MembershipInterval:
    return MembershipInterval(
        instrument=instrument,
        effective_start=_ts(start),
        effective_end=None if end is None else _ts(end),
        knowledge_time=_ts(knowledge),
        reason=reason,
        source="synthetic",
    )


# --------------------------------------------------------------------------- #
# interval construction and validation
# --------------------------------------------------------------------------- #
def test_interval_round_trips_including_open_ended_null_end() -> None:
    closed = _interval(A, "2026-01-10T00:00:00", "2026-02-01T00:00:00", "2026-01-05T00:00:00")
    restored = MembershipInterval.from_mapping(closed.canonical())
    assert restored == closed

    open_ended = _interval(A, "2026-01-10T00:00:00", None, "2026-01-05T00:00:00")
    assert open_ended.canonical()["effective_end"] is None
    assert MembershipInterval.from_mapping(open_ended.canonical()) == open_ended


def test_interval_rejects_bad_window_and_fields() -> None:
    with pytest.raises(CanonicalError, match="strictly before effective_end"):
        _interval(A, "2026-02-01T00:00:00", "2026-01-01T00:00:00", "2026-01-01T00:00:00")
    with pytest.raises(CanonicalError, match="not be after effective_start"):
        # knowledge_time strictly after effective_start
        _interval(A, "2026-01-10T00:00:00", "2026-02-01T00:00:00", "2026-01-11T00:00:00")
    with pytest.raises(CanonicalError, match="expected one of"):
        _interval(A, "2026-01-10T00:00:00", None, "2026-01-05T00:00:00", reason="nope")
    with pytest.raises(CanonicalError, match="timezone-aware"):
        MembershipInterval(
            instrument=A,
            effective_start=pd.Timestamp("2026-01-10T00:00:00"),  # naive
            effective_end=None,
            knowledge_time=_ts("2026-01-05T00:00:00"),
            reason="listing",
            source="synthetic",
        )


def test_interval_from_mapping_rejects_unknown_and_missing_keys() -> None:
    payload = _interval(A, "2026-01-10T00:00:00", None, "2026-01-05T00:00:00").canonical()
    with pytest.raises(CanonicalError, match="unexpected"):
        MembershipInterval.from_mapping({**payload, "extra": 1})
    partial = dict(payload)
    del partial["reason"]
    with pytest.raises(CanonicalError, match="missing"):
        MembershipInterval.from_mapping(partial)


def test_membership_reasons_vocabulary() -> None:
    assert "delisting" in MEMBERSHIP_REASONS
    assert "data_availability_boundary" in MEMBERSHIP_REASONS


# --------------------------------------------------------------------------- #
# active_at: knowledge_time gate + half-open effective window
# --------------------------------------------------------------------------- #
def test_active_at_respects_knowledge_time_and_half_open_window() -> None:
    schedule = MembershipSchedule(
        intervals=(
            _interval(A, "2026-01-10T00:00:00", "2026-02-01T00:00:00", "2026-01-05T00:00:00"),
        )
    )
    # strictly before knowledge_time: not usable
    assert schedule.active_at(A, _ts("2026-01-03T00:00:00")) is False
    # known but not yet effective (knowledge_time <= tau < effective_start)
    assert schedule.active_at(A, _ts("2026-01-07T00:00:00")) is False
    # effective_start is inclusive
    assert schedule.active_at(A, _ts("2026-01-10T00:00:00")) is True
    assert schedule.active_at(A, _ts("2026-01-20T00:00:00")) is True
    # effective_end is exclusive (half-open [start, end))
    assert schedule.active_at(A, _ts("2026-02-01T00:00:00")) is False
    assert schedule.active_at(A, _ts("2026-02-05T00:00:00")) is False
    # a different instrument is never active on A's interval
    assert schedule.active_at(B, _ts("2026-01-20T00:00:00")) is False


def test_open_ended_interval_stays_active() -> None:
    schedule = MembershipSchedule(
        intervals=(_interval(A, "2026-01-10T00:00:00", None, "2026-01-10T00:00:00"),)
    )
    assert schedule.active_at(A, _ts("2026-01-10T00:00:00")) is True
    assert schedule.active_at(A, _ts("2030-01-01T00:00:00")) is True
    assert schedule.active_at(A, _ts("2026-01-09T23:59:59")) is False


def test_active_universe_sorted_and_deduplicated() -> None:
    schedule = MembershipSchedule(
        intervals=(
            _interval(A, "2026-01-01T00:00:00", None, "2026-01-01T00:00:00"),
            _interval(B, "2026-01-01T00:00:00", "2026-01-15T00:00:00", "2026-01-01T00:00:00"),
        )
    )
    both = schedule.active_universe(_ts("2026-01-10T00:00:00"))
    assert both == tuple(sorted((A, B), key=lambda i: i.instrument_id))
    # after B's window closes, only A remains
    assert schedule.active_universe(_ts("2026-01-20T00:00:00")) == (A,)


def test_active_at_rejects_non_instrument() -> None:
    schedule = MembershipSchedule(intervals=())
    with pytest.raises(CanonicalError, match="expected an InstrumentId"):
        schedule.active_at("A-USD", _ts("2026-01-10T00:00:00"))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# schedule: non-overlap invariant
# --------------------------------------------------------------------------- #
def test_schedule_rejects_overlapping_same_instrument_intervals() -> None:
    with pytest.raises(CanonicalError, match="overlapping membership windows"):
        MembershipSchedule(
            intervals=(
                _interval(A, "2026-01-01T00:00:00", "2026-02-01T00:00:00", "2026-01-01T00:00:00"),
                _interval(A, "2026-01-15T00:00:00", "2026-03-01T00:00:00", "2026-01-15T00:00:00"),
            )
        )


def test_schedule_rejects_open_ended_then_later_window() -> None:
    with pytest.raises(CanonicalError, match="overlapping membership windows"):
        MembershipSchedule(
            intervals=(
                _interval(A, "2026-01-01T00:00:00", None, "2026-01-01T00:00:00"),
                _interval(A, "2026-06-01T00:00:00", None, "2026-06-01T00:00:00"),
            )
        )


def test_schedule_allows_adjacent_windows_and_independent_instruments() -> None:
    schedule = MembershipSchedule(
        intervals=(
            # A: two touching windows [start, end) then [end, ...) do not overlap
            _interval(A, "2026-01-01T00:00:00", "2026-02-01T00:00:00", "2026-01-01T00:00:00"),
            _interval(A, "2026-02-01T00:00:00", "2026-03-01T00:00:00", "2026-02-01T00:00:00"),
            # B overlapping A in wall-clock time is fine (different instrument)
            _interval(B, "2026-01-15T00:00:00", "2026-02-15T00:00:00", "2026-01-15T00:00:00"),
        )
    )
    assert schedule.active_at(A, _ts("2026-02-01T00:00:00")) is True
    assert len(schedule.intervals) == 3


# --------------------------------------------------------------------------- #
# fingerprint + round trip
# --------------------------------------------------------------------------- #
def test_schedule_fingerprint_is_order_independent_and_round_trips() -> None:
    first = _interval(A, "2026-01-01T00:00:00", None, "2026-01-01T00:00:00")
    second = _interval(B, "2026-01-01T00:00:00", "2026-02-01T00:00:00", "2026-01-01T00:00:00")
    forward = MembershipSchedule(intervals=(first, second))
    reversed_order = MembershipSchedule(intervals=(second, first))
    assert forward.fingerprint == reversed_order.fingerprint  # canonical order
    restored = MembershipSchedule.from_mapping(forward.canonical())
    assert restored.fingerprint == forward.fingerprint


def test_schedule_fingerprint_is_content_sensitive() -> None:
    base = MembershipSchedule(
        intervals=(_interval(A, "2026-01-01T00:00:00", None, "2026-01-01T00:00:00"),)
    )
    changed = MembershipSchedule(
        intervals=(
            _interval(
                A, "2026-01-01T00:00:00", None, "2026-01-01T00:00:00", reason="constituent_addition"
            ),
        )
    )
    assert base.fingerprint != changed.fingerprint
