"""The as-of clock: the shadow platform's causality guard.

A shadow run processes observations in time order. The as-of clock records "the latest instant the
operator is allowed to know about" and enforces two rules that make look-ahead mechanically
impossible:

* it only ever moves forward (``advance_to`` rejects a backwards step), so the run cannot rewind and
  re-read the future as the past;
* nothing timestamped *after* the current as-of instant may be observed (:meth:`require_visible`),
  so a bar cannot be consumed before its close is known.

The clock holds no wall-clock time of its own — it is advanced explicitly by the runner from the
data it is replaying — so a run is fully deterministic and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from eth_research.shadow.domain import ShadowDomainError, parse_timestamp


class ShadowClockError(ShadowDomainError):
    """An as-of clock rule was violated (backwards step or a look-ahead read)."""


@dataclass(slots=True)
class AsOfClock:
    """A monotonic, explicitly-advanced as-of clock (mutable: it is the run's moving frontier)."""

    _current: pd.Timestamp | None

    @staticmethod
    def unstarted() -> AsOfClock:
        """A clock that has not yet been advanced to any instant."""
        return AsOfClock(_current=None)

    @staticmethod
    def at(value: object) -> AsOfClock:
        """A clock already positioned at ``value`` (decoded strictly)."""
        return AsOfClock(_current=parse_timestamp("as_of", value))

    @property
    def is_started(self) -> bool:
        return self._current is not None

    @property
    def current(self) -> pd.Timestamp:
        if self._current is None:
            raise ShadowClockError("as-of clock has not been started")
        return self._current

    def advance_to(self, value: object) -> pd.Timestamp:
        """Move the frontier forward to ``value``; reject any backwards move (look-ahead guard)."""
        ts = parse_timestamp("as_of", value)
        if self._current is not None and ts < self._current:
            raise ShadowClockError(
                f"as-of clock cannot move backwards: {ts.isoformat()} < {self._current.isoformat()}"
            )
        self._current = ts
        return ts

    def require_visible(self, label: str, value: object) -> pd.Timestamp:
        """A timestamp is visible only if it is at or before the current as-of frontier."""
        ts = parse_timestamp(label, value)
        if ts > self.current:
            raise ShadowClockError(
                f"{label} {ts.isoformat()} is after the as-of frontier "
                f"{self.current.isoformat()} (look-ahead forbidden)"
            )
        return ts
