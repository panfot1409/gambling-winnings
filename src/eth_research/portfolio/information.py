"""The causal information set at an execution time: what a decision at ``tau`` is allowed to read.

An :class:`AsOfView` is the immutable, defensively-copied window the engine reads at each execution
timestamp ``tau``. It exposes *only* the inputs a causally-correct decision may use: the active
membership universe known by ``tau``, the completed prior bars of an instrument (those whose
``close_time`` is at or before ``tau``), the current bar's *open* (an execution reference for fills,
never a signal), and a causal FX rate. It never exposes the current bar's high/low/close/volume or
any future bar, FX, membership, or session result — a future fact appended to the panel cannot
change any value this view reports at an earlier ``tau`` (prefix invariance).
"""

from __future__ import annotations

import pandas as pd

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipSchedule
from eth_research.portfolio.panel import MarketPanel

__all__ = ["AsOfView"]


def _require_ts(value: object, field: str) -> pd.Timestamp:
    if not isinstance(value, pd.Timestamp):
        raise CanonicalError(f"{field}: expected a pandas Timestamp")
    if value.tz is None:
        raise CanonicalError(f"{field}: timestamp must be timezone-aware UTC")
    return value.tz_convert("UTC")


class AsOfView:
    """The frozen, causal information set an engine reads at one execution time ``tau``.

    Construct with :meth:`at`. Every accessor is causal: it reads only facts knowable at or before
    ``tau``. Asking for a non-active instrument fails closed with :class:`CanonicalError`.
    """

    __slots__ = ("_active_ids", "_active_universe", "_fx", "_panel", "_tau")

    def __init__(
        self,
        *,
        tau: pd.Timestamp,
        panel: MarketPanel,
        fx: FxEvidence,
        active_universe: tuple[InstrumentId, ...],
    ) -> None:
        """Internal constructor. Prefer :meth:`at`, which derives the active universe causally."""
        self._tau = _require_ts(tau, "as_of_view.tau")
        self._panel = panel
        self._fx = fx
        self._active_universe = active_universe
        self._active_ids = frozenset(instrument.instrument_id for instrument in active_universe)

    @classmethod
    def at(
        cls,
        panel: MarketPanel,
        membership: MembershipSchedule,
        fx: FxEvidence,
        tau: pd.Timestamp,
    ) -> AsOfView:
        """Build the causal view at ``tau`` from a panel, a membership schedule, and FX evidence."""
        if not isinstance(panel, MarketPanel):
            raise CanonicalError("as_of_view.at: expected a MarketPanel")
        if not isinstance(membership, MembershipSchedule):
            raise CanonicalError("as_of_view.at: expected a MembershipSchedule")
        if not isinstance(fx, FxEvidence):
            raise CanonicalError("as_of_view.at: expected an FxEvidence")
        moment = _require_ts(tau, "as_of_view.at.tau")
        return cls(
            tau=moment,
            panel=panel,
            fx=fx,
            active_universe=membership.active_universe(moment),
        )

    @property
    def tau(self) -> pd.Timestamp:
        """The execution timestamp this view is anchored to (tz-aware UTC)."""
        return self._tau

    @property
    def active_universe(self) -> tuple[InstrumentId, ...]:
        """The instruments whose membership is known and effective at ``tau``, sorted by id."""
        return self._active_universe

    def _require_active(self, instrument: InstrumentId, method: str) -> None:
        if not isinstance(instrument, InstrumentId):
            raise CanonicalError(f"as_of_view.{method}: expected an InstrumentId")
        if instrument.instrument_id not in self._active_ids:
            raise CanonicalError(
                f"as_of_view.{method}: {instrument.symbol!r} is not in the active universe at tau"
            )

    def prior_bars(self, instrument: InstrumentId) -> pd.DataFrame:
        """A defensive copy of ``instrument``'s *completed* bars (``close_time <= tau``).

        Only bars that have closed at or before ``tau`` are visible; the current bar (which opens at
        ``tau`` and has not yet closed) and every future bar are excluded, so no future price or the
        current bar's own high/low/close/volume can leak into a decision.
        """
        self._require_active(instrument, "prior_bars")
        frame = self._panel.frame(instrument)
        completed = frame[frame["close_time"] <= self._tau]
        return completed.reset_index(drop=True)

    def current_open(self, instrument: InstrumentId) -> float | None:
        """The open of the bar whose ``open_time == tau`` (fills only), or ``None`` if none opens.

        The open is an execution reference used to price fills at ``tau``; it is never a signal
        input. No other column of the current bar is exposed.
        """
        self._require_active(instrument, "current_open")
        frame = self._panel.frame(instrument)
        at_tau = frame[frame["open_time"] == self._tau]
        if len(at_tau) == 0:
            return None
        return float(at_tau["open"].iloc[0])

    def fx_rate(self, base: str, quote: str) -> float:
        """The causal ``quote``-per-``base`` rate usable at ``tau`` (never a future observation)."""
        return self._fx.rate_as_of(base, quote, self._tau)
