"""Disposable-repo publisher end-to-end rehearsal (commit 13).

Drives the whole review-only lifecycle — derive → synthetic two-runner → compare →
assemble → verify → branch → draft-PR *shape* — entirely inside a throwaway clone of
the repository. No real network, no GitHub API, no effect on the accepted repo, no
merge, no push: the rehearsal proves the privileged branch/commit step works offline
and always ends in a draft, human-review-required proposal.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from eth_research.m3e.assembly import assemble_update_proposal
from eth_research.m3e.publisher import (
    ACCEPTED_COHORT_BRANCH,
    assert_draft_only,
    build_draft_pr_descriptor,
)
from eth_research.m3e.validation import M3EValidationError
from eth_research.m3e.verify_m3e_program import verify_update_proposal

_AS_OF = "2026-07-22T02:17:00Z"
_PROPOSAL_REL = "research/m3e/proposals/rehearsal"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _stage_runners(m3e_write_runner: Callable[..., object], clone: Path) -> Path:
    from eth_research.m3e.accepted_base import verify_accepted_base
    from eth_research.m3e.cutoff import plan_update_window
    from eth_research.m3e.update_plan import build_update_plan

    base = verify_accepted_base(clone)
    plan = build_update_plan(base, plan_update_window(base, _AS_OF))
    proposal_dir = clone / _PROPOSAL_REL
    m3e_write_runner(
        proposal_dir / "runner_a",
        plan,
        attempt_id="coinbase-eth-usd-prospective-update-runner-a",
        source_commit="a" * 40,
        workflow_run_id="run-99",
        runner_identity="ubuntu-x64-a",
    )
    m3e_write_runner(
        proposal_dir / "runner_b",
        plan,
        attempt_id="coinbase-eth-usd-prospective-update-runner-b",
        source_commit="b" * 40,
        workflow_run_id="run-99",
        runner_identity="ubuntu-x64-b",
    )
    return proposal_dir


def test_end_to_end_proposal_in_a_disposable_repo(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    proposal_dir = _stage_runners(m3e_write_runner, clone)

    # derive → compare → assemble → self-verify, all offline
    assembled, digests = assemble_update_proposal(clone, proposal_dir)
    assert len(digests) == 3
    assert len(verify_update_proposal(clone, proposal_dir)) == 35

    # the single privileged action is always a DRAFT onto a fresh bot branch
    descriptor = build_draft_pr_descriptor(assembled, proposal_relpath=_PROPOSAL_REL)
    assert descriptor["draft"] is True
    assert descriptor["auto_merge"] is False
    assert descriptor["human_review_required"] is True
    assert descriptor["head_branch"].startswith("bot/m3e-prospective-update/")
    assert descriptor["base_branch"] == ACCEPTED_COHORT_BRANCH
    assert descriptor["base_branch"] != descriptor["head_branch"]

    # create the proposal branch + commit inside the disposable repo (no push)
    _git(clone, "config", "user.email", "rehearsal@example.com")
    _git(clone, "config", "user.name", "M3E Rehearsal")
    _git(clone, "checkout", "--quiet", "-b", descriptor["head_branch"])
    _git(clone, "add", _PROPOSAL_REL)
    _git(
        clone,
        "commit",
        "--quiet",
        "-m",
        "M3E: draft prospective-cohort update proposal (rehearsal)",
    )

    # the committed proposal still verifies, and the working tree is clean
    assert len(verify_update_proposal(clone, proposal_dir)) == 35
    assert _git(clone, "status", "--porcelain") == ""
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD") == descriptor["head_branch"]

    # the accepted cohort branch was not advanced or mutated by the rehearsal
    branches = _git(clone, "branch", "--list", ACCEPTED_COHORT_BRANCH)
    assert ACCEPTED_COHORT_BRANCH not in branches or branches.strip().lstrip("* ").startswith(
        ACCEPTED_COHORT_BRANCH
    )


_GOOD_DESCRIPTOR = {
    "base_branch": ACCEPTED_COHORT_BRANCH,
    "head_branch": "bot/m3e-prospective-update/20260715-20260722-" + "a" * 16,
    "draft": True,
    "auto_merge": False,
    "human_review_required": True,
    "modifies_accepted_branch": False,
}


def test_assert_draft_only_accepts_a_valid_descriptor() -> None:
    assert_draft_only(dict(_GOOD_DESCRIPTOR))


def test_assert_draft_only_rejects_a_non_draft() -> None:
    with pytest.raises(M3EValidationError, match="must be a draft"):
        assert_draft_only({**_GOOD_DESCRIPTOR, "draft": False})


def test_assert_draft_only_rejects_auto_merge() -> None:
    with pytest.raises(M3EValidationError, match="auto-merge"):
        assert_draft_only({**_GOOD_DESCRIPTOR, "auto_merge": True})


def test_assert_draft_only_rejects_a_protected_head() -> None:
    with pytest.raises(M3EValidationError):
        assert_draft_only({**_GOOD_DESCRIPTOR, "head_branch": "main"})


def test_assert_draft_only_rejects_a_bot_base() -> None:
    with pytest.raises(M3EValidationError, match="base must be an accepted branch"):
        assert_draft_only(
            {
                **_GOOD_DESCRIPTOR,
                "base_branch": "bot/m3e-prospective-update/20260715-20260722-" + "b" * 16,
            }
        )
