"""V2C section 21: the offline SLO / qualification-criteria contract.

Aggregates the cash-control run, the deterministic resource reports, and the crash/recovery reports
into one pass/fail verdict per criterion. These are **internal offline objectives**, not
live-production SLAs. A criterion passes only if it holds for **every** instrument.

Criteria: qualification coverage (a non-emptiness + coverage floor, so a run with no instruments or
uncovered evidence cannot pass vacuously through the quantified checks), event-acceptance
correctness, duplicate suppression, conflicting-duplicate detection, journal durability, checkpoint
consistency, recovery idempotency, kill-switch trip latency, alert completeness, state
reconstruction, bounded processing/memory, and -- the governing invariant -- zero risky exposure
(every fill zero-traded and zero-exposure, every intent zero-weight, no exposure-driven kill trip).
The run computes no market performance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from eth_research.shadow.checkpoint import recover
from eth_research.shadow.journal import ShadowJournal
from eth_research.v2c.oq.events import (
    FAULT_CONFLICTING_DUPLICATE,
    FAULT_DELAYED_RECEIVE,
    FAULT_DUPLICATE,
    FAULT_OUT_OF_ORDER,
    FLAG_GAP,
    FLAG_HIGH_VOLATILITY,
    FLAG_STALE,
    FLAG_ZERO_VOLUME,
    OQ_MIN_ACCEPTED_EVENTS,
    OQ_MIN_EVENT_SLOTS,
    OUTCOME_CONFLICTING_REJECTED,
    OUTCOME_DUPLICATE_SUPPRESSED,
    OUTCOME_OUT_OF_ORDER_REJECTED,
)
from eth_research.v2c.oq.harness import QualificationRun
from eth_research.v2c.oq.recovery import RecoveryReport
from eth_research.v2c.oq.resources import ResourceReport

_ALERT_RAISED_EVENT: str = "alert_raised"

QUALIFICATION_CRITERIA: tuple[str, ...] = (
    "qualification_coverage",
    "event_acceptance_correctness",
    "duplicate_suppression",
    "conflicting_duplicate_detection",
    "journal_durability",
    "checkpoint_consistency",
    "recovery_idempotency",
    "kill_switch_trip_latency",
    "alert_completeness",
    "state_reconstruction",
    "bounded_processing_memory",
    "zero_risky_exposure",
)


@dataclass(frozen=True, slots=True)
class SLOResult:
    """One qualification criterion and whether it held across all instruments."""

    criterion: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class QualificationVerdict:
    """The full qualification verdict."""

    results: tuple[SLOResult, ...]
    passed: bool


def _qualification_coverage(
    run: QualificationRun,
    resource_reports: Sequence[ResourceReport],
    recovery_reports: Sequence[RecoveryReport],
) -> SLOResult:
    """Non-emptiness + coverage floor: a run with no instruments, or an instrument with no
    resource/recovery evidence, cannot pass vacuously through the quantified criteria."""
    problems: list[str] = []
    instruments = tuple(qual.instrument_symbol for qual in run.instruments)
    if not instruments:
        problems.append("qualification run has no instruments")
    if not resource_reports:
        problems.append("no resource reports were produced")
    if not recovery_reports:
        problems.append("no recovery reports were produced")
    resource_symbols = {report.instrument_symbol for report in resource_reports}
    recovery_symbols = {report.instrument_symbol for report in recovery_reports}
    for symbol in instruments:
        if symbol not in resource_symbols:
            problems.append(f"{symbol}: no resource report covers this instrument")
        if symbol not in recovery_symbols:
            problems.append(f"{symbol}: no recovery report covers this instrument")
    return SLOResult(
        "qualification_coverage",
        not problems,
        f"{len(instruments)} instrument(s) each covered by a resource and a recovery report"
        if not problems
        else "; ".join(problems),
    )


def _event_acceptance_correctness(run: QualificationRun) -> SLOResult:
    problems: list[str] = []
    for qual in run.instruments:
        acc = qual.acceptance
        close_times = [env.close_time for env in acc.accepted]
        if any(close_times[i] >= close_times[i + 1] for i in range(len(close_times) - 1)):
            problems.append(f"{qual.instrument_symbol}: accepted stream not strictly monotonic")
        if len(set(close_times)) != len(close_times):
            problems.append(f"{qual.instrument_symbol}: accepted stream has a duplicate close-time")
        slots_built = qual.fixture_manifest.get("slots")
        if not isinstance(slots_built, int) or slots_built < OQ_MIN_EVENT_SLOTS:
            problems.append(f"{qual.instrument_symbol}: fixture slots {slots_built} < min slots")
        if not acc.accepted:
            problems.append(f"{qual.instrument_symbol}: accepted stream is empty")
        elif len(acc.accepted) < OQ_MIN_ACCEPTED_EVENTS:
            problems.append(
                f"{qual.instrument_symbol}: accepted {len(acc.accepted)} events "
                f"< {OQ_MIN_ACCEPTED_EVENTS} effective floor"
            )
        if acc.counts.get(OUTCOME_OUT_OF_ORDER_REJECTED, 0) <= 0:
            problems.append(f"{qual.instrument_symbol}: no out-of-order/delayed rejections")
        for record in acc.records:
            if record.outcome == OUTCOME_OUT_OF_ORDER_REJECTED and record.injected_fault not in (
                FAULT_OUT_OF_ORDER,
                FAULT_DELAYED_RECEIVE,
            ):
                problems.append(f"{qual.instrument_symbol}: out-of-order reject with wrong fault")
            if (
                record.outcome == OUTCOME_CONFLICTING_REJECTED
                and record.injected_fault != FAULT_CONFLICTING_DUPLICATE
            ):
                problems.append(f"{qual.instrument_symbol}: conflicting reject with wrong fault")
            if (
                record.outcome == OUTCOME_DUPLICATE_SUPPRESSED
                and record.injected_fault != FAULT_DUPLICATE
            ):
                problems.append(f"{qual.instrument_symbol}: duplicate suppress with wrong fault")
        flags = {flag for record in acc.records for flag in record.flags}
        for required in (FLAG_GAP, FLAG_STALE, FLAG_ZERO_VOLUME, FLAG_HIGH_VOLATILITY):
            if required not in flags:
                problems.append(f"{qual.instrument_symbol}: fault flag {required!r} never fired")
    return SLOResult(
        "event_acceptance_correctness",
        not problems,
        "every accepted stream monotonic/unique; rejections map to their fault; all flags fired"
        if not problems
        else "; ".join(problems),
    )


def _duplicate_suppression(run: QualificationRun) -> SLOResult:
    problems: list[str] = []
    for qual in run.instruments:
        if qual.acceptance.counts.get(OUTCOME_DUPLICATE_SUPPRESSED, 0) <= 0:
            problems.append(f"{qual.instrument_symbol}: no duplicates were suppressed")
    return SLOResult(
        "duplicate_suppression",
        not problems,
        "exact duplicates suppressed on every instrument" if not problems else "; ".join(problems),
    )


def _conflicting_duplicate_detection(run: QualificationRun) -> SLOResult:
    problems: list[str] = []
    for qual in run.instruments:
        rejected = qual.acceptance.counts.get(OUTCOME_CONFLICTING_REJECTED, 0)
        alerts = len(qual.acceptance.alerts)
        if rejected <= 0:
            problems.append(f"{qual.instrument_symbol}: no conflicting duplicates detected")
        if rejected != alerts:
            problems.append(
                f"{qual.instrument_symbol}: conflict rejects {rejected} != alerts {alerts}"
            )
    return SLOResult(
        "conflicting_duplicate_detection",
        not problems,
        "conflicting duplicates rejected and alerted 1:1" if not problems else "; ".join(problems),
    )


def _alert_completeness(run: QualificationRun) -> SLOResult:
    problems: list[str] = []
    for qual in run.instruments:
        journal_alerts = sum(
            1 for event in qual.result.journal.events if event.event_type == _ALERT_RAISED_EVENT
        )
        if journal_alerts != len(qual.result.alerts):
            problems.append(
                f"{qual.instrument_symbol}: journal alerts {journal_alerts} != "
                f"result alerts {len(qual.result.alerts)}"
            )
        if len(qual.result.alerts) <= 0:
            problems.append(f"{qual.instrument_symbol}: no runner alerts raised")
    return SLOResult(
        "alert_completeness",
        not problems,
        "every runner alert is journaled" if not problems else "; ".join(problems),
    )


def _state_reconstruction(run: QualificationRun) -> SLOResult:
    problems: list[str] = []
    for qual in run.instruments:
        journal = qual.result.journal
        if ShadowJournal.parse(journal.to_jsonl_bytes()).head_hash != journal.head_hash:
            problems.append(f"{qual.instrument_symbol}: journal did not reconstruct")
        recovered = recover(qual.result.checkpoint, journal)
        if recovered.fingerprint() != qual.result.checkpoint.fingerprint():
            problems.append(f"{qual.instrument_symbol}: checkpoint did not reconstruct")
    return SLOResult(
        "state_reconstruction",
        not problems,
        "journal + checkpoint reconstruct exactly" if not problems else "; ".join(problems),
    )


def _zero_risky_exposure(run: QualificationRun) -> SLOResult:
    problems: list[str] = []
    for qual in run.instruments:
        result = qual.result
        if any(fill.traded_units != 0.0 or fill.units_after != 0.0 for fill in result.fills):
            problems.append(f"{qual.instrument_symbol}: a fill traded or held nonzero exposure")
        if any(intent.approved_weight != 0.0 for intent in qual.dispatched_intents):
            problems.append(f"{qual.instrument_symbol}: an intent approved nonzero weight")
        if result.final_account.units != 0.0:
            problems.append(f"{qual.instrument_symbol}: final book holds nonzero units")
        if result.kill_tripped:
            problems.append(f"{qual.instrument_symbol}: an exposure-driven kill trip occurred")
    return SLOResult(
        "zero_risky_exposure",
        not problems,
        "every fill/intent is zero-exposure; book stays 100% cash"
        if not problems
        else "; ".join(problems),
    )


def _from_recovery(reports: Sequence[RecoveryReport], check_name: str, criterion: str) -> SLOResult:
    problems: list[str] = []
    for report in reports:
        match = next((c for c in report.checks if c.name == check_name), None)
        if match is None:
            problems.append(f"{report.instrument_symbol}: missing {check_name}")
        elif not match.passed:
            problems.append(f"{report.instrument_symbol}: {match.detail}")
    return SLOResult(
        criterion, not problems, f"{check_name} held" if not problems else "; ".join(problems)
    )


def _bounded_processing_memory(reports: Sequence[ResourceReport]) -> SLOResult:
    problems = [f"{r.instrument_symbol}: {r.detail}" for r in reports if not r.within_bounds]
    return SLOResult(
        "bounded_processing_memory",
        not problems,
        "within deterministic resource bounds" if not problems else "; ".join(problems),
    )


def evaluate_qualification(
    run: QualificationRun,
    *,
    resource_reports: Sequence[ResourceReport],
    recovery_reports: Sequence[RecoveryReport],
) -> QualificationVerdict:
    """Evaluate every qualification criterion against the run and its resource/recovery evidence."""
    results: tuple[SLOResult, ...] = (
        _qualification_coverage(run, resource_reports, recovery_reports),
        _event_acceptance_correctness(run),
        _duplicate_suppression(run),
        _conflicting_duplicate_detection(run),
        _from_recovery(recovery_reports, "journal_durability", "journal_durability"),
        _from_recovery(recovery_reports, "checkpoint_consistency", "checkpoint_consistency"),
        _from_recovery(recovery_reports, "restart_determinism", "recovery_idempotency"),
        _from_recovery(recovery_reports, "kill_switch_trip_drill", "kill_switch_trip_latency"),
        _alert_completeness(run),
        _state_reconstruction(run),
        _bounded_processing_memory(resource_reports),
        _zero_risky_exposure(run),
    )
    return QualificationVerdict(results, all(result.passed for result in results))


__all__ = [
    "QUALIFICATION_CRITERIA",
    "QualificationVerdict",
    "SLOResult",
    "evaluate_qualification",
]
