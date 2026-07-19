"""The market-data envelope: a strict, as-of-gated single bar.

Every price observation the shadow platform consumes is wrapped in a :class:`MarketDataEnvelope`
carrying the bar, the instrument, a source label, and a monotonic sequence number. The envelope is
*decoded, never trusted*: OHLCV consistency (``low <= open,close <= high``, non-negative volume,
finite prices) is enforced on construction, and the bar can only be revealed under an
:class:`~eth_research.shadow.clock.AsOfClock` that has reached its close time — so a future bar can
never be read as if it were already known.

Bars carry no venue, symbol mapping, or connection detail: there is nothing here to fetch. A
historical-shadow run replays committed bars; a synthetic-demo run builds them from a seed.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.shadow.clock import AsOfClock
from eth_research.shadow.domain import (
    InstrumentId,
    ShadowDomainError,
    canonical_timestamp,
)
from eth_research.v2.strict import (
    require_exact_keys,
    require_mapping,
    require_nonnegative_int,
    require_nonnegative_real,
    require_positive_real,
    require_slug,
)


class MarketDataError(ShadowDomainError):
    """A market-data bar or envelope failed its strict consistency contract."""


_BAR_KEYS = frozenset({"open", "high", "low", "close", "volume"})
_ENVELOPE_KEYS = frozenset({"instrument", "close_time", "source", "sequence", "bar"})


@dataclass(frozen=True, slots=True)
class MarketBar:
    """A single OHLCV bar with enforced price/volume consistency (prices strictly positive)."""

    open: float
    high: float
    low: float
    close: float
    volume: float

    @staticmethod
    def parse(label: str, value: object) -> MarketBar:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _BAR_KEYS)
        o = require_positive_real(f"{label}.open", obj["open"])
        h = require_positive_real(f"{label}.high", obj["high"])
        low = require_positive_real(f"{label}.low", obj["low"])
        c = require_positive_real(f"{label}.close", obj["close"])
        v = require_nonnegative_real(f"{label}.volume", obj["volume"])
        if low > o or low > c or h < o or h < c or h < low:
            raise MarketDataError(
                f"{label}: OHLC inconsistent (need low <= open,close <= high), "
                f"got o={o} h={h} low={low} c={c}"
            )
        return MarketBar(open=o, high=h, low=low, close=c, volume=v)

    def to_canonical(self) -> dict[str, object]:
        return {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass(frozen=True, slots=True)
class MarketDataEnvelope:
    """A bar plus its instrument, close time, source, and sequence — the runner's input unit."""

    instrument: InstrumentId
    close_time: str
    source: str
    sequence: int
    bar: MarketBar

    @staticmethod
    def parse(label: str, value: object) -> MarketDataEnvelope:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _ENVELOPE_KEYS)
        return MarketDataEnvelope(
            instrument=InstrumentId.parse(f"{label}.instrument", obj["instrument"]),
            close_time=canonical_timestamp(f"{label}.close_time", obj["close_time"]),
            source=require_slug(f"{label}.source", obj["source"]),
            sequence=require_nonnegative_int(f"{label}.sequence", obj["sequence"]),
            bar=MarketBar.parse(f"{label}.bar", obj["bar"]),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "instrument": self.instrument.to_canonical(),
            "close_time": self.close_time,
            "source": self.source,
            "sequence": self.sequence,
            "bar": self.bar.to_canonical(),
        }

    def reveal_under(self, clock: AsOfClock) -> MarketBar:
        """Return the bar only if the clock has reached its close time (else look-ahead error)."""
        clock.require_visible("close_time", self.close_time)
        return self.bar
