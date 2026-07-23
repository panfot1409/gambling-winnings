"""V2C section 20: the synthetic event stream + the event-acceptance ingestion gate.

The shadow runner consumes a *pre-cleaned*, strictly monotonic stream: it halts on an out-of-order
close-time and passes duplicates straight through (there is no dedup/reorder/acceptance layer in the
shadow platform). Real ingestion is messier, so this module supplies two things:

1. A **deterministic synthetic ETH/BTC event stream** (:func:`build_synthetic_raw_events`) of at
   least :data:`OQ_MIN_EVENT_SLOTS` daily slots, carrying a scheduled fault taxonomy -- normal,
   gap, stale, duplicate, conflicting-duplicate, out-of-order, delayed-receive, zero-volume, and
   high-volatility events. Prices follow an integer-derived triangular path, so every bar is valid
   (``low <= open,close <= high``, strictly positive) and byte-reproducible across platforms with no
   randomness or wall-clock.

2. The **event-acceptance gate** (:func:`ingest_events`) that the runner lacks: processed in receive
   order, it accepts strictly-newer events, suppresses exact duplicates, rejects conflicting
   duplicates (same close-time, different bar) and out-of-order / delayed arrivals, and flags gaps,
   staleness, zero-volume, and high-volatility. It returns the cleaned monotonic stream the runner
   can safely consume, plus an acceptance ledger and conflict alerts.

The event model carries no receive-time field (the shadow envelope has none), so a *delayed* arrival
is modelled as an out-of-order event that arrives after the frontier has moved past it, and is
rejected -- exactly what protects the runner from a clock halt.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from eth_research.m3d.validation import M3DValidationError, domain_sha256
from eth_research.shadow.domain import InstrumentId
from eth_research.shadow.market_data import MarketBar, MarketDataEnvelope
from eth_research.shadow.monitoring import CRITICAL, Alert

OQ_SCHEMA_VERSION: int = 1
_FIXTURE_DOMAIN: str = "v2c/oq_synthetic_fixture.v1"

#: The synthetic fixture is anchored at a fixed past instant. It is SYNTHETIC virtual time, not real
#: market data: no candle here was fetched, and the run computes no market performance.
OQ_FIXTURE_COHORT_START: str = "2016-01-01T00:00:00Z"
OQ_INTERVAL_SECONDS: int = 86400
#: The qualification requires at least this many daily slots.
OQ_MIN_EVENT_SLOTS: int = 3650
#: The qualification requires at least this many *effectively accepted* events (the declared slots
#: minus the gap/stale holes). At the minimum config the real fixture accepts 3607; this floor sits
#: safely below that and far above a degenerate run, so the qualification verdict cannot pass on a
#: near-empty accepted stream even when the declared slot count clears the floor above.
OQ_MIN_ACCEPTED_EVENTS: int = 3500
#: The fixture builds a comfortable margin above the floor so gaps never drop it below it.
OQ_DEFAULT_SLOTS: int = 3800

CONFLICT_CODE: str = "conflicting_duplicate"

# --- fault taxonomy ---------------------------------------------------------
FAULT_NORMAL: str = "normal"
FAULT_GAP: str = "gap"
FAULT_STALE: str = "stale"
FAULT_ZERO_VOLUME: str = "zero_volume"
FAULT_HIGH_VOLATILITY: str = "high_volatility"
FAULT_DUPLICATE: str = "duplicate"
FAULT_CONFLICTING_DUPLICATE: str = "conflicting_duplicate"
FAULT_OUT_OF_ORDER: str = "out_of_order"
FAULT_DELAYED_RECEIVE: str = "delayed_receive"

FAULT_CLASSES: frozenset[str] = frozenset(
    {
        FAULT_NORMAL,
        FAULT_GAP,
        FAULT_STALE,
        FAULT_ZERO_VOLUME,
        FAULT_HIGH_VOLATILITY,
        FAULT_DUPLICATE,
        FAULT_CONFLICTING_DUPLICATE,
        FAULT_OUT_OF_ORDER,
        FAULT_DELAYED_RECEIVE,
    }
)

# --- acceptance outcomes ----------------------------------------------------
OUTCOME_ACCEPTED: str = "accepted"
OUTCOME_DUPLICATE_SUPPRESSED: str = "duplicate_suppressed"
OUTCOME_CONFLICTING_REJECTED: str = "conflicting_duplicate_rejected"
OUTCOME_OUT_OF_ORDER_REJECTED: str = "out_of_order_rejected"

OUTCOMES: frozenset[str] = frozenset(
    {
        OUTCOME_ACCEPTED,
        OUTCOME_DUPLICATE_SUPPRESSED,
        OUTCOME_CONFLICTING_REJECTED,
        OUTCOME_OUT_OF_ORDER_REJECTED,
    }
)

# --- accepted-event flags ---------------------------------------------------
FLAG_GAP: str = "gap"
FLAG_STALE: str = "stale"
FLAG_ZERO_VOLUME: str = "zero_volume"
FLAG_HIGH_VOLATILITY: str = "high_volatility"

_STALENESS_SECONDS: int = 3 * OQ_INTERVAL_SECONDS
_HIGH_VOLATILITY_FRACTION: float = 0.15


class OQEventError(M3DValidationError):
    """A synthetic event or acceptance operation violated its strict contract."""


@dataclass(frozen=True, slots=True)
class SyntheticRawEvent:
    """One raw event as it *arrives* (receive order), tagged with the fault class it exercises."""

    receive_index: int
    envelope: MarketDataEnvelope
    injected_fault: str


@dataclass(frozen=True, slots=True)
class AcceptanceRecord:
    """The gate's decision for one raw event."""

    receive_index: int
    close_time: str
    injected_fault: str
    outcome: str
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    """The cleaned monotonic stream, the per-event ledger, aggregate counts, and conflict alerts."""

    accepted: tuple[MarketDataEnvelope, ...]
    records: tuple[AcceptanceRecord, ...]
    counts: dict[str, int]
    alerts: tuple[Alert, ...]


def _slot_time(index: int) -> pd.Timestamp:
    return pd.Timestamp(OQ_FIXTURE_COHORT_START) + pd.Timedelta(seconds=OQ_INTERVAL_SECONDS) * index


def _triangular(index: int) -> float:
    """A deterministic, integer-derived triangular wave in ``[0, 200]`` (no randomness)."""
    phase = index % 400
    return float(phase if phase <= 200 else 400 - phase)


def _close_for(index: int) -> float:
    return 1000.0 + _triangular(index)


def _bar_for_slot(index: int, *, band: float, volume: float) -> MarketBar:
    close = _close_for(index)
    open_ = _close_for(index - 1) if index > 0 else close
    hi = max(open_, close) * (1.0 + band)
    lo = min(open_, close) * (1.0 - band)
    return MarketBar.parse(
        "bar", {"open": open_, "high": hi, "low": lo, "close": close, "volume": volume}
    )


def _fault_for_slot(index: int) -> str:
    """A fixed, deterministic fault schedule. Normal events dominate; each fault recurs steadily."""
    if index % 500 == 37:
        return FAULT_OUT_OF_ORDER
    if index % 500 == 53:
        return FAULT_CONFLICTING_DUPLICATE
    if index % 500 == 71:
        return FAULT_DELAYED_RECEIVE
    if index % 250 == 17:
        return FAULT_DUPLICATE
    if index % 300 == 29:
        return FAULT_GAP
    if index % 400 == 41:
        return FAULT_STALE
    if index % 200 == 11:
        return FAULT_ZERO_VOLUME
    if index % 150 == 7:
        return FAULT_HIGH_VOLATILITY
    return FAULT_NORMAL


def _envelope_at(
    instrument: InstrumentId, close_time: pd.Timestamp, *, sequence: int, bar: MarketBar
) -> MarketDataEnvelope:
    return MarketDataEnvelope.parse(
        "env",
        {
            "instrument": instrument.to_canonical(),
            "close_time": close_time.isoformat(),
            "source": "oq_synthetic",
            "sequence": sequence,
            "bar": bar.to_canonical(),
        },
    )


def _envelope(
    instrument: InstrumentId, index: int, *, band: float, volume: float
) -> MarketDataEnvelope:
    return _envelope_at(
        instrument,
        _slot_time(index),
        sequence=index,
        bar=_bar_for_slot(index, band=band, volume=volume),
    )


def _skipped_slots(slots: int) -> set[int]:
    """Slots deliberately left as holes: a single hole for ``gap``, a three-slot run for ``stale``
    (so the resulting spacing crosses the staleness threshold)."""
    skipped: set[int] = set()
    for index in range(slots):
        fault = _fault_for_slot(index)
        if fault == FAULT_GAP:
            skipped.add(index)
        elif fault == FAULT_STALE and 4 < index < slots - 3:
            skipped.update({index, index + 1, index + 2})
    return skipped


def build_synthetic_raw_events(
    instrument: InstrumentId, *, slots: int = OQ_DEFAULT_SLOTS
) -> tuple[SyntheticRawEvent, ...]:
    """Build the deterministic receive-ordered raw event stream for one instrument.

    ``gap`` leaves a one-slot hole and ``stale`` a three-slot hole (both realized as gap/stale flags
    on the next accepted event, not as tagged events); ``duplicate`` emits an identical event again;
    ``conflicting_duplicate`` emits a same-time different-bar event; ``out_of_order`` /
    ``delayed_receive`` emit a late event at a mid-interval time at or before the frontier (never a
    known grid close-time, so the gate rejects it rather than the runner halting);
    ``zero_volume`` / ``high_volatility`` shape the slot's bar.
    """
    if slots < OQ_MIN_EVENT_SLOTS:
        raise OQEventError(f"slots must be >= {OQ_MIN_EVENT_SLOTS}, got {slots}")
    skipped = _skipped_slots(slots)
    half = pd.Timedelta(seconds=OQ_INTERVAL_SECONDS // 2)
    events: list[SyntheticRawEvent] = []
    receive = 0
    for index in range(slots):
        if index in skipped:
            continue
        fault = _fault_for_slot(index)
        volume = 0.0 if fault == FAULT_ZERO_VOLUME else 1000.0 + float(index % 100)
        band = 0.10 if fault == FAULT_HIGH_VOLATILITY else 0.01
        events.append(
            SyntheticRawEvent(
                receive, _envelope(instrument, index, band=band, volume=volume), fault
            )
        )
        receive += 1
        if fault == FAULT_DUPLICATE:
            events.append(
                SyntheticRawEvent(
                    receive, _envelope(instrument, index, band=band, volume=volume), fault
                )
            )
            receive += 1
        elif fault == FAULT_CONFLICTING_DUPLICATE:
            # Same close_time, materially different bar -> a conflict the gate must reject.
            conflicting = _envelope_at(
                instrument,
                _slot_time(index),
                sequence=index,
                bar=_bar_for_slot(index, band=0.05, volume=volume + 1.0),
            )
            events.append(SyntheticRawEvent(receive, conflicting, fault))
            receive += 1
        elif fault in (FAULT_OUT_OF_ORDER, FAULT_DELAYED_RECEIVE) and index >= 1:
            # A late arrival at a mid-interval instant <= frontier that is not a known grid
            # close-time: the gate rejects it out-of-order so the runner's clock never halts.
            late = _envelope_at(
                instrument,
                _slot_time(index) - half,
                sequence=index,
                bar=_bar_for_slot(index, band=0.01, volume=volume),
            )
            events.append(SyntheticRawEvent(receive, late, fault))
            receive += 1
    return tuple(events)


def _flags_for(bar: MarketBar, previous_close_time: str | None, close_time: str) -> tuple[str, ...]:
    flags: list[str] = []
    if previous_close_time is not None:
        delta = (pd.Timestamp(close_time) - pd.Timestamp(previous_close_time)).total_seconds()
        if delta > OQ_INTERVAL_SECONDS:
            flags.append(FLAG_GAP)
        if delta > _STALENESS_SECONDS:
            flags.append(FLAG_STALE)
    if bar.volume == 0.0:
        flags.append(FLAG_ZERO_VOLUME)
    if (bar.high - bar.low) / bar.close > _HIGH_VOLATILITY_FRACTION:
        flags.append(FLAG_HIGH_VOLATILITY)
    return tuple(flags)


def ingest_events(raw: Sequence[SyntheticRawEvent]) -> AcceptanceResult:
    """Accept a raw receive-ordered stream into a cleaned monotonic stream + an acceptance ledger.

    Fail-closed and order-preserving: an event strictly newer than the frontier is accepted (and
    flagged for gap/stale/zero-volume/high-volatility); an exact duplicate of an accepted close-time
    is suppressed; a same-time different-bar event is a conflicting duplicate (rejected + alerted);
    an event at/before the frontier (that is not a known close-time) is out-of-order and rejected.
    """
    accepted: list[MarketDataEnvelope] = []
    records: list[AcceptanceRecord] = []
    alerts: list[Alert] = []
    counts: dict[str, int] = dict.fromkeys(OUTCOMES, 0)
    by_close: dict[str, MarketBar] = {}
    frontier: str | None = None
    previous_close_time: str | None = None

    for event in sorted(raw, key=lambda e: e.receive_index):
        env = event.envelope
        close_time = env.close_time
        flags: tuple[str, ...] = ()
        if close_time in by_close:
            if env.bar == by_close[close_time]:
                outcome = OUTCOME_DUPLICATE_SUPPRESSED
            else:
                outcome = OUTCOME_CONFLICTING_REJECTED
                alerts.append(
                    Alert.parse(
                        "alert",
                        {
                            "as_of": close_time,
                            "severity": CRITICAL,
                            "code": CONFLICT_CODE,
                            "message": f"conflicting duplicate at {close_time} rejected",
                        },
                    )
                )
        elif frontier is not None and close_time <= frontier:
            outcome = OUTCOME_OUT_OF_ORDER_REJECTED
        else:
            outcome = OUTCOME_ACCEPTED
            flags = _flags_for(env.bar, previous_close_time, close_time)
            accepted.append(env)
            by_close[close_time] = env.bar
            frontier = close_time
            previous_close_time = close_time
        counts[outcome] += 1
        records.append(
            AcceptanceRecord(event.receive_index, close_time, event.injected_fault, outcome, flags)
        )

    return AcceptanceResult(tuple(accepted), tuple(records), counts, tuple(alerts))


def fixture_manifest(
    raw: Sequence[SyntheticRawEvent], result: AcceptanceResult, *, slots: int
) -> dict[str, object]:
    """A deterministic, self-digesting manifest of the fixture and its acceptance summary."""
    injected: dict[str, int] = dict.fromkeys(FAULT_CLASSES, 0)
    for event in raw:
        injected[event.injected_fault] += 1
    flag_counts: dict[str, int] = {
        FLAG_GAP: 0,
        FLAG_STALE: 0,
        FLAG_ZERO_VOLUME: 0,
        FLAG_HIGH_VOLATILITY: 0,
    }
    for record in result.records:
        for flag in record.flags:
            flag_counts[flag] += 1
    body: dict[str, object] = {
        "schema_version": OQ_SCHEMA_VERSION,
        "cohort_start": OQ_FIXTURE_COHORT_START,
        "interval_seconds": OQ_INTERVAL_SECONDS,
        "slots": slots,
        "raw_event_count": len(raw),
        "accepted_count": len(result.accepted),
        "injected_fault_counts": dict(sorted(injected.items())),
        "outcome_counts": dict(sorted(result.counts.items())),
        "flag_counts": dict(sorted(flag_counts.items())),
        "conflict_alert_count": len(result.alerts),
    }
    body["fixture_digest"] = domain_sha256(_FIXTURE_DOMAIN, body)
    return body


__all__ = [
    "CONFLICT_CODE",
    "FAULT_CLASSES",
    "FLAG_GAP",
    "FLAG_HIGH_VOLATILITY",
    "FLAG_STALE",
    "FLAG_ZERO_VOLUME",
    "OQ_DEFAULT_SLOTS",
    "OQ_FIXTURE_COHORT_START",
    "OQ_INTERVAL_SECONDS",
    "OQ_MIN_EVENT_SLOTS",
    "OQ_SCHEMA_VERSION",
    "OUTCOMES",
    "OUTCOME_ACCEPTED",
    "OUTCOME_CONFLICTING_REJECTED",
    "OUTCOME_DUPLICATE_SUPPRESSED",
    "OUTCOME_OUT_OF_ORDER_REJECTED",
    "AcceptanceRecord",
    "AcceptanceResult",
    "OQEventError",
    "SyntheticRawEvent",
    "build_synthetic_raw_events",
    "fixture_manifest",
    "ingest_events",
]
