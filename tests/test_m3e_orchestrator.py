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

import pytest

from eth_research.m3e.orchestrator import (
    OUTCOME_NOOP,
    OUTCOME_PREPARED,
    OUTCOME_SKIPPED,
    GitPort,
    prepare_update_proposal,
)
from eth_research.m3e.publisher import ACCEPTED_COHORT_BRANCH
from eth_research.m3e.validation import M3EValidationError

_AS_OF = "2026-07-22T02:17:00Z"
_PROPOSAL_REL = "research/m3e/proposals/rehearsal"


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


def _stage(clone: Path, m3e_write_runner: Callable[..., object]) -> Path:
    from eth_research.m3e.accepted_base import verify_accepted_base
    from eth_research.m3e.cutoff import plan_update_window
    from eth_research.m3e.update_plan import build_update_plan

    base = verify_accepted_base(clone)
    plan = build_update_plan(base, plan_update_window(base, _AS_OF))
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
    return proposal_dir


def test_seam_prepares_one_draft_and_leaves_the_accepted_branch_untouched(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    proposal_dir = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)

    result = prepare_update_proposal(
        clone, proposal_dir, as_of=_AS_OF, git=git, proposal_relpath=_PROPOSAL_REL
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
    proposal_dir = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)
    # 2026-07-14 == accepted last open → nothing new is due.
    result = prepare_update_proposal(
        clone, proposal_dir, as_of="2026-07-14T12:00:00Z", git=git, proposal_relpath=_PROPOSAL_REL
    )
    assert result.outcome == OUTCOME_NOOP
    assert result.commit_sha is None


def test_seam_skips_idempotently_when_the_lease_reports_an_open_proposal(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    proposal_dir = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)
    from eth_research.m3e.accepted_base import verify_accepted_base
    from eth_research.m3e.cutoff import plan_update_window
    from eth_research.m3e.update_plan import build_update_plan

    base = verify_accepted_base(clone)
    plan = build_update_plan(base, plan_update_window(base, _AS_OF))

    result = prepare_update_proposal(
        clone,
        proposal_dir,
        as_of=_AS_OF,
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
    proposal_dir = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)
    # First pass prepares the branch; a repeat must skip (never force-reuse an orphan).
    first = prepare_update_proposal(
        clone, proposal_dir, as_of=_AS_OF, git=git, proposal_relpath=_PROPOSAL_REL
    )
    assert first.outcome == OUTCOME_PREPARED
    assert first.proposal_branch is not None
    second = prepare_update_proposal(
        clone, proposal_dir, as_of=_AS_OF, git=git, proposal_relpath=_PROPOSAL_REL
    )
    assert second.outcome == OUTCOME_SKIPPED
    assert second.proposal_branch == first.proposal_branch


def test_seam_refuses_a_tampered_accepted_base(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    proposal_dir = _stage(clone, m3e_write_runner)
    git = _SubprocessGitPort(clone)
    accepted = clone / "research/m3e/accepted_base.json"
    doc = json.loads(accepted.read_text())
    doc["row_count"] = 999  # a stale/forged base
    accepted.write_text(json.dumps(doc))
    with pytest.raises(M3EValidationError):
        prepare_update_proposal(
            clone, proposal_dir, as_of=_AS_OF, git=git, proposal_relpath=_PROPOSAL_REL
        )
