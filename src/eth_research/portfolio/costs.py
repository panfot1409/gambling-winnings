"""The execution-cost model: a transparent, causally-available decomposition per trade.

Every trade incurs a cost expressed in the base accounting currency and decomposed into named,
separately-reported, non-negative components — exchange fee, half-spread, base slippage,
lagged-liquidity market impact, and an optional FX-conversion charge. Each component is a function
of the absolute base notional traded and predeclared parameters only; the impact term additionally
uses the participation rate computed from *lagged* volume (strictly before the execution bar), never
the current bar's volume, so a cost can never depend on information the decision could not have had.

The parameters are validated at construction to be individually non-negative and jointly
*contractive*: the worst-case marginal cost rate (the derivative of total cost with respect to the
base notional) is strictly below one. That bound is what lets the shared-cash solver prove its
post-cost equity fixed point is unique — see :mod:`eth_research.portfolio.solver`. These are
illustrative research scenarios, not a venue-calibrated fee schedule.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from eth_research.api.serialization import CanonicalError, require_finite_float
from eth_research.portfolio.validation import (
    exact_keys,
    require_non_negative_finite_float,
    require_safe_token,
)

__all__ = ["CostBreakdown", "CostParameters", "trade_cost"]

# The sqrt-impact term contributes 1.5x its average rate to the marginal rate (d/dx of
# rate*sqrt(k*x)*x is 1.5*rate*sqrt(k*x)), so the contraction bound weights the impact cap by 1.5.
_IMPACT_MARGINAL_FACTOR = 1.5


@dataclass(frozen=True)
class CostBreakdown:
    """The base-currency cost of one trade, decomposed and reconciled."""

    currency: str
    fee: float
    spread: float
    slippage: float
    impact: float
    fx_conversion: float

    def __post_init__(self) -> None:
        require_safe_token(self.currency, "cost.currency")
        for name in ("fee", "spread", "slippage", "impact", "fx_conversion"):
            require_non_negative_finite_float(getattr(self, name), f"cost.{name}")

    @property
    def total(self) -> float:
        """The sum of every component — the total base-currency cost of the trade."""
        return self.fee + self.spread + self.slippage + self.impact + self.fx_conversion

    def canonical(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "fee": self.fee,
            "spread": self.spread,
            "slippage": self.slippage,
            "impact": self.impact,
            "fx_conversion": self.fx_conversion,
            "total": self.total,
        }


@dataclass(frozen=True)
class CostParameters:
    """Predeclared, contractive cost parameters for one cost scenario."""

    scenario: str
    fee_rate: float = 0.0
    half_spread: float = 0.0
    base_slippage: float = 0.0
    impact_coefficient: float = 0.0
    impact_cap: float = 0.0
    fx_conversion_rate: float = 0.0

    def __post_init__(self) -> None:
        require_safe_token(self.scenario, "costs.scenario")
        for name in (
            "fee_rate",
            "half_spread",
            "base_slippage",
            "impact_coefficient",
            "impact_cap",
            "fx_conversion_rate",
        ):
            require_non_negative_finite_float(getattr(self, name), f"costs.{name}")
        bound = self.marginal_rate_bound()
        if not bound < 1.0:
            raise CanonicalError(
                f"costs.{self.scenario}: worst-case marginal cost rate {bound!r} is not below 1; "
                "the cost model must be contractive for the shared-cash equity solve to converge "
                "to a unique post-cost equity"
            )

    def marginal_rate_bound(self) -> float:
        """The worst-case marginal cost rate (d total-cost / d base-notional), an upper bound.

        The linear components contribute their rate directly; the sqrt-impact term contributes at
        most ``1.5 * impact_cap`` (its rate is capped and its marginal is 1.5x its average). The
        FX-conversion rate applies to at most the whole notional. This bound must be below one so
        ``total_cost(E)`` is a contraction and the post-cost equity fixed point is unique.
        """
        return (
            self.fee_rate
            + self.half_spread
            + self.base_slippage
            + _IMPACT_MARGINAL_FACTOR * self.impact_cap
            + self.fx_conversion_rate
        )

    def canonical(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "fee_rate": self.fee_rate,
            "half_spread": self.half_spread,
            "base_slippage": self.base_slippage,
            "impact_coefficient": self.impact_coefficient,
            "impact_cap": self.impact_cap,
            "fx_conversion_rate": self.fx_conversion_rate,
        }

    @classmethod
    def compatibility_v1(cls) -> CostParameters:
        """The scenario that reproduces the accepted single-asset ``compatibility_v1`` costs.

        Fee 0.1%, no spread, 0.05% base slippage, no impact, no FX conversion — the exact settings
        the M4A/M3B compatibility oracle pins, so a single-asset M4B universe matches the accepted
        fractional engine.
        """
        return cls(
            scenario="compatibility_v1",
            fee_rate=0.001,
            half_spread=0.0,
            base_slippage=0.0005,
            impact_coefficient=0.0,
            impact_cap=0.0,
            fx_conversion_rate=0.0,
        )

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "costs") -> CostParameters:
        if not isinstance(data, dict):
            raise CanonicalError(f"{field}: expected an object")
        allowed = {
            "scenario",
            "fee_rate",
            "half_spread",
            "base_slippage",
            "impact_coefficient",
            "impact_cap",
            "fx_conversion_rate",
        }
        exact_keys(data, allowed, field)
        return cls(
            scenario=require_safe_token(data["scenario"], f"{field}.scenario"),
            fee_rate=require_finite_float(data["fee_rate"], f"{field}.fee_rate"),
            half_spread=require_finite_float(data["half_spread"], f"{field}.half_spread"),
            base_slippage=require_finite_float(data["base_slippage"], f"{field}.base_slippage"),
            impact_coefficient=require_finite_float(
                data["impact_coefficient"], f"{field}.impact_coefficient"
            ),
            impact_cap=require_finite_float(data["impact_cap"], f"{field}.impact_cap"),
            fx_conversion_rate=require_finite_float(
                data["fx_conversion_rate"], f"{field}.fx_conversion_rate"
            ),
        )


def trade_cost(
    params: CostParameters,
    notional_base: float,
    *,
    participation: float = 0.0,
    apply_fx_conversion: bool = False,
    currency: str,
) -> CostBreakdown:
    """The decomposed base-currency cost of a trade of ``notional_base`` (absolute) base units.

    ``participation`` is the lagged-liquidity participation rate (local trade notional divided by
    the instrument's lagged dollar volume), computed by the caller from information strictly before
    the execution bar. ``apply_fx_conversion`` charges the FX-conversion rate when the instrument's
    quote currency differs from the base currency. A zero notional yields an all-zero breakdown.
    """
    magnitude = require_non_negative_finite_float(notional_base, "trade_cost.notional_base")
    part = require_non_negative_finite_float(participation, "trade_cost.participation")
    fee = params.fee_rate * magnitude
    spread = params.half_spread * magnitude
    slippage = params.base_slippage * magnitude
    impact_rate = min(params.impact_cap, params.impact_coefficient * math.sqrt(part))
    impact = impact_rate * magnitude
    fx_conversion = params.fx_conversion_rate * magnitude if apply_fx_conversion else 0.0
    return CostBreakdown(
        currency=currency,
        fee=fee,
        spread=spread,
        slippage=slippage,
        impact=impact,
        fx_conversion=fx_conversion,
    )
