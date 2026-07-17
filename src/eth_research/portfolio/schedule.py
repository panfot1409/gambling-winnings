"""The rebalance schedule: the explicit, deterministic times at which targets are re-solved.

A :class:`RebalanceSchedule` is a strictly-ascending tuple of tz-aware UTC timestamps — the
execution events at which the simulator computes a fresh target and runs the shared-cash solve.
Schedules are fixed evidence, never a live clock: there is no wall-clock read, no daemon, and no
cron. A schedule may be given explicitly or generated deterministically from a trading calendar's
session opens, so a run's rebalance cadence is reproducible and bound into its result fingerprint.

M4B's honest contract is that a rebalance executes only at a common timestamp where every instrument
whose target would change is tradable; the engine enforces that at run time and fails closed on a
missing common event rather than improvising a partial-universe rebalance.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from eth_research.api.serialization import CanonicalError, require_list
from eth_research.portfolio._time import iso_utc, require_utc_timestamp
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.validation import domain_hash

__all__ = ["RebalanceSchedule", "schedule_from_calendar_opens"]


def _require_ts(value: object, field: str) -> pd.Timestamp:
    if not isinstance(value, pd.Timestamp):
        raise CanonicalError(f"{field}: expected a pandas Timestamp")
    if value.tz is None:
        raise CanonicalError(f"{field}: timestamp must be timezone-aware UTC")
    return value.tz_convert("UTC")


@dataclass(frozen=True)
class RebalanceSchedule:
    """An immutable, strictly-ascending set of UTC rebalance-execution timestamps."""

    timestamps: tuple[pd.Timestamp, ...]

    def __post_init__(self) -> None:
        normalized = tuple(
            _require_ts(ts, f"rebalance_schedule.timestamps[{i}]")
            for i, ts in enumerate(self.timestamps)
        )
        if not normalized:
            raise CanonicalError("rebalance_schedule: must contain at least one rebalance event")
        for index in range(1, len(normalized)):
            if not normalized[index - 1] < normalized[index]:
                raise CanonicalError(
                    f"rebalance_schedule: timestamps must be strictly ascending (index {index})"
                )
        object.__setattr__(self, "timestamps", normalized)

    def events(self) -> tuple[pd.Timestamp, ...]:
        return self.timestamps

    def canonical(self) -> list[str]:
        return [iso_utc(ts) for ts in self.timestamps]

    @property
    def fingerprint(self) -> str:
        return domain_hash("rebalance_schedule", self.canonical())

    @classmethod
    def from_mapping(cls, data: object, *, field: str = "rebalance_schedule") -> RebalanceSchedule:
        rows = require_list(data, field)
        timestamps = tuple(
            require_utc_timestamp(row, f"{field}[{index}]") for index, row in enumerate(rows)
        )
        return cls(timestamps=timestamps)


def schedule_from_calendar_opens(calendar: TradingCalendar, *, every: int = 1) -> RebalanceSchedule:
    """Rebalance at every ``every``-th session open of a session-bearing ``calendar``.

    Deterministic and offline: the timestamps are the calendar's own session opens, taken every
    ``every`` sessions (``every=1`` rebalances each session). Raises if the calendar carries no
    sessions (a continuous 24/7 calendar has no natural rebalance boundary — supply an explicit
    schedule instead).
    """
    if every < 1:
        raise CanonicalError("schedule_from_calendar_opens: 'every' must be a positive integer")
    if not calendar.sessions:
        raise CanonicalError(
            "schedule_from_calendar_opens: calendar carries no sessions; supply an explicit "
            "RebalanceSchedule for a continuous calendar"
        )
    opens = tuple(session.open for session in calendar.sessions[::every])
    return RebalanceSchedule(timestamps=opens)
