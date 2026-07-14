"""Bounded-bisection target-weight solver: hand-calculated + randomized.

The achieved reference weight is monotone in the executed quantity, so the
solver must reach any feasible target within ``weight_tolerance`` and record an
honest partial fill (never a silent clip) when a cash / inventory / participation
constraint binds first.
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable

import pytest

from eth_research.fractional.accounting import (
    DEFAULT_TOLERANCES,
    PortfolioState,
    achieved_weight_after,
    weight_at_reference,
)
from eth_research.fractional.solver import SolveResult, solve_target_weight

TOL = DEFAULT_TOLERANCES


def _prices(
    price: float, half_spread: float, slippage: float, impact_coef: float
) -> tuple[Callable[[float], float], Callable[[float], float]]:
    """Directional fill prices with linear impact (buy >= P >= sell)."""

    def buy(x: float) -> float:
        return price * (1.0 + half_spread + slippage + impact_coef * x)

    def sell(x: float) -> float:
        return price * (1.0 - half_spread - slippage - impact_coef * x)

    return buy, sell


def _solve(
    state: PortfolioState,
    price: float,
    target: float,
    *,
    fee_rate: float = 0.0,
    half_spread: float = 0.0,
    slippage: float = 0.0,
    impact_coef: float = 0.0,
    cap: float = math.inf,
) -> SolveResult:
    buy, sell = _prices(price, half_spread, slippage, impact_coef)
    return solve_target_weight(
        state,
        price,
        target,
        buy_price=buy,
        sell_price=sell,
        fee_rate=fee_rate,
        participation_quantity_cap=cap,
    )


class TestDirectionAndNoTrade:
    def test_target_at_current_weight_is_no_trade(self) -> None:
        state = PortfolioState(cash=500.0, quantity=5.0)  # w0 = 0.5 at P=100
        result = _solve(state, 100.0, 0.5)
        assert result.side is None
        assert result.reason == "no_trade_band"
        assert result.executed_quantity == 0.0
        assert result.state_after == state

    def test_higher_target_buys_lower_target_sells(self) -> None:
        state = PortfolioState(cash=500.0, quantity=5.0)  # w0 = 0.5
        assert _solve(state, 100.0, 0.7).side == "buy"
        assert _solve(state, 100.0, 0.3).side == "sell"


class TestConverged:
    def test_zero_cost_buy_reaches_exact_weight(self) -> None:
        # C0=1000, Q0=0, P=100, no cost. achieved = x/10, so w=0.5 -> x=5.
        state = PortfolioState(cash=1000.0, quantity=0.0)
        result = _solve(state, 100.0, 0.5)
        assert result.side == "buy"
        assert result.reason == "converged"
        assert not result.partial
        assert result.executed_quantity == pytest.approx(5.0, abs=1e-9)
        assert result.achieved_target == pytest.approx(0.5, abs=TOL.weight_tolerance)

    def test_costed_buy_reaches_target_within_tolerance(self) -> None:
        state = PortfolioState(cash=1000.0, quantity=0.0)
        result = _solve(
            state, 100.0, 0.5, fee_rate=0.001, half_spread=0.001, slippage=0.0005, impact_coef=0.01
        )
        assert result.reason == "converged"
        assert abs(result.target_error) <= TOL.weight_tolerance
        # buy consumed cash and added ETH
        assert result.state_after.cash < state.cash
        assert result.state_after.quantity > state.quantity

    def test_sell_reaches_target(self) -> None:
        # C0=0, Q0=10, P=100 -> w0=1.0; target 0.3 with cost.
        state = PortfolioState(cash=0.0, quantity=10.0)
        result = _solve(state, 100.0, 0.3, fee_rate=0.001, half_spread=0.001, impact_coef=0.005)
        assert result.side == "sell"
        assert result.reason == "converged"
        assert abs(result.target_error) <= TOL.weight_tolerance

    def test_sell_all_to_cash_target_zero(self) -> None:
        state = PortfolioState(cash=0.0, quantity=10.0)
        result = _solve(state, 100.0, 0.0, fee_rate=0.001)
        assert result.side == "sell"
        assert result.state_after.quantity == pytest.approx(0.0, abs=1e-9)
        assert result.achieved_target == pytest.approx(0.0, abs=TOL.weight_tolerance)


class TestPartialFills:
    def test_full_investment_deploys_all_cash_and_converges(self) -> None:
        # Deploying all cash always drives weight -> 1 (post-trade cash -> 0), so
        # a buy toward full investment converges regardless of fees; cash is never
        # the binding partial constraint for a valid target <= 1.
        state = PortfolioState(cash=100.0, quantity=0.0)
        result = _solve(state, 100.0, 1.0, fee_rate=0.001)
        assert result.side == "buy"
        assert result.reason == "converged"
        assert not result.partial
        assert result.achieved_target == pytest.approx(1.0, abs=TOL.weight_tolerance)
        assert result.state_after.cash == pytest.approx(0.0, abs=TOL.cash_tolerance)

    def test_participation_capped_buy_is_partial(self) -> None:
        # Plenty of cash but only 0.5 ETH tradable this bar.
        state = PortfolioState(cash=100_000.0, quantity=0.0)
        result = _solve(state, 100.0, 1.0, cap=0.5)
        assert result.partial
        assert result.reason == "partial_participation_capped"
        assert result.executed_quantity == pytest.approx(0.5, abs=1e-9)

    def test_participation_capped_sell_is_partial(self) -> None:
        # Holds 10 ETH but only 0.5 tradable; can't sell enough to reach target 0.
        state = PortfolioState(cash=0.0, quantity=10.0)
        result = _solve(state, 100.0, 0.0, cap=0.5)
        assert result.side == "sell"
        assert result.partial
        assert result.reason == "partial_participation_capped"
        assert result.executed_quantity == pytest.approx(0.5, abs=1e-9)

    def test_zero_liquidity_makes_no_fill(self) -> None:
        state = PortfolioState(cash=1000.0, quantity=0.0)
        result = _solve(state, 100.0, 0.5, cap=0.0)
        assert result.reason == "no_fill_no_liquidity"
        assert result.partial
        assert result.executed_quantity == 0.0
        assert result.fill is None

    def test_dust_trade_is_dropped(self) -> None:
        # E=500; a target 1.5e-9 above w0 clears the no-trade band but the solved
        # notional (~7.5e-7) is below the 1e-6 notional floor -> dust, not partial.
        state = PortfolioState(cash=500.0, quantity=0.0)
        result = _solve(state, 100.0, 1.5e-9)
        assert result.reason == "no_trade_dust"
        assert not result.partial
        assert result.executed_quantity == 0.0


class TestInvariantsAndMonotonicity:
    def test_achieved_weight_is_monotone_in_quantity(self) -> None:
        rng = random.Random(20240714)
        for _ in range(200):
            price = rng.uniform(10.0, 5000.0)
            cash = rng.uniform(0.0, 1e5)
            qty = rng.uniform(0.0, 100.0)
            if cash + qty * price <= 0:
                continue
            state = PortfolioState(cash=cash, quantity=qty)
            hs, slip, impact = 0.0005, 0.0005, rng.uniform(0.0, 1e-4)
            fee = 0.001
            buy, sell = _prices(price, hs, slip, impact)
            # Buy: achieved strictly increases with x (within affordable range).
            x_hi = min(0.4 * cash / price, 10.0)
            if x_hi > 1e-6:
                grid = [x_hi * k / 6 for k in range(7)]
                weights = [achieved_weight_after(state, "buy", x, buy(x), fee, price) for x in grid]
                for a, b in itertools.pairwise(weights):
                    assert b >= a - 1e-15
            # Sell: achieved strictly decreases with x (within held range).
            x_hi_s = min(0.9 * qty, 10.0)
            if x_hi_s > 1e-6:
                grid = [x_hi_s * k / 6 for k in range(7)]
                weights = [
                    achieved_weight_after(state, "sell", x, sell(x), fee, price) for x in grid
                ]
                for a, b in itertools.pairwise(weights):
                    assert b <= a + 1e-15

    def test_solver_reaches_feasible_targets(self) -> None:
        rng = random.Random(99)
        for _ in range(300):
            price = rng.uniform(50.0, 3000.0)
            cash = rng.uniform(1000.0, 1e5)
            qty = rng.uniform(0.0, 50.0)
            state = PortfolioState(cash=cash, quantity=qty)
            w0 = weight_at_reference(state, price)
            # Target strictly inside the reachable interior (leave headroom for costs).
            target = rng.uniform(0.05, 0.95)
            result = solve_target_weight(
                state,
                price,
                target,
                buy_price=_prices(price, 0.0005, 0.0005, 1e-6)[0],
                sell_price=_prices(price, 0.0005, 0.0005, 1e-6)[1],
                fee_rate=0.001,
                participation_quantity_cap=math.inf,
            )
            # Every result respects long-only accounting and weight bounds.
            assert result.state_after.cash >= -TOL.cash_tolerance
            assert result.state_after.quantity >= -TOL.quantity_tolerance
            assert -TOL.weight_tolerance <= result.achieved_target <= 1.0 + TOL.weight_tolerance
            if result.reason == "converged" and result.side is not None:
                assert abs(result.target_error) <= TOL.weight_tolerance
            if result.side == "buy":
                assert target > w0
            elif result.side == "sell":
                assert target < w0
