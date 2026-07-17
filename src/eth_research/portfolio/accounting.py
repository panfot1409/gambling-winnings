"""The immutable portfolio accounting ledger: fills and cash/holding state.

A :class:`PortfolioState` is an immutable snapshot of base-currency cash and per-instrument local
holding quantities. A :class:`Fill` is one executed trade. :meth:`PortfolioState.apply_fill` returns
a *new* state after moving cash by the signed base notional plus the trade's total cost and moving
the holding by the signed local quantity — and it fails closed if the result would take cash or any
holding below zero beyond the pinned tolerance. Long-only, cash-safe accounting is therefore an
enforced invariant of every transition, not a hope: there is no code path that produces negative
cash (borrowing) or a negative quantity (a short).

The ledger holds *quantities*, not values; marking holdings to a base-currency value is the job of
the valuation layer, which supplies causal marks. Every state and fill serializes to canonical JSON
and carries a domain-separated hash so a run's accounting can be reconciled exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import pandas as pd

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio._time import iso_utc
from eth_research.portfolio.costs import CostBreakdown
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.tolerances import DEFAULT_TOLERANCES, PortfolioTolerances
from eth_research.portfolio.validation import (
    domain_hash,
    require_non_negative_finite_float,
    require_safe_token,
)

__all__ = ["Fill", "PortfolioState", "Position"]

_SIDES = ("buy", "sell", "hold")


@dataclass(frozen=True)
class Fill:
    """One executed trade, in both local and base-currency terms."""

    event_id: str
    event_time: pd.Timestamp
    instrument: InstrumentId
    side: str
    local_quantity: float  # signed: + buy, - sell
    fill_price: float  # local quote price per unit
    fx_rate: float  # quote -> base
    base_notional: float  # signed base value = local_quantity * fill_price * fx_rate
    cost: CostBreakdown

    def __post_init__(self) -> None:
        require_safe_token(self.event_id, "fill.event_id")
        if self.side not in _SIDES:
            raise CanonicalError(f"fill.side: expected one of {list(_SIDES)}, got {self.side!r}")
        for name in ("local_quantity", "fill_price", "fx_rate", "base_notional"):
            value = getattr(self, name)
            if not isinstance(value, float):
                raise CanonicalError(f"fill.{name}: expected a float")
        if not self.event_time.tz:
            raise CanonicalError("fill.event_time: must be timezone-aware UTC")

    def canonical(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_time": iso_utc(self.event_time),
            "instrument": self.instrument.canonical(),
            "side": self.side,
            "local_quantity": self.local_quantity,
            "fill_price": self.fill_price,
            "fx_rate": self.fx_rate,
            "base_notional": self.base_notional,
            "cost": self.cost.canonical(),
        }

    @property
    def fingerprint(self) -> str:
        return domain_hash("fill", self.canonical())


@dataclass(frozen=True)
class Position:
    """A held quantity of one instrument in its local units."""

    instrument: InstrumentId
    quantity: float

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, float):
            raise CanonicalError("position.quantity: expected a float")

    def canonical(self) -> dict[str, Any]:
        return {"instrument": self.instrument.canonical(), "quantity": self.quantity}


@dataclass(frozen=True)
class PortfolioState:
    """An immutable snapshot of base cash and per-instrument local holdings."""

    base_currency: str
    base_cash: float
    positions: tuple[Position, ...]
    tolerances: PortfolioTolerances = DEFAULT_TOLERANCES

    def __post_init__(self) -> None:
        require_safe_token(self.base_currency, "state.base_currency")
        if self.base_cash < -self.tolerances.cash:
            raise CanonicalError(f"state.base_cash: {self.base_cash!r} is negative (not cash-safe)")
        seen: set[str] = set()
        ordered = sorted(self.positions, key=lambda p: p.instrument.instrument_id)
        for position in ordered:
            key = position.instrument.instrument_id
            if key in seen:
                raise CanonicalError(
                    f"state: duplicate position for {position.instrument.symbol!r}"
                )
            seen.add(key)
            if position.quantity < -self.tolerances.quantity:
                raise CanonicalError(
                    f"state: holding of {position.instrument.symbol!r} is negative (not long-only)"
                )
        object.__setattr__(self, "positions", tuple(ordered))

    def quantity_of(self, instrument: InstrumentId) -> float:
        key = instrument.instrument_id
        for position in self.positions:
            if position.instrument.instrument_id == key:
                return position.quantity
        return 0.0

    def with_cash(self, base_cash: float) -> PortfolioState:
        return replace(self, base_cash=base_cash)

    def apply_fill(self, fill: Fill) -> PortfolioState:
        """Return a new state after ``fill``: move cash by ``-(base_notional + cost)`` and the
        holding by the signed local quantity. Fails closed if cash or the holding goes negative."""
        if fill.side == "hold":
            return self
        new_cash = self.base_cash - fill.base_notional - fill.cost.total
        if new_cash < -self.tolerances.cash:
            raise CanonicalError(
                f"apply_fill: cash would go negative ({new_cash!r}); the portfolio is cash-safe"
            )
        key = fill.instrument.instrument_id
        positions = list(self.positions)
        for index, position in enumerate(positions):
            if position.instrument.instrument_id == key:
                new_quantity = position.quantity + fill.local_quantity
                if new_quantity < -self.tolerances.quantity:
                    raise CanonicalError(
                        f"apply_fill: holding of {fill.instrument.symbol!r} would go negative "
                        f"({new_quantity!r}); the portfolio is long-only"
                    )
                positions[index] = replace(position, quantity=new_quantity)
                break
        else:
            if fill.local_quantity < -self.tolerances.quantity:
                raise CanonicalError(
                    f"apply_fill: opening a short position in {fill.instrument.symbol!r}"
                )
            positions.append(Position(fill.instrument, fill.local_quantity))
        return replace(self, base_cash=new_cash, positions=tuple(positions))

    def base_value(self, marks: dict[str, float]) -> float:
        """The base value of the holdings given ``marks`` (instrument_id -> base value per unit)."""
        total = 0.0
        for position in self.positions:
            key = position.instrument.instrument_id
            if key not in marks:
                raise CanonicalError(
                    f"base_value: no mark for held instrument {position.instrument.symbol!r}"
                )
            total += position.quantity * marks[key]
        return total

    def equity(self, marks: dict[str, float]) -> float:
        """Total base-currency equity: cash plus the base value of every holding."""
        return self.base_cash + self.base_value(marks)

    def canonical(self) -> dict[str, Any]:
        return {
            "base_currency": self.base_currency,
            "base_cash": self.base_cash,
            "positions": [position.canonical() for position in self.positions],
        }

    @property
    def fingerprint(self) -> str:
        return domain_hash("portfolio_state", self.canonical())

    @classmethod
    def opening(
        cls,
        base_currency: str,
        base_cash: float,
        *,
        tolerances: PortfolioTolerances = DEFAULT_TOLERANCES,
    ) -> PortfolioState:
        """An all-cash opening state with no holdings."""
        require_non_negative_finite_float(base_cash, "state.base_cash")
        return cls(
            base_currency=base_currency,
            base_cash=base_cash,
            positions=(),
            tolerances=tolerances,
        )
