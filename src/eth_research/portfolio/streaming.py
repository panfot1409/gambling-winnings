"""Batch/streaming equivalence and strict checkpoint/resume (Milestone 4B, §24-25).

The batch engine (:func:`~eth_research.portfolio.engine.run_portfolio_simulation`) and the streaming
driver here run over *one* accounting core (:func:`~eth_research.portfolio.engine.run_event`), so a
full stream reproduces the batch run's events, fills, states, and final-state hash exactly.
Streaming is deterministic local iteration — it reads a complete local panel one event at a time;
there is no network, no live clock, and no source of nondeterminism.

A :class:`PortfolioCheckpoint` is the strict, canonical-JSON snapshot taken after an event. It binds
the schema version and every input fingerprint (protocol, panel, membership, schedule, FX), the next
event index, the carried accounting state (cash + holdings) and attribution baseline (previous
marks, local closes, FX legs, equity), the cumulative fill count, the canonical records of the
events already completed, and a domain-separated content hash over all of it. Nothing is pickled and
no code is deserialized. :func:`resume_portfolio_simulation` reconstructs the carried state and
replays the remaining events, producing a full canonical result *byte-identical* to the batch run —
and it fails closed on a tampered hash, a mutated holding, a substituted protocol / panel /
membership / schedule / FX / calendars, or an out-of-range event index, rather than silently
resuming an inconsistent run.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from eth_research.api.serialization import (
    CanonicalError,
    require_finite_float,
    require_int,
    require_list,
    require_mapping,
    require_sha256_hex,
    require_str,
)
from eth_research.portfolio.accounting import PortfolioState, Position
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.corporate_actions import CorporateActionSet
from eth_research.portfolio.engine import (
    EventRecord,
    StepCarry,
    _refuse_in_window_corporate_actions,
    _validate_calendars,
    initial_carry,
    run_event,
)
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipSchedule
from eth_research.portfolio.panel import MarketPanel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.validation import domain_hash

__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "PortfolioCheckpoint",
    "ResumedRun",
    "resume_portfolio_simulation",
    "stream_portfolio_simulation",
]

CHECKPOINT_SCHEMA_VERSION = 1

_FINGERPRINT_FIELDS = (
    "protocol_fingerprint",
    "panel_fingerprint",
    "membership_fingerprint",
    "schedule_fingerprint",
    "fx_fingerprint",
    "calendars_fingerprint",
)
_CHECKPOINT_FIELDS = {
    "schema_version",
    "base_currency",
    "initial_equity",
    "next_event_index",
    *_FINGERPRINT_FIELDS,
    "base_cash",
    "positions",
    "prev_marks",
    "prev_local_close",
    "prev_fx",
    "prev_equity",
    "all_fills",
    "committed_events",
    "checkpoint_hash",
}


def _calendars_fingerprint(calendars: dict[str, TradingCalendar]) -> str:
    """A single domain-separated hash over the sorted calendar fingerprints.

    Trading calendars govern tradability, so resuming a checkpoint against different calendars is a
    materially different run. Folding them into one bound fingerprint lets the checkpoint reject
    that substitution the same way it rejects a substituted protocol / panel / membership / schedule
    / FX.
    """
    return domain_hash(
        "portfolio_calendars",
        [
            {"calendar_id": calendar_id, "fingerprint": calendars[calendar_id].fingerprint}
            for calendar_id in sorted(calendars)
        ],
    )


def _evidence_fingerprints(
    protocol: PortfolioProtocol,
    panel: MarketPanel,
    membership: MembershipSchedule,
    schedule: RebalanceSchedule,
    fx: FxEvidence,
    calendars: dict[str, TradingCalendar],
) -> dict[str, str]:
    return {
        "protocol_fingerprint": protocol.fingerprint,
        "panel_fingerprint": panel.fingerprint,
        "membership_fingerprint": membership.fingerprint,
        "schedule_fingerprint": schedule.fingerprint,
        "fx_fingerprint": fx.fingerprint,
        "calendars_fingerprint": _calendars_fingerprint(calendars),
    }


def _require_float_map(value: Any, field: str) -> dict[str, float]:
    mapping = require_mapping(value, field)
    out: dict[str, float] = {}
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise CanonicalError(f"{field}: keys must be strings")
        out[key] = require_finite_float(item, f"{field}[{key}]")
    return out


@dataclass(frozen=True)
class PortfolioCheckpoint:
    """A strict, hashed snapshot of a run after ``next_event_index`` completed events."""

    base_currency: str
    initial_equity: float
    next_event_index: int
    fingerprints: dict[str, str]
    base_cash: float
    positions: tuple[tuple[InstrumentId, float], ...]
    prev_marks: dict[str, float]
    prev_local_close: dict[str, float]
    prev_fx: dict[str, float]
    prev_equity: float
    all_fills: int
    committed_events: tuple[dict[str, Any], ...]

    def _payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "base_currency": self.base_currency,
            "initial_equity": self.initial_equity,
            "next_event_index": self.next_event_index,
            "base_cash": self.base_cash,
            "positions": [
                {"instrument": instrument.canonical(), "quantity": quantity}
                for instrument, quantity in self.positions
            ],
            "prev_marks": dict(self.prev_marks),
            "prev_local_close": dict(self.prev_local_close),
            "prev_fx": dict(self.prev_fx),
            "prev_equity": self.prev_equity,
            "all_fills": self.all_fills,
            "committed_events": [dict(event) for event in self.committed_events],
        }
        for name in _FINGERPRINT_FIELDS:
            payload[name] = self.fingerprints[name]
        return payload

    @property
    def checkpoint_hash(self) -> str:
        """The domain-separated content hash over the whole payload (tamper evidence)."""
        return domain_hash("portfolio_checkpoint", self._payload())

    def canonical(self) -> dict[str, Any]:
        """The canonical mapping, including the self-certifying ``checkpoint_hash``."""
        return {**self._payload(), "checkpoint_hash": self.checkpoint_hash}

    def to_carry(self, protocol: PortfolioProtocol) -> StepCarry:
        """Reconstruct the carried state (fails closed if it is not cash-safe / long-only)."""
        state = PortfolioState(
            base_currency=self.base_currency,
            base_cash=self.base_cash,
            positions=tuple(
                Position(instrument, quantity) for instrument, quantity in self.positions
            ),
            tolerances=protocol.tolerances,
        )
        return StepCarry(
            state=state,
            prev_marks=dict(self.prev_marks),
            prev_local_close=dict(self.prev_local_close),
            prev_fx=dict(self.prev_fx),
            prev_equity=self.prev_equity,
        )

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "portfolio_checkpoint") -> PortfolioCheckpoint:
        """Rebuild from an untrusted canonical mapping, verifying the self-certifying hash."""
        mapping = require_mapping(data, field)
        _reject_unexpected_keys(mapping, field)
        if require_int(mapping["schema_version"], f"{field}.schema_version") != (
            CHECKPOINT_SCHEMA_VERSION
        ):
            raise CanonicalError(f"{field}.schema_version: unsupported")
        positions = tuple(
            (
                InstrumentId.from_mapping(
                    require_mapping(row, f"{field}.positions[{index}]")["instrument"],
                    field=f"{field}.positions[{index}].instrument",
                ),
                require_finite_float(
                    require_mapping(row, f"{field}.positions[{index}]")["quantity"],
                    f"{field}.positions[{index}].quantity",
                ),
            )
            for index, row in enumerate(require_list(mapping["positions"], f"{field}.positions"))
        )
        committed = tuple(
            require_mapping(row, f"{field}.committed_events[{index}]")
            for index, row in enumerate(
                require_list(mapping["committed_events"], f"{field}.committed_events")
            )
        )
        checkpoint = cls(
            base_currency=require_str(mapping["base_currency"], f"{field}.base_currency"),
            initial_equity=require_finite_float(
                mapping["initial_equity"], f"{field}.initial_equity"
            ),
            next_event_index=require_int(mapping["next_event_index"], f"{field}.next_event_index"),
            fingerprints={
                name: require_sha256_hex(mapping[name], f"{field}.{name}")
                for name in _FINGERPRINT_FIELDS
            },
            base_cash=require_finite_float(mapping["base_cash"], f"{field}.base_cash"),
            positions=positions,
            prev_marks=_require_float_map(mapping["prev_marks"], f"{field}.prev_marks"),
            prev_local_close=_require_float_map(
                mapping["prev_local_close"], f"{field}.prev_local_close"
            ),
            prev_fx=_require_float_map(mapping["prev_fx"], f"{field}.prev_fx"),
            prev_equity=require_finite_float(mapping["prev_equity"], f"{field}.prev_equity"),
            all_fills=require_int(mapping["all_fills"], f"{field}.all_fills"),
            committed_events=committed,
        )
        stored_hash = require_sha256_hex(mapping["checkpoint_hash"], f"{field}.checkpoint_hash")
        if checkpoint.checkpoint_hash != stored_hash:
            raise CanonicalError(
                f"{field}.checkpoint_hash: does not match the checkpoint contents (tampered)"
            )
        if checkpoint.next_event_index < 0:
            raise CanonicalError(f"{field}.next_event_index: must not be negative")
        if len(checkpoint.committed_events) != checkpoint.next_event_index:
            raise CanonicalError(f"{field}: committed_events count must equal next_event_index")
        return checkpoint

    def verify_against(
        self,
        protocol: PortfolioProtocol,
        panel: MarketPanel,
        membership: MembershipSchedule,
        schedule: RebalanceSchedule,
        fx: FxEvidence,
        calendars: dict[str, TradingCalendar],
    ) -> None:
        """Fail closed unless every bound fingerprint matches the supplied evidence."""
        expected = _evidence_fingerprints(protocol, panel, membership, schedule, fx, calendars)
        for name, value in expected.items():
            if self.fingerprints[name] != value:
                raise CanonicalError(
                    f"checkpoint.{name}: does not match the supplied evidence "
                    f"(checkpoint {self.fingerprints[name][:12]}..., supplied {value[:12]}...)"
                )


def _capture(
    fingerprints: dict[str, str],
    base_currency: str,
    initial_equity: float,
    *,
    next_event_index: int,
    carry: StepCarry,
    all_fills: int,
    committed_events: tuple[dict[str, Any], ...],
) -> PortfolioCheckpoint:
    return PortfolioCheckpoint(
        base_currency=base_currency,
        initial_equity=initial_equity,
        next_event_index=next_event_index,
        fingerprints=dict(fingerprints),
        base_cash=carry.state.base_cash,
        positions=tuple(
            (position.instrument, position.quantity) for position in carry.state.positions
        ),
        prev_marks=dict(carry.prev_marks),
        prev_local_close=dict(carry.prev_local_close),
        prev_fx=dict(carry.prev_fx),
        prev_equity=carry.prev_equity,
        all_fills=all_fills,
        committed_events=committed_events,
    )


def stream_portfolio_simulation(
    protocol: PortfolioProtocol,
    panel: MarketPanel,
    membership: MembershipSchedule,
    fx: FxEvidence,
    schedule: RebalanceSchedule,
    *,
    calendars: dict[str, TradingCalendar],
    corporate_actions: CorporateActionSet | None = None,
) -> Iterator[tuple[EventRecord, PortfolioCheckpoint]]:
    """Yield ``(event, checkpoint)`` for each rebalance event, in schedule order.

    The event sequence and every accounting state are byte-identical to the batch engine (they share
    one core); the checkpoint yielded with event ``k`` snapshots the run *after* event ``k``, ready
    to resume from event ``k+1``. The same fail-closed guards as the batch engine apply up front.
    """
    _validate_calendars(calendars)
    _refuse_in_window_corporate_actions(corporate_actions, panel, schedule)
    fingerprints = _evidence_fingerprints(protocol, panel, membership, schedule, fx, calendars)
    carry = initial_carry(protocol)
    committed: list[dict[str, Any]] = []
    all_fills = 0
    for index, tau in enumerate(schedule.events()):
        record, carry = run_event(protocol, panel, membership, fx, calendars, tau, carry)
        committed.append(record.canonical())
        all_fills += len(record.fills)
        checkpoint = _capture(
            fingerprints,
            protocol.base_currency,
            protocol.initial_cash,
            next_event_index=index + 1,
            carry=carry,
            all_fills=all_fills,
            committed_events=tuple(committed),
        )
        yield record, checkpoint


@dataclass(frozen=True)
class ResumedRun:
    """The outcome of resuming a checkpoint: the full canonical result plus the newly-run tail."""

    canonical_result: dict[str, Any]
    tail_events: tuple[EventRecord, ...]

    @property
    def result_fingerprint(self) -> str:
        """The domain-separated hash over the full canonical result (equals the batch run's)."""
        return domain_hash("portfolio_run_result", self.canonical_result)


def resume_portfolio_simulation(
    checkpoint: PortfolioCheckpoint,
    protocol: PortfolioProtocol,
    panel: MarketPanel,
    membership: MembershipSchedule,
    fx: FxEvidence,
    schedule: RebalanceSchedule,
    *,
    calendars: dict[str, TradingCalendar],
    corporate_actions: CorporateActionSet | None = None,
) -> ResumedRun:
    """Resume from ``checkpoint`` and return a full canonical result identical to the batch run.

    Fails closed (``CanonicalError``) on a substituted protocol / panel / membership / schedule / FX
    / calendars (fingerprint mismatch), a next-event index past the schedule, or an in-window
    corporate action.
    A tampered checkpoint is already rejected at parse time via
    :meth:`PortfolioCheckpoint.from_mapping`.
    """
    if not isinstance(checkpoint, PortfolioCheckpoint):
        raise CanonicalError("resume: expected a PortfolioCheckpoint")
    _validate_calendars(calendars)
    _refuse_in_window_corporate_actions(corporate_actions, panel, schedule)
    checkpoint.verify_against(protocol, panel, membership, schedule, fx, calendars)

    events = schedule.events()
    start = checkpoint.next_event_index
    if start > len(events):
        raise CanonicalError(
            f"resume: next_event_index {start} exceeds the schedule's {len(events)} events"
        )

    carry = checkpoint.to_carry(protocol)
    tail: list[EventRecord] = []
    all_fills = checkpoint.all_fills
    for tau in events[start:]:
        record, carry = run_event(protocol, panel, membership, fx, calendars, tau, carry)
        tail.append(record)
        all_fills += len(record.fills)

    events_canonical = [*checkpoint.committed_events, *(event.canonical() for event in tail)]
    terminal_equity = (
        events_canonical[-1]["equity"] if events_canonical else checkpoint.initial_equity
    )
    fingerprints = _evidence_fingerprints(protocol, panel, membership, schedule, fx, calendars)
    canonical_result = {
        "protocol_fingerprint": fingerprints["protocol_fingerprint"],
        "panel_fingerprint": fingerprints["panel_fingerprint"],
        "membership_fingerprint": fingerprints["membership_fingerprint"],
        "schedule_fingerprint": fingerprints["schedule_fingerprint"],
        "calendar_fingerprints": [
            {"calendar_id": calendar_id, "fingerprint": calendars[calendar_id].fingerprint}
            for calendar_id in sorted(calendars)
        ],
        "base_currency": checkpoint.base_currency,
        "initial_equity": checkpoint.initial_equity,
        "terminal_equity": terminal_equity,
        "all_fills": all_fills,
        "final_state_fingerprint": carry.state.fingerprint,
        "events": events_canonical,
    }
    return ResumedRun(canonical_result=canonical_result, tail_events=tuple(tail))


def _reject_unexpected_keys(mapping: dict[str, Any], field: str) -> None:
    extra = set(mapping) - _CHECKPOINT_FIELDS
    if extra:
        raise CanonicalError(f"{field}: unexpected key(s) {sorted(extra)}")
    missing = _CHECKPOINT_FIELDS - set(mapping)
    if missing:
        raise CanonicalError(f"{field}: missing key(s) {sorted(missing)}")
