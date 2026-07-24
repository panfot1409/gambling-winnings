"""The coherent offline orchestration seam (audit §8).

``prepare_update_proposal`` drives the whole review-only lifecycle through one public
callable. These tests run it inside a disposable clone with a subprocess-backed
``GitPort`` (fixed argv, in the test — never in package code) and prove: the happy
path creates exactly one draft-only bot branch and leaves the accepted cohort branch
untouched; a not-due window is a no-op; a repeat run is an idempotent skip (both via
the lease and via a pre-existing branch); and a tampered/stale accepted base is
refused. The seam is what a later activation wires up — no test here calls unrelated
helpers in sequence.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from eth_research.m3e.accepted_base import AcceptedProspectiveBase
from eth_research.m3e.orchestrator import (
    OUTCOME_NOOP,
    OUTCOME_PREPARED,
    OUTCOME_SKIPPED,
    GitPort,
    prepare_update_proposal,
)
from eth_research.m3e.publisher import ACCEPTED_COHORT_BRANCH
from eth_research.m3e.validation import M3EValidationError

_PROPOSAL_REL = "research/m3e/proposals/rehearsal"


def _z(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _due_as_of(base: AcceptedProspectiveBase) -> str:
    """A due as_of derived from the clone's accepted base (7 settled days due)."""
    return _z(pd.Timestamp(base.last_open) + pd.Timedelta(days=8, hours=2, minutes=17))


class _SubprocessGitPort:
    """A disposable-repo GitPort that runs fixed Git argv (no shell string)."""

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo)

    def _run(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True
        )
        return result.stdout

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD").strip()

    def branch_exists(self, name: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def create_and_checkout_branch(self, name: str) -> None:
        self._run("checkout", "--quiet", "-b", name)

    def add(self, pathspec: str) -> None:
        self._run("add", pathspec)

    def commit(self, message: str) -> str:
        self._run("commit", "--quiet", "-m", message)
        return self._run("rev-parse", "HEAD").strip()

    def status_porcelain(self) -> str:
        return self._run("status", "--porcelain").strip()


def test_subprocess_git_port_satisfies_the_protocol() -> None:
    assert isinstance(_SubprocessGitPort(Path(".")), GitPort)


def _stage(
    clone: Path, m3e_write_runner: Callable[..., object]
) -> tuple[Path, AcceptedProspectiveBase]:
    from eth_research.m3e.accepted_base import verify_accepted_base
    from eth_research.m3e.cutoff import plan_update_window
    from eth_research.m3e.update_plan import build_update_plan

    base = verify_accepted_base(clone)
    plan = build_update_plan(base, plan_update_window(base, _due_as_of(base)))
    proposal_dir = clone / _PROPOSAL_REL
    for label in ("a", "b"):
        m3e_write_runner(
            proposal_dir / f"runner_{label}",
            plan,
            attempt_id=f"coinbase-eth-usd-prospective-update-runner-{label}",
            source_commit=(label * 40)[:40],
            workflow_run_id="run-99",
            runner_identity=f"ubuntu-x64-{label}",
        )
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "a@b.c"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "Rehearsal"], check=True)
    return proposal_dir, base


def test_seam_prepares_one_draft_and_leaves_the_accepted_branch_untouched(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    proposal_dir, base = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)

    result = prepare_update_proposal(
        clone, proposal_dir, as_of=_due_as_of(base), git=git, proposal_relpath=_PROPOSAL_REL
    )
    assert result.outcome == OUTCOME_PREPARED
    assert result.proposal_branch is not None
    assert result.proposal_branch.startswith("bot/m3e-prospective-update/")
    assert result.commit_sha
    assert result.descriptor is not None
    assert result.descriptor["draft"] is True
    assert result.descriptor["auto_merge"] is False
    assert result.descriptor["base_branch"] == ACCEPTED_COHORT_BRANCH
    # exactly one privileged effect: on the bot branch, clean tree, base branch untouched
    assert git.current_branch() == result.proposal_branch
    assert git.status_porcelain() == ""
    assert not git.branch_exists(ACCEPTED_COHORT_BRANCH)  # never materialised/advanced


def test_seam_is_a_noop_when_nothing_is_due(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    proposal_dir, base = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)
    # Mid-day on the accepted last open's own day → nothing new is due.
    same_day = _z(pd.Timestamp(base.last_open) + pd.Timedelta(hours=12))
    result = prepare_update_proposal(
        clone, proposal_dir, as_of=same_day, git=git, proposal_relpath=_PROPOSAL_REL
    )
    assert result.outcome == OUTCOME_NOOP
    assert result.commit_sha is None


def test_seam_skips_idempotently_when_the_lease_reports_an_open_proposal(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    proposal_dir, base = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)
    from eth_research.m3e.cutoff import plan_update_window
    from eth_research.m3e.update_plan import build_update_plan

    plan = build_update_plan(base, plan_update_window(base, _due_as_of(base)))

    result = prepare_update_proposal(
        clone,
        proposal_dir,
        as_of=_due_as_of(base),
        git=git,
        proposal_relpath=_PROPOSAL_REL,
        existing_open_proposal_keys={plan.idempotency_key},
    )
    assert result.outcome == OUTCOME_SKIPPED
    assert result.commit_sha is None


def test_seam_refuses_to_reuse_a_preexisting_branch(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    proposal_dir, base = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)
    origin_branch = git.current_branch()
    # First pass prepares the branch; a repeat must skip (never force-reuse an orphan).
    first = prepare_update_proposal(
        clone, proposal_dir, as_of=_due_as_of(base), git=git, proposal_relpath=_PROPOSAL_REL
    )
    assert first.outcome == OUTCOME_PREPARED
    assert first.proposal_branch is not None
    # Production repeat runs start from a fresh checkout of the (ungrown) accepted
    # branch — the staged growth lives only on the bot branch until a human merges
    # it. Model that: return to the pre-update branch, re-stage the runner bundles,
    # and the repeat must skip on the pre-existing bot branch, never force-reuse it.
    git._run("checkout", "--quiet", origin_branch)
    assert git.status_porcelain() == ""
    proposal_dir, base = _stage(clone, m3e_write_runner)
    second = prepare_update_proposal(
        clone, proposal_dir, as_of=_due_as_of(base), git=git, proposal_relpath=_PROPOSAL_REL
    )
    assert second.outcome == OUTCOME_SKIPPED
    assert second.proposal_branch == first.proposal_branch


def test_seam_refuses_a_tampered_accepted_base(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    proposal_dir, base = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)
    # Derive the due as_of from the honest base *before* forging the snapshot.
    as_of = _due_as_of(base)
    accepted = clone / "research/m3e/accepted_base.json"
    doc = json.loads(accepted.read_text())
    doc["row_count"] = int(doc["row_count"]) + 987  # a stale/forged base
    accepted.write_text(json.dumps(doc))
    with pytest.raises(M3EValidationError):
        prepare_update_proposal(
            clone, proposal_dir, as_of=as_of, git=git, proposal_relpath=_PROPOSAL_REL
        )


def test_seam_refuses_a_proposal_relpath_that_is_not_the_proposal_dir(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    # audit §17 (Auditor B finding 6): the committed pathspec must resolve to exactly
    # the proposal directory. A hostile/mistaken relpath (here the repo root ".") that
    # would stage unrelated files onto the bot branch is refused before any git effect.
    clone = m3a_checkout
    proposal_dir, base = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)
    with pytest.raises(M3EValidationError, match="proposal_relpath must name the proposal"):
        prepare_update_proposal(
            clone, proposal_dir, as_of=_due_as_of(base), git=git, proposal_relpath="."
        )
    # No bot branch was created — the refusal happened before the single git effect.
    assert git.current_branch() != "."
    assert not any(
        b.startswith("bot/m3e-prospective-update/")
        for b in git._run("branch", "--format=%(refname:short)").split()
    )


def test_rehearsal_clone_is_pinned_to_a_named_branch(m3a_checkout: Path) -> None:
    """The disposable rehearsal clone must sit on a real, *named* local branch.

    ``actions/checkout`` leaves a ``pull_request`` CI run on a detached HEAD, and a
    ``--local`` clone of a detached (or mid-suite re-checked-out) repository is itself
    detached — so ``current_branch()`` returns the literal ``"HEAD"``. A seam test that
    models a repeat run by returning to the accepted branch
    (``git checkout <current_branch>``) would then be a silent no-op that strands the
    working tree on a bot branch's staged cohort growth; the next plan sees an
    already-grown base and crashes on a spurious no-op. Regression for the V2D
    activation-PR CI failure — the ``make_m3a_checkout`` fixture pins a named branch so
    the accepted cohort is modelled the way production holds it (never a detached HEAD).

    It must equally not carry a *stray* local accepted-cohort branch. A ``--local`` clone
    of a source checked out on ``main`` (the push-to-``main`` checkout of post-merge main
    CI) inherits a local ``main``; a production runner checks out a detached HEAD at
    ``main``'s SHA with no local accepted branch. The fixture drops the inherited ``main``
    so the seam's "the accepted branch is never materialised/advanced" assertion holds in
    every CI event — regression for the post-merge-main CI failure.
    """
    git = _SubprocessGitPort(m3a_checkout)
    branch = git.current_branch()
    assert branch not in ("", "HEAD")
    assert git.branch_exists(branch)
    # The round-trip the seam rehearsal depends on is a real branch switch, not a no-op.
    assert not branch.startswith("bot/m3e-prospective-update/")
    # No stray local accepted-cohort branch inherited from a main-checked-out source.
    assert not git.branch_exists(ACCEPTED_COHORT_BRANCH)
