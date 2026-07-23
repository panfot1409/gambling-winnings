"""Offline draft-PR descriptor for a verified update proposal.

The single privileged action in the M3E lifecycle — creating the proposal branch
and opening the pull request — is always a **draft** onto a **new bot branch**,
never a merge and never a push to an accepted branch. This module builds the
descriptor of that draft PR from a verified :class:`~eth_research.m3e.proposal.AssembledProposal`
and fails closed unless it is a draft, human-review-required, non-auto-merge PR onto
a publishable bot branch whose base is an accepted branch (never the head).

It opens no socket, calls no GitHub API, and creates no branch — it produces the
*data* a caller (a human, or a separately-reviewed activation) would use to open the
draft PR. The disposable-repo end-to-end rehearsal drives the git branch/commit
steps entirely inside a throwaway repository to prove the whole lifecycle works
offline, with no real network and no effect on the accepted repository.
"""

from __future__ import annotations

from typing import Any

from eth_research.m3e.lease import assert_publishable_proposal_branch
from eth_research.m3e.proposal import AssembledProposal
from eth_research.m3e.validation import M3EValidationError, require_bool, require_str

# The accepted cohort branch a data-update proposal targets for human review. The
# M2B-M3E stack (and every later accepted layer) is true-merged, so the accepted
# cohort now lives on the default branch: proposals are drafts based on main and
# land only through a human merge there. The stale pre-merge milestone branch
# remains protected in the lease (never a publish target).
ACCEPTED_COHORT_BRANCH = "main"
DRAFT_PR_TITLE = "M3E prospective-cohort update proposal (DRAFT — human review required)"


def build_draft_pr_descriptor(
    assembled: AssembledProposal,
    *,
    base_branch: str = ACCEPTED_COHORT_BRANCH,
    proposal_relpath: str,
) -> dict[str, Any]:
    """Build + validate the draft-PR descriptor for a verified proposal."""
    transition = assembled.transition
    body = (
        "## Prospective cohort update proposal (review-only)\n\n"
        "This is an **append-only** extension of the accepted prospective ETH-USD "
        "daily cohort, assembled offline and independently attested by **two isolated "
        "runners** that produced byte-identical canonical content. It evaluates no "
        "strategy, declares no candidate, computes no performance metric, and moves no "
        "money.\n\n"
        f"- Accepted (old) rows: **{transition.old_row_count}**, last open "
        f"`{transition.old_last_open}`\n"
        f"- Newly-completed days appended: **{transition.new_window_row_count}**\n"
        f"- Proposed cohort rows: **{transition.proposed_row_count}**, last open "
        f"`{transition.proposed_last_open}`\n"
        f"- Proposed cohort fingerprint: `{transition.proposed_cohort_fingerprint}`\n"
        f"- Idempotency key: `{assembled.idempotency_key}`\n\n"
        "**HUMAN REVIEW REQUIRED. Do not auto-merge.** CI replays the complete proposed "
        "cohort and re-runs the 35-check proposal verifier.\n"
    )
    descriptor: dict[str, Any] = {
        "base_branch": require_str("base_branch", base_branch),
        "head_branch": assembled.proposal_branch,
        "draft": True,
        "auto_merge": False,
        "human_review_required": True,
        "modifies_accepted_branch": False,
        "title": DRAFT_PR_TITLE,
        "body": body,
        "idempotency_key": assembled.idempotency_key,
        "proposal_relpath": require_str("proposal_relpath", proposal_relpath),
        "proposed_last_open": transition.proposed_last_open,
        "proposed_row_count": transition.proposed_row_count,
        "manifest_sha256": require_str(
            "manifest_sha256", assembled.manifest_document["manifest_sha256"]
        ),
    }
    assert_draft_only(descriptor)
    return descriptor


def assert_draft_only(descriptor: dict[str, Any]) -> None:
    """Fail closed unless the descriptor is a draft, human-required, non-auto-merge PR."""
    if require_bool("draft", descriptor.get("draft")) is not True:
        raise M3EValidationError("proposal PR must be a draft")
    if require_bool("auto_merge", descriptor.get("auto_merge")) is not False:
        raise M3EValidationError("proposal PR must not enable auto-merge")
    if require_bool("human_review_required", descriptor.get("human_review_required")) is not True:
        raise M3EValidationError("proposal PR must require human review")
    if require_bool("modifies_accepted_branch", descriptor.get("modifies_accepted_branch")):
        raise M3EValidationError("proposal must not modify the accepted branch")
    head = assert_publishable_proposal_branch(require_str("head_branch", descriptor["head_branch"]))
    base = require_str("base_branch", descriptor["base_branch"])
    if base == head:
        raise M3EValidationError("proposal base and head must differ")
    # The base is pinned to the accepted cohort branch — never the default branch,
    # another milestone branch, a bot branch, or the empty string.
    if base != ACCEPTED_COHORT_BRANCH:
        raise M3EValidationError(
            "proposal base must be an accepted branch (the accepted cohort branch)"
        )
