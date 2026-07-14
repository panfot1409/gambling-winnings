"""Exact fractional long-only ETH/cash accounting (Milestone 3B, Phase 5).

Single-asset (ETH vs cash) long-only portfolio accounting with every identity in
``docs/M3B_FRACTIONAL_ACCOUNTING_SPEC.md`` enforced by construction. All
quantities are ``float``. There is **no** borrowing, leverage, margin, or
shorting: cash is never driven materially negative and the ETH quantity is never
driven materially negative.

The ETH leg is always marked at a *reference* price (the execution ``open[t]``)
when computing a portfolio weight; execution costs enter a weight only through
the post-trade cash. Fill prices are supplied by the caller (the execution-cost
model, Phase 8); this module is deliberately agnostic to how a fill price was
formed so the accounting can be verified in isolation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]
_SIDES: frozenset[str] = frozenset({"buy", "sell"})


class AccountingError(Exception):
    """A fractional accounting identity was violated (never silently clipped)."""


def _finite(label: str, value: float) -> float:
    """Reject a non-finite (NaN/inf) value before any ``<`` comparison.

    ``NaN < 0.0`` is ``False``, so a NaN would silently pass every ordinary
    accounting guard; every numeric input is finiteness-checked first.
    """
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise AccountingError(f"{label} must be a finite number, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class Tolerances:
    """The pinned numerical tolerances (see the accounting spec)."""

    cash_tolerance: float = 1e-6
    quantity_tolerance: float = 1e-12
    weight_tolerance: float = 1e-9
    solver_tolerance: float = 1e-12
    no_trade_epsilon: float = 1e-9
    notional_epsilon: float = 1e-6
    max_iterations: int = 100

    def __post_init__(self) -> None:
        for label in (
            "cash_tolerance",
            "quantity_tolerance",
            "weight_tolerance",
            "solver_tolerance",
            "no_trade_epsilon",
            "notional_epsilon",
        ):
            value = _finite(label, getattr(self, label))
            if value < 0.0:
                raise AccountingError(f"{label} must be >= 0, got {value!r}")
        if isinstance(self.max_iterations, bool) or not isinstance(self.max_iterations, int):
            raise AccountingError(f"max_iterations must be an int, got {self.max_iterations!r}")
        if self.max_iterations < 1:
            raise AccountingError(f"max_iterations must be >= 1, got {self.max_iterations}")


DEFAULT_TOLERANCES = Tolerances()


@dataclass(frozen=True)
class PortfolioState:
    """Cash (USD) and ETH quantity held at an instant. Long-only: both >= 0.

    Both legs must be **finite**; the long-only sign constraint is enforced with
    tolerance by :func:`validate_state` (a bit-exact fill can leave a
    within-tolerance negative leg, which is legal), so it is deliberately not
    part of construction.
    """

    cash: float
    quantity: float

    def __post_init__(self) -> None:
        _finite("cash", self.cash)
        _finite("quantity", self.quantity)


@dataclass(frozen=True)
class Fill:
    """The exact record of one executed fill (or a no-trade with ``quantity`` 0).

    Carries the pre- and post-trade legs so a downstream reconciler can prove
    the cash/ETH deltas from the primitive numbers alone. Every leg is finite;
    the traded quantity, notional, and fee are non-negative and the fill price
    positive; the pre/post cash and quantity legs may be within-tolerance
    negative (their sign is reconciled downstream, not here).
    """

    side: Side
    quantity: float
    fill_price: float
    fill_notional: float
    fee: float
    cash_before: float
    cash_after: float
    quantity_before: float
    quantity_after: float

    def __post_init__(self) -> None:
        if self.side not in _SIDES:
            raise AccountingError(f"side must be 'buy' or 'sell', got {self.side!r}")
        for label in (
            "quantity",
            "fill_price",
            "fill_notional",
            "fee",
            "cash_before",
            "cash_after",
            "quantity_before",
            "quantity_after",
        ):
            _finite(label, getattr(self, label))
        if self.quantity < 0.0:
            raise AccountingError(f"fill quantity must be >= 0, got {self.quantity!r}")
        if self.fill_price <= 0.0:
            raise AccountingError(f"fill price must be > 0, got {self.fill_price!r}")
        if self.fill_notional < 0.0:
            raise AccountingError(f"fill notional must be >= 0, got {self.fill_notional!r}")
        if self.fee < 0.0:
            raise AccountingError(f"fee must be >= 0, got {self.fee!r}")


def equity_at(state: PortfolioState, price: float) -> float:
    """Mark-to-market equity ``cash + quantity * price`` at a finite ``price``."""
    _finite("price", price)
    return state.cash + state.quantity * price


def weight_at_reference(
    state: PortfolioState, reference_price: float, *, tol: Tolerances = DEFAULT_TOLERANCES
) -> float:
    """The ETH weight ``Q * P / (C + Q * P)`` at the reference price ``P``.

    Both legs are marked at the same reference price, so this is the fraction of
    reference-marked equity held in ETH. The state must be a *legal* long-only
    state (validated here); a within-tolerance negative cash or ETH — a float
    artifact of the bit-exact accounting — can push the raw ratio a hair outside
    ``[0, 1]``, so the definitionally long-only exposure is clamped to the
    boundary it represents. An out-of-tolerance state is rejected, not clamped.
    """
    _finite("reference_price", reference_price)
    if reference_price <= 0.0:
        raise AccountingError(f"reference price must be positive, got {reference_price!r}")
    validate_state(state, tol=tol)
    eth_value = state.quantity * reference_price
    equity = state.cash + eth_value
    if equity <= 0.0:
        raise AccountingError(f"non-positive reference equity {equity!r}")
    return min(1.0, max(0.0, eth_value / equity))


def validate_state(state: PortfolioState, *, tol: Tolerances = DEFAULT_TOLERANCES) -> None:
    """Reject a state with materially negative cash or ETH."""
    if state.cash < -tol.cash_tolerance:
        raise AccountingError(f"negative cash {state.cash!r} beyond tolerance")
    if state.quantity < -tol.quantity_tolerance:
        raise AccountingError(f"negative ETH quantity {state.quantity!r} beyond tolerance")


def apply_fill(
    state: PortfolioState,
    side: Side,
    quantity: float,
    fill_price: float,
    fee_rate: float,
    *,
    tol: Tolerances = DEFAULT_TOLERANCES,
) -> tuple[PortfolioState, Fill]:
    """Apply a directional fill of ``quantity`` ETH at ``fill_price`` plus fee.

    Buy: ``Q1 = Q0 + x``, ``C1 = C0 - x*f - fee`` (cash never created; a cash
    shortfall beyond ``cash_tolerance`` is an error). Sell: ``Q1 = Q0 - x``,
    ``C1 = C0 + x*f - fee`` (ETH never created; an inventory shortfall beyond
    ``quantity_tolerance`` is an error). ``fee = x * fill_price * fee_rate``.
    """
    _finite("quantity", quantity)
    _finite("fill_price", fill_price)
    _finite("fee_rate", fee_rate)
    if quantity < 0.0:
        raise AccountingError(f"fill quantity must be non-negative, got {quantity!r}")
    if fill_price <= 0.0:
        raise AccountingError(f"fill price must be positive, got {fill_price!r}")
    if fee_rate < 0.0:
        raise AccountingError(f"fee rate must be non-negative, got {fee_rate!r}")

    fill_notional = quantity * fill_price
    fee = fill_notional * fee_rate

    if side == "buy":
        quantity_after = state.quantity + quantity
        cash_after = state.cash - fill_notional - fee
        if cash_after < -tol.cash_tolerance:
            raise AccountingError(
                f"buy would drive cash to {cash_after!r} (below -{tol.cash_tolerance})"
            )
    elif side == "sell":
        quantity_after = state.quantity - quantity
        if quantity_after < -tol.quantity_tolerance:
            raise AccountingError(
                f"sell would drive ETH quantity to {quantity_after!r} "
                f"(below -{tol.quantity_tolerance})"
            )
        cash_after = state.cash + fill_notional - fee
    else:  # pragma: no cover - Side is a closed Literal
        raise AccountingError(f"unknown side {side!r}")

    new_state = PortfolioState(cash=cash_after, quantity=quantity_after)
    validate_state(new_state, tol=tol)
    fill = Fill(
        side=side,
        quantity=quantity,
        fill_price=fill_price,
        fill_notional=fill_notional,
        fee=fee,
        cash_before=state.cash,
        cash_after=cash_after,
        quantity_before=state.quantity,
        quantity_after=quantity_after,
    )
    return new_state, fill


def achieved_weight_after(
    state: PortfolioState,
    side: Side,
    quantity: float,
    fill_price: float,
    fee_rate: float,
    reference_price: float,
    *,
    tol: Tolerances = DEFAULT_TOLERANCES,
) -> float:
    """The ETH reference weight *after* applying the given fill.

    A pure helper the solver bisects on: the ETH leg is marked at
    ``reference_price`` while the fill's cost has already reduced post-trade cash.
    """
    new_state, _ = apply_fill(state, side, quantity, fill_price, fee_rate, tol=tol)
    return weight_at_reference(new_state, reference_price)
