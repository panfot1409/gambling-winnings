"""Trading calendars: which timestamps a venue is open, as immutable, hashable evidence.

A :class:`TradingCalendar` is one of three deterministic kinds. ``continuous_24_7`` is always open
and carries no sessions (a crypto venue). ``session_list`` and ``synthetic_weekday`` carry an
explicit, strictly ordered, non-overlapping tuple of :class:`Session` windows (a cash-equity or FX
venue). Every calendar serializes to a canonical mapping and carries a domain-separated
``fingerprint`` so it can be bound into an instrument identity and reconciled exactly across runs.

The module claims no real-world holiday authority: :func:`synthetic_weekday_calendar` fabricates a
plain Monday-Friday calendar from its arguments alone, with no wall-clock read, so identical
arguments always produce an identical fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from eth_research.api.serialization import (
    CanonicalError,
    require_bool,
    require_list,
    require_mapping,
    require_str,
)
from eth_research.portfolio._time import iso_utc, require_utc_timestamp
from eth_research.portfolio.validation import (
    domain_hash,
    exact_keys,
    require_safe_token,
)

__all__ = [
    "CALENDAR_KINDS",
    "Session",
    "TradingCalendar",
    "synthetic_weekday_calendar",
]

#: The exact calendar-kind vocabulary. ``continuous_24_7`` never carries sessions; the other two
#: always do.
CALENDAR_KINDS = ("continuous_24_7", "session_list", "synthetic_weekday")

_SESSION_FIELDS = {"session_id", "date", "open", "close", "early_close", "source"}
_CALENDAR_FIELDS = {"calendar_id", "kind", "sessions", "source"}

# A synthetic weekday is a calendar day whose ``dayofweek`` (Monday=0) is strictly below this bound.
_WEEKEND_START = 5
_EARLY_CLOSE_HOURS = 2


def _require_ts(value: Any, field: str) -> pd.Timestamp:
    """A timezone-aware :class:`Timestamp`, normalized to UTC (rejects naive or non-Timestamp)."""
    if not isinstance(value, pd.Timestamp):
        raise CanonicalError(f"{field}: expected a pandas Timestamp")
    if value.tz is None:
        raise CanonicalError(f"{field}: timestamp must be timezone-aware UTC")
    return value.tz_convert("UTC")


def _require_iso_date(value: Any, field: str) -> str:
    """A canonical ``YYYY-MM-DD`` calendar date string (zero-padded, real calendar date)."""
    text = require_str(value, field)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise CanonicalError(f"{field}: expected an ISO date 'YYYY-MM-DD'") from exc
    if parsed.strftime("%Y-%m-%d") != text:
        raise CanonicalError(f"{field}: expected a canonical ISO date 'YYYY-MM-DD' ({text!r})")
    return text


@dataclass(frozen=True)
class Session:
    """One open-to-close trading window on a fixed calendar date.

    ``open`` and ``close`` are timezone-aware UTC timestamps with ``open < close``; both are
    normalized to UTC on construction so two sessions naming the same instants compare equal
    regardless of the incoming timezone spelling.
    """

    session_id: str
    date: str
    open: pd.Timestamp
    close: pd.Timestamp
    early_close: bool
    source: str

    def __post_init__(self) -> None:
        require_safe_token(self.session_id, "session.session_id")
        _require_iso_date(self.date, "session.date")
        require_safe_token(self.source, "session.source")
        if not isinstance(self.early_close, bool):
            raise CanonicalError("session.early_close: expected a boolean")
        object.__setattr__(self, "open", _require_ts(self.open, "session.open"))
        object.__setattr__(self, "close", _require_ts(self.close, "session.close"))
        if not self.open < self.close:
            raise CanonicalError(
                f"session.open: must be strictly before close "
                f"({iso_utc(self.open)} !< {iso_utc(self.close)})"
            )

    def canonical(self) -> dict[str, Any]:
        """The canonical field mapping (timestamps as canonical UTC ISO-8601 strings)."""
        return {
            "session_id": self.session_id,
            "date": self.date,
            "open": iso_utc(self.open),
            "close": iso_utc(self.close),
            "early_close": self.early_close,
            "source": self.source,
        }

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "session") -> Session:
        """Construct from an untrusted mapping, rejecting unknown or missing keys."""
        mapping = require_mapping(data, field)
        exact_keys(mapping, _SESSION_FIELDS, field)
        return cls(
            session_id=require_str(mapping["session_id"], f"{field}.session_id"),
            date=require_str(mapping["date"], f"{field}.date"),
            open=require_utc_timestamp(mapping["open"], f"{field}.open"),
            close=require_utc_timestamp(mapping["close"], f"{field}.close"),
            early_close=require_bool(mapping["early_close"], f"{field}.early_close"),
            source=require_str(mapping["source"], f"{field}.source"),
        )


@dataclass(frozen=True)
class TradingCalendar:
    """A venue's open/closed schedule as immutable, fingerprinted evidence."""

    calendar_id: str
    kind: str
    sessions: tuple[Session, ...]
    source: str

    def __post_init__(self) -> None:
        require_safe_token(self.calendar_id, "calendar.calendar_id")
        require_safe_token(self.source, "calendar.source")
        if self.kind not in CALENDAR_KINDS:
            raise CanonicalError(
                f"calendar.kind: expected one of {list(CALENDAR_KINDS)}, got {self.kind!r}"
            )
        sessions = tuple(self.sessions)
        object.__setattr__(self, "sessions", sessions)
        for index, session in enumerate(sessions):
            if not isinstance(session, Session):
                raise CanonicalError(f"calendar.sessions[{index}]: expected a Session")
        if self.kind == "continuous_24_7":
            if sessions:
                raise CanonicalError("calendar.sessions: continuous_24_7 must carry no sessions")
        elif not sessions:
            raise CanonicalError(f"calendar.sessions: {self.kind} must carry at least one session")
        self._check_ordering(sessions)

    @staticmethod
    def _check_ordering(sessions: tuple[Session, ...]) -> None:
        seen_ids: set[str] = set()
        for index, session in enumerate(sessions):
            if session.session_id in seen_ids:
                raise CanonicalError(
                    f"calendar.sessions: duplicate session_id {session.session_id!r}"
                )
            seen_ids.add(session.session_id)
            if index == 0:
                continue
            previous = sessions[index - 1]
            if not previous.open < session.open:
                raise CanonicalError(
                    f"calendar.sessions[{index}]: open times must be strictly ascending"
                )
            if not previous.close <= session.open:
                raise CanonicalError(
                    f"calendar.sessions[{index}]: sessions must not overlap "
                    f"({iso_utc(previous.close)} > {iso_utc(session.open)})"
                )

    def is_open(self, ts: pd.Timestamp) -> bool:
        """Whether the venue is open at ``ts`` (always ``True`` for ``continuous_24_7``)."""
        if self.kind == "continuous_24_7":
            return True
        moment = _require_ts(ts, "is_open.ts")
        return any(session.open <= moment < session.close for session in self.sessions)

    def session_containing(self, ts: pd.Timestamp) -> Session | None:
        """The session whose ``[open, close)`` window contains ``ts``, or ``None``."""
        if self.kind == "continuous_24_7":
            return None
        moment = _require_ts(ts, "session_containing.ts")
        for session in self.sessions:
            if session.open <= moment < session.close:
                return session
        return None

    def canonical(self) -> dict[str, Any]:
        """The canonical mapping (sessions as a list of canonical session dicts)."""
        return {
            "calendar_id": self.calendar_id,
            "kind": self.kind,
            "source": self.source,
            "sessions": [session.canonical() for session in self.sessions],
        }

    @property
    def fingerprint(self) -> str:
        """The domain-separated content hash of this calendar (stable across runtimes)."""
        return domain_hash("trading_calendar", self.canonical())

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "trading_calendar") -> TradingCalendar:
        """Construct from an untrusted mapping, rejecting unknown or missing keys."""
        mapping = require_mapping(data, field)
        exact_keys(mapping, _CALENDAR_FIELDS, field)
        raw_sessions = require_list(mapping["sessions"], f"{field}.sessions")
        sessions = tuple(
            Session.from_mapping(item, field=f"{field}.sessions[{index}]")
            for index, item in enumerate(raw_sessions)
        )
        return cls(
            calendar_id=require_str(mapping["calendar_id"], f"{field}.calendar_id"),
            kind=require_str(mapping["kind"], f"{field}.kind"),
            sessions=sessions,
            source=require_str(mapping["source"], f"{field}.source"),
        )


def synthetic_weekday_calendar(
    calendar_id: str,
    start_date: str,
    num_days: int,
    open_hour: int = 13,
    close_hour: int = 21,
    early_close_dates: tuple[str, ...] = (),
) -> TradingCalendar:
    """A deterministic Monday-Friday calendar fabricated from arguments alone (no wall clock).

    One session is emitted per weekday among the ``num_days`` calendar days starting at
    ``start_date`` (inclusive), opening at ``open_hour`` and closing at ``close_hour`` UTC. Any
    weekday whose date appears in ``early_close_dates`` closes ``_EARLY_CLOSE_HOURS`` hours earlier
    and is flagged ``early_close=True``. Identical arguments always yield an identical fingerprint.
    """
    require_safe_token(calendar_id, "synthetic_weekday_calendar.calendar_id")
    _require_iso_date(start_date, "synthetic_weekday_calendar.start_date")
    if isinstance(num_days, bool) or not isinstance(num_days, int) or num_days < 1:
        raise CanonicalError("synthetic_weekday_calendar.num_days: expected a positive integer")
    for hour, name in ((open_hour, "open_hour"), (close_hour, "close_hour")):
        if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
            raise CanonicalError(f"synthetic_weekday_calendar.{name}: expected an hour in 0..23")
    if not open_hour < close_hour:
        raise CanonicalError("synthetic_weekday_calendar: open_hour must be < close_hour")
    early = {
        _require_iso_date(d, "synthetic_weekday_calendar.early_close_dates")
        for d in early_close_dates
    }
    if early and not open_hour < close_hour - _EARLY_CLOSE_HOURS:
        raise CanonicalError(
            "synthetic_weekday_calendar: an early close must still leave open_hour < close"
        )

    start = pd.Timestamp(start_date)
    sessions: list[Session] = []
    for offset in range(num_days):
        day = start + pd.Timedelta(days=offset)
        if day.dayofweek >= _WEEKEND_START:
            continue
        date_str = day.strftime("%Y-%m-%d")
        is_early = date_str in early
        closing_hour = close_hour - _EARLY_CLOSE_HOURS if is_early else close_hour
        midnight = pd.Timestamp(date_str, tz="UTC")
        sessions.append(
            Session(
                session_id=f"{calendar_id}:{date_str}",
                date=date_str,
                open=midnight + pd.Timedelta(hours=open_hour),
                close=midnight + pd.Timedelta(hours=closing_hour),
                early_close=is_early,
                source="synthetic_weekday",
            )
        )
    if not sessions:
        raise CanonicalError(
            "synthetic_weekday_calendar: the requested window contains no weekdays"
        )
    return TradingCalendar(
        calendar_id=calendar_id,
        kind="synthetic_weekday",
        sessions=tuple(sessions),
        source="synthetic_weekday",
    )
