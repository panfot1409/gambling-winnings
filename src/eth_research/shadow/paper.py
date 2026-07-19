"""Deterministic paper accounting for a single-instrument, long-only shadow book.

The paper book answers "if the operator had held exactly the approved weight each bar, what would
the book look like?" It is a pure mark-to-market ledger: given a starting cash balance and, each
bar, an approved target weight and the bar's close price, it rebalances the position to that weight
and marks equity. There are no real fills, no venue, and no money — a "fill" here is a bookkeeping
entry, not an instruction to anyone.

Accounting is a pure state transition (:func:`rebalance`), so a paper run is byte-reproducible and
each entry can be re-derived independently from the one before it. Execution costs are a
research-layer concept and are deliberately *not* modelled here; a paper mark is a clean baseline.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.shadow.domain import ShadowDomainError, canonical_timestamp
from eth_research.v2.strict import (
    require_exact_keys,
    require_mapping,
    require_nonnegative_real,
    require_positive_real,
    require_real,
    require_unit_interval,
)

_ACCOUNT_KEYS = frozenset({"cash", "units"})
_FILL_KEYS = frozenset(
    {"as_of", "price", "target_weight", "traded_units", "units_after", "cash_after", "equity_after"}
)


class PaperError(ShadowDomainError):
    """A paper-accounting value or transition violated its contract."""


@dataclass(frozen=True, slots=True)
class PaperAccount:
    """Cash + units held. Equity is cash plus the marked value of the position."""

    cash: float
    units: float

    @staticmethod
    def opening(cash: float) -> PaperAccount:
        return PaperAccount(cash=require_positive_real("cash", cash), units=0.0)

    @staticmethod
    def parse(label: str, value: object) -> PaperAccount:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _ACCOUNT_KEYS)
        return PaperAccount(
            cash=require_real(f"{label}.cash", obj["cash"]),
            units=require_nonnegative_real(f"{label}.units", obj["units"]),
        )

    def equity(self, price: float) -> float:
        return self.cash + self.units * price

    def to_canonical(self) -> dict[str, object]:
        return {"cash": self.cash, "units": self.units}


@dataclass(frozen=True, slots=True)
class PaperFill:
    """The bookkeeping record of one rebalance to a target weight at a bar's close price."""

    as_of: str
    price: float
    target_weight: float
    traded_units: float
    units_after: float
    cash_after: float
    equity_after: float

    @staticmethod
    def parse(label: str, value: object) -> PaperFill:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _FILL_KEYS)
        return PaperFill(
            as_of=canonical_timestamp(f"{label}.as_of", obj["as_of"]),
            price=require_positive_real(f"{label}.price", obj["price"]),
            target_weight=require_unit_interval(f"{label}.target_weight", obj["target_weight"]),
            traded_units=require_real(f"{label}.traded_units", obj["traded_units"]),
            units_after=require_nonnegative_real(f"{label}.units_after", obj["units_after"]),
            cash_after=require_real(f"{label}.cash_after", obj["cash_after"]),
            equity_after=require_positive_real(f"{label}.equity_after", obj["equity_after"]),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "price": self.price,
            "target_weight": self.target_weight,
            "traded_units": self.traded_units,
            "units_after": self.units_after,
            "cash_after": self.cash_after,
            "equity_after": self.equity_after,
        }


def rebalance(
    account: PaperAccount, *, as_of: object, price: float, target_weight: float
) -> tuple[PaperAccount, PaperFill]:
    """Rebalance the book to ``target_weight`` of current equity at ``price`` (pure)."""
    stamp = canonical_timestamp("as_of", as_of)
    px = require_positive_real("price", price)
    weight = require_unit_interval("target_weight", target_weight)

    equity = account.equity(px)
    if equity <= 0.0:
        raise PaperError("paper book is insolvent; cannot rebalance a non-positive equity")

    desired_units = weight * equity / px
    traded = desired_units - account.units
    cash_after = account.cash - traded * px
    new_account = PaperAccount(cash=cash_after, units=desired_units)
    fill = PaperFill(
        as_of=stamp,
        price=px,
        target_weight=weight,
        traded_units=traded,
        units_after=desired_units,
        cash_after=cash_after,
        equity_after=new_account.equity(px),
    )
    return new_account, fill
