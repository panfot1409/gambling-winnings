"""V2C sections 11 + 12: the fail-closed OQ orchestrator + calculation-before-start proof.

Proves the ordered pre-start gate sequence passes against the real committed tree with a correctly
bound identity, that every gate fails closed when its precondition is violated (a superseded
authoritative freeze, a deleted supersession record, an identity that misbinds a committed artifact,
a candidate reference, a non-empty sealed ledger, a firewall drift, the wrong registry state, an
unattested CI), and that the lifecycle transitions are ordered so no StartedToken -- the runner's
only entry to computation -- can exist before the durable ``started`` event.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.v2c.oq import orchestrator as O
from eth_research.v2c.oq import protocol as P
from eth_research.v2c.oq.freeze import OQ_SOURCE_FREEZE_RELPATH
from eth_research.v2c.oq.registry import QualificationIdentity, read_oq_registry, registry_state
from eth_research.v2c.oq.supersession import OQ_SUPERSESSION_PATH, SEALED_LEDGER_RELPATHS

REPO = Path(__file__).resolve().parents[1]
_E4B3CC3 = "e4b3cc3d6ecfa0d58dd4c71c01f06b2e252ba6ee"
_E2_COMMIT = "a" * 40  # a placeholder replacement-freeze commit that is NOT superseded

_OQ_312_ONLY = pytest.mark.skipif(
    sys.version_info[:2] != (3, 12),
    reason="the OQ orchestrator enforces CPython 3.12; the live lifecycle runs only there",
)


def _identity() -> QualificationIdentity:
    """The identity OQ-R will bind: every hash equals the committed artifact's byte hash."""
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


def _ctx(registry_path: Path, **over: object) -> O.QualificationContext:
    base = {
        "repo_root": REPO,
        "registry_path": registry_path,
        "supersession_path": REPO / OQ_SUPERSESSION_PATH,
        "identity": _identity(),
        "source_freeze_id": "oq_e2",
        "source_freeze_commit": _E2_COMMIT,
        "ci_terminal_success": True,
    }
    base.update(over)
    return O.QualificationContext(**base)  # type: ignore[arg-type]


def _pristine_registry(tmp_path: Path) -> Path:
    reg = tmp_path / "oq_registry.jsonl"
    reg.write_bytes(b"")
    return reg


def _failed_gates(report: O.PreflightReport) -> set[str]:
    return {gate.name for gate in report.gates if not gate.passed}


# --------------------------------------------------------------------------- #
# The ordered gate sequence + the happy path                                  #
# --------------------------------------------------------------------------- #
def test_gate_order_is_nonempty_and_unique() -> None:
    assert len(O.GATE_ORDER) >= 20
    assert len(set(O.GATE_ORDER)) == len(O.GATE_ORDER)
    # The ordering contract: structural first, CI attestation last.
    assert O.GATE_ORDER[0] == "repo_root_is_directory"
    assert O.GATE_ORDER[-1] == "ci_terminal_success_attested"


@_OQ_312_ONLY
def test_full_preflight_passes_on_the_pristine_tree(tmp_path: Path, pristine_oq_repo: Path) -> None:
    # The canonical tree now carries a completed run; the pristine (pre-run) tree is reconstructed
    # in an isolated copy so the happy path -- every gate green, including no_prior_run_artifacts --
    # is still proven.
    ctx = _ctx(_pristine_registry(tmp_path), repo_root=pristine_oq_repo)
    report = O.preflight_report(ctx, expect_state="pristine")
    assert report.passed, _failed_gates(report)
    # assert_preflight (fail-closed) returns one detail per gate.
    details = O.assert_preflight(ctx, expect_state="pristine")
    assert len(details) == len(O.GATE_ORDER)


# --------------------------------------------------------------------------- #
# The lifecycle transitions + the calculation-before-start proof              #
# --------------------------------------------------------------------------- #
@_OQ_312_ONLY
def test_register_then_start_yields_a_started_token(tmp_path: Path, pristine_oq_repo: Path) -> None:
    reg = _pristine_registry(tmp_path)
    ctx = _ctx(reg, repo_root=pristine_oq_repo)
    O.register_qualification(ctx, event_time_utc="2026-07-22T00:00:00Z", reason="OQ-R")
    assert registry_state(reg) == "registered"
    token = O.start_qualification(ctx, event_time_utc="2026-07-22T00:00:01Z", reason="OQ-P")
    # The durable 'started' event exists before the token is usable: the registry reads back
    # 'started', and the token is at ordinal 1 (registered=0, started=1).
    assert registry_state(reg) == "started"
    assert token.started_ordinal == 1
    assert token.qualification_id == P.OQ_QUALIFICATION_ID
    O.assert_started(token)  # must not raise
    events = read_oq_registry(reg)
    assert events[-1].entry_hash == token.started_entry_hash


@_OQ_312_ONLY
def test_start_refuses_a_pristine_registry(tmp_path: Path, pristine_oq_repo: Path) -> None:
    ctx = _ctx(_pristine_registry(tmp_path), repo_root=pristine_oq_repo)
    with pytest.raises(O.OQOrchestratorError, match=r"registry state|does not permit"):
        O.start_qualification(ctx, event_time_utc="2026-07-22T00:00:00Z", reason="OQ-P")


@_OQ_312_ONLY
def test_register_refuses_a_non_pristine_registry(tmp_path: Path, pristine_oq_repo: Path) -> None:
    reg = _pristine_registry(tmp_path)
    ctx = _ctx(reg, repo_root=pristine_oq_repo)
    O.register_qualification(ctx, event_time_utc="2026-07-22T00:00:00Z", reason="OQ-R")
    with pytest.raises(O.OQOrchestratorError, match=r"registry state|does not permit"):
        O.register_qualification(ctx, event_time_utc="2026-07-22T00:00:02Z", reason="again")


def test_assert_started_rejects_a_non_started_registry(tmp_path: Path) -> None:
    reg = _pristine_registry(tmp_path)
    token = O.StartedToken(
        qualification_id=P.OQ_QUALIFICATION_ID,
        registry_path=str(reg),
        started_ordinal=1,
        started_entry_hash="0" * 64,
    )
    with pytest.raises(O.OQOrchestratorError, match="'started'"):
        O.assert_started(token)


# --------------------------------------------------------------------------- #
# Every gate fails closed                                                      #
# --------------------------------------------------------------------------- #
def test_superseded_authoritative_freeze_is_refused(tmp_path: Path) -> None:
    # The premature e4b3cc3 freeze cannot authorize: as the authoritative freeze it is superseded.
    ctx = _ctx(_pristine_registry(tmp_path), source_freeze_commit=_E4B3CC3)
    with pytest.raises(O.OQOrchestratorError):
        O.assert_preflight(ctx, expect_state="pristine")
    assert "source_freeze_not_superseded" in _failed_gates(
        O.preflight_report(ctx, expect_state="pristine")
    )


def test_missing_premature_supersession_is_refused(tmp_path: Path) -> None:
    # If the premature freeze is NOT recorded superseded (e.g. the record was deleted), refuse.
    ctx = _ctx(_pristine_registry(tmp_path), premature_freeze_commit="f" * 40)
    assert "premature_freeze_superseded" in _failed_gates(
        O.preflight_report(ctx, expect_state="pristine")
    )
    with pytest.raises(O.OQOrchestratorError):
        O.assert_preflight(ctx, expect_state="pristine")


def test_unattested_ci_is_refused(tmp_path: Path) -> None:
    ctx = _ctx(_pristine_registry(tmp_path), ci_terminal_success=False)
    assert "ci_terminal_success_attested" in _failed_gates(
        O.preflight_report(ctx, expect_state="pristine")
    )


def test_identity_that_misbinds_an_artifact_is_refused(tmp_path: Path) -> None:
    bad = replace(_identity(), protocol_sha256="0" * 64)
    ctx = _ctx(_pristine_registry(tmp_path), identity=bad)
    assert "identity_binds_protocol" in _failed_gates(
        O.preflight_report(ctx, expect_state="pristine")
    )


def test_candidate_reference_in_identity_is_refused(tmp_path: Path) -> None:
    # A legacy candidate id smuggled into the methodology id must be caught by the candidate screen.
    bad = replace(_identity(), methodology_id="meanrev_zscore_accumulation")
    ctx = _ctx(_pristine_registry(tmp_path), identity=bad)
    failed = _failed_gates(O.preflight_report(ctx, expect_state="pristine"))
    assert "no_candidate_reference_in_identity" in failed


def test_wrong_registry_state_is_refused(tmp_path: Path) -> None:
    # Expecting 'registered' against a pristine registry fails the lifecycle gate.
    ctx = _ctx(_pristine_registry(tmp_path))
    assert "registry_state_permits" in _failed_gates(
        O.preflight_report(ctx, expect_state="registered")
    )


def test_nonempty_sealed_ledger_is_refused(tmp_path: Path) -> None:
    # A repo whose sealed ledger is non-empty must fail the sealed-partition gate (called directly
    # so the check is exercised without materializing the whole governance tree).
    for relpath in SEALED_LEDGER_RELPATHS:
        path = tmp_path / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    (tmp_path / SEALED_LEDGER_RELPATHS[0]).write_bytes(b"contaminated\n")
    ctx = _ctx(_pristine_registry(tmp_path), repo_root=tmp_path)
    with pytest.raises(O.OQOrchestratorError, match="byte-empty"):
        O._gate_sealed_ledgers_byte_empty(ctx, "pristine")


def test_firewall_drift_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # If the firewall stopped refusing a forbidden request kind, the gate must catch it.
    monkeypatch.setattr(O, "guard_request_kind", lambda kind: kind)
    ctx = _ctx(_pristine_registry(tmp_path))
    with pytest.raises(O.OQOrchestratorError, match=r"forbidden request kind|cash_control"):
        O._gate_firewall_admits_only_cash_control(ctx, "pristine")


def test_symlinked_registry_is_refused(tmp_path: Path) -> None:
    reg = _pristine_registry(tmp_path)
    link = tmp_path / "link.jsonl"
    link.symlink_to(reg)
    ctx = _ctx(link)
    assert "registry_is_not_symlink" in _failed_gates(
        O.preflight_report(ctx, expect_state="pristine")
    )
