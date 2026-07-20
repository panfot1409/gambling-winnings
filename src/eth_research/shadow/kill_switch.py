"""The latching kill switch: once tripped, the shadow book is frozen until an explicit reset.

A latching kill switch is the platform's fail-safe. When a risk breach (or any operator-defined
condition) trips it, it *latches*: every subsequent intent is blocked, and it stays blocked even if
the triggering condition clears on its own. Only an explicit :meth:`reset` with a stated reason
re-arms it. The first trip reason is preserved (a later re-trip does not overwrite the story of what
went wrong first), and a trip/reset count is kept for the audit journal.

The switch holds only its own latch state — no clock, no I/O — so a run's safety behaviour is
deterministic and reconstructible from the event journal.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.shadow.domain import ShadowDomainError
from eth_research.v2.strict import require_nonempty_str


class KillSwitchTripped(ShadowDomainError):
    """An intent was attempted while the latching kill switch was tripped."""


@dataclass(slots=True)
class LatchingKillSwitch:
    """A fail-safe latch: trips on demand, blocks until an explicit reset (mutable by design)."""

    _tripped: bool
    _reason: str | None
    _trip_count: int
    _reset_count: int

    @staticmethod
    def armed() -> LatchingKillSwitch:
        """A fresh, clear (armed) kill switch."""
        return LatchingKillSwitch(_tripped=False, _reason=None, _trip_count=0, _reset_count=0)

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def trip_count(self) -> int:
        return self._trip_count

    @property
    def reset_count(self) -> int:
        return self._reset_count

    def trip(self, reason: str) -> None:
        """Latch the switch. The first reason is kept; a re-trip only increments the count."""
        text = require_nonempty_str("reason", reason)
        if not self._tripped:
            self._tripped = True
            self._reason = text
        self._trip_count += 1

    def require_clear(self) -> None:
        """Raise :class:`KillSwitchTripped` if the switch is latched (used to gate every intent)."""
        if self._tripped:
            raise KillSwitchTripped(f"kill switch is tripped: {self._reason}")

    def reset(self, *, reason: str) -> None:
        """Explicitly re-arm the switch (requires a stated reason; records the reset)."""
        require_nonempty_str("reason", reason)
        self._tripped = False
        self._reason = None
        self._reset_count += 1
