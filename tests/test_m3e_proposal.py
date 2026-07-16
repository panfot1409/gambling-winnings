"""Proposal assembly + the 35-check whole-proposal verifier (commit 11)."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.m3e.proposal import (
    COMPARISON_NAME,
    PROPOSAL_MANIFEST_DOMAIN,
    PROPOSAL_MANIFEST_NAME,
    AssembledProposal,
)
from eth_research.m3e.validation import M3EValidationError, canonical_json_bytes, domain_sha256
from eth_research.m3e.verify_m3e_program import verify_proposals_root, verify_update_proposal

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def _rehash_manifest(doc: dict[str, Any]) -> bytes:
    body = {k: v for k, v in doc.items() if k != "manifest_sha256"}
    doc = dict(doc)
    doc["manifest_sha256"] = domain_sha256(PROPOSAL_MANIFEST_DOMAIN, body)
    return canonical_json_bytes(doc)


def test_a_clean_proposal_passes_all_35_checks(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    checks = verify_update_proposal(REPO_ROOT, tmp_path / "prop")
    names = [name for name, _ in checks]
    assert len(names) == 35
    assert len(set(names)) == 35
    assert names[0] == "01_accepted_base_rebuilds"
    assert names[-1] == "35_no_smuggled_field_or_artifact"


def test_verifier_has_no_skip_parameter() -> None:
    params = list(inspect.signature(verify_update_proposal).parameters)
    assert params == ["repo_root", "proposal_dir"]


def test_assembled_branch_is_a_bot_proposal_branch(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    assembled = m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    assert assembled.proposal_branch.startswith("bot/m3e-prospective-update/")
    assert assembled.transition.proposed_row_count == 10


def test_a_tampered_comparison_file_is_caught(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    comp = tmp_path / "prop" / COMPARISON_NAME
    doc = json.loads(comp.read_text())
    doc["row_count"] = 999
    comp.write_bytes(canonical_json_bytes(doc))
    with pytest.raises(M3EValidationError):
        verify_update_proposal(REPO_ROOT, tmp_path / "prop")


def test_a_set_governance_flag_is_rejected(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    assembled = m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    doc = dict(assembled.manifest_document)
    doc["governance_flags"] = {**doc["governance_flags"], "strategy_evaluated": True}
    (tmp_path / "prop" / PROPOSAL_MANIFEST_NAME).write_bytes(_rehash_manifest(doc))
    with pytest.raises(M3EValidationError, match="governance flag is set"):
        verify_update_proposal(REPO_ROOT, tmp_path / "prop")


def test_a_flipped_review_policy_is_rejected(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    assembled = m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    doc = dict(assembled.manifest_document)
    doc["review_policy"] = {**doc["review_policy"], "auto_merge_forbidden": False}
    (tmp_path / "prop" / PROPOSAL_MANIFEST_NAME).write_bytes(_rehash_manifest(doc))
    with pytest.raises(M3EValidationError, match="auto-merge"):
        verify_update_proposal(REPO_ROOT, tmp_path / "prop")


def test_a_forbidden_evaluation_artifact_in_the_proposal_is_caught(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    (tmp_path / "prop" / "candidate_results.json").write_text("{}")
    # The closed expected-file-set check refuses any unexpected top-level entry
    # (stronger than the name-marker scan, which still guards the runner subtrees).
    with pytest.raises(
        M3EValidationError, match=r"unexpected entries|forbidden evaluation artifact"
    ):
        verify_update_proposal(REPO_ROOT, tmp_path / "prop")


def test_a_forged_manifest_self_hash_is_rejected(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    assembled = m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    doc = dict(assembled.manifest_document)
    doc["idempotency_key"] = "0" * 64  # a lie, without recomputing the self-hash
    (tmp_path / "prop" / PROPOSAL_MANIFEST_NAME).write_bytes(canonical_json_bytes(doc))
    with pytest.raises(M3EValidationError, match="manifest_sha256 does not match"):
        verify_update_proposal(REPO_ROOT, tmp_path / "prop")


# --------------------------------------------------------------------------- #
# audit §17 (Auditor B finding 3): the proposals root is a closed set         #
# --------------------------------------------------------------------------- #
def test_proposals_root_is_empty_returns_no_proposals(tmp_path: Path) -> None:
    # A repo with no proposals root at all yields the empty list, not an error.
    assert verify_proposals_root(tmp_path) == []


def test_proposals_root_accepts_a_manifest_bearing_directory(tmp_path: Path) -> None:
    root = tmp_path / "research/m3e/proposals"
    (root / "good").mkdir(parents=True)
    (root / "good" / PROPOSAL_MANIFEST_NAME).write_text("{}")
    assert verify_proposals_root(tmp_path) == [root / "good"]


def test_proposals_root_rejects_a_manifest_less_sibling(tmp_path: Path) -> None:
    # A sibling directory without a manifest would be skipped by a per-proposal check
    # that only visits manifest-bearing dirs — a place to smuggle unverified files.
    root = tmp_path / "research/m3e/proposals"
    (root / "good").mkdir(parents=True)
    (root / "good" / PROPOSAL_MANIFEST_NAME).write_text("{}")
    (root / "smuggled").mkdir()
    (root / "smuggled" / "aux.json").write_text('{"sharpe": 2.1}')
    with pytest.raises(M3EValidationError, match="manifest-less"):
        verify_proposals_root(tmp_path)


def test_proposals_root_rejects_a_stray_top_level_file(tmp_path: Path) -> None:
    root = tmp_path / "research/m3e/proposals"
    root.mkdir(parents=True)
    (root / "stowaway.json").write_text('{"pnl": 1.0}')
    with pytest.raises(M3EValidationError, match="non-directory entry"):
        verify_proposals_root(tmp_path)
