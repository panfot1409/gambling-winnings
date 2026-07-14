"""Execution-cost model and frozen scenarios (Milestone 3B, Phase 8).

A **deterministic causal liquidity-and-impact research proxy** on daily candles —
explicitly *not* a calibrated venue model (this project has daily OHLCV only, no
quotes or order book). Costs are directional and transparent: the fill price
carries only spread + base slippage + a volume-impact proxy; the fee is applied
separately to the fill notional and is never mixed into the price.

See ``docs/M3B_EXECUTION_COST_SPEC.md``. Three scenarios are frozen ahead of any
result: ``compatibility_v1`` (spread/impact off, for exact parity with the binary
engine), ``causal_proxy_base``, and ``causal_proxy_stressed``. Impact uses the
lagged (through ``t-1``) median dollar volume from Phase 7; a scenario with a
participation constraint and no lagged liquidity yields no fill, never an
infinite impact.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from eth_research.fractional.accounting import Side

PriceFn = Callable[[float], float]


class CostModelError(Exception):
    """A cost scenario or state violated a construction invariant."""


@dataclass(frozen=True)
class CostScenario:
    """A frozen, predeclared execution-cost scenario.

    ``max_participation`` is ``None`` when the participation (liquidity)
    constraint is disabled; otherwise it is the maximum fraction of lagged daily
    dollar volume a single bar's fill may consume.
    """

    name: str
    fee_rate: float
    half_spread_rate: float
    base_slippage_rate: float
    impact_coefficient: float
    impact_cap: float
    liquidity_lookback: int
    liquidity_min_observations: int
    max_participation: float | None

    def __post_init__(self) -> None:
        for label, rate in (
            ("fee_rate", self.fee_rate),
            ("half_spread_rate", self.half_spread_rate),
            ("base_slippage_rate", self.base_slippage_rate),
            ("impact_coefficient", self.impact_coefficient),
            ("impact_cap", self.impact_cap),
        ):
            if not math.isfinite(rate) or rate < 0.0:
                raise CostModelError(f"{label} must be a non-negative finite rate, got {rate!r}")
        if self.half_spread_rate + self.base_slippage_rate + self.impact_cap >= 1.0:
            raise CostModelError(
                f"scenario {self.name!r}: spread + slippage + impact_cap must be < 1"
            )
        if self.liquidity_lookback <= 0 or self.liquidity_min_observations <= 0:
            raise CostModelError("liquidity lookback and min_observations must be positive")
        if self.max_participation is not None and self.max_participation <= 0.0:
            raise CostModelError("max_participation must be positive or None")


COMPATIBILITY_V1 = CostScenario(
    name="compatibility_v1",
    fee_rate=0.001,
    half_spread_rate=0.0,
    base_slippage_rate=0.0005,
    impact_coefficient=0.0,
    impact_cap=0.0,
    liquidity_lookback=30,
    liquidity_min_observations=30,
    max_participation=None,
)
CAUSAL_PROXY_BASE = CostScenario(
    name="causal_proxy_base",
    fee_rate=0.001,
    half_spread_rate=0.00025,
    base_slippage_rate=0.0005,
    impact_coefficient=0.01,
    impact_cap=0.005,
    liquidity_lookback=30,
    liquidity_min_observations=30,
    max_participation=0.001,
)
CAUSAL_PROXY_STRESSED = CostScenario(
    name="causal_proxy_stressed",
    fee_rate=0.002,
    half_spread_rate=0.0005,
    base_slippage_rate=0.001,
    impact_coefficient=0.03,
    impact_cap=0.015,
    liquidity_lookback=30,
    liquidity_min_observations=30,
    max_participation=0.0005,
)
SCENARIOS: tuple[CostScenario, ...] = (COMPATIBILITY_V1, CAUSAL_PROXY_BASE, CAUSAL_PROXY_STRESSED)
SCENARIOS_BY_NAME: dict[str, CostScenario] = {s.name: s for s in SCENARIOS}


@dataclass(frozen=True)
class CostBreakdown:
    """The exact additive cost decomposition of one fill (each component >= 0).

    ``price_shortfall == half_spread_cost + base_slippage_cost + impact_cost`` and
    ``total_cost == fee_cost + price_shortfall`` hold exactly (up to float noise).
    """

    side: Side
    quantity: float
    reference_price: float
    reference_notional: float
    participation: float | None
    impact_rate: float
    fill_price: float
    fill_notional: float
    fee_cost: float
    half_spread_cost: float
    base_slippage_cost: float
    impact_cost: float
    price_shortfall: float
    total_cost: float


def _impact_rate(
    scenario: CostScenario, reference_notional: float, lagged_dollar_volume: float | None
) -> tuple[float, float | None]:
    """Return ``(impact_rate, participation)``; participation is ``None`` when impact is off."""
    if scenario.impact_coefficient == 0.0:
        return 0.0, None
    if lagged_dollar_volume is None or lagged_dollar_volume <= 0.0:
        raise CostModelError("impact requires positive lagged dollar volume")
    if not math.isfinite(lagged_dollar_volume):
        raise CostModelError(f"lagged dollar volume is not finite: {lagged_dollar_volume!r}")
    participation = reference_notional / lagged_dollar_volume
    rate = min(scenario.impact_cap, scenario.impact_coefficient * math.sqrt(participation))
    return rate, participation


def _concession_rate(scenario: CostScenario, impact_rate: float) -> float:
    total = scenario.half_spread_rate + scenario.base_slippage_rate + impact_rate
    if total >= 1.0:
        raise CostModelError(
            f"total directional price concession {total!r} must be < 1 (scenario {scenario.name!r})"
        )
    return total


def fill_price(
    scenario: CostScenario,
    reference_price: float,
    side: Side,
    quantity: float,
    lagged_dollar_volume: float | None,
) -> float:
    """Directional fill price: buy pays ``P*(1+concession)``, sell receives ``P*(1-concession)``."""
    if reference_price <= 0.0:
        raise CostModelError(f"reference price must be positive, got {reference_price!r}")
    if quantity < 0.0:
        raise CostModelError(f"quantity must be non-negative, got {quantity!r}")
    reference_notional = quantity * reference_price
    impact_rate, _ = _impact_rate(scenario, reference_notional, lagged_dollar_volume)
    concession = _concession_rate(scenario, impact_rate)
    if side == "buy":
        return reference_price * (1.0 + concession)
    if side == "sell":
        return reference_price * (1.0 - concession)
    raise CostModelError(f"unknown side {side!r}")  # pragma: no cover - closed Literal


def cost_breakdown(
    scenario: CostScenario,
    reference_price: float,
    side: Side,
    quantity: float,
    lagged_dollar_volume: float | None,
) -> CostBreakdown:
    """The full additive cost decomposition of a fill of ``quantity`` ETH."""
    if quantity < 0.0:
        raise CostModelError(f"quantity must be non-negative, got {quantity!r}")
    reference_notional = quantity * reference_price
    impact_rate, participation = _impact_rate(scenario, reference_notional, lagged_dollar_volume)
    _concession_rate(scenario, impact_rate)  # validate < 1
    price = fill_price(scenario, reference_price, side, quantity, lagged_dollar_volume)
    fill_notional = quantity * price

    half_spread_cost = reference_notional * scenario.half_spread_rate
    base_slippage_cost = reference_notional * scenario.base_slippage_rate
    impact_cost = reference_notional * impact_rate
    price_shortfall = abs(fill_notional - reference_notional)
    fee_cost = fill_notional * scenario.fee_rate
    total_cost = fee_cost + price_shortfall
    return CostBreakdown(
        side=side,
        quantity=quantity,
        reference_price=reference_price,
        reference_notional=reference_notional,
        participation=participation,
        impact_rate=impact_rate,
        fill_price=price,
        fill_notional=fill_notional,
        fee_cost=fee_cost,
        half_spread_cost=half_spread_cost,
        base_slippage_cost=base_slippage_cost,
        impact_cost=impact_cost,
        price_shortfall=price_shortfall,
        total_cost=total_cost,
    )


def participation_quantity_cap(
    scenario: CostScenario, reference_price: float, lagged_dollar_volume: float | None
) -> float:
    """Maximum ETH tradable this bar under the participation constraint.

    ``inf`` when the constraint is disabled; ``0`` when it is enabled but no
    lagged liquidity is available (no fill). Equality at the cap is permitted.
    """
    if reference_price <= 0.0:
        raise CostModelError(f"reference price must be positive, got {reference_price!r}")
    if scenario.max_participation is None:
        return math.inf
    if lagged_dollar_volume is None or lagged_dollar_volume <= 0.0:
        return 0.0
    if not math.isfinite(lagged_dollar_volume):
        raise CostModelError(f"lagged dollar volume is not finite: {lagged_dollar_volume!r}")
    max_reference_notional = scenario.max_participation * lagged_dollar_volume
    return max_reference_notional / reference_price


def solver_prices(
    scenario: CostScenario, reference_price: float, lagged_dollar_volume: float | None
) -> tuple[PriceFn, PriceFn, float, float]:
    """Bind ``(buy_price(x), sell_price(x), fee_rate, participation_cap)`` for the solver."""

    def buy(x: float) -> float:
        return fill_price(scenario, reference_price, "buy", x, lagged_dollar_volume)

    def sell(x: float) -> float:
        return fill_price(scenario, reference_price, "sell", x, lagged_dollar_volume)

    cap = participation_quantity_cap(scenario, reference_price, lagged_dollar_volume)
    return buy, sell, scenario.fee_rate, cap
