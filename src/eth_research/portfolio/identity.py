"""Immutable instrument identity for the portfolio simulator.

An :class:`InstrumentId` names *one* tradable spot instrument by its full economic identity — asset
class, traded asset, quote currency, venue, venue-local symbol, price and quantity units, and the
calendar that governs its sessions — never by a bare ticker. Two instruments are the same only when
every field matches; a symbol reused across venues is a *different* instrument. The identity
serializes to canonical JSON and carries a domain-separated ``instrument_id`` hash so it can be
bound into a panel, a target, a fill, and a result and reconciled exactly.

M4B supports spot instruments only. Margin, leverage, futures, options, swaps, perpetuals, and any
other derivative are structurally rejected at construction — they are outside the milestone's
long-only, cash-safe contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_research.api.serialization import CanonicalError, require_str
from eth_research.portfolio.currencies import require_currency_code
from eth_research.portfolio.validation import domain_hash, exact_keys, require_safe_token

__all__ = ["ASSET_CLASSES", "INSTRUMENT_TYPES", "InstrumentId"]

#: The exact asset-class vocabulary. ``crypto_spot`` and ``cash_equity`` trade a non-currency asset
#: against a quote currency; ``fx_spot`` trades one currency against another.
ASSET_CLASSES = ("cash_equity", "crypto_spot", "fx_spot")
#: The exact instrument-type vocabulary. Spot only — every derivative kind is unsupported.
INSTRUMENT_TYPES = ("spot",)

_FIELDS = {
    "asset_class",
    "base_asset",
    "quote_currency",
    "venue",
    "symbol",
    "instrument_type",
    "price_unit",
    "quantity_unit",
    "calendar_id",
}


@dataclass(frozen=True)
class InstrumentId:
    """One tradable spot instrument's full, immutable economic identity."""

    asset_class: str
    base_asset: str
    quote_currency: str
    venue: str
    symbol: str
    instrument_type: str
    price_unit: str
    quantity_unit: str
    calendar_id: str

    def __post_init__(self) -> None:
        if self.asset_class not in ASSET_CLASSES:
            raise CanonicalError(
                f"instrument.asset_class: expected one of {list(ASSET_CLASSES)}, "
                f"got {self.asset_class!r}"
            )
        if self.instrument_type not in INSTRUMENT_TYPES:
            raise CanonicalError(
                "instrument.instrument_type: only spot instruments are supported "
                "(no margin, leverage, futures, options, swaps, or perpetuals); "
                f"got {self.instrument_type!r}"
            )
        require_safe_token(self.venue, "instrument.venue")
        require_safe_token(self.symbol, "instrument.symbol")
        require_safe_token(self.quantity_unit, "instrument.quantity_unit")
        require_safe_token(self.calendar_id, "instrument.calendar_id")
        quote = require_currency_code(self.quote_currency, "instrument.quote_currency")
        price_unit = require_currency_code(self.price_unit, "instrument.price_unit")
        # A spot instrument is priced in its quote currency; keeping the explicit field but
        # binding it removes a whole class of inconsistent identities.
        if price_unit != quote:
            raise CanonicalError(
                "instrument.price_unit: a spot instrument's price is denominated in its quote "
                f"currency ({quote}), not {price_unit}"
            )
        # An FX-spot instrument trades one currency for another: the base asset is itself a
        # currency and must differ from the quote. Other asset classes trade a non-currency asset,
        # validated as a safe token — but it must still differ from the quote currency (an asset
        # cannot be priced in itself).
        if self.asset_class == "fx_spot":
            base = require_currency_code(self.base_asset, "instrument.base_asset")
        else:
            base = require_safe_token(self.base_asset, "instrument.base_asset")
        if base == quote:
            raise CanonicalError(
                f"instrument.base_asset: must differ from the quote currency ({quote})"
            )

    def canonical(self) -> dict[str, str]:
        """The canonical field mapping, in a stable order (canonical JSON sorts keys anyway)."""
        return {
            "asset_class": self.asset_class,
            "base_asset": self.base_asset,
            "quote_currency": self.quote_currency,
            "venue": self.venue,
            "symbol": self.symbol,
            "instrument_type": self.instrument_type,
            "price_unit": self.price_unit,
            "quantity_unit": self.quantity_unit,
            "calendar_id": self.calendar_id,
        }

    @property
    def instrument_id(self) -> str:
        """The domain-separated content hash of this identity (stable across runtimes)."""
        return domain_hash("instrument_id", self.canonical())

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "instrument") -> InstrumentId:
        """Construct from an untrusted mapping, rejecting unknown or missing keys."""
        mapping = data if isinstance(data, dict) else None
        if mapping is None:
            raise CanonicalError(f"{field}: expected an object")
        exact_keys(mapping, _FIELDS, field)
        return cls(
            asset_class=require_str(mapping["asset_class"], f"{field}.asset_class"),
            base_asset=require_str(mapping["base_asset"], f"{field}.base_asset"),
            quote_currency=require_str(mapping["quote_currency"], f"{field}.quote_currency"),
            venue=require_str(mapping["venue"], f"{field}.venue"),
            symbol=require_str(mapping["symbol"], f"{field}.symbol"),
            instrument_type=require_str(mapping["instrument_type"], f"{field}.instrument_type"),
            price_unit=require_str(mapping["price_unit"], f"{field}.price_unit"),
            quantity_unit=require_str(mapping["quantity_unit"], f"{field}.quantity_unit"),
            calendar_id=require_str(mapping["calendar_id"], f"{field}.calendar_id"),
        )
