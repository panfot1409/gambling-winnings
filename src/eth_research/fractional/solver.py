"""Bounded-bisection target-weight solver (Milestone 3B, Phase 6).

Given a portfolio, a reference open price, and a *risk-approved* executable
target weight, find the ETH quantity to trade at the next open so the achieved
reference weight equals the target — subject to cash, inventory, and
participation (lagged-liquidity) constraints. Directional fill prices are
supplied as callables of the executed quantity, so the solver is agnostic to how
the execution-cost model (Phase 8) forms a price.

The achieved reference weight is strictly monotone in the executed quantity —
strictly increasing for a buy (ETH value rises while post-cost cash falls) and
strictly decreasing for a sell (ETH value falls while proceeds rise) — so a
bounded bisection on the residual converges. When the risk target lies beyond
the feasible endpoint (cash / inventory / participation binds first) the solver
executes the endpoint and records an honest **partial fill** with the residual
target error; it never silently clips or substitutes same-bar liquidity. A trade
whose notional rounds below ``notional_epsilon`` is dropped as dust; a zero
participation cap yields no fill at all, for a typed reason.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from eth_research.fractional.accounting import (
    DEFAULT_TOLERANCES,
    AccountingError,
    Fill,
    PortfolioState,
    Side,
    Tolerances,
    achieved_weight_after,
    apply_fill,
    weight_at_reference,
)

PriceFn = Callable[[float], float]


class SolverError(Exception):
    """The solver was asked for an impossible target or a non-monotone bracket."""


def _finite(label: str, value: float) -> float:
    """Reject a ``bool``, non-real, or non-finite (NaN/inf) solver input.

    A NaN ``reference_price`` / ``fee_rate`` / ``target`` would pass every ``<``
    comparison silently and then either poison the arithmetic or degrade to a
    spurious no-trade, so finiteness is asserted before any bracketing.
    """
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise SolverError(f"{label} must be a finite number, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class SolveResult:
    """The outcome of solving one bar's target weight.

    ``side`` is ``None`` for a no-trade. ``fill`` is ``None`` when no ETH changed
    hands (no-trade, dust, or no liquidity). ``target_error`` is
    ``achieved_target - executable_target``; a non-zero error with ``partial``
    set means a constraint bound before the target was reached.
    """

    side: Side | None
    executed_quantity: float
    state_after: PortfolioState
    fill: Fill | None
    requested_target: float
    executable_target: float
    achieved_target: float
    target_error: float
    reason: str
    partial: bool


def _no_trade(
    state: PortfolioState,
    reference_price: float,
    requested: float,
    executable: float,
    reason: str,
    *,
    partial: bool = False,
    side: Side | None = None,
) -> SolveResult:
    achieved = weight_at_reference(state, reference_price)
    return SolveResult(
        side=side,
        executed_quantity=0.0,
        state_after=state,
        fill=None,
        requested_target=requested,
        executable_target=executable,
        achieved_target=achieved,
        target_error=achieved - executable,
        reason=reason,
        partial=partial,
    )


def _bisect(residual: Callable[[float], float], lo: float, hi: float, tol: Tolerances) -> float:
    """Bisect a monotone ``residual`` with a sign change on ``[lo, hi]``.

    Works for either monotone direction; returns the abscissa where the residual
    is within ``solver_tolerance`` of zero (or the final bracket midpoint).
    """
    g_lo = residual(lo)
    g_hi = residual(hi)
    if g_lo == 0.0:
        return lo
    if g_hi == 0.0:
        return hi
    if (g_lo > 0.0) == (g_hi > 0.0):  # pragma: no cover - guarded by callers
        raise SolverError("residual does not bracket a root (non-monotone or bad bracket)")
    for _ in range(tol.max_iterations):
        mid = 0.5 * (lo + hi)
        g_mid = residual(mid)
        if abs(g_mid) <= tol.solver_tolerance or (hi - lo) <= tol.solver_tolerance:
            return mid
        if (g_mid > 0.0) == (g_lo > 0.0):
            lo, g_lo = mid, g_mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _max_buy_within_cash(
    state: PortfolioState, buy_price: PriceFn, fee_rate: float, upper: float, tol: Tolerances
) -> float:
    """Largest buy quantity in ``[0, upper]`` keeping post-trade cash >= 0.

    Post-trade cash is strictly decreasing in the quantity. If the whole bracket
    fits, return it. If the fill price is constant in the quantity (no impact —
    the compatibility scenario), the cash-exhausting quantity has the exact
    closed form ``cash / (price * (1 + fee_rate))`` the binary engine uses, which
    preserves bit-for-bit parity. Only impact scenarios fall through to bisection.
    """

    def cash_after(x: float) -> float:
        notional = x * buy_price(x)
        return state.cash - notional - notional * fee_rate

    if cash_after(upper) >= 0.0:
        return upper
    price0 = buy_price(0.0)
    if buy_price(upper) == price0:
        return state.cash / (price0 * (1.0 + fee_rate))
    lo, hi = 0.0, upper
    for _ in range(tol.max_iterations):
        mid = 0.5 * (lo + hi)
        if cash_after(mid) >= 0.0:
            lo = mid
        else:
            hi = mid
        if (hi - lo) <= tol.solver_tolerance:
            break
    return lo  # feasible side: cash_after(lo) >= 0


def solve_target_weight(
    state: PortfolioState,
    reference_price: float,
    executable_target: float,
    *,
    buy_price: PriceFn,
    sell_price: PriceFn,
    fee_rate: float,
    participation_quantity_cap: float,
    requested_target: float | None = None,
    tol: Tolerances = DEFAULT_TOLERANCES,
) -> SolveResult:
    """Solve for the fill that reaches ``executable_target`` at the next open.

    ``participation_quantity_cap`` is the maximum ETH tradable this bar from the
    lagged-liquidity estimate (``float('inf')`` when the scenario disables the
    participation constraint). ``requested_target`` (default: ``executable_target``)
    is the pre-risk target recorded for reconciliation.
    """
    P = _finite("reference_price", reference_price)
    if P <= 0.0:
        raise SolverError(f"reference price must be positive, got {P!r}")
    if _finite("fee_rate", fee_rate) < 0.0:
        raise SolverError(f"fee rate must be non-negative, got {fee_rate!r}")
    # The participation cap is the one input that is legally ``+inf`` (constraint
    # disabled), so it is NaN-checked but not finiteness-checked; ``-inf`` and any
    # negative are rejected by the sign guard below.
    if (
        isinstance(participation_quantity_cap, bool)
        or not isinstance(participation_quantity_cap, int | float)
        or math.isnan(participation_quantity_cap)
    ):
        raise SolverError(
            f"participation cap must be a real number, got {participation_quantity_cap!r}"
        )
    if participation_quantity_cap < 0.0:
        raise SolverError(
            f"participation cap must be non-negative, got {participation_quantity_cap!r}"
        )
    _finite("executable_target", executable_target)
    if not (-tol.weight_tolerance <= executable_target <= 1.0 + tol.weight_tolerance):
        raise SolverError(f"executable target weight {executable_target!r} is outside [0, 1]")
    if requested_target is not None:
        _finite("requested_target", requested_target)

    requested = executable_target if requested_target is None else requested_target
    w0 = weight_at_reference(state, P)
    cap = participation_quantity_cap

    # Direction: a dead band around the current weight avoids float-noise churn.
    if executable_target > w0 + tol.no_trade_epsilon:
        side: Side = "buy"
    elif executable_target < w0 - tol.no_trade_epsilon:
        side = "sell"
    else:
        return _no_trade(state, P, requested, executable_target, "no_trade_band")

    if cap <= 0.0:
        return _no_trade(
            state, P, requested, executable_target, "no_fill_no_liquidity", partial=True, side=side
        )

    def residual(x: float) -> float:
        price = buy_price(x) if side == "buy" else sell_price(x)
        achieved = achieved_weight_after(state, side, x, price, fee_rate, P, tol=tol)
        return achieved - executable_target

    if side == "buy":
        # A buy fill price is always >= P, so no more than cash/P ETH is ever
        # affordable — a finite bracket even when participation is uncapped (inf).
        bracket_upper = min(cap, state.cash / P)
        cash_max = _max_buy_within_cash(state, buy_price, fee_rate, bracket_upper, tol)
        x_max = cash_max
        binding = "participation" if cash_max >= cap - tol.quantity_tolerance else "cash"
    else:
        x_max = min(state.quantity, cap)
        binding = "participation" if cap < state.quantity else "inventory"

    if x_max <= 0.0:
        return _no_trade(
            state,
            P,
            requested,
            executable_target,
            f"partial_{binding}_capped",
            partial=True,
            side=side,
        )

    g_max = residual(x_max)
    # Execute the feasible endpoint when it cannot overshoot the target by more
    # than the weight tolerance. This keeps a full-investment buy on the exact
    # cash-exhausting quantity (binary-engine parity) even when float noise makes
    # the endpoint's achieved weight round a hair past the target; a genuinely
    # interior target still bisects.
    if side == "buy":
        reached_endpoint = g_max <= tol.weight_tolerance
    else:
        reached_endpoint = g_max >= -tol.weight_tolerance
    if reached_endpoint:
        executed = x_max
        endpoint_capped = True
    else:
        executed = _bisect(residual, 0.0, x_max, tol)
        endpoint_capped = False

    if executed * P < tol.notional_epsilon:
        # A binding cap that leaves no executable size is an honest partial.
        if endpoint_capped:
            return _no_trade(
                state,
                P,
                requested,
                executable_target,
                f"partial_{binding}_capped",
                partial=True,
                side=side,
            )
        # An interior solution below the USD notional floor is dropped to avoid
        # float-noise churn. Honesty is on the WEIGHT scale, not the notional
        # scale: it is a genuine partial iff the untraded weight gap still exceeds
        # the weight tolerance (at small equity a real weight move can require a
        # sub-floor notional), so the flag never disagrees with the reconciler.
        dust_gap = abs(w0 - executable_target)
        dust_partial = dust_gap > tol.weight_tolerance
        reason = "partial_dust_below_notional_floor" if dust_partial else "no_trade_dust"
        return _no_trade(
            state, P, requested, executable_target, reason, partial=dust_partial, side=side
        )

    price = buy_price(executed) if side == "buy" else sell_price(executed)
    try:
        new_state, fill = apply_fill(state, side, executed, price, fee_rate, tol=tol)
    except AccountingError as exc:  # pragma: no cover - brackets keep fills feasible
        raise SolverError(f"solved fill violated accounting: {exc}") from exc
    achieved = weight_at_reference(new_state, P)
    error = achieved - executable_target
    partial = abs(error) > tol.weight_tolerance
    if not partial:
        reason = "converged"
    elif endpoint_capped:
        reason = f"partial_{binding}_capped"
    else:  # pragma: no cover - a bracketed monotone bisection converges within tol
        reason = "partial_unconverged"
    return SolveResult(
        side=side,
        executed_quantity=executed,
        state_after=new_state,
        fill=fill,
        requested_target=requested,
        executable_target=executable_target,
        achieved_target=achieved,
        target_error=error,
        reason=reason,
        partial=partial,
    )
