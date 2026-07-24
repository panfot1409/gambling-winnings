"""Mechanical completed-day cutoff and the no-op decision (commit 4).

All boundary instants are derived from the committed accepted base's ``last_open``
(never hard-coded), so the same boundary semantics are checked against whatever
cohort state governance has accepted.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import eth_research
from eth_research.m3e.accepted_base import AcceptedProspectiveBase, verify_accepted_base
from eth_research.m3e.cutoff import completed_day_exclusive_end, plan_update_window
from eth_research.m3e.validation import M3EValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
_DAY = pd.Timedelta(days=1)


def _z(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def base() -> AcceptedProspectiveBase:
    return verify_accepted_base(REPO_ROOT)


@pytest.fixture(scope="module")
def last_open(base: AcceptedProspectiveBase) -> pd.Timestamp:
    return pd.Timestamp(base.last_open)


def test_today_is_a_noop_nothing_new_is_due(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    # Mid-morning on the first missing day: that candle is still forming.
    first_missing = last_open + _DAY
    decision = plan_update_window(base, first_missing + pd.Timedelta(hours=9))
    assert decision.is_noop is True
    assert decision.expected_new_buckets == 0
    assert decision.first_missing_open == _z(first_missing)
    assert decision.completed_day_exclusive_end == _z(first_missing)
    assert decision.window_start is None
    assert decision.window_end is None


def test_same_day_as_last_open_is_a_noop(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    decision = plan_update_window(base, last_open + pd.Timedelta(hours=12))
    assert decision.is_noop is True


def test_just_before_first_candle_completes_is_a_noop(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    decision = plan_update_window(
        base, last_open + _DAY + pd.Timedelta(hours=23, minutes=59, seconds=59)
    )
    assert decision.is_noop is True


def test_one_completed_day_becomes_due_after_it_settles(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    # The first missing day closes at last_open + 2 days; it becomes due only once it
    # has settled past the _SETTLE_DELAY (1h) floor — here 2h after close.
    decision = plan_update_window(base, last_open + 2 * _DAY + pd.Timedelta(hours=2))
    assert decision.is_noop is False
    assert decision.expected_new_buckets == 1
    assert decision.window_start == _z(last_open + _DAY)
    assert decision.window_end == _z(last_open + 2 * _DAY)


def test_a_just_closed_candle_is_deferred_until_it_settles(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    # A run fired seconds after the first missing day's close (last_open + 2 days)
    # must NOT fetch it — the venue may still revise it. It stays a NO-OP until
    # _SETTLE_DELAY (1h) has elapsed.
    close = last_open + 2 * _DAY
    just_after = plan_update_window(base, close + pd.Timedelta(seconds=30))
    assert just_after.is_noop is True
    assert just_after.expected_new_buckets == 0
    within_delay = plan_update_window(base, close + pd.Timedelta(minutes=59, seconds=59))
    assert within_delay.is_noop is True
    at_delay = plan_update_window(base, close + pd.Timedelta(hours=1))
    assert at_delay.is_noop is False
    assert at_delay.window_end == _z(close)


def test_multiple_completed_days_are_bound_contiguously(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    decision = plan_update_window(base, last_open + 6 * _DAY + pd.Timedelta(hours=2, minutes=17))
    assert decision.is_noop is False
    assert decision.expected_new_buckets == 5  # the five settled days after last_open
    assert decision.window_start == _z(last_open + _DAY)
    assert decision.window_end == _z(last_open + 6 * _DAY)


def test_a_clock_rewind_before_the_base_hard_stops(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    with pytest.raises(M3EValidationError, match="predates the accepted last open"):
        plan_update_window(base, last_open - _DAY + pd.Timedelta(hours=9))


def test_a_naive_non_utc_as_of_is_rejected(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    naive = (last_open + _DAY + pd.Timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S")
    with pytest.raises((M3EValidationError, ValueError)):
        plan_update_window(base, naive)  # no tz → not UTC-aware


def test_the_window_end_never_includes_the_forming_candle(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    # At mid-day one day past the first missing close, the current day's candle is
    # forming; the window must stop at its midnight.
    decision = plan_update_window(base, last_open + 2 * _DAY + pd.Timedelta(hours=12))
    assert decision.window_end == _z(last_open + 2 * _DAY)
    assert decision.expected_new_buckets == 1  # only the first missing day is completed


# --------------------------------------------------------------------------- #
# audit §12 — clock/cutoff boundary adversarial matrix                        #
# --------------------------------------------------------------------------- #
def test_cutoff_is_exact_floor_to_utc_midnight_at_boundaries() -> None:
    # The raw completed-day boundary is floor_to_utc_midnight(as_of) exactly — the forming
    # candle (the as_of day, whenever after its own midnight) is always excluded. This is the
    # pure floor; the settle-delay adjustment is applied only inside plan_update_window (which
    # may drop the effective window cutoff to the prior day for an unsettled boundary).
    cases = {
        "2026-07-16T00:00:00Z": "2026-07-16T00:00:00Z",  # exact midnight
        "2026-07-16T00:00:00.000001Z": "2026-07-16T00:00:00Z",  # 1us after midnight
        "2026-07-16T23:59:59.999999Z": "2026-07-16T00:00:00Z",  # 1us before next midnight
        "2027-01-01T00:00:01Z": "2027-01-01T00:00:00Z",  # year transition
        "2028-02-29T12:00:00Z": "2028-02-29T00:00:00Z",  # leap day
    }
    for as_of, expected_end in cases.items():
        assert completed_day_exclusive_end(as_of) == pd.Timestamp(expected_end), as_of


def test_one_microsecond_before_the_first_due_midnight_is_a_noop(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    # The first missing day completes at last_open + 2 days; one microsecond before
    # that midnight is still a NO-OP.
    decision = plan_update_window(base, last_open + 2 * _DAY - pd.Timedelta(microseconds=1))
    assert decision.is_noop is True


def test_one_microsecond_after_the_first_due_midnight_is_still_unsettled(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    # One microsecond after the first missing day's close the candle has not settled
    # past _SETTLE_DELAY, so it is a NO-OP; the effective settled cutoff drops to the
    # prior midnight (the first missing open itself).
    decision = plan_update_window(base, last_open + 2 * _DAY + pd.Timedelta(microseconds=1))
    assert decision.is_noop is True
    assert decision.completed_day_exclusive_end == _z(last_open + _DAY)


def test_a_malformed_as_of_is_rejected(base: AcceptedProspectiveBase) -> None:
    for bad in ("not-a-timestamp", "2026-13-01T00:00:00Z", "2026-07-16T24:00:00Z", ""):
        with pytest.raises((M3EValidationError, ValueError)):
            plan_update_window(base, bad)
