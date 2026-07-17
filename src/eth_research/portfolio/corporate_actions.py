"""Corporate actions: splits, reverse splits, cash dividends, and delisting cash-outs.

A :class:`CorporateAction` is one causally-stamped event on a single
:class:`~eth_research.portfolio.identity.InstrumentId`. It carries a ``knowledge_time`` (when the
event became usable at decision time), an ``effective_time`` (when the quantity/price adjustment
applies), and — for cash events — a ``payment_time`` (when cash is actually received). A
:class:`CorporateActionSet` is the immutable, fingerprinted collection with unique action ids.

The supported effects are intentionally narrow:

* ``split`` multiplies held quantity by ``ratio`` and divides price by ``ratio`` (``ratio > 1``).
* ``reverse_split`` is the same mechanic with ``0 < ratio < 1`` (e.g. ``0.2`` for a 1-for-5).
* ``cash_dividend`` pays ``cash_amount`` per share in ``currency`` at ``payment_time``.
* ``delisting_cash_out`` pays a final ``cash_amount`` in ``currency`` and terminates the holding.

This model assumes the caller supplies **raw, unadjusted** prices and quantities: applying these
actions on top of an already back-adjusted price series would double-count every split and dividend,
so the caller must declare which convention their bars use. Rights issues, spin-offs, stock
dividends, mergers, and dividend withholding tax are deliberately unsupported rather than
approximated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from eth_research.api.serialization import (
    CanonicalError,
    require_finite_float,
    require_list,
    require_mapping,
    require_str,
)
from eth_research.portfolio._time import iso_utc, require_utc_timestamp
from eth_research.portfolio.currencies import require_currency_code
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.validation import (
    domain_hash,
    exact_keys,
    require_non_negative_finite_float,
    require_positive_finite_float,
    require_safe_token,
)

__all__ = ["ACTION_TYPES", "CorporateAction", "CorporateActionSet"]

#: The exact corporate-action vocabulary. Two ratio adjustments and two cash events; nothing else.
ACTION_TYPES = ("split", "reverse_split", "cash_dividend", "delisting_cash_out")

_ACTION_FIELDS = {
    "instrument",
    "action_id",
    "action_type",
    "knowledge_time",
    "effective_time",
    "payment_time",
    "ratio",
    "cash_amount",
    "currency",
    "source",
}


def _require_ts(value: Any, field: str) -> pd.Timestamp:
    """A timezone-aware :class:`Timestamp`, normalized to UTC (rejects naive or non-Timestamp)."""
    if not isinstance(value, pd.Timestamp):
        raise CanonicalError(f"{field}: expected a pandas Timestamp")
    if value.tz is None:
        raise CanonicalError(f"{field}: timestamp must be timezone-aware UTC")
    return value.tz_convert("UTC")


@dataclass(frozen=True)
class CorporateAction:
    """One causally-stamped corporate action with type-specific field rules."""

    instrument: InstrumentId
    action_id: str
    action_type: str
    knowledge_time: pd.Timestamp
    effective_time: pd.Timestamp
    payment_time: pd.Timestamp | None
    ratio: float | None
    cash_amount: float | None
    currency: str | None
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, InstrumentId):
            raise CanonicalError("corporate_action.instrument: expected an InstrumentId")
        require_safe_token(self.action_id, "corporate_action.action_id")
        require_safe_token(self.source, "corporate_action.source")
        if self.action_type not in ACTION_TYPES:
            raise CanonicalError(
                f"corporate_action.action_type: expected one of {list(ACTION_TYPES)}, "
                f"got {self.action_type!r}"
            )
        object.__setattr__(
            self,
            "knowledge_time",
            _require_ts(self.knowledge_time, "corporate_action.knowledge_time"),
        )
        object.__setattr__(
            self,
            "effective_time",
            _require_ts(self.effective_time, "corporate_action.effective_time"),
        )
        if self.payment_time is not None:
            object.__setattr__(
                self,
                "payment_time",
                _require_ts(self.payment_time, "corporate_action.payment_time"),
            )
        if not self.knowledge_time <= self.effective_time:
            raise CanonicalError(
                "corporate_action.knowledge_time: must not be after effective_time "
                f"({iso_utc(self.knowledge_time)} > {iso_utc(self.effective_time)})"
            )
        if self.ratio is not None:
            require_positive_finite_float(self.ratio, "corporate_action.ratio")
        if self.cash_amount is not None:
            require_non_negative_finite_float(self.cash_amount, "corporate_action.cash_amount")
        if self.currency is not None:
            require_currency_code(self.currency, "corporate_action.currency")
        self._validate_fields_for_type()

    def _validate_fields_for_type(self) -> None:
        if self.action_type == "split":
            ratio = self._required_ratio()
            if not ratio > 1.0:
                raise CanonicalError(
                    "corporate_action.split: ratio must be > 1 (e.g. 2.0 for a 2-for-1)"
                )
            self._reject_cash_fields("split")
        elif self.action_type == "reverse_split":
            ratio = self._required_ratio()
            if not 0.0 < ratio < 1.0:
                raise CanonicalError(
                    "corporate_action.reverse_split: ratio must be in (0, 1) (e.g. 0.2 for 1-for-5)"
                )
            self._reject_cash_fields("reverse_split")
        elif self.action_type == "cash_dividend":
            payment = self._required_cash_fields("cash_dividend", strictly_positive=True)
            if not self.effective_time <= payment:
                raise CanonicalError(
                    "corporate_action.cash_dividend: payment_time must be >= effective_time"
                )
        else:  # delisting_cash_out
            payment = self._required_cash_fields("delisting_cash_out", strictly_positive=False)
            if not self.effective_time <= payment:
                raise CanonicalError(
                    "corporate_action.delisting_cash_out: payment_time must be >= effective_time"
                )

    def _required_ratio(self) -> float:
        if self.ratio is None:
            raise CanonicalError(f"corporate_action.{self.action_type}: ratio is required")
        return self.ratio

    def _reject_cash_fields(self, kind: str) -> None:
        for name in ("cash_amount", "currency", "payment_time"):
            if getattr(self, name) is not None:
                raise CanonicalError(f"corporate_action.{kind}: {name} must be null")

    def _required_cash_fields(self, kind: str, *, strictly_positive: bool) -> pd.Timestamp:
        if self.ratio is not None:
            raise CanonicalError(f"corporate_action.{kind}: ratio must be null")
        if self.cash_amount is None:
            raise CanonicalError(f"corporate_action.{kind}: cash_amount is required")
        if strictly_positive and not self.cash_amount > 0.0:
            raise CanonicalError(f"corporate_action.{kind}: cash_amount must be > 0")
        if self.currency is None:
            raise CanonicalError(f"corporate_action.{kind}: currency is required")
        if self.payment_time is None:
            raise CanonicalError(f"corporate_action.{kind}: payment_time is required")
        return self.payment_time

    def canonical(self) -> dict[str, Any]:
        """The canonical field mapping (timestamps as ISO-8601 UTC; absent optionals as null)."""
        payment = self.payment_time
        return {
            "instrument": self.instrument.canonical(),
            "action_id": self.action_id,
            "action_type": self.action_type,
            "knowledge_time": iso_utc(self.knowledge_time),
            "effective_time": iso_utc(self.effective_time),
            "payment_time": None if payment is None else iso_utc(payment),
            "ratio": self.ratio,
            "cash_amount": self.cash_amount,
            "currency": self.currency,
            "source": self.source,
        }

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "corporate_action") -> CorporateAction:
        """Construct from an untrusted mapping, rejecting unknown or missing keys."""
        mapping = require_mapping(data, field)
        exact_keys(mapping, _ACTION_FIELDS, field)
        raw_payment = mapping["payment_time"]
        payment_time = (
            None
            if raw_payment is None
            else require_utc_timestamp(raw_payment, f"{field}.payment_time")
        )
        raw_ratio = mapping["ratio"]
        ratio = None if raw_ratio is None else require_finite_float(raw_ratio, f"{field}.ratio")
        raw_cash = mapping["cash_amount"]
        cash_amount = (
            None if raw_cash is None else require_finite_float(raw_cash, f"{field}.cash_amount")
        )
        raw_currency = mapping["currency"]
        currency = None if raw_currency is None else require_str(raw_currency, f"{field}.currency")
        return cls(
            instrument=InstrumentId.from_mapping(
                mapping["instrument"], field=f"{field}.instrument"
            ),
            action_id=require_str(mapping["action_id"], f"{field}.action_id"),
            action_type=require_str(mapping["action_type"], f"{field}.action_type"),
            knowledge_time=require_utc_timestamp(
                mapping["knowledge_time"], f"{field}.knowledge_time"
            ),
            effective_time=require_utc_timestamp(
                mapping["effective_time"], f"{field}.effective_time"
            ),
            payment_time=payment_time,
            ratio=ratio,
            cash_amount=cash_amount,
            currency=currency,
            source=require_str(mapping["source"], f"{field}.source"),
        )


@dataclass(frozen=True)
class CorporateActionSet:
    """An immutable, canonically ordered set of corporate actions with unique ``action_id``\\ s.

    Actions are sorted by ``(instrument_id, effective_time, action_id)`` on construction, so the
    set's :attr:`fingerprint` reflects its contents and not the caller's input order.
    """

    actions: tuple[CorporateAction, ...]

    def __post_init__(self) -> None:
        actions = tuple(self.actions)
        seen: set[str] = set()
        for index, action in enumerate(actions):
            if not isinstance(action, CorporateAction):
                raise CanonicalError(
                    f"corporate_action_set.actions[{index}]: expected a CorporateAction"
                )
            if action.action_id in seen:
                raise CanonicalError(
                    f"corporate_action_set: duplicate action_id {action.action_id!r}"
                )
            seen.add(action.action_id)
        ordered = sorted(
            actions,
            key=lambda a: (a.instrument.instrument_id, iso_utc(a.effective_time), a.action_id),
        )
        object.__setattr__(self, "actions", tuple(ordered))

    def actions_for(self, instrument: InstrumentId) -> tuple[CorporateAction, ...]:
        """Every action on ``instrument``, in the set's canonical order."""
        if not isinstance(instrument, InstrumentId):
            raise CanonicalError("corporate_action_set.actions_for: expected an InstrumentId")
        key = instrument.instrument_id
        return tuple(a for a in self.actions if a.instrument.instrument_id == key)

    def known_by(self, tau: pd.Timestamp) -> tuple[CorporateAction, ...]:
        """The subset whose ``knowledge_time`` is at or before ``tau`` (causally usable)."""
        moment = _require_ts(tau, "corporate_action_set.known_by.tau")
        return tuple(a for a in self.actions if a.knowledge_time <= moment)

    def canonical(self) -> list[dict[str, Any]]:
        """The canonical list of action mappings, in the set's canonical order."""
        return [action.canonical() for action in self.actions]

    @property
    def fingerprint(self) -> str:
        """The domain-separated content hash of this set (stable across runtimes)."""
        return domain_hash("corporate_action_set", self.canonical())

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "corporate_action_set") -> CorporateActionSet:
        """Construct from an untrusted list of action mappings, rejecting unknown keys."""
        rows = require_list(data, field)
        actions = tuple(
            CorporateAction.from_mapping(row, field=f"{field}[{index}]")
            for index, row in enumerate(rows)
        )
        return cls(actions=actions)
