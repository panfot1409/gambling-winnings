"""Mechanical completed-day cutoff and the no-op decision.

Given the verified accepted base and an **explicit** ``as_of`` UTC instant (never a
wall clock inside the library), M3E derives — with no market data and no judgement
— exactly which new daily candles are *due*:

* ``completed_day_exclusive_end = floor_to_utc_midnight(as_of)`` — the candle
  opening at this instant is still **forming** and is always excluded.
* ``first_missing_open = accepted_last_open + 1 day`` — the first open strictly
  after the accepted cohort.
* the proposed new window is the half-open ``[first_missing_open,
  completed_day_exclusive_end)``.

If ``first_missing_open >= completed_day_exclusive_end`` the window is empty and the
correct outcome is a **NO-OP**: nothing is due, so the facility proposes nothing.
An ``as_of`` whose completed-day boundary falls *before* the accepted cohort's last
open is a clock anomaly and hard-stops rather than silently no-opping.

At 2026-07-15 the accepted last open is 2026-07-14, ``first_missing_open`` is
2026-07-15, and the cutoff is 2026-07-15, so the window is empty → no-op. The
cohort is not due to grow until the 2026-07-15 candle completes at
2026-07-16T00:00:00Z.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from eth_research.m3e.accepted_base import AcceptedProspectiveBase
from eth_research.m3e.validation import (
    M3EValidationError,
    require_utc_timestamp,
)

_DAY = pd.Timedelta(days=1)
_INTERVAL_SECONDS = 86400
# A just-closed daily candle counts as due only after settling this long past its UTC
# close, so a run fired moments after midnight never fetches a candle the venue may still
# be revising. The scheduled cadence (Mondays 02:17 UTC) clears this by 1h17m; a
# workflow_dispatch fired at 00:00:30 is deferred to the next run. Append-only rows are
# never re-checked against the venue, so this floor is the only settling guarantee.
_SETTLE_DELAY = pd.Timedelta(hours=1)


def _z(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_utc_midnight(label: str, value: str) -> pd.Timestamp:
    ts = require_utc_timestamp(label, pd.Timestamp(value))
    if ts != ts.floor("D"):
        raise M3EValidationError(f"{label} must be a UTC midnight, got {ts}")
    return ts


@dataclass(frozen=True)
class UpdateWindowDecision:
    """The mechanical decision: no-op, or a contiguous new completed-day window."""

    is_noop: bool
    reason: str
    as_of_utc: str
    accepted_last_open: str
    first_missing_open: str
    completed_day_exclusive_end: str
    expected_new_buckets: int
    window_start: str | None
    window_end: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_noop": self.is_noop,
            "reason": self.reason,
            "as_of_utc": self.as_of_utc,
            "accepted_last_open": self.accepted_last_open,
            "first_missing_open": self.first_missing_open,
            "completed_day_exclusive_end": self.completed_day_exclusive_end,
            "expected_new_buckets": self.expected_new_buckets,
            "window_start": self.window_start,
            "window_end": self.window_end,
        }


def completed_day_exclusive_end(as_of_utc: pd.Timestamp | str) -> pd.Timestamp:
    """The first UTC midnight at/before ``as_of``; the candle opening here is forming."""
    as_of = require_utc_timestamp(
        "as_of_utc", as_of_utc if isinstance(as_of_utc, pd.Timestamp) else pd.Timestamp(as_of_utc)
    )
    return as_of.floor("D")


def plan_update_window(
    base: AcceptedProspectiveBase, as_of_utc: pd.Timestamp | str
) -> UpdateWindowDecision:
    """Derive the due new completed-day window from the accepted base and ``as_of``.

    Returns a NO-OP decision when no new completed day is due. Raises on a clock
    anomaly (``as_of`` whose completed-day boundary predates the accepted cohort).
    """
    as_of = require_utc_timestamp(
        "as_of_utc", as_of_utc if isinstance(as_of_utc, pd.Timestamp) else pd.Timestamp(as_of_utc)
    )
    last_open = _require_utc_midnight("accepted_last_open", base.last_open)
    end = as_of.floor("D")
    first_missing = last_open + _DAY

    if end < last_open:
        raise M3EValidationError(
            f"as_of completed-day boundary {_z(end)} predates the accepted last open "
            f"{_z(last_open)} (clock anomaly; HARD STOP)"
        )

    # Exclude the most-recently completed day (closing at ``end``) until it has settled
    # for at least ``_SETTLE_DELAY`` past its close; an unsettled boundary drops the
    # effective cutoff to the prior midnight, so a just-after-midnight run NO-OPs rather
    # than fetching a candle the venue may still revise.
    settled_end = end if (as_of - end) >= _SETTLE_DELAY else end - _DAY

    if first_missing >= settled_end:
        return UpdateWindowDecision(
            is_noop=True,
            reason=(
                "no new settled completed day is due: first missing open "
                f"{_z(first_missing)} is not before the settled completed-day cutoff "
                f"{_z(settled_end)}"
            ),
            as_of_utc=_z(as_of),
            accepted_last_open=_z(last_open),
            first_missing_open=_z(first_missing),
            completed_day_exclusive_end=_z(settled_end),
            expected_new_buckets=0,
            window_start=None,
            window_end=None,
        )

    buckets = int((settled_end - first_missing) / _DAY)
    return UpdateWindowDecision(
        is_noop=False,
        reason=f"{buckets} newly-completed daily candle(s) due for proposal",
        as_of_utc=_z(as_of),
        accepted_last_open=_z(last_open),
        first_missing_open=_z(first_missing),
        completed_day_exclusive_end=_z(settled_end),
        expected_new_buckets=buckets,
        window_start=_z(first_missing),
        window_end=_z(settled_end),
    )
