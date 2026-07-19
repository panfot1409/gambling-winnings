"""Domain model for the signal-only shadow-operations platform.

The shadow platform is what a prospective operator would run *beside* a live desk to observe a
research candidate's behaviour without ever acting on it. It has three non-live modes and no others:

* ``synthetic_demo`` — drive the pipeline with a generated price path (no real data at all);
* ``historical_shadow`` — replay committed historical bars through the pipeline as-of each bar;
* ``paper_simulation`` — the same, accounted as a paper portfolio with a starting cash balance.

None of these connect to a network, place an order, hold a credential, or move money. Any
live/production/real-money mode is rejected *fail-closed* at this boundary
(:func:`require_shadow_mode`) so the prohibition is mechanical, not merely documented. Every value
type here is strict (decode-never-repair), frozen, and hashable, so a shadow run reproduces byte for
byte.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from eth_research.v2.strict import (
    V2ValidationError,
    require_nonempty_str,
    require_slug,
    require_utc_timestamp,
)

SHADOW_SCHEMA_VERSION: int = 1

# The only three modes the platform supports. All are non-live.
SYNTHETIC_DEMO: str = "synthetic_demo"
HISTORICAL_SHADOW: str = "historical_shadow"
PAPER_SIMULATION: str = "paper_simulation"
SHADOW_MODES: frozenset[str] = frozenset({SYNTHETIC_DEMO, HISTORICAL_SHADOW, PAPER_SIMULATION})

# Modes that are named *only* so the platform can refuse them with an honest message. If any of
# these is ever requested, the boundary fails closed — the platform cannot be flipped to live.
FORBIDDEN_LIVE_MODES: frozenset[str] = frozenset(
    {
        "live",
        "production",
        "production_live",
        "real_money",
        "real",
        "exchange",
        "mainnet",
        "prod",
    }
)


class ShadowDomainError(V2ValidationError):
    """A shadow-platform value violated the signal-only domain contract."""


def require_shadow_mode(label: str, value: object) -> str:
    """Return a supported non-live mode, or fail closed on a live/production/unknown mode."""
    text = require_nonempty_str(label, value)
    if text in FORBIDDEN_LIVE_MODES:
        raise ShadowDomainError(
            f"{label}: mode {text!r} is a live/production mode; the shadow platform is signal-only "
            "and never trades, connects, or moves money"
        )
    if text not in SHADOW_MODES:
        raise ShadowDomainError(f"{label} must be one of {sorted(SHADOW_MODES)!r}, got {text!r}")
    return text


@dataclass(frozen=True, slots=True)
class InstrumentId:
    """A traded-instrument identity as a stable lowercase slug (e.g. ``eth_usd``).

    The shadow platform observes signals *about* an instrument; it never resolves the slug to a
    venue, symbol, or contract — there is nothing to connect to.
    """

    symbol: str

    @staticmethod
    def parse(label: str, value: object) -> InstrumentId:
        return InstrumentId(symbol=require_slug(label, value))

    def to_canonical(self) -> str:
        return self.symbol


ETH_USD: InstrumentId = InstrumentId(symbol="eth_usd")


def parse_timestamp(label: str, value: object) -> pd.Timestamp:
    """Coerce a ``pd.Timestamp`` or an ISO-8601 string to a validated UTC timestamp.

    Naive or non-UTC values are rejected (via the reviewed ``require_utc_timestamp``), so a shadow
    timestamp is always exactly UTC whether it arrives as an object or as JSON text.
    """
    if isinstance(value, pd.Timestamp):
        candidate = value
    elif isinstance(value, str):
        try:
            candidate = pd.Timestamp(value)
        except (ValueError, TypeError) as exc:
            raise ShadowDomainError(
                f"{label} is not a valid ISO-8601 timestamp: {value!r}"
            ) from exc
    else:
        raise ShadowDomainError(
            f"{label} must be a timestamp or ISO-8601 string, got {type(value).__name__}"
        )
    return require_utc_timestamp(label, candidate)


def canonical_timestamp(label: str, value: object) -> str:
    """Decode a UTC timestamp and re-emit it as a canonical ISO-8601 string (stable for hashing)."""
    return format_timestamp(parse_timestamp(label, value))


def format_timestamp(ts: pd.Timestamp) -> str:
    """Canonical ISO-8601 rendering of a tz-aware UTC timestamp (``...+00:00``)."""
    if ts.tzinfo is None:
        raise ShadowDomainError("timestamp must be timezone-aware UTC")
    return ts.isoformat()
