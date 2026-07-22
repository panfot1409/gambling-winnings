"""V2C sections 23-24: the read-only OQ status / replay / verify / recover CLIs.

Proves the state-aware CLIs on the real pristine tree (governance invariants reproduce, the registry
is byte-empty, sealed ledgers are byte-empty) and on a completed run materialized in a temp tree
(status reports completed, verify re-proves the archive, recover is a no-op once finalized).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.v2c.oq import archive as A
from eth_research.v2c.oq import cli as CLI
from eth_research.v2c.oq import completion as C
from eth_research.v2c.oq import finalize as Fz
from eth_research.v2c.oq import orchestrator as O
from eth_research.v2c.oq import protocol as P
from eth_research.v2c.oq import run as R
from eth_research.v2c.oq.freeze import OQ_SOURCE_FREEZE_RELPATH
from eth_research.v2c.oq.registry import OQ_REGISTRY_PATH, QualificationIdentity
from eth_research.v2c.oq.supersession import OQ_SUPERSESSION_PATH, SEALED_LEDGER_RELPATHS

REPO = Path(__file__).resolve().parents[1]
_SLOTS = 3650


def _identity() -> QualificationIdentity:
    def h(rel: str) -> str:
        return P.committed_artifact_sha256(REPO, rel)

    return QualificationIdentity(
        qualification_id=P.OQ_QUALIFICATION_ID,
        methodology_id=P.OQ_METHODOLOGY_ID,
        protocol_sha256=h(P.OQ_PROTOCOL_RELPATH),
        source_freeze_id="oq_e2",
        source_freeze_sha256=h(OQ_SOURCE_FREEZE_RELPATH),
        fixture_sha256=h(P.OQ_FIXTURE_MANIFEST_RELPATH),
        fault_schedule_sha256=h(P.OQ_FAULT_SCHEDULE_RELPATH),
        slo_contract_sha256=h(P.OQ_SLO_CONTRACT_RELPATH),
        cash_control_identity=h(P.OQ_CASH_CONTROL_IDENTITY_RELPATH),
        runtime_contract_sha256=h(CANONICAL_RUNTIME_CONTRACT_RELPATH),
        package_version=PACKAGE_VERSION,
    )


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, object]]:
    code = CLI.main(argv)
    out = capsys.readouterr()
    payload = json.loads((out.out or out.err).strip().splitlines()[-1])
    return code, payload


# --------------------------------------------------------------------------- #
# Pristine (not-yet-run) tree                                                 #
# --------------------------------------------------------------------------- #
def test_status_pristine(capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _run(["status", "--repo-root", str(REPO)], capsys)
    assert code == 0
    assert payload["registry_state"] == "pristine"
    assert payload["pending_completion_intent"] is False


def test_replay_pristine_reproduces_governance(capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _run(["replay", "--repo-root", str(REPO)], capsys)
    assert code == 0
    checks = payload["checks"]
    assert isinstance(checks, list)
    assert "source_freeze_reproduces" in checks
    assert "protocol_bundle_reproduces" in checks
    assert "premature_freeze_recorded_superseded" in checks
    assert "sealed_ledgers_byte_empty" in checks
    assert "registry_pristine_no_run_registered" in checks


def test_verify_pristine_is_a_noop(capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _run(["verify", "--repo-root", str(REPO)], capsys)
    assert code == 0
    assert payload["checks"] == []


def test_recover_pristine_has_no_intent(capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _run(["recover", "--repo-root", str(REPO)], capsys)
    assert code == 0
    assert payload["state"] == Fz.STATE_NO_INTENT


# --------------------------------------------------------------------------- #
# Completed run in a temp tree                                                #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def completed_repo() -> tuple[Path, Path]:
    ident = _identity()
    tmp = Path(tempfile.mkdtemp())
    for rel in SEALED_LEDGER_RELPATHS:
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_bytes(b"")
    reg = tmp / OQ_REGISTRY_PATH
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_bytes(b"")
    ctx = O.QualificationContext(
        repo_root=REPO,
        registry_path=reg,
        supersession_path=REPO / OQ_SUPERSESSION_PATH,
        identity=ident,
        source_freeze_id="oq_e2",
        source_freeze_commit="a" * 40,
        ci_terminal_success=True,
    )
    O.register_qualification(ctx, event_time_utc="2026-07-22T00:00:00Z", reason="OQ-R")
    token = O.start_qualification(ctx, event_time_utc="2026-07-22T00:00:01Z", reason="OQ-P")
    outcome = R.execute_qualification(token, workdir=tmp / "work", slots=_SLOTS)
    archive = A.build_oq_archive(outcome, identity=ident)
    C.write_completion_intent(
        tmp,
        C.build_completion_intent(
            archive,
            identity=ident,
            event_time_utc="2026-07-22T00:00:02Z",
            reason="done",
            prev_hash=token.started_entry_hash,
        ),
    )
    A.publish_oq_archive(tmp, archive)
    Fz.finalize(tmp, reg)
    return tmp, reg


def test_status_completed(
    completed_repo: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    tmp, reg = completed_repo
    code, payload = _run(["status", "--repo-root", str(tmp), "--registry", str(reg)], capsys)
    assert code == 0
    assert payload["registry_state"] == "completed"
    assert payload["pending_completion_intent"] is False


def test_verify_completed_reproves_the_archive(
    completed_repo: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    tmp, reg = completed_repo
    code, payload = _run(["verify", "--repo-root", str(tmp), "--registry", str(reg)], capsys)
    assert code == 0
    checks = payload["checks"]
    assert isinstance(checks, list)
    assert "report_re_renders" in checks
    assert len(checks) == 10


def test_recover_completed_is_a_noop(
    completed_repo: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    tmp, reg = completed_repo
    code, payload = _run(["recover", "--repo-root", str(tmp), "--registry", str(reg)], capsys)
    assert code == 0
    assert payload["state"] == Fz.STATE_NO_INTENT  # intent was cleared at finalize
