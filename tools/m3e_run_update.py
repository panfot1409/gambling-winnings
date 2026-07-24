"""Assemble-job driver: proposal + staged cohort extension on a new bot branch.

Runs INSIDE the update workflow's assemble job (never on a schedule of its own).
It moves the two verified runner artifacts into the deterministic proposal
directory, then drives the whole reviewed offline seam —
``eth_research.m3e.orchestrator.prepare_update_proposal`` — with a fixed-argv
subprocess GitPort. The seam re-verifies the accepted base, self-verifies the
35-check proposal graph, stages the append-only cohort extension (verified as a
landed update), and commits the closed pathspec allowlist onto one new
``bot/m3e-prospective-update/*`` branch. This driver then emits the branch/title
outputs and the draft-PR body; pushing the bot branch and opening the DRAFT PR
are separate, job-scoped workflow steps. Nothing here merges, undrafts,
retargets, or touches an accepted branch.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


class _SubprocessGitPort:
    """Fixed-argv Git against the checked-out workspace (never a shell string)."""

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
        for ref in (f"refs/heads/{name}", f"refs/remotes/origin/{name}"):
            probe = subprocess.run(
                ["git", "-C", str(self.repo), "rev-parse", "--verify", "--quiet", ref],
                capture_output=True,
            )
            if probe.returncode == 0:
                return True
        return False

    def create_and_checkout_branch(self, name: str) -> None:
        self._run("checkout", "--quiet", "-b", name)

    def add(self, pathspec: str) -> None:
        self._run("add", "--", pathspec)

    def commit(self, message: str) -> str:
        self._run("commit", "--quiet", "-m", message)
        return self._run("rev-parse", "HEAD").strip()

    def status_porcelain(self) -> str:
        return self._run("status", "--porcelain").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M3E update assemble driver (workflow-only)")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--plan-dir", required=True)
    parser.add_argument("--runner-a", required=True)
    parser.add_argument("--runner-b", required=True)
    parser.add_argument("--output", required=True, help="GITHUB_OUTPUT file")
    parser.add_argument("--body-out", required=True)
    args = parser.parse_args(argv)

    from eth_research.m3e.lease import PROPOSAL_BRANCH_PREFIX
    from eth_research.m3e.orchestrator import OUTCOME_PREPARED, prepare_update_proposal
    from eth_research.m3e.update_plan import load_update_plan

    root = Path(args.repo_root).resolve()
    plan_dir = Path(args.plan_dir)
    plan = load_update_plan(plan_dir / "update_plan.json")
    as_of = (plan_dir / "as_of.txt").read_text().strip()

    first = plan.first_missing_open[:10].replace("-", "")
    last_exclusive = plan.completed_day_exclusive_end[:10].replace("-", "")
    proposal_id = f"{first}-{last_exclusive}-{plan.idempotency_key[:16]}"
    proposal_rel = f"research/m3e/proposals/{proposal_id}"
    proposal_dir = root / proposal_rel
    if proposal_dir.exists():
        # This driver runs only in the assemble job, whose checkout is fresh (fetch-depth 0,
        # no prior-run debris), so an existing directory is a committed proposal for this
        # window — an idempotent skip. The wording is deliberately existence-based (not a
        # git-tracked assertion) because that is the exact condition tested.
        print(f"proposal directory already present: {proposal_rel}; idempotent skip")
        with Path(args.output).open("a", encoding="utf-8") as out:
            out.write("branch=\ntitle=\n")
        return 0
    (proposal_dir / "runner_a").parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(args.runner_a, proposal_dir / "runner_a")
    shutil.copytree(args.runner_b, proposal_dir / "runner_b")

    git = _SubprocessGitPort(root)
    result = prepare_update_proposal(
        root,
        proposal_dir,
        as_of=as_of,
        git=git,
        proposal_relpath=proposal_rel,
    )
    print(f"outcome: {result.outcome} — {result.reason}")
    if result.outcome != OUTCOME_PREPARED:
        shutil.rmtree(proposal_dir, ignore_errors=True)
        with Path(args.output).open("a", encoding="utf-8") as out:
            out.write("branch=\ntitle=\n")
        return 0

    descriptor = result.descriptor or {}
    branch = str(result.proposal_branch)
    if not branch.startswith(PROPOSAL_BRANCH_PREFIX):
        print("prepared branch is not a bot proposal branch", file=sys.stderr)
        return 1
    Path(args.body_out).write_text(str(descriptor["body"]), encoding="utf-8")
    with Path(args.output).open("a", encoding="utf-8") as out:
        out.write(f"branch={branch}\n")
        out.write(f"title={descriptor['title']}\n")
    print(f"prepared {branch} (staged attempt {result.staged_attempt_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
