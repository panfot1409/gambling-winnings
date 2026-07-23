"""V2C operational-qualification harness: cash_control through the shadow platform.

For each instrument (ETH and BTC run **separately** -- the shadow runner is single-instrument):

1. builds the deterministic synthetic raw stream and runs it through the acceptance gate to get a
   cleaned monotonic stream (:mod:`eth_research.v2c.oq.events`);
2. pairs every accepted bar with a **zero-weight** ``cash_control`` signal (the only target the §14
   firewall resolves), so the paper book holds 100% cash throughout; and
3. drives ``eth_research.shadow.run_shadow`` under deterministic virtual time (no wall clock),
   collecting the journal, fills, alerts, checkpoint, and the adapter's dispatched intents.

The risk cap is pinned to **zero** exposure (``max_target_weight = 0``), so even a hypothetical
non-zero request would be refused by the risk engine before any exposure is taken. No market
performance is computed; this is not a forward record. The firewall gates the whole run
(:func:`guard_request_kind` + :func:`resolve_operational_target`) so no strategy can be substituted.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.shadow.adapter import ExecutionIntent, PaperExecutionAdapter
from eth_research.shadow.domain import SYNTHETIC_DEMO, InstrumentId
from eth_research.shadow.monitoring import MonitoringThresholds
from eth_research.shadow.risk import RiskLimits
from eth_research.shadow.runner import ShadowConfig, ShadowRunResult, ShadowStep, run_shadow
from eth_research.shadow.signal import SignalEnvelope
from eth_research.v2c.firewall import (
    CASH_CONTROL_TARGET_ID,
    guard_request_kind,
    resolve_operational_target,
)
from eth_research.v2c.oq.events import (
    OQ_DEFAULT_SLOTS,
    OQ_INTERVAL_SECONDS,
    AcceptanceResult,
    build_synthetic_raw_events,
    fixture_manifest,
    ingest_events,
)

#: Default instruments; each is a separate single-instrument run.
DEFAULT_INSTRUMENTS: tuple[str, ...] = ("eth_usd", "btc_usd")
#: Deterministic run parameters (no wall clock is ever read).
DEFAULT_STARTING_CASH: float = 10_000.0
#: Staleness threshold for the runner: the fixture's stale gaps (four intervals) cross it.
DEFAULT_STALENESS_SECONDS: int = 3 * OQ_INTERVAL_SECONDS
DEFAULT_MAX_DRAWDOWN_FRACTION: float = 0.5


@dataclass(frozen=True, slots=True)
class InstrumentQualification:
    """One instrument's acceptance summary, shadow run, and the intents the adapter observed."""

    instrument_symbol: str
    acceptance: AcceptanceResult
    fixture_manifest: dict[str, object]
    result: ShadowRunResult
    dispatched_intents: tuple[ExecutionIntent, ...]


@dataclass(frozen=True, slots=True)
class QualificationRun:
    """The full cash-control qualification across every instrument."""

    slots: int
    starting_cash: float
    instruments: tuple[InstrumentQualification, ...]


def _cash_control_steps(
    instrument: InstrumentId, acceptance: AcceptanceResult
) -> tuple[ShadowStep, ...]:
    steps: list[ShadowStep] = []
    for envelope in acceptance.accepted:
        signal = SignalEnvelope.create(
            candidate_id=CASH_CONTROL_TARGET_ID,
            instrument=instrument,
            as_of=envelope.close_time,
            target_weight=0.0,
        )
        steps.append(ShadowStep(envelope=envelope, signal=signal))
    return tuple(steps)


def _zero_exposure_config(instrument: InstrumentId, *, starting_cash: float) -> ShadowConfig:
    return ShadowConfig.create(
        mode=SYNTHETIC_DEMO,
        instrument=instrument,
        candidate_id=CASH_CONTROL_TARGET_ID,
        starting_cash=starting_cash,
        limits=RiskLimits.parse("limits", {"max_target_weight": 0.0, "max_weight_step": 0.0}),
        thresholds=MonitoringThresholds.parse(
            "thresholds",
            {
                "max_staleness_seconds": DEFAULT_STALENESS_SECONDS,
                "max_drawdown_fraction": DEFAULT_MAX_DRAWDOWN_FRACTION,
            },
        ),
    )


def qualify_instrument(symbol: str, *, slots: int, starting_cash: float) -> InstrumentQualification:
    """Run the cash-control qualification for one instrument (offline, deterministic)."""
    instrument = InstrumentId(symbol)
    raw = build_synthetic_raw_events(instrument, slots=slots)
    acceptance = ingest_events(raw)
    manifest = fixture_manifest(raw, acceptance, slots=slots)
    config = _zero_exposure_config(instrument, starting_cash=starting_cash)
    adapter = PaperExecutionAdapter()
    result = run_shadow(config, _cash_control_steps(instrument, acceptance), adapter=adapter)
    return InstrumentQualification(
        instrument_symbol=symbol,
        acceptance=acceptance,
        fixture_manifest=manifest,
        result=result,
        dispatched_intents=adapter.dispatched,
    )


def run_cash_control_qualification(
    *,
    slots: int = OQ_DEFAULT_SLOTS,
    starting_cash: float = DEFAULT_STARTING_CASH,
    instruments: tuple[str, ...] = DEFAULT_INSTRUMENTS,
) -> QualificationRun:
    """Execute the whole cash-control operational qualification.

    Firewall-gated: only the ``cash_control_operation`` request kind is admitted, and only the
    ``cash_control`` operational target is resolvable, so no strategy can be substituted.
    """
    guard_request_kind("cash_control_operation")
    target = resolve_operational_target(CASH_CONTROL_TARGET_ID)
    assert target.target_id == CASH_CONTROL_TARGET_ID
    qualifications = tuple(
        qualify_instrument(symbol, slots=slots, starting_cash=starting_cash)
        for symbol in instruments
    )
    return QualificationRun(slots=slots, starting_cash=starting_cash, instruments=qualifications)


__all__ = [
    "DEFAULT_INSTRUMENTS",
    "DEFAULT_MAX_DRAWDOWN_FRACTION",
    "DEFAULT_STALENESS_SECONDS",
    "DEFAULT_STARTING_CASH",
    "InstrumentQualification",
    "QualificationRun",
    "qualify_instrument",
    "run_cash_control_qualification",
]
