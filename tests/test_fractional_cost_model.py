"""Execution-cost model: exact decomposition identity + metamorphic guarantees."""

from __future__ import annotations

import dataclasses
import math
import random

import pytest

from eth_research.fractional.cost_model import (
    CAUSAL_PROXY_BASE,
    CAUSAL_PROXY_STRESSED,
    COMPATIBILITY_V1,
    SCENARIOS,
    SCENARIOS_BY_NAME,
    CostModelError,
    cost_breakdown,
    fill_price,
    participation_quantity_cap,
    solver_prices,
)


class TestFrozenScenarios:
    def test_scenario_parameters_are_pinned(self) -> None:
        assert COMPATIBILITY_V1.max_participation is None
        assert (COMPATIBILITY_V1.half_spread_rate, COMPATIBILITY_V1.impact_coefficient) == (
            0.0,
            0.0,
        )
        assert COMPATIBILITY_V1.base_slippage_rate == 0.0005
        assert (CAUSAL_PROXY_BASE.impact_coefficient, CAUSAL_PROXY_BASE.impact_cap) == (0.01, 0.005)
        assert CAUSAL_PROXY_BASE.max_participation == 0.001
        assert (CAUSAL_PROXY_STRESSED.fee_rate, CAUSAL_PROXY_STRESSED.max_participation) == (
            0.002,
            0.0005,
        )
        assert {s.name for s in SCENARIOS} == set(SCENARIOS_BY_NAME)
        assert all(s.liquidity_lookback == 30 for s in SCENARIOS)


class TestDecompositionIdentity:
    def test_price_shortfall_equals_component_sum(self) -> None:
        rng = random.Random(7)
        for _ in range(500):
            scenario = rng.choice(SCENARIOS)
            price = rng.uniform(10.0, 4000.0)
            qty = rng.uniform(1e-3, 50.0)
            liquidity = rng.uniform(1e5, 1e9)
            for side in ("buy", "sell"):
                cb = cost_breakdown(scenario, price, side, qty, liquidity)
                components = cb.half_spread_cost + cb.base_slippage_cost + cb.impact_cost
                tol = 1e-9 * max(1.0, cb.reference_notional)
                assert cb.price_shortfall == pytest.approx(components, abs=tol)
                assert cb.total_cost == pytest.approx(cb.fee_cost + cb.price_shortfall, abs=tol)
                assert cb.half_spread_cost >= 0.0
                assert cb.base_slippage_cost >= 0.0
                assert cb.impact_cost >= 0.0

    def test_hand_calculated_base_scenario(self) -> None:
        # P=100, x=1, L=1e6: participation 1e-4, impact 0.01*sqrt(1e-4)=1e-4.
        cb = cost_breakdown(CAUSAL_PROXY_BASE, 100.0, "buy", 1.0, 1_000_000.0)
        assert cb.impact_rate == pytest.approx(1e-4, abs=1e-15)
        assert cb.fill_price == pytest.approx(100.085, abs=1e-9)
        assert cb.half_spread_cost == pytest.approx(0.025, abs=1e-12)
        assert cb.base_slippage_cost == pytest.approx(0.05, abs=1e-12)
        assert cb.impact_cost == pytest.approx(0.01, abs=1e-12)
        assert cb.price_shortfall == pytest.approx(0.085, abs=1e-12)
        assert cb.fee_cost == pytest.approx(100.085 * 0.001, abs=1e-12)


class TestDirectionalPricing:
    def test_buy_above_reference_sell_below(self) -> None:
        for scenario in SCENARIOS:
            buy = fill_price(scenario, 100.0, "buy", 1.0, 1_000_000.0)
            sell = fill_price(scenario, 100.0, "sell", 1.0, 1_000_000.0)
            assert buy > 100.0 > sell

    def test_impact_saturates_at_cap(self) -> None:
        # x=10000, L=1e6 -> participation 1.0 -> 0.01*sqrt(1)=0.01, capped to 0.005.
        cb = cost_breakdown(CAUSAL_PROXY_BASE, 100.0, "buy", 10_000.0, 1_000_000.0)
        assert cb.impact_rate == pytest.approx(0.005, abs=1e-15)

    def test_compatibility_has_no_spread_or_impact(self) -> None:
        cb = cost_breakdown(COMPATIBILITY_V1, 100.0, "buy", 5.0, 1_000_000.0)
        assert cb.half_spread_cost == 0.0
        assert cb.impact_cost == 0.0
        assert cb.impact_rate == 0.0
        # only base slippage moves the price: 100 * (1 + 0.0005)
        assert cb.fill_price == pytest.approx(100.05, abs=1e-9)


class TestParticipationCap:
    def test_hand_calculated_cap(self) -> None:
        # max_part 0.001, L=1e6, P=100 -> max notional 1000 -> 10 ETH.
        cap = participation_quantity_cap(CAUSAL_PROXY_BASE, 100.0, 1_000_000.0)
        assert cap == pytest.approx(10.0, abs=1e-12)

    def test_disabled_participation_is_infinite(self) -> None:
        assert participation_quantity_cap(COMPATIBILITY_V1, 100.0, None) == math.inf
        assert participation_quantity_cap(COMPATIBILITY_V1, 100.0, 1_000_000.0) == math.inf

    def test_constrained_with_no_liquidity_is_zero(self) -> None:
        assert participation_quantity_cap(CAUSAL_PROXY_BASE, 100.0, None) == 0.0
        assert participation_quantity_cap(CAUSAL_PROXY_BASE, 100.0, 0.0) == 0.0


class TestLiquidityFailures:
    def test_impact_without_liquidity_fails_loudly(self) -> None:
        with pytest.raises(CostModelError, match="lagged dollar volume"):
            fill_price(CAUSAL_PROXY_BASE, 100.0, "buy", 1.0, None)

    def test_non_finite_liquidity_fails_loudly(self) -> None:
        with pytest.raises(CostModelError, match="finite"):
            fill_price(CAUSAL_PROXY_BASE, 100.0, "buy", 1.0, math.inf)

    def test_zero_volume_never_yields_infinite_impact(self) -> None:
        # Constrained scenario + zero liquidity -> no fill (cap 0), not inf impact.
        assert participation_quantity_cap(CAUSAL_PROXY_STRESSED, 100.0, 0.0) == 0.0


class TestMetamorphic:
    def test_raising_any_cost_never_lowers_buy_fill_or_total(self) -> None:
        base = CAUSAL_PROXY_BASE
        ref = cost_breakdown(base, 100.0, "buy", 5.0, 1_000_000.0)
        for field in ("fee_rate", "half_spread_rate", "base_slippage_rate", "impact_coefficient"):
            higher = dataclasses.replace(base, **{field: getattr(base, field) + 0.001})
            bumped = cost_breakdown(higher, 100.0, "buy", 5.0, 1_000_000.0)
            assert bumped.total_cost >= ref.total_cost - 1e-12
            if field != "fee_rate":  # fee does not move the fill price
                assert bumped.fill_price >= ref.fill_price - 1e-12

    def test_reducing_max_participation_never_raises_the_cap(self) -> None:
        big = participation_quantity_cap(
            dataclasses.replace(CAUSAL_PROXY_BASE, max_participation=0.001), 100.0, 1e6
        )
        small = participation_quantity_cap(
            dataclasses.replace(CAUSAL_PROXY_BASE, max_participation=0.0005), 100.0, 1e6
        )
        assert small <= big

    def test_more_liquidity_never_lowers_the_cap(self) -> None:
        low = participation_quantity_cap(CAUSAL_PROXY_BASE, 100.0, 1e6)
        high = participation_quantity_cap(CAUSAL_PROXY_BASE, 100.0, 2e6)
        assert high >= low

    def test_more_liquidity_never_raises_impact(self) -> None:
        low_liq = cost_breakdown(CAUSAL_PROXY_BASE, 100.0, "buy", 5.0, 1e6)
        high_liq = cost_breakdown(CAUSAL_PROXY_BASE, 100.0, "buy", 5.0, 2e6)
        assert high_liq.impact_rate <= low_liq.impact_rate


class TestSolverInterface:
    def test_solver_prices_bind_scenario_and_liquidity(self) -> None:
        buy, sell, fee_rate, cap = solver_prices(CAUSAL_PROXY_BASE, 100.0, 1_000_000.0)
        assert fee_rate == CAUSAL_PROXY_BASE.fee_rate
        assert cap == pytest.approx(10.0)
        assert buy(1.0) == pytest.approx(fill_price(CAUSAL_PROXY_BASE, 100.0, "buy", 1.0, 1e6))
        assert sell(1.0) == pytest.approx(fill_price(CAUSAL_PROXY_BASE, 100.0, "sell", 1.0, 1e6))

    def test_compatibility_needs_no_liquidity(self) -> None:
        buy, _sell, _fee_rate, cap = solver_prices(COMPATIBILITY_V1, 100.0, None)
        assert cap == math.inf
        assert buy(3.0) == pytest.approx(100.05)  # no impact, needs no liquidity
