"""Predeclared cost-stress scenarios for the Milestone 3A walk-forward.

Every strategy is evaluated under **every** scenario; no scenario is ever
selected after seeing results. The three scenarios are pinned here and in
the committed walk-forward protocol — there is deliberately **no**
frictionless headline scenario, so a cost-free number can never become the
reported result.

Each scenario reuses the Milestone 1 :class:`CostModel` (proportional fee
on fill notional plus directional open-price slippage); the accounting,
reconciliation, and terminal-liquidation rules are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.backtest import CostModel

BASE_SCENARIO: str = "base"
STRESSED_SCENARIO: str = "stressed"
SEVERE_SCENARIO: str = "severe"
_SCENARIO_NAMES: tuple[str, ...] = (BASE_SCENARIO, STRESSED_SCENARIO, SEVERE_SCENARIO)


@dataclass(frozen=True)
class CostScenario:
    """One named, pinned cost scenario."""

    name: str
    fee_rate: float
    slippage_rate: float

    def __post_init__(self) -> None:
        if self.name not in _SCENARIO_NAMES:
            raise ValueError(f"scenario name must be one of {_SCENARIO_NAMES}, got {self.name!r}")
        # Delegates rate-range validation to CostModel (0 <= rate < 1).
        CostModel(fee_rate=self.fee_rate, slippage_rate=self.slippage_rate)

    def cost_model(self) -> CostModel:
        return CostModel(fee_rate=self.fee_rate, slippage_rate=self.slippage_rate)


COST_SCENARIOS: tuple[CostScenario, ...] = (
    CostScenario(name=BASE_SCENARIO, fee_rate=0.001, slippage_rate=0.0005),
    CostScenario(name=STRESSED_SCENARIO, fee_rate=0.002, slippage_rate=0.001),
    CostScenario(name=SEVERE_SCENARIO, fee_rate=0.005, slippage_rate=0.0025),
)
"""The three predeclared scenarios, in fixed order (base → stressed → severe)."""


def cost_scenario(name: str) -> CostScenario:
    """Return the pinned scenario with ``name`` (raises on an unknown name)."""
    for scenario in COST_SCENARIOS:
        if scenario.name == name:
            return scenario
    raise ValueError(f"unknown cost scenario {name!r}; expected one of {_SCENARIO_NAMES}")
