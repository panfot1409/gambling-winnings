"""The deterministic shared-cash simultaneous rebalance solver.

Given a pre-trade portfolio — base cash plus holdings whose base values are ``V_i = q_i * p_i *
fx_i`` — and a set of long-only target weights ``w_i`` (summing to at most one), the solver finds
the single post-cost base equity ``E_post`` at which trading every asset to ``w_i * E_post``
simultaneously, and paying the resulting costs, exactly consumes the equity. It solves one shared
pool of cash for all assets at once, so the result never depends on which asset "spends first" — it
is permutation-invariant by construction.

**Why the fixed point is unique.** Let ``h(E) = E_pre - total_cost(E) - E`` where ``total_cost(E)``
is the summed cost of trading each asset from ``V_i`` to ``w_i * E``. The cost parameters are
validated contractive (worst-case marginal rate ``B < 1``), so ``|total_cost'(E)| <= B * sum(w_i)
<= B < 1`` and therefore ``h'(E) <= -1 + B < 0`` — ``h`` is strictly decreasing. At ``E = 0`` all
assets are sold and ``total_cost(0) <= B * sum(V_i) < E_pre``, so ``h(0) > 0``; at ``E = E_pre``,
``h(E_pre) = -total_cost(E_pre) <= 0``. A strictly-decreasing continuous function with ``h(0) > 0``
and ``h(E_pre) <= 0`` has exactly one root in ``[0, E_pre]``, found by bounded bisection.

The post-trade cash is ``E_post * (1 - sum(w_i)) >= 0`` and each post-trade holding value is
``w_i * E_post >= 0``, so the accounting is cash-safe and long-only by construction; the solver then
asserts these invariants to the pinned tolerances and fails closed otherwise.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.costs import CostBreakdown, CostParameters, trade_cost
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.tolerances import DEFAULT_TOLERANCES, PortfolioTolerances
from eth_research.portfolio.validation import (
    require_non_negative_finite_float,
    require_positive_finite_float,
)

__all__ = ["AssetSolveInput", "AssetTrade", "SolveResult", "solve_shared_cash"]

# Bisect the equity fixed point down to a few ULPs of the pre-trade equity (not merely the
# reconciliation tolerance) so the single-asset reduction is exact enough for the compatibility
# contract; ``max_iterations`` (100) comfortably covers the ~52 halvings this needs.
_RELATIVE_ROOT_WIDTH = 4.0 * sys.float_info.epsilon


@dataclass(frozen=True)
class AssetSolveInput:
    """One asset's pre-trade state and execution references for the shared-cash solve."""

    instrument: InstrumentId
    base_value: float  # V_i = q_i * p_i * fx_i, current holding value in base currency (>= 0)
    target_weight: float  # w_i in [0, 1]
    fx_rate: float  # quote -> base conversion at the execution event (> 0)
    local_price: float  # execution reference price in the quote currency (> 0)
    lagged_dollar_volume: float  # lagged participation denominator, quote-currency volume (> 0)
    quote_currency: str
    base_currency: str

    def __post_init__(self) -> None:
        require_non_negative_finite_float(self.base_value, "solve.base_value")
        weight = require_non_negative_finite_float(self.target_weight, "solve.target_weight")
        if weight > 1.0:
            raise CanonicalError("solve.target_weight: must be within [0, 1]")
        require_positive_finite_float(self.fx_rate, "solve.fx_rate")
        require_positive_finite_float(self.local_price, "solve.local_price")
        require_positive_finite_float(self.lagged_dollar_volume, "solve.lagged_dollar_volume")

    @property
    def applies_fx_conversion(self) -> bool:
        return self.quote_currency != self.base_currency


@dataclass(frozen=True)
class AssetTrade:
    """The resolved trade for one asset at the solved post-cost equity."""

    instrument: InstrumentId
    side: str  # "buy" | "sell" | "hold"
    base_notional: float  # signed: + buy, - sell
    local_quantity: float  # signed local-unit quantity traded
    post_base_value: float  # w_i * E_post
    cost: CostBreakdown


@dataclass(frozen=True)
class SolveResult:
    """The shared-cash solve outcome: the post equity, residual cash, and per-asset trades."""

    equity_pre: float
    equity_post: float
    total_cost: float
    residual_cash: float
    trades: tuple[AssetTrade, ...]
    iterations: int


def _asset_cost(item: AssetSolveInput, delta_base: float, params: CostParameters) -> CostBreakdown:
    magnitude = abs(delta_base)
    # Participation is the local trade notional over the lagged dollar volume — lagged, never the
    # current bar's volume, so the cost cannot depend on unavailable information.
    local_notional = magnitude / item.fx_rate
    participation = local_notional / item.lagged_dollar_volume
    return trade_cost(
        params,
        magnitude,
        participation=participation,
        apply_fx_conversion=item.applies_fx_conversion,
        currency=item.base_currency,
    )


def _total_cost_at(
    items: tuple[AssetSolveInput, ...], equity: float, params: CostParameters, no_trade: float
) -> float:
    total = 0.0
    threshold = no_trade * equity
    for item in items:
        delta = item.target_weight * equity - item.base_value
        if abs(delta) <= threshold:
            continue
        total += _asset_cost(item, delta, params).total
    return total


def solve_shared_cash(
    inputs: tuple[AssetSolveInput, ...],
    *,
    base_cash: float,
    params: CostParameters,
    tolerances: PortfolioTolerances = DEFAULT_TOLERANCES,
) -> SolveResult:
    """Solve the joint post-cost equity fixed point and return the per-asset trades.

    ``inputs`` are the pre-trade assets (any order — the result is permutation-invariant),
    ``base_cash`` is the current base-currency cash. Raises :class:`CanonicalError` if the pre-trade
    equity is non-positive, the target weights sum above one, or a post-solve invariant is violated.
    """
    require_non_negative_finite_float(base_cash, "solve.base_cash")
    # Canonicalize the input order up front so the pre-trade-equity, gross-weight, and total-cost
    # sums below are evaluated in a fixed order regardless of how the caller passed the assets.
    # Floating-point addition is not associative, so without this a reordering of the same assets
    # would perturb those sums (and hence the bisection bracket) at the ULP level, breaking the
    # documented permutation invariance for callers that do not pre-sort. The engine already feeds
    # inputs in canonical instrument-id order, so end-to-end runs are unchanged.
    inputs = tuple(sorted(inputs, key=lambda item: item.instrument.instrument_id))
    equity_pre = base_cash + sum(item.base_value for item in inputs)
    if not equity_pre > 0.0:
        raise CanonicalError("solve: pre-trade equity must be positive")
    gross_weight = sum(item.target_weight for item in inputs)
    if gross_weight > 1.0 + tolerances.weight:
        raise CanonicalError(
            f"solve: target weights sum to {gross_weight!r} > 1 (long-only, cash remainder)"
        )

    def h(equity: float) -> float:
        return equity_pre - _total_cost_at(inputs, equity, params, tolerances.no_trade) - equity

    low, high = 0.0, equity_pre
    # h(low) > 0 and h(high) <= 0; h strictly decreasing -> a unique root by bisection. Converge
    # to the tightest representable width (a few ULPs of the equity), not merely solver_tol, so the
    # single-asset reduction lands within the accepted engine's ULP contract; the no-progress break
    # stops once no float lies strictly between the bounds.
    iterations = 0
    width_target = equity_pre * _RELATIVE_ROOT_WIDTH
    while high - low > width_target and iterations < tolerances.max_iterations:
        mid = 0.5 * (low + high)
        if mid <= low or mid >= high:
            break
        if h(mid) > 0.0:
            low = mid
        else:
            high = mid
        iterations += 1
    equity_post = 0.5 * (low + high)

    trades = _resolve_trades(inputs, equity_post, params, tolerances)
    total_cost = sum(trade.cost.total for trade in trades)
    residual_cash = equity_post * (1.0 - gross_weight)
    _assert_invariants(
        inputs, base_cash, equity_pre, equity_post, total_cost, residual_cash, trades, tolerances
    )
    return SolveResult(
        equity_pre=equity_pre,
        equity_post=equity_post,
        total_cost=total_cost,
        residual_cash=residual_cash,
        trades=trades,
        iterations=iterations,
    )


def _resolve_trades(
    inputs: tuple[AssetSolveInput, ...],
    equity_post: float,
    params: CostParameters,
    tolerances: PortfolioTolerances,
) -> tuple[AssetTrade, ...]:
    threshold = tolerances.no_trade * equity_post
    ordered = sorted(inputs, key=lambda item: item.instrument.instrument_id)
    trades: list[AssetTrade] = []
    for item in ordered:
        post_value = item.target_weight * equity_post
        delta = post_value - item.base_value
        if abs(delta) <= threshold:
            side, delta, post_value = "hold", 0.0, item.base_value
            cost = CostBreakdown(item.base_currency, 0.0, 0.0, 0.0, 0.0, 0.0)
        else:
            side = "buy" if delta > 0.0 else "sell"
            cost = _asset_cost(item, delta, params)
        local_quantity = delta / (item.fx_rate * item.local_price)
        trades.append(
            AssetTrade(
                instrument=item.instrument,
                side=side,
                base_notional=delta,
                local_quantity=local_quantity,
                post_base_value=post_value,
                cost=cost,
            )
        )
    return tuple(trades)


def _assert_invariants(
    inputs: tuple[AssetSolveInput, ...],
    base_cash: float,
    equity_pre: float,
    equity_post: float,
    total_cost: float,
    residual_cash: float,
    trades: tuple[AssetTrade, ...],
    tolerances: PortfolioTolerances,
) -> None:
    if residual_cash < -tolerances.cash:
        raise CanonicalError(f"solve: residual cash {residual_cash!r} is negative (not cash-safe)")
    for trade in trades:
        if trade.post_base_value < -tolerances.cash:
            raise CanonicalError(
                f"solve: post-trade value of {trade.instrument.symbol!r} is negative "
                "(not long-only)"
            )
    # Equity identity: E_post == E_pre - total_cost within a scaled tolerance.
    if abs((equity_pre - total_cost) - equity_post) > max(tolerances.notional, equity_pre * 1e-9):
        raise CanonicalError("solve: post equity does not reconcile with pre equity minus cost")
    # Cash identity: residual == base_cash - sum(base_notional) - total_cost.
    spent = sum(trade.base_notional for trade in trades)
    if abs((base_cash - spent - total_cost) - residual_cash) > max(
        tolerances.notional, equity_pre * 1e-9
    ):
        raise CanonicalError("solve: cash does not reconcile after trades")
