"""Mechanical completed-day cutoff and the no-op decision (commit 4)."""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.m3e.accepted_base import verify_accepted_base
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.validation import M3EValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def base():
    return verify_accepted_base(REPO_ROOT)


def test_today_is_a_noop_nothing_new_is_due(base) -> None:
    # 2026-07-15: accepted last open is 2026-07-14; 2026-07-15 is still forming.
    decision = plan_update_window(base, "2026-07-15T09:00:00Z")
    assert decision.is_noop is True
    assert decision.expected_new_buckets == 0
    assert decision.first_missing_open == "2026-07-15T00:00:00Z"
    assert decision.completed_day_exclusive_end == "2026-07-15T00:00:00Z"
    assert decision.window_start is None
    assert decision.window_end is None


def test_same_day_as_last_open_is_a_noop(base) -> None:
    decision = plan_update_window(base, "2026-07-14T12:00:00Z")
    assert decision.is_noop is True


def test_just_before_first_candle_completes_is_a_noop(base) -> None:
    decision = plan_update_window(base, "2026-07-15T23:59:59Z")
    assert decision.is_noop is True


def test_one_completed_day_becomes_due_at_next_midnight(base) -> None:
    decision = plan_update_window(base, "2026-07-16T00:00:01Z")
    assert decision.is_noop is False
    assert decision.expected_new_buckets == 1
    assert decision.window_start == "2026-07-15T00:00:00Z"
    assert decision.window_end == "2026-07-16T00:00:00Z"


def test_multiple_completed_days_are_bound_contiguously(base) -> None:
    decision = plan_update_window(base, "2026-07-20T02:17:00Z")
    assert decision.is_noop is False
    assert decision.expected_new_buckets == 5  # 07-15, 16, 17, 18, 19
    assert decision.window_start == "2026-07-15T00:00:00Z"
    assert decision.window_end == "2026-07-20T00:00:00Z"


def test_a_clock_rewind_before_the_base_hard_stops(base) -> None:
    with pytest.raises(M3EValidationError, match="predates the accepted last open"):
        plan_update_window(base, "2026-07-13T09:00:00Z")


def test_a_naive_non_utc_as_of_is_rejected(base) -> None:
    with pytest.raises((M3EValidationError, ValueError)):
        plan_update_window(base, "2026-07-16T00:00:01")  # no tz → not UTC-aware


def test_the_window_end_never_includes_the_forming_candle(base) -> None:
    # At 2026-07-16T12:00 the 07-16 candle is forming; the window must stop at 07-16.
    decision = plan_update_window(base, "2026-07-16T12:00:00Z")
    assert decision.window_end == "2026-07-16T00:00:00Z"
    assert decision.expected_new_buckets == 1  # only 07-15 is completed
