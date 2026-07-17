"""Universe membership and survivorship: which instruments are tradable, and when.

A :class:`MembershipInterval` is one causally-stamped window during which a single
:class:`~eth_research.portfolio.identity.InstrumentId` belongs to the tradable universe — a listing,
a constituent addition or removal, a delisting, or a data-availability boundary. Each interval
carries a ``knowledge_time`` (when the membership fact became usable at decision time) separate from
its ``effective_start``/``effective_end`` (the half-open ``[start, end)`` window over which the
instrument is actually a member), so a backtest can only ever *see* a membership change once its
knowledge_time has passed. A :class:`MembershipSchedule` is the immutable, fingerprinted collection
of those intervals with per-instrument non-overlap enforced.

Modeling membership explicitly *mitigates but does not eliminate* survivorship bias: it only removes
the bias that would come from treating a delisted or not-yet-listed instrument as tradable. It
cannot correct a caller-supplied dataset that silently omits the instruments that failed — if the
evidence never mentions a delisted name, no schedule can resurrect it. Survivorship-free results
still require survivorship-free inputs; this module makes the membership assumption auditable, not
automatically correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from eth_research.api.serialization import (
    CanonicalError,
    require_list,
    require_mapping,
    require_str,
)
from eth_research.portfolio._time import iso_utc, require_utc_timestamp
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.validation import domain_hash, exact_keys, require_safe_token

__all__ = ["MEMBERSHIP_REASONS", "MembershipInterval", "MembershipSchedule"]

#: The exact vocabulary of reasons a membership window opens or closes.
MEMBERSHIP_REASONS = (
    "listing",
    "constituent_addition",
    "constituent_removal",
    "delisting",
    "data_availability_boundary",
)

_INTERVAL_FIELDS = {
    "instrument",
    "effective_start",
    "effective_end",
    "knowledge_time",
    "reason",
    "source",
}


def _require_ts(value: Any, field: str) -> pd.Timestamp:
    """A timezone-aware :class:`Timestamp`, normalized to UTC (rejects naive or non-Timestamp)."""
    if not isinstance(value, pd.Timestamp):
        raise CanonicalError(f"{field}: expected a pandas Timestamp")
    if value.tz is None:
        raise CanonicalError(f"{field}: timestamp must be timezone-aware UTC")
    return value.tz_convert("UTC")


@dataclass(frozen=True)
class MembershipInterval:
    """One causally-stamped ``[effective_start, effective_end)`` window for an instrument.

    ``effective_end`` is ``None`` for an open-ended membership. ``knowledge_time`` is
    when the fact became usable and must not be *after* ``effective_start``, so a decision at time
    ``tau`` can only rely on a membership window it already knew about.
    """

    instrument: InstrumentId
    effective_start: pd.Timestamp
    effective_end: pd.Timestamp | None
    knowledge_time: pd.Timestamp
    reason: str
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, InstrumentId):
            raise CanonicalError("membership_interval.instrument: expected an InstrumentId")
        if self.reason not in MEMBERSHIP_REASONS:
            raise CanonicalError(
                f"membership_interval.reason: expected one of {list(MEMBERSHIP_REASONS)}, "
                f"got {self.reason!r}"
            )
        require_safe_token(self.source, "membership_interval.source")
        start = _require_ts(self.effective_start, "membership_interval.effective_start")
        knowledge = _require_ts(self.knowledge_time, "membership_interval.knowledge_time")
        object.__setattr__(self, "effective_start", start)
        object.__setattr__(self, "knowledge_time", knowledge)
        if self.effective_end is not None:
            end = _require_ts(self.effective_end, "membership_interval.effective_end")
            object.__setattr__(self, "effective_end", end)
            if not start < end:
                raise CanonicalError(
                    "membership_interval.effective_start: must be strictly before effective_end "
                    f"({iso_utc(start)} !< {iso_utc(end)})"
                )
        if not knowledge <= start:
            raise CanonicalError(
                "membership_interval.knowledge_time: must not be after effective_start "
                f"({iso_utc(knowledge)} > {iso_utc(start)})"
            )

    def contains(self, tau: pd.Timestamp) -> bool:
        """Whether ``tau`` falls in this window and the window was known by ``tau`` (causal)."""
        moment = _require_ts(tau, "membership_interval.contains.tau")
        if not (self.knowledge_time <= moment and self.effective_start <= moment):
            return False
        return self.effective_end is None or moment < self.effective_end

    def canonical(self) -> dict[str, Any]:
        """The canonical field mapping (timestamps as ISO-8601 UTC; open end serialized as null)."""
        end = self.effective_end
        return {
            "instrument": self.instrument.canonical(),
            "effective_start": iso_utc(self.effective_start),
            "effective_end": None if end is None else iso_utc(end),
            "knowledge_time": iso_utc(self.knowledge_time),
            "reason": self.reason,
            "source": self.source,
        }

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "membership_interval") -> MembershipInterval:
        """Construct from an untrusted mapping, rejecting unknown or missing keys."""
        mapping = require_mapping(data, field)
        exact_keys(mapping, _INTERVAL_FIELDS, field)
        raw_end = mapping["effective_end"]
        effective_end = (
            None if raw_end is None else require_utc_timestamp(raw_end, f"{field}.effective_end")
        )
        return cls(
            instrument=InstrumentId.from_mapping(
                mapping["instrument"], field=f"{field}.instrument"
            ),
            effective_start=require_utc_timestamp(
                mapping["effective_start"], f"{field}.effective_start"
            ),
            effective_end=effective_end,
            knowledge_time=require_utc_timestamp(
                mapping["knowledge_time"], f"{field}.knowledge_time"
            ),
            reason=require_str(mapping["reason"], f"{field}.reason"),
            source=require_str(mapping["source"], f"{field}.source"),
        )


@dataclass(frozen=True)
class MembershipSchedule:
    """An immutable, canonically ordered set of intervals with per-instrument non-overlap.

    Intervals are sorted by ``(instrument_id, effective_start)`` on construction, so the schedule's
    :attr:`fingerprint` reflects its contents and never the caller's input order. Two intervals for
    the *same* instrument may not overlap in effective time (an open-ended interval overlaps any
    later window for that instrument); intervals for *different* instruments are independent.
    """

    intervals: tuple[MembershipInterval, ...]

    def __post_init__(self) -> None:
        intervals = tuple(self.intervals)
        for index, interval in enumerate(intervals):
            if not isinstance(interval, MembershipInterval):
                raise CanonicalError(
                    f"membership_schedule.intervals[{index}]: expected a MembershipInterval"
                )
        ordered = sorted(
            intervals, key=lambda iv: (iv.instrument.instrument_id, iso_utc(iv.effective_start))
        )
        self._check_non_overlapping(ordered)
        object.__setattr__(self, "intervals", tuple(ordered))

    @staticmethod
    def _check_non_overlapping(ordered: list[MembershipInterval]) -> None:
        for index in range(1, len(ordered)):
            previous = ordered[index - 1]
            current = ordered[index]
            if previous.instrument.instrument_id != current.instrument.instrument_id:
                continue
            if previous.effective_end is None or previous.effective_end > current.effective_start:
                raise CanonicalError(
                    "membership_schedule: overlapping membership windows for instrument "
                    f"{current.instrument.symbol!r}"
                )

    def active_at(self, instrument: InstrumentId, tau: pd.Timestamp) -> bool:
        """Whether ``instrument`` is a known, effective member at ``tau``.

        True iff some interval for ``instrument`` has ``knowledge_time <= tau`` and
        ``effective_start <= tau`` and (``effective_end`` is open or ``tau < effective_end``).
        """
        if not isinstance(instrument, InstrumentId):
            raise CanonicalError("membership_schedule.active_at: expected an InstrumentId")
        moment = _require_ts(tau, "membership_schedule.active_at.tau")
        key = instrument.instrument_id
        return any(
            interval.contains(moment)
            for interval in self.intervals
            if interval.instrument.instrument_id == key
        )

    def active_universe(self, tau: pd.Timestamp) -> tuple[InstrumentId, ...]:
        """Every instrument active at ``tau``, de-duplicated and sorted by ``instrument_id``."""
        moment = _require_ts(tau, "membership_schedule.active_universe.tau")
        active: dict[str, InstrumentId] = {}
        for interval in self.intervals:
            if interval.contains(moment):
                active[interval.instrument.instrument_id] = interval.instrument
        return tuple(sorted(active.values(), key=lambda inst: inst.instrument_id))

    def canonical(self) -> list[dict[str, Any]]:
        """The canonical list of interval mappings, in the schedule's canonical order."""
        return [interval.canonical() for interval in self.intervals]

    @property
    def fingerprint(self) -> str:
        """The domain-separated content hash of this schedule (stable across runtimes)."""
        return domain_hash("membership_schedule", self.canonical())

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "membership_schedule") -> MembershipSchedule:
        """Construct from an untrusted list of interval mappings, rejecting unknown keys."""
        rows = require_list(data, field)
        intervals = tuple(
            MembershipInterval.from_mapping(row, field=f"{field}[{index}]")
            for index, row in enumerate(rows)
        )
        return cls(intervals=intervals)
