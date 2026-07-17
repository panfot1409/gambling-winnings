"""An immutable, fingerprinted panel of per-instrument bar frames over asynchronous calendars.

A :class:`MarketPanel` maps each :class:`~eth_research.portfolio.identity.InstrumentId` to its own
validated bar frame. Instruments may follow different calendars: their timestamps need not align,
and a missing bar is genuinely absent, never an implied zero. The panel is built through
:func:`build_market_panel`, which validates and canonicalizes every frame, rejects an empty panel
and duplicate instrument identities, and stores private canonical copies. Reads return defensive
copies, and the ``fingerprint`` binds each instrument's bar-frame fingerprint in a fixed,
identity-sorted order, so the panel identity is independent of the order frames were supplied in.
"""

from __future__ import annotations

import pandas as pd

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.bars import bar_frame_fingerprint, validate_bar_frame
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.validation import domain_hash

__all__ = ["MarketPanel", "build_market_panel"]


class MarketPanel:
    """An immutable mapping of instrument identity to a validated, canonical bar frame."""

    __slots__ = ("_frames", "_instruments")

    def __init__(self, instruments: tuple[InstrumentId, ...], frames: dict[str, pd.DataFrame]):
        """Internal constructor. Use :func:`build_market_panel`; ``frames`` is keyed by hash."""
        self._instruments = instruments
        self._frames = frames

    @property
    def instruments(self) -> tuple[InstrumentId, ...]:
        """The panel's instruments, sorted by their ``instrument_id`` content hash."""
        return self._instruments

    def frame(self, instrument: InstrumentId) -> pd.DataFrame:
        """A defensive deep copy of ``instrument``'s canonical bar frame."""
        if not isinstance(instrument, InstrumentId):
            raise CanonicalError("market_panel.frame: expected an InstrumentId")
        key = instrument.instrument_id
        if key not in self._frames:
            raise CanonicalError(f"market_panel: no frame for instrument {instrument.symbol!r}")
        return self._frames[key].copy(deep=True)

    @property
    def fingerprint(self) -> str:
        """A domain-separated hash binding every instrument's bar-frame fingerprint, in order."""
        entries = [
            {
                "instrument_id": instrument.instrument_id,
                "bar_frame_fingerprint": bar_frame_fingerprint(
                    self._frames[instrument.instrument_id], instrument
                ),
            }
            for instrument in self._instruments
        ]
        return domain_hash("market_panel", {"instruments": entries})


def build_market_panel(frames: dict[InstrumentId, pd.DataFrame]) -> MarketPanel:
    """Validate and freeze a mapping of instrument to bar frame into a :class:`MarketPanel`.

    Each frame is validated and canonicalized via
    :func:`~eth_research.portfolio.bars.validate_bar_frame`. An empty panel, a non-mapping input, a
    non-:class:`InstrumentId` key, or two keys sharing an ``instrument_id`` are rejected with
    :class:`CanonicalError`. Stored frames are canonical copies independent of the caller's.
    """
    if not isinstance(frames, dict):
        raise CanonicalError("market_panel: expected a mapping of InstrumentId to DataFrame")
    if not frames:
        raise CanonicalError("market_panel: must contain at least one instrument")
    by_hash: dict[str, pd.DataFrame] = {}
    instruments_by_hash: dict[str, InstrumentId] = {}
    for instrument, frame in frames.items():
        if not isinstance(instrument, InstrumentId):
            raise CanonicalError("market_panel: keys must be InstrumentId instances")
        key = instrument.instrument_id
        if key in by_hash:
            raise CanonicalError(
                f"market_panel: duplicate instrument identity {instrument.symbol!r}"
            )
        by_hash[key] = validate_bar_frame(frame, instrument)
        instruments_by_hash[key] = instrument
    ordered = tuple(instruments_by_hash[key] for key in sorted(by_hash))
    return MarketPanel(ordered, by_hash)
