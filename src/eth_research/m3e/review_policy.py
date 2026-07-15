"""The review policy: draft-only, human-required, never auto-merged.

Every M3E update proposal declares — and every verifier enforces — the same
review policy: the proposal is opened as a **draft**, requires **human review**,
must **not** be auto-merged, must **not** be retargeted, and must **not** modify the
accepted branch. This module formalizes that policy as pinned data plus fail-closed
guards, so no code path can quietly relax it.

M3E decides nothing and merges nothing. The guards here reject any attempt to merge,
undraft, enable auto-merge, or retarget a proposal.
"""

from __future__ import annotations

from typing import Any

from eth_research.m3e.proposal import GOVERNANCE_FLAGS, REVIEW_POLICY
from eth_research.m3e.validation import (
    M3EValidationError,
    require_bool,
    require_mapping,
    require_str,
)

# Operations M3E must never perform on a proposal (or any PR).
FORBIDDEN_REVIEW_OPERATIONS = frozenset(
    {
        "merge",
        "squash_merge",
        "rebase_merge",
        "auto_merge",
        "enable_auto_merge",
        "undraft",
        "mark_ready_for_review",
        "retarget",
        "change_base",
        "force_merge",
        "push_to_accepted_branch",
    }
)


def require_review_policy(mapping: object) -> dict[str, Any]:
    """Validate a proposal's review policy matches the pinned draft-only policy."""
    policy = require_mapping("review_policy", mapping)
    for flag in (
        "draft_required",
        "human_review_required",
        "auto_merge_forbidden",
        "retarget_forbidden",
    ):
        if not require_bool(flag, policy.get(flag)):
            raise M3EValidationError(f"review policy must set {flag} true")
    if require_bool("modifies_accepted_branch", policy.get("modifies_accepted_branch")):
        raise M3EValidationError("review policy must not modify the accepted branch")
    if policy != REVIEW_POLICY:
        raise M3EValidationError("review policy drifted from the pinned policy")
    return policy


def require_governance_flags(mapping: object) -> dict[str, Any]:
    """Validate the explicit false governance flags — M3E evaluates nothing."""
    flags = require_mapping("governance_flags", mapping)
    if flags != GOVERNANCE_FLAGS or any(bool(v) for v in flags.values()):
        raise M3EValidationError("a governance flag is set — M3E evaluates nothing")
    return flags


def require_reviewable_operation(operation: str) -> str:
    """Fail closed on any merge/auto-merge/undraft/retarget operation name."""
    text = require_str("operation", operation)
    if text in FORBIDDEN_REVIEW_OPERATIONS:
        raise M3EValidationError(f"operation {text!r} is forbidden — proposals are review-only")
    return text
