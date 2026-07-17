"""The universe specification: one immutable identity binding every piece of a research universe.

A :class:`UniverseSpec` names, in one canonical object, exactly what a portfolio simulation runs
over: the base accounting currency, the canonical ordered instrument list, the calendar governing
each instrument, the bar-interval contract, the staleness bound, and the content fingerprints of the
membership schedule, the FX evidence, the corporate-action set, and the rebalance schedule. Its
aggregate ``fingerprint`` is order-stable (reordering the inputs yields the same identity) and
domain-separated (changing any one economic identity yields a different fingerprint), so a result
can bind the exact universe it was produced against and a verifier can reconcile it.

The spec is a *binding*, not the evidence itself: it references the membership / FX / corporate-
action / schedule artifacts by their fingerprints so those large objects are identified without
being copied, and it fails closed on an unsupported configuration — an empty universe, a duplicate
economic instrument, or an instrument naming a calendar the spec does not carry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from eth_research.api.serialization import (
    CanonicalError,
    require_int,
    require_list,
    require_mapping,
    require_sha256_hex,
    require_str,
)
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.currencies import require_currency_code
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.validation import domain_hash, exact_keys, require_positive_finite_float

__all__ = ["UNIVERSE_SCHEMA_VERSION", "UniverseSpec"]

UNIVERSE_SCHEMA_VERSION = 1
_PROVENANCE_ALGORITHM_ID = "eth_research.portfolio.domain-sha256.v1"

_FIELDS = {
    "schema_version",
    "provenance_algorithm_id",
    "base_currency",
    "bar_interval_seconds",
    "max_staleness_seconds",
    "instruments",
    "calendars",
    "membership_fingerprint",
    "fx_fingerprint",
    "corporate_action_fingerprint",
    "rebalance_schedule_fingerprint",
}


@dataclass(frozen=True)
class UniverseSpec:
    """An immutable, fingerprinted binding of every identity a simulation runs over."""

    base_currency: str
    instruments: tuple[InstrumentId, ...]
    calendars: Mapping[str, TradingCalendar]
    bar_interval_seconds: int
    max_staleness_seconds: float
    membership_fingerprint: str
    fx_fingerprint: str
    corporate_action_fingerprint: str
    rebalance_schedule_fingerprint: str

    def __post_init__(self) -> None:
        require_currency_code(self.base_currency, "universe.base_currency")
        interval = require_int(self.bar_interval_seconds, "universe.bar_interval_seconds")
        if interval <= 0:
            raise CanonicalError("universe.bar_interval_seconds: must be a positive integer")
        require_positive_finite_float(self.max_staleness_seconds, "universe.max_staleness_seconds")
        for name in (
            "membership_fingerprint",
            "fx_fingerprint",
            "corporate_action_fingerprint",
            "rebalance_schedule_fingerprint",
        ):
            require_sha256_hex(getattr(self, name), f"universe.{name}")
        if not self.instruments:
            raise CanonicalError("universe.instruments: must not be empty")
        if not isinstance(self.calendars, Mapping):
            raise CanonicalError("universe.calendars: expected a mapping")
        seen: set[str] = set()
        ordered = sorted(self.instruments, key=lambda inst: inst.instrument_id)
        for instrument in ordered:
            if not isinstance(instrument, InstrumentId):
                raise CanonicalError("universe.instruments: each must be an InstrumentId")
            key = instrument.instrument_id
            if key in seen:
                raise CanonicalError(
                    f"universe.instruments: duplicate economic instrument {instrument.symbol!r}"
                )
            seen.add(key)
            if instrument.calendar_id not in self.calendars:
                raise CanonicalError(
                    f"universe.instruments: {instrument.symbol!r} names calendar "
                    f"{instrument.calendar_id!r}, which the universe does not carry"
                )
        for calendar_id, calendar in self.calendars.items():
            if not isinstance(calendar, TradingCalendar):
                raise CanonicalError(f"universe.calendars[{calendar_id!r}]: expected a calendar")
            if calendar.calendar_id != calendar_id:
                raise CanonicalError(
                    f"universe.calendars: key {calendar_id!r} does not match calendar id "
                    f"{calendar.calendar_id!r}"
                )
        object.__setattr__(self, "instruments", tuple(ordered))

    @property
    def required_fx_pairs(self) -> tuple[tuple[str, str], ...]:
        """The distinct ``(quote_currency, base_currency)`` pairs the universe must be able to
        convert (every instrument not already quoted in the base currency), sorted."""
        pairs = {
            (instrument.quote_currency, self.base_currency)
            for instrument in self.instruments
            if instrument.quote_currency != self.base_currency
        }
        return tuple(sorted(pairs))

    def canonical(self) -> dict[str, Any]:
        return {
            "schema_version": UNIVERSE_SCHEMA_VERSION,
            "provenance_algorithm_id": _PROVENANCE_ALGORITHM_ID,
            "base_currency": self.base_currency,
            "bar_interval_seconds": self.bar_interval_seconds,
            "max_staleness_seconds": self.max_staleness_seconds,
            "instruments": [instrument.canonical() for instrument in self.instruments],
            "calendars": {
                calendar_id: self.calendars[calendar_id].fingerprint
                for calendar_id in sorted(self.calendars)
            },
            "membership_fingerprint": self.membership_fingerprint,
            "fx_fingerprint": self.fx_fingerprint,
            "corporate_action_fingerprint": self.corporate_action_fingerprint,
            "rebalance_schedule_fingerprint": self.rebalance_schedule_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        """The order-stable, domain-separated identity of the whole universe."""
        return domain_hash("universe_spec", self.canonical())

    @classmethod
    def from_mapping(
        cls, data: Any, calendars: Mapping[str, TradingCalendar], *, field: str = "universe"
    ) -> UniverseSpec:
        """Rebuild from a canonical mapping plus the concrete calendars (the mapping carries only
        calendar fingerprints, so the caller supplies the calendar objects to bind against)."""
        mapping = require_mapping(data, field)
        exact_keys(mapping, _FIELDS, field)
        if (
            require_int(mapping["schema_version"], f"{field}.schema_version")
            != UNIVERSE_SCHEMA_VERSION
        ):
            raise CanonicalError(f"{field}.schema_version: unsupported")
        instruments = tuple(
            InstrumentId.from_mapping(item, field=f"{field}.instruments[{index}]")
            for index, item in enumerate(
                require_list(mapping["instruments"], f"{field}.instruments")
            )
        )
        spec = cls(
            base_currency=require_str(mapping["base_currency"], f"{field}.base_currency"),
            instruments=instruments,
            calendars=calendars,
            bar_interval_seconds=require_int(
                mapping["bar_interval_seconds"], f"{field}.bar_interval_seconds"
            ),
            max_staleness_seconds=require_positive_finite_float(
                mapping["max_staleness_seconds"], f"{field}.max_staleness_seconds"
            ),
            membership_fingerprint=require_str(
                mapping["membership_fingerprint"], f"{field}.membership_fingerprint"
            ),
            fx_fingerprint=require_str(mapping["fx_fingerprint"], f"{field}.fx_fingerprint"),
            corporate_action_fingerprint=require_str(
                mapping["corporate_action_fingerprint"], f"{field}.corporate_action_fingerprint"
            ),
            rebalance_schedule_fingerprint=require_str(
                mapping["rebalance_schedule_fingerprint"],
                f"{field}.rebalance_schedule_fingerprint",
            ),
        )
        committed = require_mapping(mapping["calendars"], f"{field}.calendars")
        if {cid: cal.fingerprint for cid, cal in spec.calendars.items()} != committed:
            raise CanonicalError(f"{field}.calendars: fingerprints do not match supplied calendars")
        return spec
