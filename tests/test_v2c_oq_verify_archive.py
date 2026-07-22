"""V2C section 21: the deep, read-only OQ run-archive verifier.

Executes and publishes one qualification, captures the completed-run bytes, and re-materializes them
into fresh trees to prove the deep verifier passes on a clean archive and fails closed on every
tamper: a mutated result or report, a non-empty sealed ledger, an extra archive entry, a pending
completion intent, and a truncated (not-completed) registry.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.v2c.oq import archive as A
from eth_research.v2c.oq import completion as C
from eth_research.v2c.oq import finalize as Fz
from eth_research.v2c.oq import orchestrator as O
from eth_research.v2c.oq import protocol as P
from eth_research.v2c.oq import run as R
from eth_research.v2c.oq.freeze import OQ_SOURCE_FREEZE_RELPATH
from eth_research.v2c.oq.registry import OQ_REGISTRY_PATH, QualificationIdentity
from eth_research.v2c.oq.supersession import OQ_SUPERSESSION_PATH, SEALED_LEDGER_RELPATHS
from eth_research.v2c.oq.verify_archive import OQRunArchiveError, verify_oq_run_archive

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


@pytest.fixture(scope="module")
def completed_bytes() -> dict[str, bytes]:
    """Execute + publish + finalize one run; capture the completed-run tree as relpath -> bytes."""
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
    Fz.finalize(tmp, reg)  # clears the intent, appends completed
    captured: dict[str, bytes] = {OQ_REGISTRY_PATH: reg.read_bytes()}
    for rel in SEALED_LEDGER_RELPATHS:
        captured[rel] = b""
    for name in (
        A.OQ_ARCHIVE_RESULT_RELNAME,
        A.OQ_ARCHIVE_REPORT_RELNAME,
        A.OQ_ARCHIVE_MANIFEST_RELNAME,
    ):
        captured[A.archive_relpath(name)] = (tmp / A.archive_relpath(name)).read_bytes()
    return captured


def _materialize(root: Path, captured: dict[str, bytes]) -> Path:
    for rel, data in captured.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root / OQ_REGISTRY_PATH


def test_deep_verify_passes_on_a_clean_archive(
    completed_bytes: dict[str, bytes], tmp_path: Path
) -> None:
    reg = _materialize(tmp_path, completed_bytes)
    checks = verify_oq_run_archive(tmp_path, reg)
    assert "report_re_renders" in checks
    assert "result_bundle_re_derives" in checks
    assert len(checks) == 10


def test_tampered_result_is_refused(completed_bytes: dict[str, bytes], tmp_path: Path) -> None:
    data = dict(completed_bytes)
    data[A.archive_relpath(A.OQ_ARCHIVE_RESULT_RELNAME)] += b"\n"
    reg = _materialize(tmp_path, data)
    with pytest.raises(OQRunArchiveError, match="result_sha256"):
        verify_oq_run_archive(tmp_path, reg)


def test_tampered_report_is_refused(completed_bytes: dict[str, bytes], tmp_path: Path) -> None:
    data = dict(completed_bytes)
    data[A.archive_relpath(A.OQ_ARCHIVE_REPORT_RELNAME)] += b"tampered\n"
    reg = _materialize(tmp_path, data)
    with pytest.raises(OQRunArchiveError, match="report_sha256"):
        verify_oq_run_archive(tmp_path, reg)


def test_nonempty_sealed_ledger_is_refused(
    completed_bytes: dict[str, bytes], tmp_path: Path
) -> None:
    data = dict(completed_bytes)
    data[SEALED_LEDGER_RELPATHS[0]] = b"contaminated\n"
    reg = _materialize(tmp_path, data)
    with pytest.raises(OQRunArchiveError, match="byte-empty"):
        verify_oq_run_archive(tmp_path, reg)


def test_extra_archive_entry_is_refused(completed_bytes: dict[str, bytes], tmp_path: Path) -> None:
    reg = _materialize(tmp_path, completed_bytes)
    (tmp_path / A.OQ_ARCHIVE_DIR / "stray.json").write_bytes(b"{}\n")
    with pytest.raises(OQRunArchiveError, match="unexpected entries"):
        verify_oq_run_archive(tmp_path, reg)


def test_pending_completion_intent_is_refused(
    completed_bytes: dict[str, bytes], tmp_path: Path
) -> None:
    reg = _materialize(tmp_path, completed_bytes)
    (tmp_path / C.OQ_COMPLETION_INTENT_RELPATH).write_bytes(b'{"stale": true}\n')
    with pytest.raises(OQRunArchiveError):
        verify_oq_run_archive(tmp_path, reg)


def test_not_completed_registry_is_refused(
    completed_bytes: dict[str, bytes], tmp_path: Path
) -> None:
    data = dict(completed_bytes)
    # Drop the final (completed) registry line, leaving registered -> started.
    lines = data[OQ_REGISTRY_PATH].splitlines(keepends=True)
    data[OQ_REGISTRY_PATH] = b"".join(lines[:-1])
    reg = _materialize(tmp_path, data)
    with pytest.raises(OQRunArchiveError, match="lifecycle"):
        verify_oq_run_archive(tmp_path, reg)
