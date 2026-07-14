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

from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]


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


DEFAULT_TOLERANCES = Tolerances()


class AccountingError(Exception):
    """A fractional accounting identity was violated (never silently clipped)."""


@dataclass(frozen=True)
class PortfolioState:
    """Cash (USD) and ETH quantity held at an instant. Long-only: both >= 0."""

    cash: float
    quantity: float


@dataclass(frozen=True)
class Fill:
    """The exact record of one executed fill (or a no-trade with ``quantity`` 0).

    Carries the pre- and post-trade legs so a downstream reconciler can prove
    the cash/ETH deltas from the primitive numbers alone.
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


def equity_at(state: PortfolioState, price: float) -> float:
    """Mark-to-market equity ``cash + quantity * price`` at ``price``."""
    return state.cash + state.quantity * price


def weight_at_reference(state: PortfolioState, reference_price: float) -> float:
    """The ETH weight ``Q * P / (C + Q * P)`` at the reference price ``P``.

    Both legs are marked at the same reference price, so this is the fraction of
    reference-marked equity held in ETH. Returns ``0.0`` for a zero-equity or
    all-cash state.
    """
    if reference_price <= 0.0:
        raise AccountingError(f"reference price must be positive, got {reference_price!r}")
    eth_value = state.quantity * reference_price
    equity = state.cash + eth_value
    if equity <= 0.0:
        raise AccountingError(f"non-positive reference equity {equity!r}")
    return eth_value / equity


def validate_state(state: PortfolioState, *, tol: Tolerances = DEFAULT_TOLERANCES) -> None:
    """Reject a state with materially negative cash or ETH."""
    if state.cash < -tol.cash_tolerance:
        raise AccountingError(f"negative cash {state.cash!r} beyond tolerance")
    if state.quantity < -tol.quantity_tolerance:
        raise AccountingError(f"negative ETH quantity {state.quantity!r} beyond tolerance")


def _clamp_zero(value: float, tolerance: float) -> float:
    """Collapse a tiny negative (within ``tolerance``) to exactly ``0.0``."""
    if -tolerance <= value < 0.0:
        return 0.0
    return value


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
        cash_after = _clamp_zero(cash_after, tol.cash_tolerance)
    elif side == "sell":
        quantity_after = state.quantity - quantity
        if quantity_after < -tol.quantity_tolerance:
            raise AccountingError(
                f"sell would drive ETH quantity to {quantity_after!r} "
                f"(below -{tol.quantity_tolerance})"
            )
        quantity_after = _clamp_zero(quantity_after, tol.quantity_tolerance)
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
