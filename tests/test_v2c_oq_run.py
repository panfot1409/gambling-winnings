"""V2C sections 13-20: the virtual-time runner + result/report models + forbidden-vocab scan.

Proves the runner refuses to compute without a durable ``started`` token, that a full run over both
instruments qualifies with exactly zero risky exposure, that the result and report reproduce and
carry the operational evidence, and that the forbidden financial-performance vocabulary scanner
refuses return/equity/PnL/Sharpe/etc. anywhere in a result -- so a result narrating market
performance can never be built.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.v2c.oq import orchestrator as O
from eth_research.v2c.oq import protocol as P
from eth_research.v2c.oq import result as RES
from eth_research.v2c.oq import run as R
from eth_research.v2c.oq.freeze import OQ_SOURCE_FREEZE_RELPATH
from eth_research.v2c.oq.registry import OQ_VERDICT_QUALIFIED, QualificationIdentity
from eth_research.v2c.oq.supersession import OQ_SUPERSESSION_PATH

REPO = Path(__file__).resolve().parents[1]
_SLOTS = 3650  # the minimum admissible fixture size, for a faster test


def _identity() -> QualificationIdentity:
    return QualificationIdentity(
        qualification_id=P.OQ_QUALIFICATION_ID,
        methodology_id=P.OQ_METHODOLOGY_ID,
        protocol_sha256=P.committed_artifact_sha256(REPO, P.OQ_PROTOCOL_RELPATH),
        source_freeze_id="oq_e2",
        source_freeze_sha256=P.committed_artifact_sha256(REPO, OQ_SOURCE_FREEZE_RELPATH),
        fixture_sha256=P.committed_artifact_sha256(REPO, P.OQ_FIXTURE_MANIFEST_RELPATH),
        fault_schedule_sha256=P.committed_artifact_sha256(REPO, P.OQ_FAULT_SCHEDULE_RELPATH),
        slo_contract_sha256=P.committed_artifact_sha256(REPO, P.OQ_SLO_CONTRACT_RELPATH),
        cash_control_identity=P.committed_artifact_sha256(REPO, P.OQ_CASH_CONTROL_IDENTITY_RELPATH),
        runtime_contract_sha256=P.committed_artifact_sha256(
            REPO, CANONICAL_RUNTIME_CONTRACT_RELPATH
        ),
        package_version=PACKAGE_VERSION,
    )


def _ctx(reg: Path) -> O.QualificationContext:
    return O.QualificationContext(
        repo_root=REPO,
        registry_path=reg,
        supersession_path=REPO / OQ_SUPERSESSION_PATH,
        identity=_identity(),
        source_freeze_id="oq_e2",
        source_freeze_commit="a" * 40,
        ci_terminal_success=True,
    )


@pytest.fixture(scope="module")
def outcome() -> R.QualificationOutcome:
    """Run the full qualification once (expensive) and share it across the module's tests."""
    if sys.version_info[:2] != (3, 12):
        pytest.skip("the V2C OQ lifecycle requires CPython 3.12")
    tmp = Path(tempfile.mkdtemp())
    reg = tmp / "reg.jsonl"
    reg.write_bytes(b"")
    ctx = _ctx(reg)
    O.register_qualification(ctx, event_time_utc="2026-07-22T00:00:00Z", reason="OQ-R")
    token = O.start_qualification(ctx, event_time_utc="2026-07-22T00:00:01Z", reason="OQ-P")
    return R.execute_qualification(token, workdir=tmp / "work", slots=_SLOTS)


# --------------------------------------------------------------------------- #
# The runner                                                                  #
# --------------------------------------------------------------------------- #
def test_runner_refuses_without_a_started_token(tmp_path: Path) -> None:
    reg = tmp_path / "reg.jsonl"
    reg.write_bytes(b"")  # pristine, never started
    token = O.StartedToken(
        qualification_id=P.OQ_QUALIFICATION_ID,
        registry_path=str(reg),
        started_ordinal=1,
        started_entry_hash="0" * 64,
    )
    with pytest.raises(O.OQOrchestratorError, match="'started'"):
        R.execute_qualification(token, workdir=tmp_path / "work", slots=_SLOTS)


def test_run_qualifies_with_zero_risky_exposure(outcome: R.QualificationOutcome) -> None:
    assert outcome.verdict.passed
    assert {q.instrument_symbol for q in outcome.run.instruments} == {"eth_usd", "btc_usd"}
    for qual in outcome.run.instruments:
        assert all(fill.traded_units == 0.0 for fill in qual.result.fills)
        assert all(intent.approved_weight == 0.0 for intent in qual.dispatched_intents)
        assert qual.result.final_account.units == 0.0
        assert not qual.result.kill_tripped


# --------------------------------------------------------------------------- #
# The result + report                                                         #
# --------------------------------------------------------------------------- #
def test_result_is_qualified_and_zero_exposure(outcome: R.QualificationOutcome) -> None:
    result = RES.build_oq_result(outcome, identity=_identity())
    assert result["verdict"] == OQ_VERDICT_QUALIFIED
    counts = result["operational_counts"]
    assert counts["risky_intent_count"] == 0
    assert counts["risky_fill_count"] == 0
    assert counts["turnover"] == 0.0
    assert counts["terminal_book_units"] == 0.0
    assert counts["total_cash_control_instructions"] > 0
    assert len(result["criteria"]) == 12


def test_result_is_deterministic_and_round_trips(outcome: R.QualificationOutcome) -> None:
    a = RES.build_oq_result(outcome, identity=_identity())
    b = RES.build_oq_result(outcome, identity=_identity())
    assert a == b
    assert RES.render_oq_result_bytes(a).endswith(b"\n")


def test_report_carries_verdict_and_counts(outcome: R.QualificationOutcome) -> None:
    result = RES.build_oq_result(outcome, identity=_identity())
    report = RES.build_oq_report(result)
    assert "Verdict: **qualified**" in report
    assert "Risky fills: 0" in report
    assert "100% cash" in report


# --------------------------------------------------------------------------- #
# The forbidden-vocabulary scanner                                            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "term",
    ["Sharpe ratio", "equity curve", "annualized returns", "PnL", "max drawdown", "alpha"],
)
def test_forbidden_vocabulary_is_refused(term: str) -> None:
    with pytest.raises(RES.ForbiddenVocabularyError):
        RES.scan_for_forbidden_vocabulary("payload", {"note": f"we computed the {term}"})


def test_forbidden_vocabulary_scans_nested_structures() -> None:
    payload = {"a": [{"b": ["fine", "the sharpe was 2.0"]}]}
    with pytest.raises(RES.ForbiddenVocabularyError, match="sharpe"):
        RES.scan_for_forbidden_vocabulary("payload", payload)


def test_operational_vocabulary_passes() -> None:
    payload = {
        "verdict": "qualified",
        "detail": "every fill/intent is zero-exposure; book stays 100% cash",
        "criteria": [
            "kill_switch_trip_latency",
            "bounded_processing_memory",
            "zero_risky_exposure",
        ],
    }
    RES.scan_for_forbidden_vocabulary("payload", payload)  # must not raise
