"""Tests for the offline V2A replay verifier and the v2a-replay workflow (§28).

The verifier must pass clean on the current (pre-run) repository, flag a non-empty sealed ledger,
and its ``--check`` CLI must exit zero here. The v2a-replay workflow must be read-only, run the
replay verifier + the v2 suites, and assert the sealed ledgers are byte-empty before and after (the
repository-wide workflow-security tests additionally enforce SHA-pinning, host allowlist, no
secrets, no id-token, and no artifact upload across every workflow).
"""

from __future__ import annotations

import re
from pathlib import Path

from eth_research.v2.replay import SEALED_LEDGERS, main, verify_v2a

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "v2a-replay.yml"


def test_verify_v2a_clean_on_current_repo() -> None:
    assert verify_v2a(REPO) == []


def test_verify_v2a_flags_a_dirty_sealed_ledger(tmp_path: Path) -> None:
    for rel in SEALED_LEDGERS:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    (tmp_path / SEALED_LEDGERS[0]).write_bytes(b"leak\n")
    problems = verify_v2a(tmp_path)
    assert any("development_gate_access" in p and "byte-empty" in p for p in problems)


def test_verify_v2a_flags_missing_ledger(tmp_path: Path) -> None:
    problems = verify_v2a(tmp_path)
    assert any("is missing" in p for p in problems)


def test_replay_cli_check_returns_zero() -> None:
    assert main(["--check", "--repo-root", str(REPO)]) == 0


# --- v2a-replay workflow shape -------------------------------------------------


def test_workflow_exists_and_is_read_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^permissions:\n\s+contents:\s*read\b", text, re.MULTILINE)
    assert "contents: write" not in text
    assert "id-token" not in text


def test_workflow_runs_the_replay_verifier_and_suites() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m eth_research.v2.replay --check" in text
    assert "tests/test_shadow_platform.py" in text
    assert "tests/test_buyer_boundary.py" in text


def test_workflow_asserts_sealed_ledgers_byte_empty_before_and_after() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("byte-empty") >= 2
    assert "development_gate_access.jsonl" in text or "GATE_LEDGER" in text
    assert "test_evaluations.jsonl" in text or "HOLDOUT_LEDGER" in text
    assert "prospective_evaluations.jsonl" in text or "PROSPECTIVE_LEDGER" in text


def test_workflow_checkout_is_sha_pinned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text
