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
from pathlib import Path

from eth_research.v2c.oq import cli as CLI
from eth_research.v2c.oq import verify_archive as V
from eth_research.v2c.oq.archive import (
    OQ_ARCHIVE_DIR,
    OQ_ARCHIVE_MANIFEST_RELNAME,
    OQ_ARCHIVE_REPORT_RELNAME,
    OQ_ARCHIVE_RESULT_RELNAME,
)
from eth_research.v2c.oq.finalize import STATE_NO_INTENT, assess
from eth_research.v2c.oq.registry import (
    OQ_REGISTRY_PATH,
    OQ_VERDICT_QUALIFIED,
    read_oq_registry,
    registry_state,
)
from eth_research.v2c.oq.supersession import EMPTY_SHA256, SEALED_LEDGER_RELPATHS

REPO = Path(__file__).resolve().parents[1]
_REG = REPO / OQ_REGISTRY_PATH

# The immutable terminal digests of the committed, qualified run. These are a governance anchor:
# the published archive is write-once, so a change here would mean the run was rewritten.
_RESULT_SHA256 = "739cec5dca07b984d6fb624384e490dcab7722c5341053790d5ba8cd1945b897"
_RESULT_BUNDLE_SHA256 = "e52308a0ffd048ffe4283b51b052fd65e2aab4a37156e53952c16354a9dcb525"

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
