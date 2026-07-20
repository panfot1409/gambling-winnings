"""V2C sections 20-23: virtual-time operational qualification of the shadow platform.

Fast unit tests cover the synthetic event stream and the acceptance gate; the slower integration
tests drive the zero-exposure ``cash_control`` target through the shadow runner and evaluate every
qualification criterion. The governing invariant is proven directly: every fill is zero-traded and
zero-exposure, every intent is zero-weight, and the book stays 100% cash -- the qualification
computes no market performance. A fresh-interpreter proof shows the whole OQ surface imports no
candidate/engine module.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from eth_research.shadow.domain import InstrumentId
from eth_research.v2c.oq.events import (
    FLAG_GAP,
    FLAG_HIGH_VOLATILITY,
    FLAG_STALE,
    FLAG_ZERO_VOLUME,
    OQ_MIN_EVENT_SLOTS,
    OUTCOME_CONFLICTING_REJECTED,
    OUTCOME_DUPLICATE_SUPPRESSED,
    OUTCOME_OUT_OF_ORDER_REJECTED,
    OQEventError,
    build_synthetic_raw_events,
    fixture_manifest,
    ingest_events,
)
from eth_research.v2c.oq.harness import (
    QualificationRun,
    run_cash_control_qualification,
)
from eth_research.v2c.oq.recovery import RecoveryReport, run_recovery_campaign
from eth_research.v2c.oq.resources import measure_resources
from eth_research.v2c.oq.slo import QUALIFICATION_CRITERIA, evaluate_qualification

_SLOTS = OQ_MIN_EVENT_SLOTS  # smallest valid fixture keeps the integration tests quick


# --------------------------------------------------------------------------- #
# Section 20: synthetic stream + acceptance gate (fast)                       #
# --------------------------------------------------------------------------- #
def test_synthetic_stream_is_deterministic_and_monotonic() -> None:
    eth = InstrumentId("eth_usd")
    raw = build_synthetic_raw_events(eth, slots=_SLOTS)
    result = ingest_events(raw)
    close_times = [env.close_time for env in result.accepted]
    assert close_times == sorted(set(close_times))  # strictly monotonic, no duplicates
    assert result.accepted
    # Rebuilding + re-ingesting yields a byte-identical fixture digest (no randomness / wall clock).
    again = fixture_manifest(
        build_synthetic_raw_events(eth, slots=_SLOTS),
        ingest_events(build_synthetic_raw_events(eth, slots=_SLOTS)),
        slots=_SLOTS,
    )
    first = fixture_manifest(raw, result, slots=_SLOTS)
    assert first["fixture_digest"] == again["fixture_digest"]


def test_every_fault_class_is_exercised() -> None:
    raw = build_synthetic_raw_events(InstrumentId("eth_usd"), slots=_SLOTS)
    result = ingest_events(raw)
    assert result.counts[OUTCOME_OUT_OF_ORDER_REJECTED] > 0
    assert result.counts[OUTCOME_DUPLICATE_SUPPRESSED] > 0
    assert result.counts[OUTCOME_CONFLICTING_REJECTED] > 0
    flags = {flag for record in result.records for flag in record.flags}
    for required in (FLAG_GAP, FLAG_STALE, FLAG_ZERO_VOLUME, FLAG_HIGH_VOLATILITY):
        assert required in flags, required


def test_conflicting_duplicates_are_detected_and_alerted_one_to_one() -> None:
    result = ingest_events(build_synthetic_raw_events(InstrumentId("btc_usd"), slots=_SLOTS))
    assert result.counts[OUTCOME_CONFLICTING_REJECTED] == len(result.alerts)
    assert len(result.alerts) > 0


def test_build_rejects_too_few_slots() -> None:
    with pytest.raises(OQEventError, match="slots must be"):
        build_synthetic_raw_events(InstrumentId("eth_usd"), slots=OQ_MIN_EVENT_SLOTS - 1)


# --------------------------------------------------------------------------- #
# Sections 21-23: cash-control qualification (slower integration)             #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def eth_run() -> QualificationRun:
    return run_cash_control_qualification(slots=_SLOTS, instruments=("eth_usd",))


@pytest.fixture(scope="module")
def eth_recovery(tmp_path_factory: pytest.TempPathFactory) -> RecoveryReport:
    workdir = tmp_path_factory.mktemp("oq_recovery")
    return run_recovery_campaign("eth_usd", workdir=workdir, slots=_SLOTS)


@pytest.mark.slow
def test_cash_control_run_holds_only_cash(eth_run: QualificationRun) -> None:
    (qual,) = eth_run.instruments
    result = qual.result
    assert result.bars_processed >= 1
    # Every fill is a zero-trade, zero-exposure flat rebalance; every intent is zero-weight.
    assert all(fill.traded_units == 0.0 and fill.units_after == 0.0 for fill in result.fills)
    assert all(intent.approved_weight == 0.0 for intent in qual.dispatched_intents)
    assert result.final_account.units == 0.0
    assert result.kill_tripped is False


@pytest.mark.slow
def test_resource_bounds_hold(eth_run: QualificationRun) -> None:
    (qual,) = eth_run.instruments
    report = measure_resources(qual)
    assert report.within_bounds, report.detail
    assert report.processing_steps == qual.result.bars_processed


@pytest.mark.slow
def test_recovery_campaign_passes(eth_recovery: RecoveryReport) -> None:
    assert eth_recovery.passed, [c.detail for c in eth_recovery.checks if not c.passed]
    names = {c.name for c in eth_recovery.checks}
    assert "kill_switch_trip_drill" in names
    assert "restart_determinism" in names


@pytest.mark.slow
def test_full_qualification_verdict_passes(
    eth_run: QualificationRun, eth_recovery: RecoveryReport
) -> None:
    resources = [measure_resources(q) for q in eth_run.instruments]
    verdict = evaluate_qualification(
        eth_run, resource_reports=resources, recovery_reports=[eth_recovery]
    )
    failed = [r.criterion for r in verdict.results if not r.passed]
    assert verdict.passed, failed
    assert {r.criterion for r in verdict.results} == set(QUALIFICATION_CRITERIA)


@pytest.mark.slow
def test_qualification_fails_without_coverage_evidence(eth_run: QualificationRun) -> None:
    # Coverage gate: without resource/recovery evidence the quantified recovery/resource criteria
    # pass vacuously, so the verdict must FAIL on the coverage floor, not pass on no evidence.
    verdict = evaluate_qualification(eth_run, resource_reports=[], recovery_reports=[])
    assert not verdict.passed
    coverage = next(r for r in verdict.results if r.criterion == "qualification_coverage")
    assert not coverage.passed
    assert "no resource reports" in coverage.detail or "no recovery reports" in coverage.detail


# --------------------------------------------------------------------------- #
# The OQ surface imports no candidate/engine module                           #
# --------------------------------------------------------------------------- #
def test_oq_imports_no_candidate_or_engine_module() -> None:
    banned = [
        "eth_research.v2.candidates",
        "eth_research.v2.evaluator",
        "eth_research.v2b.candidates",
        "eth_research.v2b.evaluation",
        "eth_research.portfolio.engine",
        "eth_research.fractional.engine",
    ]
    code = (
        "import sys, json\n"
        "import eth_research.v2c.oq.events\n"
        "import eth_research.v2c.oq.harness\n"
        "import eth_research.v2c.oq.resources\n"
        "import eth_research.v2c.oq.recovery\n"
        "import eth_research.v2c.oq.slo\n"
        f"banned = {banned!r}\n"
        "print(json.dumps(sorted(m for m in banned if m in sys.modules)))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert json.loads(proc.stdout) == []
