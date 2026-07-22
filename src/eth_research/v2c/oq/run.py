"""V2C sections 13-16: the virtual-time qualification runner.

Drives the whole offline operational qualification once a run is durably ``started``. Given the
:class:`~eth_research.v2c.oq.orchestrator.StartedToken` the orchestrator mints, it re-asserts that
the registry is durably ``started`` (so computation cannot precede the durable start), then runs the
existing candidate-free machinery in virtual time -- no wall clock, no network, no exposure:

1. the cash-control qualification across every instrument (the shadow platform under the synthetic
   ETH/BTC event stream with the full fault taxonomy), collecting the journal, checkpoints, fills,
   alerts, and the adapter's dispatched intents;
2. the deterministic resource measurements per instrument; and
3. the crash/recovery + kill-switch campaign per instrument.

It then evaluates every SLO criterion into a single verdict. It computes **no** market performance:
every fill is exactly zero-traded and zero-exposure, every intent is zero-weight, turnover is zero,
and the paper book holds 100% cash throughout. The runner produces only an in-memory
:class:`QualificationOutcome`; serialization, publication, and completion happen downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eth_research.v2c.oq.harness import (
    DEFAULT_INSTRUMENTS,
    DEFAULT_STARTING_CASH,
    QualificationRun,
    run_cash_control_qualification,
)
from eth_research.v2c.oq.orchestrator import StartedToken, assert_started
from eth_research.v2c.oq.protocol import OQ_PROTOCOL_SLOTS
from eth_research.v2c.oq.recovery import RecoveryReport, run_recovery_campaign
from eth_research.v2c.oq.resources import ResourceReport, measure_resources
from eth_research.v2c.oq.slo import QualificationVerdict, evaluate_qualification


@dataclass(frozen=True, slots=True)
class QualificationOutcome:
    """The full in-memory outcome of one qualification run (pre-serialization)."""

    qualification_id: str
    slots: int
    starting_cash: float
    instruments: tuple[str, ...]
    run: QualificationRun
    resource_reports: tuple[ResourceReport, ...]
    recovery_reports: tuple[RecoveryReport, ...]
    verdict: QualificationVerdict


def execute_qualification(
    token: StartedToken,
    *,
    workdir: str | Path,
    slots: int = OQ_PROTOCOL_SLOTS,
    starting_cash: float = DEFAULT_STARTING_CASH,
    instruments: tuple[str, ...] = DEFAULT_INSTRUMENTS,
) -> QualificationOutcome:
    """Execute the qualification once a run is durably ``started``.

    Re-asserts the ``StartedToken`` first, so no operational count or SLO can be computed before the
    durable ``started`` event. ``workdir`` holds the crash/recovery campaign's ephemeral checkpoint
    files (not archived evidence). Returns the in-memory outcome; it appends no registry event.
    """
    # Calculation-before-start guarantee: refuse to compute anything unless the run is 'started'.
    assert_started(token)
    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)

    run = run_cash_control_qualification(
        slots=slots, starting_cash=starting_cash, instruments=instruments
    )
    resource_reports = tuple(measure_resources(qual) for qual in run.instruments)
    recovery_reports: tuple[RecoveryReport, ...] = tuple(
        run_recovery_campaign(
            qual.instrument_symbol, workdir=root / qual.instrument_symbol, slots=slots
        )
        for qual in run.instruments
    )
    verdict = evaluate_qualification(
        run, resource_reports=resource_reports, recovery_reports=recovery_reports
    )
    return QualificationOutcome(
        qualification_id=token.qualification_id,
        slots=slots,
        starting_cash=starting_cash,
        instruments=instruments,
        run=run,
        resource_reports=resource_reports,
        recovery_reports=recovery_reports,
        verdict=verdict,
    )


__all__ = [
    "QualificationOutcome",
    "execute_qualification",
]
