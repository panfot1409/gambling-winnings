"""Deterministic proposal-branch naming and the concurrency lease.

An update proposal is always published onto a **new, uniquely-named** bot branch —
never ``main``, never an accepted ``claude/*`` research branch, never the accepted
cohort branch. The branch name is a **deterministic function of the idempotency
key** (and the human-readable due window), so:

* the *same* due window always maps to the *same* branch — a second scheduled run
  for the same window converges on the existing proposal instead of duplicating it
  (idempotence);
* *distinct* due windows never collide (the key is folded into the name);
* the name always carries the reserved ``bot/m3e-prospective-update/`` prefix and
  can never be a protected or accepted branch (``assert_publishable_proposal_branch``
  fails closed otherwise).

The :class:`ProposalLease` is the concurrency guard: given the branches and open
proposals that already exist, it decides whether this run should *proceed* to
publish a fresh proposal or *skip* because one already exists for this key. Paired
with the workflow's ``concurrency:`` group and the append-only proposal registry,
it makes overlapping runs safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from eth_research.m3e.validation import (
    M3EValidationError,
    domain_sha256,
    require_sha256_hex,
    require_str,
)

PROPOSAL_BRANCH_PREFIX = "bot/m3e-prospective-update/"
LEASE_DOMAIN = "m3e_proposal_lease"

# Branch names M3E must never publish onto. The accepted research/cohort branches
# and the default branch are all off-limits; a proposal only ever lands on a fresh
# bot branch under the reserved prefix.
_PROTECTED_BRANCHES = frozenset(
    {
        "main",
        "master",
        "HEAD",
        "claude/m3d-prospective-evidence-governance",
        "claude/m3c-adaptive-research-governance",
        "claude/m3b-fractional-risk-engine",
        "claude/m3a-development-research-lab",
        "claude/m2b-real-data-benchmarks",
        "claude/m2-dataset-provenance",
        "claude/eth-trading-research-setup-cux72m",
        "claude/m3e-review-only-prospective-updates",
    }
)
_PROTECTED_PREFIXES = ("claude/", "refs/", "origin/")
# A conservative, git-safe branch-name charset (no spaces, no .., no control chars).
_BRANCH_SEGMENT_RE = re.compile(r"^[0-9]{8}-[0-9]{8}-[0-9a-f]{16}$")
_COMPACT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00Z$")


def _compact_day(open_z: str) -> str:
    if not _COMPACT_DATE_RE.fullmatch(open_z):
        raise M3EValidationError(f"expected a UTC-midnight open, got {open_z!r}")
    return open_z[:10].replace("-", "")


def proposal_branch_name(
    *, idempotency_key: str, first_missing_open: str, completed_day_exclusive_end: str
) -> str:
    """Deterministic, unique, human-readable proposal branch under the bot prefix."""
    key = require_sha256_hex("idempotency_key", idempotency_key)
    segment = (
        f"{_compact_day(first_missing_open)}-{_compact_day(completed_day_exclusive_end)}-{key[:16]}"
    )
    if not _BRANCH_SEGMENT_RE.fullmatch(segment):  # pragma: no cover - defensive
        raise M3EValidationError(f"computed branch segment is unsafe: {segment!r}")
    return PROPOSAL_BRANCH_PREFIX + segment


def assert_publishable_proposal_branch(name: str) -> str:
    """Fail closed unless ``name`` is a fresh bot proposal branch (never protected)."""
    text = require_str("branch", name)
    if text in _PROTECTED_BRANCHES:
        raise M3EValidationError(f"refusing to publish onto protected branch {text!r}")
    if not text.startswith(PROPOSAL_BRANCH_PREFIX):
        raise M3EValidationError(f"proposal branch must start with {PROPOSAL_BRANCH_PREFIX!r}")
    tail = text[len(PROPOSAL_BRANCH_PREFIX) :]
    for prefix in _PROTECTED_PREFIXES:
        if tail.startswith(prefix):
            raise M3EValidationError(f"proposal branch tail must not start with {prefix!r}")
    if ".." in text or text.endswith("/") or text.endswith(".lock"):
        raise M3EValidationError(f"proposal branch {text!r} is not a safe git ref")
    if not _BRANCH_SEGMENT_RE.fullmatch(tail):
        raise M3EValidationError(f"proposal branch tail {tail!r} is not the expected shape")
    return text


@dataclass(frozen=True)
class ProposalLease:
    """The concurrency decision for a due window over the accepted base."""

    idempotency_key: str
    plan_sha256: str
    branch_name: str
    lease_id: str
    should_proceed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "plan_sha256": self.plan_sha256,
            "branch_name": self.branch_name,
            "lease_id": self.lease_id,
            "should_proceed": self.should_proceed,
            "reason": self.reason,
        }


def acquire_proposal_lease(
    *,
    idempotency_key: str,
    plan_sha256: str,
    first_missing_open: str,
    completed_day_exclusive_end: str,
    existing_branch_names: frozenset[str] | set[str] | tuple[str, ...] = (),
    existing_open_proposal_keys: frozenset[str] | set[str] | tuple[str, ...] = (),
) -> ProposalLease:
    """Decide whether to publish a fresh proposal or skip (one already exists).

    The lease is a pure function of the plan identity and the currently-existing
    branches / open proposals, so it is safe to evaluate on every runner. It never
    mutates anything: publication is a separate, later step gated on
    ``should_proceed``.
    """
    key = require_sha256_hex("idempotency_key", idempotency_key)
    plan_hash = require_sha256_hex("plan_sha256", plan_sha256)
    branch = proposal_branch_name(
        idempotency_key=key,
        first_missing_open=first_missing_open,
        completed_day_exclusive_end=completed_day_exclusive_end,
    )
    assert_publishable_proposal_branch(branch)
    lease_id = domain_sha256(
        LEASE_DOMAIN,
        {"idempotency_key": key, "plan_sha256": plan_hash, "branch_name": branch},
    )

    branch_exists = branch in set(existing_branch_names)
    key_open = key in set(existing_open_proposal_keys)
    if branch_exists or key_open:
        reason = (
            "a proposal for this due window already exists "
            f"(branch_exists={branch_exists}, open_proposal={key_open}); "
            "skipping to stay idempotent"
        )
        return ProposalLease(key, plan_hash, branch, lease_id, should_proceed=False, reason=reason)
    return ProposalLease(
        key,
        plan_hash,
        branch,
        lease_id,
        should_proceed=True,
        reason="no existing proposal for this due window; proceeding to assemble a fresh proposal",
    )
