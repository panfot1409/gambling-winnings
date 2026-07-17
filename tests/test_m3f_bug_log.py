"""Reproduced M3F defects (failing-test-first).

Each test here reproduces a concrete defect discovered while building the M3F
verification layer. They are written to fail against the buggy code and pass once
the fix lands; see docs/M3F_BUG_LOG.md for the narrative.

F1 — fail-open proposal count. ``honest_state`` and ``catalog`` counted created
proposals with the substring ``'"proposal_created": true'`` (a space after the
colon). The M3E registry serializes compactly via ``canonical_jsonl_line`` with
``separators=(",", ":")`` — a genuine proposal line is ``"proposal_created":true``
with no space, so the substring never matched and the "zero production proposals"
forever-invariant passed fail-open.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.m3f.honest_state import derive_honest_state
from eth_research.m3f.validation import M3FValidationError, count_created_proposals

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

# A real proposal line as the M3E registry would serialize it: compact, no space.
_COMPACT_PROPOSAL = (
    '{"as_of_date":"2026-07-16","entry_kind":"proposal","package_version":"0.8.0",'
    '"previous_line_sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",'
    '"proposal_created":true,"schema_version":1}'
)


def _minimal_repo(tmp_path: Path, registry_body: str) -> Path:
    """Assemble the smallest tree derive_honest_state reads, with a chosen registry."""
    (tmp_path / "research/m3c").mkdir(parents=True)
    (tmp_path / "research/m3e").mkdir(parents=True)
    (tmp_path / "research/m2b").mkdir(parents=True)
    (tmp_path / "research/m3a").mkdir(parents=True)
    (tmp_path / "research/m3d").mkdir(parents=True)
    shutil.copyfile(
        REPO_ROOT / "research/m3c/candidate_decision.json",
        tmp_path / "research/m3c/candidate_decision.json",
    )
    shutil.copyfile(
        REPO_ROOT / "research/m3e/accepted_base.json",
        tmp_path / "research/m3e/accepted_base.json",
    )
    (tmp_path / "research/m3e/proposal_registry.jsonl").write_text(registry_body, encoding="utf-8")
    for empty in (
        "research/m2b/test_evaluations.jsonl",
        "research/m3a/development_gate_access.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    ):
        (tmp_path / empty).write_bytes(b"")
    return tmp_path


def _real_registry_prefix() -> str:
    return (REPO_ROOT / "research/m3e/proposal_registry.jsonl").read_text(encoding="utf-8")


def test_f1_clean_repo_registry_still_derives(tmp_path: Path) -> None:
    # Control: the unmodified registry (genesis + audit_noop:false) yields 0 proposals.
    root = _minimal_repo(tmp_path, _real_registry_prefix())
    state = derive_honest_state(root)
    assert state["m3e_production_proposal_count"] == 0


def test_f1_compact_proposal_triggers_hard_stop(tmp_path: Path) -> None:
    # A genuine (compact) proposal line MUST trip the forever-invariant. The buggy
    # substring-with-space missed it and this derivation returned a state (fail-open).
    body = _real_registry_prefix() + _COMPACT_PROPOSAL + "\n"
    root = _minimal_repo(tmp_path, body)
    with pytest.raises(M3FValidationError, match="production proposal exists"):
        derive_honest_state(root)


def test_f1_count_created_proposals_is_whitespace_independent() -> None:
    genesis = '{"entry_kind":"genesis","schema_version":1}\n'
    noop = '{"entry_kind":"audit_noop","proposal_created":false,"schema_version":1}\n'
    assert count_created_proposals(genesis.encode()) == 0
    assert count_created_proposals(noop.encode()) == 0
    # Compact (no space) and spaced serializations both count.
    assert count_created_proposals(b'{"proposal_created":true}\n') == 1
    assert count_created_proposals(b'{"proposal_created": true}\n') == 1
    # Fail-closed: a smuggled truthy non-bool is still counted, never ignored.
    assert count_created_proposals(b'{"proposal_created":1}\n') == 1
    assert count_created_proposals(genesis.encode() + noop.encode()) == 0
