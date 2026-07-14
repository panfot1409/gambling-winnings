"""Predeclared cost-stress scenarios: pinned, ordered, no frictionless headline."""

from __future__ import annotations

import pytest

from eth_research.backtest import CostModel
from eth_research.costs import COST_SCENARIOS, CostScenario, cost_scenario


def test_exactly_three_scenarios_in_fixed_order() -> None:
    assert tuple(s.name for s in COST_SCENARIOS) == ("base", "stressed", "severe")


def test_pinned_rates() -> None:
    rates = {s.name: (s.fee_rate, s.slippage_rate) for s in COST_SCENARIOS}
    assert rates == {
        "base": (0.001, 0.0005),
        "stressed": (0.002, 0.001),
        "severe": (0.005, 0.0025),
    }


def test_no_frictionless_scenario() -> None:
    for scenario in COST_SCENARIOS:
        assert scenario.fee_rate > 0.0
        assert scenario.slippage_rate > 0.0


def test_costs_are_monotonically_increasing() -> None:
    fees = [s.fee_rate for s in COST_SCENARIOS]
    slips = [s.slippage_rate for s in COST_SCENARIOS]
    assert fees == sorted(fees)
    assert slips == sorted(slips)
    assert len(set(fees)) == 3


def test_cost_model_round_trips() -> None:
    for scenario in COST_SCENARIOS:
        model = scenario.cost_model()
        assert isinstance(model, CostModel)
        assert model.fee_rate == scenario.fee_rate
        assert model.slippage_rate == scenario.slippage_rate


def test_lookup_by_name() -> None:
    assert cost_scenario("severe").fee_rate == 0.005
    with pytest.raises(ValueError, match="unknown cost scenario"):
        cost_scenario("frictionless")


def test_unknown_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="scenario name must be one of"):
        CostScenario(name="frictionless", fee_rate=0.0, slippage_rate=0.0)


def test_out_of_range_rate_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be in"):
        CostScenario(name="base", fee_rate=1.5, slippage_rate=0.0005)
