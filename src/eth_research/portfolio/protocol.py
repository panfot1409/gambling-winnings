"""The portfolio protocol: the frozen, fingerprinted declaration of a simulation run.

A :class:`PortfolioProtocol` pins everything the engine needs that is *not* market evidence: the
base accounting currency, the opening cash, which reference allocation policy to follow, the
declared weights (only when the policy is ``declared_weights``), the cost scenario, the staleness
policy, and the numeric tolerances. It serializes to canonical JSON and carries a domain-separated
fingerprint, so a run is reproducible from its protocol plus its evidence and reconciles exactly.

The three reference policies (:data:`REFERENCE_POLICIES`) are deterministic plumbing benchmarks —
they make no alpha claim and fit no parameters; they exist so the accounting, solver, and
attribution machinery can be exercised end to end against hand-computable weights.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from eth_research.api.serialization import (
    CanonicalError,
    require_finite_float,
    require_int,
    require_list,
    require_mapping,
    require_str,
)
from eth_research.portfolio.costs import CostParameters
from eth_research.portfolio.currencies import require_currency_code
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.targets import (
    PortfolioTarget,
    cash_target,
    declared_weights_target,
    equal_weight_target,
)
from eth_research.portfolio.tolerances import DEFAULT_TOLERANCES, PortfolioTolerances
from eth_research.portfolio.validation import domain_hash, exact_keys, require_positive_finite_float
from eth_research.portfolio.valuation import StalenessPolicy

__all__ = ["REFERENCE_POLICIES", "PortfolioProtocol", "ReferencePolicy", "build_target"]

#: The exact reference-policy vocabulary the engine can dispatch to.
ReferencePolicy = Literal["cash", "declared_weights", "equal_weight"]
REFERENCE_POLICIES: tuple[ReferencePolicy, ...] = ("cash", "declared_weights", "equal_weight")

_SCHEMA_VERSION = 1
_PROTOCOL_FIELDS = {
    "schema_version",
    "base_currency",
    "initial_cash",
    "policy",
    "declared_weights",
    "cost_scenario",
    "staleness",
    "tolerances",
}
_STALENESS_FIELDS = {"max_staleness_seconds"}
_TOLERANCE_FIELDS = {
    "cash",
    "quantity",
    "weight",
    "solver",
    "no_trade",
    "notional",
    "max_iterations",
}
_WEIGHT_FIELDS = {"instrument", "weight"}


@dataclass(frozen=True)
class PortfolioProtocol:
    """The immutable, fingerprinted declaration of one simulation run's non-market parameters."""

    base_currency: str
    initial_cash: float
    policy: ReferencePolicy
    cost_scenario: CostParameters
    staleness: StalenessPolicy
    declared_weights: tuple[tuple[InstrumentId, float], ...] = ()
    tolerances: PortfolioTolerances = DEFAULT_TOLERANCES
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION:
            raise CanonicalError(
                f"protocol.schema_version: expected {_SCHEMA_VERSION}, got {self.schema_version!r}"
            )
        require_currency_code(self.base_currency, "protocol.base_currency")
        require_positive_finite_float(self.initial_cash, "protocol.initial_cash")
        if self.policy not in REFERENCE_POLICIES:
            raise CanonicalError(
                f"protocol.policy: expected one of {list(REFERENCE_POLICIES)}, got {self.policy!r}"
            )
        if not isinstance(self.cost_scenario, CostParameters):
            raise CanonicalError("protocol.cost_scenario: expected CostParameters")
        if not isinstance(self.staleness, StalenessPolicy):
            raise CanonicalError("protocol.staleness: expected StalenessPolicy")
        if not isinstance(self.tolerances, PortfolioTolerances):
            raise CanonicalError("protocol.tolerances: expected PortfolioTolerances")
        self._validate_declared_weights()

    def _validate_declared_weights(self) -> None:
        declared = tuple(self.declared_weights)
        if self.policy == "declared_weights":
            if not declared:
                raise CanonicalError(
                    "protocol.declared_weights: must be non-empty when policy is declared_weights"
                )
        elif declared:
            raise CanonicalError(
                f"protocol.declared_weights: must be empty when policy is {self.policy!r}"
            )
        seen: set[str] = set()
        gross = 0.0
        for instrument, weight in declared:
            if not isinstance(instrument, InstrumentId):
                raise CanonicalError("protocol.declared_weights: each key must be an InstrumentId")
            require_finite_float(weight, f"protocol.declared_weights[{instrument.symbol}]")
            if not 0.0 <= weight <= 1.0:
                raise CanonicalError(
                    f"protocol.declared_weights[{instrument.symbol}]: must be within [0, 1]"
                )
            key = instrument.instrument_id
            if key in seen:
                raise CanonicalError(
                    f"protocol.declared_weights: duplicate instrument {instrument.symbol!r}"
                )
            seen.add(key)
            gross += weight
        if gross > 1.0 + self.tolerances.weight:
            raise CanonicalError(
                f"protocol.declared_weights: gross weight {gross!r} exceeds 1 (long-only)"
            )

    def canonical(self) -> dict[str, Any]:
        """The canonical mapping (declared weights, cost, staleness, and tolerances inlined)."""
        return {
            "schema_version": self.schema_version,
            "base_currency": self.base_currency,
            "initial_cash": self.initial_cash,
            "policy": self.policy,
            "declared_weights": [
                {"instrument": instrument.canonical(), "weight": weight}
                for instrument, weight in self.declared_weights
            ],
            "cost_scenario": self.cost_scenario.canonical(),
            "staleness": {"max_staleness_seconds": self.staleness.max_staleness_seconds},
            "tolerances": {
                "cash": self.tolerances.cash,
                "quantity": self.tolerances.quantity,
                "weight": self.tolerances.weight,
                "solver": self.tolerances.solver,
                "no_trade": self.tolerances.no_trade,
                "notional": self.tolerances.notional,
                "max_iterations": self.tolerances.max_iterations,
            },
        }

    @property
    def fingerprint(self) -> str:
        """The domain-separated content hash of this protocol (stable across runtimes)."""
        return domain_hash("portfolio_protocol", self.canonical())

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "portfolio_protocol") -> PortfolioProtocol:
        """Construct from an untrusted mapping, rejecting unknown or missing keys."""
        mapping = require_mapping(data, field)
        exact_keys(mapping, _PROTOCOL_FIELDS, field)
        policy = require_str(mapping["policy"], f"{field}.policy")
        if policy not in REFERENCE_POLICIES:
            raise CanonicalError(
                f"{field}.policy: expected one of {list(REFERENCE_POLICIES)}, got {policy!r}"
            )
        return cls(
            base_currency=require_str(mapping["base_currency"], f"{field}.base_currency"),
            initial_cash=require_finite_float(mapping["initial_cash"], f"{field}.initial_cash"),
            policy=policy,
            cost_scenario=CostParameters.from_mapping(
                mapping["cost_scenario"], field=f"{field}.cost_scenario"
            ),
            staleness=_staleness_from_mapping(mapping["staleness"], f"{field}.staleness"),
            declared_weights=_declared_from_mapping(
                mapping["declared_weights"], f"{field}.declared_weights"
            ),
            tolerances=_tolerances_from_mapping(mapping["tolerances"], f"{field}.tolerances"),
            schema_version=require_int(mapping["schema_version"], f"{field}.schema_version"),
        )


def _staleness_from_mapping(data: Any, field: str) -> StalenessPolicy:
    mapping = require_mapping(data, field)
    exact_keys(mapping, _STALENESS_FIELDS, field)
    seconds = require_finite_float(
        mapping["max_staleness_seconds"], f"{field}.max_staleness_seconds"
    )
    return StalenessPolicy(max_staleness_seconds=seconds)


def _tolerances_from_mapping(data: Any, field: str) -> PortfolioTolerances:
    mapping = require_mapping(data, field)
    exact_keys(mapping, _TOLERANCE_FIELDS, field)
    try:
        return PortfolioTolerances(
            cash=require_finite_float(mapping["cash"], f"{field}.cash"),
            quantity=require_finite_float(mapping["quantity"], f"{field}.quantity"),
            weight=require_finite_float(mapping["weight"], f"{field}.weight"),
            solver=require_finite_float(mapping["solver"], f"{field}.solver"),
            no_trade=require_finite_float(mapping["no_trade"], f"{field}.no_trade"),
            notional=require_finite_float(mapping["notional"], f"{field}.notional"),
            max_iterations=require_int(mapping["max_iterations"], f"{field}.max_iterations"),
        )
    except ValueError as exc:
        raise CanonicalError(f"{field}: {exc}") from exc


def _declared_from_mapping(data: Any, field: str) -> tuple[tuple[InstrumentId, float], ...]:
    rows = require_list(data, field)
    weights: list[tuple[InstrumentId, float]] = []
    for index, row in enumerate(rows):
        mapping = require_mapping(row, f"{field}[{index}]")
        exact_keys(mapping, _WEIGHT_FIELDS, f"{field}[{index}]")
        instrument = InstrumentId.from_mapping(
            mapping["instrument"], field=f"{field}[{index}].instrument"
        )
        weight = require_finite_float(mapping["weight"], f"{field}[{index}].weight")
        weights.append((instrument, weight))
    return tuple(weights)


def build_target(
    protocol: PortfolioProtocol, active_instruments: Sequence[InstrumentId]
) -> PortfolioTarget:
    """Dispatch the protocol's reference policy over ``active_instruments`` to a target.

    ``cash`` allocates nothing; ``equal_weight`` splits ``1/N`` over the active set;
    ``declared_weights`` filters the protocol's declared weights down to the active set (an
    instrument declared but no longer active is simply dropped from this event's target).
    """
    tolerances = protocol.tolerances
    if protocol.policy == "cash":
        return cash_target(active_instruments, tolerances=tolerances)
    if protocol.policy == "equal_weight":
        return equal_weight_target(active_instruments, tolerances=tolerances)
    active_ids = {instrument.instrument_id for instrument in active_instruments}
    filtered = {
        instrument: weight
        for instrument, weight in protocol.declared_weights
        if instrument.instrument_id in active_ids
    }
    return declared_weights_target(active_instruments, filtered, tolerances=tolerances)
