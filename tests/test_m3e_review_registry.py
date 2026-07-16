"""Review policy + append-only proposal registry (commit 19)."""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.m3e.proposal import GOVERNANCE_FLAGS, REVIEW_POLICY
from eth_research.m3e.registry import (
    REGISTRY_PATH,
    build_registry_bytes,
    verify_registry,
)
from eth_research.m3e.review_policy import (
    require_governance_flags,
    require_review_policy,
    require_reviewable_operation,
)
from eth_research.m3e.validation import M3EValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# review policy                                                               #
# --------------------------------------------------------------------------- #
def test_pinned_review_policy_is_accepted() -> None:
    assert require_review_policy(dict(REVIEW_POLICY)) == REVIEW_POLICY


def test_a_relaxed_review_policy_is_rejected() -> None:
    with pytest.raises(M3EValidationError):
        require_review_policy({**REVIEW_POLICY, "auto_merge_forbidden": False})
    with pytest.raises(M3EValidationError):
        require_review_policy({**REVIEW_POLICY, "modifies_accepted_branch": True})


def test_governance_flags_must_all_be_false() -> None:
    assert require_governance_flags(dict(GOVERNANCE_FLAGS)) == GOVERNANCE_FLAGS
    with pytest.raises(M3EValidationError):
        require_governance_flags({**GOVERNANCE_FLAGS, "strategy_evaluated": True})


@pytest.mark.parametrize(
    "op", ["merge", "squash_merge", "auto_merge", "enable_auto_merge", "undraft", "retarget"]
)
def test_forbidden_review_operations_fail_closed(op: str) -> None:
    with pytest.raises(M3EValidationError):
        require_reviewable_operation(op)


def test_a_safe_operation_is_allowed() -> None:
    assert require_reviewable_operation("verify") == "verify"


# --------------------------------------------------------------------------- #
# proposal registry                                                           #
# --------------------------------------------------------------------------- #
def test_registry_verifies_on_the_real_repo() -> None:
    records = verify_registry(REPO_ROOT)
    assert records[0]["entry_kind"] == "genesis"
    assert records[1]["entry_kind"] == "audit_noop"
    assert records[1]["proposal_created"] is False
    assert records[1]["workflow_run_id"] == "29441490761"


def test_registry_is_deterministic_and_matches_committed() -> None:
    assert build_registry_bytes() == (REPO_ROOT / REGISTRY_PATH).read_bytes()


def test_a_tampered_registry_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "research/m3e").mkdir(parents=True)
    raw = build_registry_bytes()
    (tmp_path / REGISTRY_PATH).write_bytes(raw.replace(b"29441490761", b"00000000000"))
    with pytest.raises(M3EValidationError):
        verify_registry(tmp_path)


def test_an_audit_noop_record_may_not_claim_a_proposal(tmp_path: Path) -> None:
    # A record that flips proposal_created to true no longer matches the rebuild.
    (tmp_path / "research/m3e").mkdir(parents=True)
    raw = build_registry_bytes()
    (tmp_path / REGISTRY_PATH).write_bytes(
        raw.replace(b'"proposal_created":false', b'"proposal_created":true')
    )
    with pytest.raises(M3EValidationError):
        verify_registry(tmp_path)
