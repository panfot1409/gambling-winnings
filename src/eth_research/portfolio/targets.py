"""The long-only portfolio target contract and the reference allocation policies.

A :class:`PortfolioTarget` is a set of long-only fractional weights, one per instrument the target
allocates to: each weight is finite and in ``[0, 1]``, the weights sum to at most one within a
pinned tolerance, and the unallocated remainder is held as base-currency cash. There is no negative
weight, no gross exposure above one, no borrowed cash, and no synthetic short — the contract is
structurally long-only and cash-safe, so an accounting path built on it can never go leveraged.

The three reference policies (:func:`cash_target`, :func:`equal_weight_target`,
:func:`declared_weights_target`) are deterministic *plumbing* benchmarks that exercise the
accounting and solver machinery. They make no alpha claim, fit no parameters, and are not predictive
strategies; they exist so the simulator can be tested end to end against hand-computable weights.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from eth_research.api.serialization import CanonicalError, require_finite_float, require_list
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.tolerances import DEFAULT_TOLERANCES, PortfolioTolerances
from eth_research.portfolio.validation import domain_hash, exact_keys

__all__ = [
    "PortfolioTarget",
    "cash_target",
    "declared_weights_target",
    "equal_weight_target",
]


@dataclass(frozen=True)
class PortfolioTarget:
    """An immutable, long-only, canonically ordered set of fractional target weights."""

    weights: tuple[tuple[InstrumentId, float], ...]
    weight_tolerance: float = DEFAULT_TOLERANCES.weight

    def __post_init__(self) -> None:
        seen: set[str] = set()
        ordered: list[tuple[InstrumentId, float]] = []
        for instrument, weight in self.weights:
            if not isinstance(instrument, InstrumentId):
                raise CanonicalError("portfolio_target: each key must be an InstrumentId")
            require_finite_float(weight, f"portfolio_target.weight[{instrument.symbol}]")
            if not 0.0 <= weight <= 1.0:
                raise CanonicalError(
                    f"portfolio_target.weight[{instrument.symbol}]: must be within [0, 1] "
                    "(long-only, no leverage)"
                )
            key = instrument.instrument_id
            if key in seen:
                raise CanonicalError(
                    f"portfolio_target: duplicate instrument {instrument.symbol!r}"
                )
            seen.add(key)
            ordered.append((instrument, weight))
        ordered.sort(key=lambda pair: pair[0].instrument_id)
        total = sum(weight for _, weight in ordered)
        if total > 1.0 + self.weight_tolerance:
            raise CanonicalError(
                f"portfolio_target: gross weight {total!r} exceeds 1 "
                "(long-only with a base-currency cash remainder)"
            )
        object.__setattr__(self, "weights", tuple(ordered))

    @property
    def instruments(self) -> tuple[InstrumentId, ...]:
        return tuple(instrument for instrument, _ in self.weights)

    @property
    def gross_weight(self) -> float:
        """The total allocated fraction; the residual ``1 - gross_weight`` is base cash."""
        return sum(weight for _, weight in self.weights)

    @property
    def residual_cash_weight(self) -> float:
        return 1.0 - self.gross_weight

    def weight_for(self, instrument: InstrumentId) -> float:
        """This target's weight for ``instrument`` (zero if the target does not allocate to it)."""
        key = instrument.instrument_id
        for candidate, weight in self.weights:
            if candidate.instrument_id == key:
                return weight
        return 0.0

    def require_subset_of(self, active: Sequence[InstrumentId], *, field: str = "target") -> None:
        """Fail closed unless every allocated instrument is in the active tradable set."""
        active_ids = {instrument.instrument_id for instrument in active}
        for instrument, _ in self.weights:
            if instrument.instrument_id not in active_ids:
                raise CanonicalError(
                    f"{field}: allocates to {instrument.symbol!r}, which is not in the active "
                    "universe at this event"
                )

    def canonical(self) -> list[dict[str, Any]]:
        return [
            {"instrument": instrument.canonical(), "weight": weight}
            for instrument, weight in self.weights
        ]

    @property
    def fingerprint(self) -> str:
        return domain_hash("portfolio_target", self.canonical())

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "portfolio_target") -> PortfolioTarget:
        rows = require_list(data, field)
        weights: list[tuple[InstrumentId, float]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise CanonicalError(f"{field}[{index}]: expected an object")
            exact_keys(row, {"instrument", "weight"}, f"{field}[{index}]")
            instrument = InstrumentId.from_mapping(
                row["instrument"], field=f"{field}[{index}].instrument"
            )
            weight = require_finite_float(row["weight"], f"{field}[{index}].weight")
            weights.append((instrument, weight))
        return cls(weights=tuple(weights))


def cash_target(
    active: Sequence[InstrumentId], *, tolerances: PortfolioTolerances = DEFAULT_TOLERANCES
) -> PortfolioTarget:
    """The all-cash reference policy: allocate nothing, hold the full equity as base cash."""
    return PortfolioTarget(weights=(), weight_tolerance=tolerances.weight)


def equal_weight_target(
    active: Sequence[InstrumentId], *, tolerances: PortfolioTolerances = DEFAULT_TOLERANCES
) -> PortfolioTarget:
    """The equal-weight reference policy: ``1/N`` to each of the ``N`` active instruments."""
    count = len(active)
    if count == 0:
        return PortfolioTarget(weights=(), weight_tolerance=tolerances.weight)
    share = 1.0 / count
    return PortfolioTarget(
        weights=tuple((instrument, share) for instrument in active),
        weight_tolerance=tolerances.weight,
    )


def declared_weights_target(
    active: Sequence[InstrumentId],
    declared: Mapping[InstrumentId, float],
    *,
    tolerances: PortfolioTolerances = DEFAULT_TOLERANCES,
) -> PortfolioTarget:
    """The declared-weights reference policy: the caller's fixed weights over active instruments.

    Every declared instrument must be in ``active``; the :class:`PortfolioTarget` invariants (each
    weight in ``[0, 1]``, gross ``<= 1``) are enforced at construction.
    """
    active_ids = {instrument.instrument_id for instrument in active}
    for instrument in declared:
        if instrument.instrument_id not in active_ids:
            raise CanonicalError(
                f"declared_weights_target: {instrument.symbol!r} is not in the active universe"
            )
    return PortfolioTarget(weights=tuple(declared.items()), weight_tolerance=tolerances.weight)
