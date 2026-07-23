"""V2C sections 17-18 + 21: immutable archive, completion intent, calculation-free finalizer.

Proves the archive assembles three immutable artifacts bound by five terminal digests and publishes
transactionally (immutable paths never overwritten); that the completion intent round-trips and
refuses tampering; and that a crashed-but-published run finalizes without recomputation -- the
finalizer re-appends the recorded completed event only when the archive is present and the registry
is exactly registered -> started, and refuses every incomplete or mismatched state.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.publication import PublicationError
from eth_research.v2c.oq import archive as A
from eth_research.v2c.oq import completion as C
from eth_research.v2c.oq import finalize as F
from eth_research.v2c.oq import orchestrator as O
from eth_research.v2c.oq import protocol as P
from eth_research.v2c.oq import run as R
from eth_research.v2c.oq.freeze import OQ_SOURCE_FREEZE_RELPATH
from eth_research.v2c.oq.registry import (
    OQ_VERDICT_QUALIFIED,
    QualificationIdentity,
    read_oq_registry,
)
from eth_research.v2c.oq.supersession import OQ_SUPERSESSION_PATH

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


def _started(tmp_path: Path) -> tuple[Path, O.StartedToken]:
    """A fresh registry advanced to registered -> started (fast; no execution)."""
    if sys.version_info[:2] != (3, 12):
        pytest.skip("the V2C OQ lifecycle requires CPython 3.12")
    reg = tmp_path / "governance/v2c/oq_registry.jsonl"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_bytes(b"")
    ctx = _ctx(reg)
    O.register_qualification(ctx, event_time_utc="2026-07-22T00:00:00Z", reason="OQ-R")
    token = O.start_qualification(ctx, event_time_utc="2026-07-22T00:00:01Z", reason="OQ-P")
    return reg, token


@pytest.fixture(scope="module")
def archive() -> A.OQArchive:
    """Execute the qualification once and assemble its archive (shared across the module)."""
    tmp = Path(tempfile.mkdtemp())
    _, token = _started(tmp)
    outcome = R.execute_qualification(token, workdir=tmp / "work", slots=_SLOTS)
    return A.build_oq_archive(outcome, identity=_identity())


def _intent(archive: A.OQArchive, token: O.StartedToken) -> C.OQCompletionIntent:
    return C.build_completion_intent(
        archive,
        identity=_identity(),
        event_time_utc="2026-07-22T00:00:02Z",
        reason="OQ-P complete",
        prev_hash=token.started_entry_hash,
    )


# --------------------------------------------------------------------------- #
# The archive                                                                 #
# --------------------------------------------------------------------------- #
def test_archive_binds_the_five_terminal_hashes(archive: A.OQArchive) -> None:
    assert archive.verdict == OQ_VERDICT_QUALIFIED
    for digest in (
        archive.result_sha256,
        archive.report_sha256,
        archive.evidence_sha256,
        archive.archive_manifest_sha256,
        archive.result_bundle_sha256,
    ):
        assert len(digest) == 64
    manifest = json.loads(archive.manifest_bytes)
    assert manifest["artifacts"][A.OQ_ARCHIVE_RESULT_RELNAME] == archive.result_sha256
    assert manifest["artifacts"][A.OQ_ARCHIVE_REPORT_RELNAME] == archive.report_sha256


def test_publish_writes_immutable_artifacts_and_refuses_overwrite(
    archive: A.OQArchive, tmp_path: Path
) -> None:
    A.publish_oq_archive(tmp_path, archive)
    published = sorted(p.name for p in (tmp_path / A.OQ_ARCHIVE_DIR).iterdir())
    assert published == [
        A.OQ_ARCHIVE_MANIFEST_RELNAME,
        A.OQ_ARCHIVE_REPORT_RELNAME,
        A.OQ_ARCHIVE_RESULT_RELNAME,
    ]
    with pytest.raises(PublicationError, match="immutable"):
        A.publish_oq_archive(tmp_path, archive)  # per-run paths are never overwritten


# --------------------------------------------------------------------------- #
# The completion intent                                                       #
# --------------------------------------------------------------------------- #
def test_completion_intent_round_trips(archive: A.OQArchive, tmp_path: Path) -> None:
    _, token = _started(tmp_path)
    intent = _intent(archive, token)
    parsed = C.OQCompletionIntent.from_json_bytes(intent.to_json_bytes())
    assert parsed == intent
    assert parsed.terminal_hashes()["result_sha256"] == archive.result_sha256
    assert parsed.verdict == OQ_VERDICT_QUALIFIED


def test_completion_intent_refuses_artifact_outside_archive(
    archive: A.OQArchive, tmp_path: Path
) -> None:
    _, token = _started(tmp_path)
    raw = json.loads(_intent(archive, token).to_json_bytes())
    raw["artifacts"] = [["governance/v2c/elsewhere.json", "a" * 64]]
    # The intent's artifact relpaths are bound to the exact known archive artifacts (a hardening
    # that closes a startswith-prefix path-traversal), so an out-of-archive relpath is refused.
    with pytest.raises(
        C.OQCompletionIntentError, match="not one of the published archive artifacts"
    ):
        C.OQCompletionIntent.from_json_bytes(json.dumps(raw).encode())


def test_completion_intent_refuses_bad_verdict(archive: A.OQArchive, tmp_path: Path) -> None:
    _, token = _started(tmp_path)
    raw = json.loads(_intent(archive, token).to_json_bytes())
    raw["verdict"] = "spectacular"
    with pytest.raises(C.OQCompletionIntentError, match="verdict"):
        C.OQCompletionIntent.from_json_bytes(json.dumps(raw).encode())


# --------------------------------------------------------------------------- #
# The calculation-free finalizer                                              #
# --------------------------------------------------------------------------- #
def test_crash_after_publish_finalizes_without_recomputation(
    archive: A.OQArchive, tmp_path: Path
) -> None:
    reg, token = _started(tmp_path)
    intent = _intent(archive, token)
    C.write_completion_intent(tmp_path, intent)
    A.publish_oq_archive(tmp_path, archive)  # crash here: 'completed' never appended
    assert F.assess(tmp_path, reg).state == F.STATE_FINALIZABLE
    assert F.finalize(tmp_path, reg).state == F.STATE_FINALIZED
    completed = read_oq_registry(reg)[-1]
    assert completed.event == "completed"
    assert completed.result_sha256 == archive.result_sha256
    assert completed.result_bundle_sha256 == archive.result_bundle_sha256
    assert C.read_completion_intent(tmp_path) is None  # cleared


def test_finalize_is_noop_without_an_intent(tmp_path: Path) -> None:
    reg, _ = _started(tmp_path)
    assert F.assess(tmp_path, reg).state == F.STATE_NO_INTENT
    assert F.finalize(tmp_path, reg).state == F.STATE_NO_INTENT


def test_finalize_refuses_a_missing_artifact(archive: A.OQArchive, tmp_path: Path) -> None:
    reg, token = _started(tmp_path)
    C.write_completion_intent(tmp_path, _intent(archive, token))
    # Never published the archive: the recorded artifacts are absent.
    status = F.assess(tmp_path, reg)
    assert status.state == F.STATE_NOT_FINALIZABLE
    assert "incomplete" in status.detail


def test_finalize_refuses_a_mismatched_started_chain(archive: A.OQArchive, tmp_path: Path) -> None:
    reg, _ = _started(tmp_path)
    intent = C.build_completion_intent(
        archive,
        identity=_identity(),
        event_time_utc="2026-07-22T00:00:02Z",
        reason="OQ-P complete",
        prev_hash="b" * 64,  # not the started event's hash
    )
    C.write_completion_intent(tmp_path, intent)
    A.publish_oq_archive(tmp_path, archive)
    status = F.assess(tmp_path, reg)
    assert status.state == F.STATE_NOT_FINALIZABLE
    assert "chains onto" in status.detail
