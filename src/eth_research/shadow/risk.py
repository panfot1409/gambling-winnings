"""The risk-limit engine: a pure clamp between a candidate's intent and the paper book.

Before any signal is accounted, it passes the risk engine, which reduces the requested exposure to
what the pre-set limits allow and reports which limits bound:

* ``max_target_weight`` — a hard exposure cap. Requesting more than this is a *breach* (the runner
  trips the latching kill switch on a breach);
* ``max_weight_step`` — a per-bar turnover throttle. Moving the weight faster than this is
  *throttled* (clamped) but is not itself a breach.

The engine is a pure function of ``(requested_weight, current_weight)`` — no state, no clock, no
I/O — so its decisions are deterministic and independently checkable. It never *increases* exposure.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.shadow.domain import ShadowDomainError
from eth_research.v2.strict import (
    require_exact_keys,
    require_mapping,
    require_unit_interval,
)

_LIMITS_KEYS = frozenset({"max_target_weight", "max_weight_step"})
MAX_TARGET_WEIGHT_LIMIT: str = "max_target_weight"
MAX_WEIGHT_STEP_LIMIT: str = "max_weight_step"


class RiskError(ShadowDomainError):
    """A risk-limit configuration was malformed."""


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """The pre-set exposure cap and per-bar turnover throttle (both long-only, in ``[0, 1]``)."""

    max_target_weight: float
    max_weight_step: float

    @staticmethod
    def parse(label: str, value: object) -> RiskLimits:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _LIMITS_KEYS)
        return RiskLimits(
            max_target_weight=require_unit_interval(
                f"{label}.max_target_weight", obj["max_target_weight"]
            ),
            max_weight_step=require_unit_interval(
                f"{label}.max_weight_step", obj["max_weight_step"]
            ),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "max_target_weight": self.max_target_weight,
            "max_weight_step": self.max_weight_step,
        }


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """The outcome of clamping one requested weight against the limits."""

    requested_weight: float
    approved_weight: float
    breached_limits: tuple[str, ...]
    throttled_limits: tuple[str, ...]

    @property
    def is_breach(self) -> bool:
        return bool(self.breached_limits)

    def to_canonical(self) -> dict[str, object]:
        return {
            "requested_weight": self.requested_weight,
            "approved_weight": self.approved_weight,
            "breached_limits": list(self.breached_limits),
            "throttled_limits": list(self.throttled_limits),
        }


@dataclass(frozen=True, slots=True)
class RiskLimitEngine:
    """Applies :class:`RiskLimits` to a requested weight given the current weight (pure)."""

    limits: RiskLimits

    def evaluate(self, *, requested_weight: float, current_weight: float) -> RiskDecision:
        requested = require_unit_interval("requested_weight", requested_weight)
        current = require_unit_interval("current_weight", current_weight)

        breached: list[str] = []
        throttled: list[str] = []
        approved = requested

        # Hard exposure cap: exceeding it is a breach, and the weight is clamped down.
        if approved > self.limits.max_target_weight:
            breached.append(MAX_TARGET_WEIGHT_LIMIT)
            approved = self.limits.max_target_weight

        # Per-bar turnover throttle: limit how far the weight may move from where it is now.
        step = approved - current
        if step > self.limits.max_weight_step:
            throttled.append(MAX_WEIGHT_STEP_LIMIT)
            approved = current + self.limits.max_weight_step
        elif step < -self.limits.max_weight_step:
            throttled.append(MAX_WEIGHT_STEP_LIMIT)
            approved = current - self.limits.max_weight_step

        return RiskDecision(
            requested_weight=requested,
            approved_weight=approved,
            breached_limits=tuple(breached),
            throttled_limits=tuple(throttled),
        )
