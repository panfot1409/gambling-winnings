"""Coherent offline orchestration seam for the review-only update lifecycle.

:func:`prepare_update_proposal` drives the *entire* offline lifecycle through **one**
public callable — verify the accepted base, compute the completed-day cutoff, acquire
the idempotency lease, transactionally assemble and self-verify (the full 35-check
graph) the proposal from the two already-staged runner bundles, build the draft-PR
descriptor, and create the bot branch + commit — so the "ready" claim rests on a
single reachable seam, not a test-only sequence of unrelated helpers.

The package itself opens no socket, holds no key, runs no ``subprocess``, contacts no
exchange, grants no write permission, and opens no pull request. The two privileged,
environment-specific effects are **injected**:

* the two-runner **acquisition** over the network happens on isolated GitHub runners
  and is out of this offline boundary — the seam consumes the already-committed runner
  artifacts under ``proposal_dir``;
* the local Git branch/commit is delegated to an injected :class:`GitPort` (a real
  one at activation, a disposable-repo one under test), so no fixed Git command lives
  in package code.

Opening the *draft* pull request from the returned descriptor is a further, separate,
human-reviewed step. This module is that seam; it is what a later activation wires up.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from eth_research.m3e.accepted_base import verify_accepted_base
from eth_research.m3e.assembly import assemble_update_proposal
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.lease import acquire_proposal_lease
from eth_research.m3e.publisher import assert_draft_only, build_draft_pr_descriptor
from eth_research.m3e.staging import stage_cohort_extension
from eth_research.m3e.update_plan import build_update_plan
from eth_research.m3e.validation import M3EValidationError

OUTCOME_NOOP = "noop_not_due"
OUTCOME_SKIPPED = "skipped_existing_proposal"
OUTCOME_PREPARED = "prepared_draft"

DEFAULT_COMMIT_MESSAGE = "M3E: draft prospective-cohort update proposal (review-only)"


@runtime_checkable
class GitPort(Protocol):
    """The minimal local-Git surface the seam needs, injected by the caller.

    Implementations run **fixed** Git argv against a single repository (never a shell
    string) — a disposable clone under test, the checked-out workspace at activation.
    The package never constructs one.
    """

    def current_branch(self) -> str: ...

    def branch_exists(self, name: str) -> bool: ...

    def create_and_checkout_branch(self, name: str) -> None: ...

    def add(self, pathspec: str) -> None: ...

    def commit(self, message: str) -> str: ...

    def status_porcelain(self) -> str: ...


@dataclass(frozen=True)
class PreparedProposal:
    """The outcome of one offline preparation pass — data only, no side effects beyond
    the injected GitPort's branch/commit."""

    outcome: str
    reason: str
    proposal_branch: str | None = None
    commit_sha: str | None = None
    descriptor: dict[str, Any] | None = None
    staged_attempt_id: str | None = None
    staged_relpaths: tuple[str, ...] = ()


def prepare_update_proposal(
    repo_root: str | Path,
    proposal_dir: str | Path,
    *,
    as_of: str,
    git: GitPort,
    proposal_relpath: str,
    existing_branch_names: frozenset[str] | set[str] | tuple[str, ...] = (),
    existing_open_proposal_keys: frozenset[str] | set[str] | tuple[str, ...] = (),
    commit_message: str = DEFAULT_COMMIT_MESSAGE,
) -> PreparedProposal:
    """Drive the whole offline update-proposal lifecycle through one seam.

    Returns a :class:`PreparedProposal`. A no-op (nothing due) and an idempotent skip
    (a proposal for this window already exists) are ordinary, side-effect-free
    outcomes. A ``prepared_draft`` outcome has created exactly one new bot branch and
    committed exactly the proposal path; the accepted cohort branch is never touched
    and no pull request is opened. Any integrity failure raises ``M3EValidationError``.
    """
    root = Path(repo_root)

    # 1. Trusted anchor + mechanical cutoff.
    base = verify_accepted_base(root)
    decision = plan_update_window(base, as_of)
    if decision.is_noop:
        return PreparedProposal(OUTCOME_NOOP, "no completed day is due; nothing to propose")

    # 2. Deterministic plan + idempotency lease (pure; mutates nothing).
    plan = build_update_plan(base, decision)
    lease = acquire_proposal_lease(
        idempotency_key=plan.idempotency_key,
        plan_sha256=plan.plan_sha256,
        first_missing_open=plan.first_missing_open,
        completed_day_exclusive_end=plan.completed_day_exclusive_end,
        existing_branch_names=existing_branch_names,
        existing_open_proposal_keys=existing_open_proposal_keys,
    )
    if not lease.should_proceed:
        return PreparedProposal(OUTCOME_SKIPPED, lease.reason, proposal_branch=lease.branch_name)

    # A branch already present in the live repository is an idempotent stop — the seam
    # never force-reuses a (possibly orphaned) proposal branch.
    if git.branch_exists(lease.branch_name):
        return PreparedProposal(
            OUTCOME_SKIPPED,
            "proposal branch already exists in the repository; refusing to reuse it",
            proposal_branch=lease.branch_name,
        )

    # 3. Transactional assemble + self-verify (35 checks) from the two staged runners.
    #    A stale accepted base makes the manifest binding / transition fail here.
    assembled, _digests = assemble_update_proposal(root, proposal_dir)
    if assembled.proposal_branch != lease.branch_name:
        raise M3EValidationError("assembled proposal branch does not match the idempotency lease")

    # 4. Stage the cohort extension the proposal implies (V2D): the attempt
    #    evidence, the ledger entry, and the rebuilt derived artifacts — written
    #    transactionally and self-verified as a landed update, rolled back whole
    #    on any failure. The bot commit will carry evidence + growth atomically.
    staged = stage_cohort_extension(root, assembled)

    # 5. The draft-PR descriptor (draft-only, base pinned to the accepted cohort branch).
    descriptor = build_draft_pr_descriptor(assembled, proposal_relpath=proposal_relpath)
    assert_draft_only(descriptor)
    head = str(descriptor["head_branch"])

    # 6. The single privileged effect: a new bot branch + a commit of exactly the
    #    proposal directory and the staged cohort extension. The committed pathspecs
    #    are a closed allowlist — never an arbitrary caller string (e.g. ``.``) that
    #    could stage unrelated files onto the bot branch.
    if (root / proposal_relpath).resolve() != Path(proposal_dir).resolve():
        raise M3EValidationError(
            "proposal_relpath must name the proposal directory being committed"
        )
    git.create_and_checkout_branch(head)
    git.add(proposal_relpath)
    for relpath in staged.all_relpaths:
        git.add(relpath)
    commit_sha = git.commit(commit_message)
    dirty = git.status_porcelain()
    if dirty:
        raise M3EValidationError(f"working tree not clean after the proposal commit: {dirty!r}")
    if git.current_branch() != head:
        raise M3EValidationError("git did not check out the new proposal branch")

    return PreparedProposal(
        OUTCOME_PREPARED,
        "draft proposal + staged cohort extension prepared on a new bot branch; a "
        "separate human-reviewed step opens the draft pull request — nothing is "
        "auto-merged or pushed to an accepted branch",
        proposal_branch=head,
        commit_sha=commit_sha,
        descriptor=descriptor,
        staged_attempt_id=staged.attempt_id,
        staged_relpaths=staged.all_relpaths,
    )
