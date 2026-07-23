"""V2C: certify the REAL committed offline-operational-qualification run.

Steps 11-13 executed the OQ once on the canonical registry ``governance/v2c/oq_registry.jsonl`` and
published the immutable run archive under ``governance/v2c/qualifications/``. This module is the
standing certification of that committed artifact: it drives the read-only status / replay / verify
CLIs against the real repository tree (no lifecycle is re-run -- the committed run is verified in
place) and locks the terminal digests so the qualified result can never silently change.

Unlike the lifecycle tests, nothing here registers or starts a run, so no CPython-3.12 runtime gate
applies: the committed run must re-verify identically on both the authoritative (3.12) and the
compatibility (3.13) legs of CI.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.v2c.oq import archive as A
from eth_research.v2c.oq import cli as CLI
from eth_research.v2c.oq import orchestrator as O
from eth_research.v2c.oq import protocol as P
from eth_research.v2c.oq import run as R
from eth_research.v2c.oq import verify_archive as V
from eth_research.v2c.oq.archive import (
    OQ_ARCHIVE_DIR,
    OQ_ARCHIVE_MANIFEST_RELNAME,
    OQ_ARCHIVE_REPORT_RELNAME,
    OQ_ARCHIVE_RESULT_RELNAME,
)
from eth_research.v2c.oq.finalize import STATE_NO_INTENT, assess
from eth_research.v2c.oq.freeze import OQ_E2_FREEZE_ID, OQ_SOURCE_FREEZE_RELPATH
from eth_research.v2c.oq.registry import (
    OQ_REGISTRY_PATH,
    OQ_VERDICT_QUALIFIED,
    QualificationIdentity,
    read_oq_registry,
    registry_state,
)
from eth_research.v2c.oq.supersession import (
    EMPTY_SHA256,
    OQ_SUPERSESSION_PATH,
    SEALED_LEDGER_RELPATHS,
)

REPO = Path(__file__).resolve().parents[1]
_REG = REPO / OQ_REGISTRY_PATH

# The immutable terminal digests of the committed, qualified run. These are a governance anchor:
# the published archive is write-once, so a change here would mean the run was rewritten.
_RESULT_SHA256 = "739cec5dca07b984d6fb624384e490dcab7722c5341053790d5ba8cd1945b897"
_RESULT_BUNDLE_SHA256 = "e52308a0ffd048ffe4283b51b052fd65e2aab4a37156e53952c16354a9dcb525"

# The exact execution parameters the committed run used: the OQ-E2 freeze commit it registered
# under, and the slot count it executed (recorded as `slots` in the committed oq_result.json). Both
# are pinned as literals so the re-execution below is a source-derived proof of the digests, not a
# self-referential read-back.
_OQ_E2_FREEZE_COMMIT = "cea86a5fb93802fcb6d32977f8cdabef222bcf3d"
_CANONICAL_SLOTS = 3800


def _canonical_identity() -> QualificationIdentity:
    """The identity the committed run bound: every hash is the committed artifact's byte hash."""

    def h(rel: str) -> str:
        return P.committed_artifact_sha256(REPO, rel)

    return QualificationIdentity(
        qualification_id=P.OQ_QUALIFICATION_ID,
        methodology_id=P.OQ_METHODOLOGY_ID,
        protocol_sha256=h(P.OQ_PROTOCOL_RELPATH),
        source_freeze_id=OQ_E2_FREEZE_ID,
        source_freeze_sha256=h(OQ_SOURCE_FREEZE_RELPATH),
        fixture_sha256=h(P.OQ_FIXTURE_MANIFEST_RELPATH),
        fault_schedule_sha256=h(P.OQ_FAULT_SCHEDULE_RELPATH),
        slo_contract_sha256=h(P.OQ_SLO_CONTRACT_RELPATH),
        cash_control_identity=h(P.OQ_CASH_CONTROL_IDENTITY_RELPATH),
        runtime_contract_sha256=h(CANONICAL_RUNTIME_CONTRACT_RELPATH),
        package_version=PACKAGE_VERSION,
    )


# The full ordered check list a completed-run replay must certify.
_EXPECTED_REPLAY_CHECKS = [
    "source_freeze_reproduces",
    "oq_e2_activation_anchor_reproduces",
    "protocol_bundle_reproduces",
    "premature_freeze_recorded_superseded",
    "sealed_ledgers_byte_empty",
    "registry_lifecycle_registered_started_completed",
    "archive_artifacts_present",
    "terminal_hashes_match_published_bytes",
    "result_rescans_clean_and_zero_exposure",
    "result_bundle_re_derives",
    "report_re_renders",
    "manifest_re_derives_and_binds",
    "sealed_ledgers_byte_empty",
    "no_pending_completion_intent",
    "archive_directory_shape",
    "oq_q_oracle_independently_accepts",
]


def test_committed_registry_is_completed_and_qualified() -> None:
    assert registry_state(_REG) == "completed"
    events = read_oq_registry(_REG)
    assert [e.event for e in events] == ["registered", "started", "completed"]
    completed = events[-1]
    assert completed.verdict == OQ_VERDICT_QUALIFIED
    assert completed.result_sha256 == _RESULT_SHA256
    assert completed.result_bundle_sha256 == _RESULT_BUNDLE_SHA256


def test_status_reports_completed_with_no_pending_intent() -> None:
    assert CLI.status(REPO, _REG) == {
        "registry_state": "completed",
        "pending_completion_intent": False,
    }


def test_replay_certifies_the_full_completed_check_list() -> None:
    # The state-aware replay re-derives the archive and re-runs the OQ-Q oracle over the committed
    # run; the ordered check list is the mechanical certificate of an independently-accepted run.
    assert CLI.replay(REPO, _REG) == _EXPECTED_REPLAY_CHECKS


def test_deep_verifier_reproves_the_archive() -> None:
    checks = V.verify_oq_run_archive(REPO, _REG)
    assert "terminal_hashes_match_published_bytes" in checks
    assert "result_rescans_clean_and_zero_exposure" in checks
    assert len(checks) == 10


def test_oracle_independently_accepts_the_committed_run() -> None:
    # replay() calls assert_independent_acceptance internally; a clean 16-check replay proves the
    # oracle accepted. This asserts the acceptance check is present rather than swallowed.
    assert "oq_q_oracle_independently_accepts" in CLI.replay(REPO, _REG)


def test_recover_is_a_noop_no_pending_intent() -> None:
    # finalize cleared the completion intent; recovery finds nothing to do on the committed tree.
    assert assess(REPO, _REG).state == STATE_NO_INTENT


def test_sealed_ledgers_remain_byte_empty() -> None:
    # The qualification touched no sealed partition: all three ledgers stay byte-empty (empty-hash).
    for rel in SEALED_LEDGER_RELPATHS:
        path = REPO / rel
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == EMPTY_SHA256


def test_published_archive_holds_exactly_three_immutable_artifacts() -> None:
    archive_dir = REPO / OQ_ARCHIVE_DIR
    names = sorted(p.name for p in archive_dir.iterdir())
    assert names == sorted(
        [
            OQ_ARCHIVE_MANIFEST_RELNAME,
            OQ_ARCHIVE_REPORT_RELNAME,
            OQ_ARCHIVE_RESULT_RELNAME,
        ]
    )
    manifest = json.loads((archive_dir / OQ_ARCHIVE_MANIFEST_RELNAME).read_bytes())
    assert manifest["verdict"] == OQ_VERDICT_QUALIFIED


def test_committed_digests_re_derive_from_the_frozen_source(
    pristine_oq_repo: Path, tmp_path: Path
) -> None:
    """The strongest provenance check: re-EXECUTE the qualification from the frozen source and prove
    it reproduces the committed terminal digests byte-for-byte.

    The read-only replay/verify/oracle above prove the published archive is internally consistent,
    independently accepted, and hash-immutable -- but not that its result is what the frozen source
    actually produces (a self-consistent fabrication of oq_result.json, with every dependent digest
    and the registry chain recomputed, would satisfy them). This test closes that gap: it registers
    -> starts -> executes -> build_oq_archive against an isolated copy of the frozen source at the
    exact canonical slot count and asserts the re-derived digests equal the committed literals. A
    forged
    result cannot pass both this and the read-back assertions above unless the frozen source itself
    were altered -- which verify_oq_source_freeze independently refuses. Re-execution needs the OQ
    runtime (CPython 3.12); the runtime-agnostic checks above cover the 3.13 compatibility leg.
    """
    if sys.version_info[:2] != (3, 12):
        pytest.skip("re-executing the OQ lifecycle requires CPython 3.12")
    identity = _canonical_identity()
    reg = tmp_path / OQ_REGISTRY_PATH
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_bytes(b"")
    ctx = O.QualificationContext(
        repo_root=pristine_oq_repo,
        registry_path=reg,
        supersession_path=pristine_oq_repo / OQ_SUPERSESSION_PATH,
        identity=identity,
        source_freeze_id=OQ_E2_FREEZE_ID,
        source_freeze_commit=_OQ_E2_FREEZE_COMMIT,
        ci_terminal_success=True,
    )
    O.register_qualification(ctx, event_time_utc="2026-07-22T00:00:00Z", reason="re-derive")
    token = O.start_qualification(ctx, event_time_utc="2026-07-22T00:00:01Z", reason="re-derive")
    outcome = R.execute_qualification(token, workdir=tmp_path / "work", slots=_CANONICAL_SLOTS)
    archive = A.build_oq_archive(outcome, identity=identity)
    assert archive.result_sha256 == _RESULT_SHA256
    assert archive.result_bundle_sha256 == _RESULT_BUNDLE_SHA256
