"""The first-gate V2C execution firewall (section 14): V2C cannot evaluate a strategy.

V2C is a candidate-free, data-only milestone. Nothing it runs may compute a trading candidate's
performance. This module is the boundary that makes that structural rather than aspirational:

* The **only** operational target it will resolve is ``cash_control`` -- not a strategy, but a
  degenerate "hold 100% cash" instruction that always requests zero risky exposure, zero notional,
  zero fills, and zero turnover. :func:`resolve_operational_target` is a strict allowlist; every
  other name (including the five legacy candidate ids) is refused.
* :func:`assert_no_candidate_reference` is a fail-closed structural screen for any object that
  enters the V2C operational layer. It refuses callables (a strategy or signal function),
  modules (a candidate/engine module), objects carrying candidate/strategy markers
  (``candidate_id``, ``generate_signals``, ...), and the known legacy candidate id strings.
* :func:`guard_request_kind` refuses the thirteen forbidden request kinds by name
  (:data:`FORBIDDEN_REQUEST_KINDS`) and admits only ``cash_control_operation``.

Crucially, this module imports **no** candidate, strategy, evaluator, or backtest-engine module.
It recognizes the legacy candidate ids as opaque literal strings
(:data:`KNOWN_LEGACY_CANDIDATE_IDS`), so it can refuse them without importing -- and thereby being
able to run -- the code that produced them. ``tests/test_v2c_firewall.py`` proves this by importing
the firewall in a fresh interpreter and asserting the candidate/engine modules never load, and by
monkeypatching every candidate and engine entry point and proving the cash-control path reaches
none of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import NoReturn

import pandas as pd

from eth_research.v2.strict import (
    V2ValidationError,
    require_nonempty_str,
    require_utc_timestamp,
)

#: The one operational target V2C may resolve. It is not a strategy.
CASH_CONTROL_TARGET_ID: str = "cash_control"

#: The legacy V2A + V2B candidate ids, recorded here as **opaque literal strings** so the firewall
#: can refuse them without importing (and thereby being able to execute) any candidate module.
#: ``tests/test_v2c_firewall.py`` cross-checks this set against the real candidate modules so it
#: cannot silently drift out of date.
KNOWN_LEGACY_CANDIDATE_IDS: frozenset[str] = frozenset(
    {
        # V2A (ETH-only families)
        "meanrev_zscore_accumulation",
        "trend_regime_single_horizon",
        "vol_scaled_hold_drawdown_guard",
        # V2B (cross-asset families)
        "cross_asset_btc_confirmed_eth_trend",
        "cross_asset_eth_btc_relative_strength_rotation",
    }
)

#: The thirteen forbidden request kinds. Any of these, offered to the V2C operational layer, is a
#: strategy-evaluation attempt and is refused fail-closed.
FORBIDDEN_REQUEST_KINDS: frozenset[str] = frozenset(
    {
        "candidate_id",
        "candidate_fingerprint",
        "strategy_callable",
        "signal_callable",
        "candidate_module",
        "research_protocol",
        "financial_data_endpoint",
        "nomination_rule",
        "return_metric",
        "equity_metric",
        "benchmark",
        "optimization_request",
        "market_performance_report",
    }
)

#: The only request kind the operational layer admits.
ALLOWED_REQUEST_KINDS: frozenset[str] = frozenset({"cash_control_operation"})

#: Attribute names that mark an object as a candidate/strategy/research artifact. Their presence
#: makes an object inadmissible to the candidate-free operational layer. These are specific to the
#: research/candidate domain (not generic method names) to avoid refusing innocuous payloads.
_CANDIDATE_ATTRIBUTE_MARKERS: frozenset[str] = frozenset(
    {
        "candidate_id",
        "candidate_fingerprint",
        "generate_signals",
        "signal_at",
        "nomination_rule",
        "benchmark_id",
        "equity_curve",
        "evaluate_candidate",
    }
)

_TARGET_SENTINEL: object = object()


class V2CFirewallError(V2ValidationError):
    """A candidate/strategy reference reached the V2C firewall, or a non-cash target was requested.

    Subclasses the shared strict validation error so a single ``(ValueError, TypeError)`` catch
    covers every strict rejection across V2 and V2C.
    """


def _canonical_utc(label: str, value: object) -> str:
    """Decode a ``pd.Timestamp`` or ISO-8601 string to a canonical UTC ISO-8601 string.

    Naive or non-UTC values are rejected via the reviewed ``require_utc_timestamp``, so a
    cash-control instant is always exactly UTC whether it arrives as an object or as JSON text.
    """
    if isinstance(value, pd.Timestamp):
        candidate: object = value
    elif isinstance(value, str):
        try:
            candidate = pd.Timestamp(value)
        except (ValueError, TypeError) as exc:
            raise V2CFirewallError(f"{label} is not a valid ISO-8601 timestamp: {value!r}") from exc
    else:
        raise V2CFirewallError(
            f"{label} must be a timestamp or ISO-8601 string, got {type(value).__name__}"
        )
    try:
        return require_utc_timestamp(label, candidate).isoformat()
    except V2ValidationError as exc:
        raise V2CFirewallError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CashControlIntent:
    """A single cash-control instruction: exactly zero risky exposure, at an as-of instant.

    Every field is validated to be exactly zero on construction, so a ``CashControlIntent`` can
    never carry exposure. It names no candidate, computes no return, and references no market
    performance.
    """

    as_of: str
    risky_target_weight: float
    requested_notional: float
    requested_fills: int
    requested_turnover: float

    def __post_init__(self) -> None:
        # bool is an int subclass; refuse it explicitly so ``True`` cannot masquerade as a count.
        if isinstance(self.requested_fills, bool) or not isinstance(self.requested_fills, int):
            raise V2CFirewallError("cash_control requested_fills must be a plain int (0)")
        if (
            self.risky_target_weight != 0.0
            or self.requested_notional != 0.0
            or self.requested_turnover != 0.0
            or self.requested_fills != 0
        ):
            raise V2CFirewallError(
                "cash_control intent must request exactly zero exposure, notional, fills, and "
                "turnover"
            )

    @staticmethod
    def zero(as_of: object) -> CashControlIntent:
        """Build the canonical all-zero cash-control intent for ``as_of`` (a UTC timestamp)."""
        return CashControlIntent(
            as_of=_canonical_utc("cash_control.as_of", as_of),
            risky_target_weight=0.0,
            requested_notional=0.0,
            requested_fills=0,
            requested_turnover=0.0,
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "risky_target_weight": self.risky_target_weight,
            "requested_notional": self.requested_notional,
            "requested_fills": self.requested_fills,
            "requested_turnover": self.requested_turnover,
        }


class CashControl:
    """The only allowed V2C operational target: hold 100% cash, request zero risky exposure.

    ``CashControl`` is **not** a strategy. It reads no market data to make a decision, references no
    candidate, and every intent it emits is exactly zero exposure/notional/fills/turnover. Obtain
    one only through :func:`resolve_operational_target`; the constructor is guarded by a private
    module sentinel so an operational target cannot be fabricated outside the firewall's allowlist.
    """

    __slots__ = ()

    #: Stable identifier, equal to :data:`CASH_CONTROL_TARGET_ID`.
    target_id: str = CASH_CONTROL_TARGET_ID

    def __init__(self, *, _token: object) -> None:
        if _token is not _TARGET_SENTINEL:
            raise V2CFirewallError(
                "CashControl cannot be constructed directly; "
                "use resolve_operational_target('cash_control')"
            )

    def intent(self, *, as_of: object) -> CashControlIntent:
        """Emit the zero-exposure cash-control intent valid as-of ``as_of``."""
        return CashControlIntent.zero(as_of)


def assert_no_candidate_reference(label: str, value: object) -> None:
    """Refuse any object that is (or points at) a candidate/strategy/research artifact.

    Fail-closed: a callable (a strategy or signal function), a module (a candidate/engine module),
    an object carrying a candidate/strategy marker attribute, or a known legacy candidate id string
    all raise :class:`V2CFirewallError`. Plain data (scalars, timestamps, non-candidate strings,
    containers of the same) passes.
    """
    if isinstance(value, ModuleType):
        raise V2CFirewallError(f"{label} refused: a module cannot enter the candidate-free layer")
    if callable(value):
        raise V2CFirewallError(
            f"{label} refused: a callable (possible strategy/signal function) is not admissible"
        )
    if isinstance(value, str) and value in KNOWN_LEGACY_CANDIDATE_IDS:
        raise V2CFirewallError(f"{label} refused: {value!r} is a legacy candidate id")
    present = sorted(m for m in _CANDIDATE_ATTRIBUTE_MARKERS if hasattr(value, m))
    if present:
        raise V2CFirewallError(
            f"{label} refused: object carries candidate/strategy markers {present!r}"
        )


def _refuse_request_kind(kind: str) -> NoReturn:
    if kind in FORBIDDEN_REQUEST_KINDS:
        raise V2CFirewallError(
            f"request kind {kind!r} is a strategy-evaluation request and is forbidden in V2C"
        )
    raise V2CFirewallError(
        f"request kind {kind!r} is not an allowed V2C operation "
        f"(only {sorted(ALLOWED_REQUEST_KINDS)!r})"
    )


def guard_request_kind(kind: object) -> str:
    """Admit only ``cash_control_operation``; refuse the thirteen forbidden kinds and anything else.

    Returns the validated kind on success so callers can use it as a checked token.
    """
    try:
        text = require_nonempty_str("request_kind", kind)
    except V2ValidationError as exc:
        raise V2CFirewallError(str(exc)) from exc
    if text not in ALLOWED_REQUEST_KINDS:
        _refuse_request_kind(text)
    return text


def resolve_operational_target(name: object) -> CashControl:
    """Resolve the requested operational target, admitting only ``cash_control``.

    Strict allowlist. A non-string, a callable, a module, a candidate-marked object, any legacy
    candidate id, and every other name are all refused before any target object is produced -- so a
    strategy can never be resolved as a V2C operational target.
    """
    # Refuse candidate-shaped inputs first for a precise diagnostic (also catches callables/modules
    # passed where a name is expected, and the legacy candidate id strings).
    assert_no_candidate_reference("operational target", name)
    try:
        text = require_nonempty_str("operational_target_name", name)
    except V2ValidationError as exc:
        raise V2CFirewallError(str(exc)) from exc
    if text != CASH_CONTROL_TARGET_ID:
        raise V2CFirewallError(
            f"operational target {text!r} is not allowed; V2C resolves only "
            f"{CASH_CONTROL_TARGET_ID!r} (it evaluates no strategy)"
        )
    return CashControl(_token=_TARGET_SENTINEL)


__all__ = [
    "ALLOWED_REQUEST_KINDS",
    "CASH_CONTROL_TARGET_ID",
    "FORBIDDEN_REQUEST_KINDS",
    "KNOWN_LEGACY_CANDIDATE_IDS",
    "CashControl",
    "CashControlIntent",
    "V2CFirewallError",
    "assert_no_candidate_reference",
    "guard_request_kind",
    "resolve_operational_target",
]
