"""V2D staged-cohort-extension tests (m3e.staging + verify_landed_update).

The orchestrator seam now stages, in the same bot commit as the proposal evidence,
the exact cohort extension the proposal attests — so one human merge lands evidence
and growth atomically. These tests drive the full seam inside a disposable clone and
prove: the grown clone passes the landed-update verification and its base grew by
exactly the attested window; every staged byte is the deterministic consequence of
runner A's artifact; and any post-staging tamper (manifest, appended raw data,
registry) or double-stage is refused. No test touches the real repository.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from eth_research.m3e.accepted_base import AcceptedProspectiveBase, verify_accepted_base
from eth_research.m3e.orchestrator import (
    OUTCOME_PREPARED,
    PreparedProposal,
    prepare_update_proposal,
)
from eth_research.m3e.staging import StagingError, stage_cohort_extension
from eth_research.m3e.validation import M3EValidationError
from eth_research.m3e.verify_m3e_program import verify_landed_update

_PROPOSAL_REL = "research/m3e/proposals/staging-rehearsal"


def _due_as_of(base: AcceptedProspectiveBase) -> str:
    """A due as_of derived from the clone's accepted base (7 settled days due)."""
    ts = pd.Timestamp(base.last_open) + pd.Timedelta(days=8, hours=2, minutes=17)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


class _GitPort:
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
        probe = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
            capture_output=True,
            text=True,
        )
        return probe.returncode == 0

    def create_and_checkout_branch(self, name: str) -> None:
        self._run("checkout", "--quiet", "-b", name)

    def add(self, pathspec: str) -> None:
        self._run("add", pathspec)

    def commit(self, message: str) -> str:
        self._run("commit", "--quiet", "-m", message)
        return self._run("rev-parse", "HEAD").strip()

    def status_porcelain(self) -> str:
        return self._run("status", "--porcelain").strip()


def _prepare(
    clone: Path, m3e_write_runner: Callable[..., object]
) -> tuple[_GitPort, PreparedProposal]:
    from eth_research.m3e.cutoff import plan_update_window
    from eth_research.m3e.update_plan import build_update_plan

    base = verify_accepted_base(clone)
    as_of = _due_as_of(base)
    plan = build_update_plan(base, plan_update_window(base, as_of))
    proposal_dir = clone / _PROPOSAL_REL
    for label in ("a", "b"):
        m3e_write_runner(
            proposal_dir / f"runner_{label}",
            plan,
            attempt_id=f"coinbase-eth-usd-prospective-update-runner-{label}",
            source_commit=(label * 40)[:40],
            workflow_run_id="run-77",
            runner_identity=f"ubuntu-x64-{label}",
        )
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "a@b.c"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "Rehearsal"], check=True)
    git = _GitPort(clone)
    result = prepare_update_proposal(
        clone, proposal_dir, as_of=as_of, git=git, proposal_relpath=_PROPOSAL_REL
    )
    assert result.outcome == OUTCOME_PREPARED
    return git, result


def test_prepared_bot_commit_carries_a_verified_grown_cohort(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    before = verify_accepted_base(clone).row_count
    _git, result = _prepare(clone, m3e_write_runner)

    assert result.staged_attempt_id is not None
    assert result.staged_attempt_id.startswith("coinbase-eth-usd-prospective-update-")
    assert "research/m3d/update_attempts.jsonl" in result.staged_relpaths
    assert "research/m3e/accepted_base.json" in result.staged_relpaths
    assert "research/m3e/proposal_registry.jsonl" in result.staged_relpaths

    grown = verify_accepted_base(clone)
    assert grown.row_count > before
    checks = verify_landed_update(clone, clone / _PROPOSAL_REL)
    assert [name for name, _ in checks][:2] == [
        "L01_grown_base_rebuilds",
        "L02_genesis_fingerprint_anchored",
    ]
    assert len(checks) == 11


def test_tampered_staged_manifest_is_refused(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    _prepare(clone, m3e_write_runner)
    manifest = clone / "research/m3d/prospective_manifest.json"
    doc = json.loads(manifest.read_text())
    doc["row_count"] = int(doc["row_count"]) + 1
    manifest.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")
    with pytest.raises(M3EValidationError):
        verify_landed_update(clone, clone / _PROPOSAL_REL)


def test_tampered_appended_raw_value_is_refused(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    _git, result = _prepare(clone, m3e_write_runner)
    attempt_dir = clone / f"research/m3d/raw/coinbase/{result.staged_attempt_id}"
    raw_files = [p for p in attempt_dir.iterdir() if p.name.startswith("coinbase-eth-usd-1d")]
    raw = raw_files[0]
    rows = json.loads(raw.read_bytes())
    rows[0][4] = rows[0][4] + 1.0  # nudge one close — value tampering after staging
    raw.write_bytes(json.dumps(rows).encode())
    with pytest.raises(M3EValidationError):
        verify_landed_update(clone, clone / _PROPOSAL_REL)


def test_dropped_registry_record_is_refused(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    clone = m3a_checkout
    _prepare(clone, m3e_write_runner)
    registry = clone / "research/m3e/proposal_registry.jsonl"
    lines = registry.read_bytes().splitlines()
    registry.write_bytes(b"\n".join(lines[:-1]) + b"\n")
    with pytest.raises(M3EValidationError):
        verify_landed_update(clone, clone / _PROPOSAL_REL)


def test_double_stage_is_refused_and_rolls_back(
    m3a_checkout: Path, m3e_write_runner: Callable[..., object]
) -> None:
    from eth_research.m3e.assembly import assemble_update_proposal
    from eth_research.m3e.cutoff import plan_update_window
    from eth_research.m3e.update_plan import build_update_plan

    clone = m3a_checkout
    base = verify_accepted_base(clone)
    plan = build_update_plan(base, plan_update_window(base, _due_as_of(base)))
    proposal_dir = clone / _PROPOSAL_REL
    for label in ("a", "b"):
        m3e_write_runner(
            proposal_dir / f"runner_{label}",
            plan,
            attempt_id=f"coinbase-eth-usd-prospective-update-runner-{label}",
            source_commit=(label * 40)[:40],
            workflow_run_id="run-77",
            runner_identity=f"ubuntu-x64-{label}",
        )
    assembled, _digests = assemble_update_proposal(clone, proposal_dir)
    staged = stage_cohort_extension(clone, assembled)
    grown_bytes = (clone / "research/m3e/accepted_base.json").read_bytes()
    # A second stage of the same proposal must refuse (the attempt dir exists) and
    # must not disturb the already-staged state.
    with pytest.raises(StagingError, match="already exists"):
        stage_cohort_extension(clone, assembled)
    assert (clone / "research/m3e/accepted_base.json").read_bytes() == grown_bytes
    assert (clone / f"research/m3d/raw/coinbase/{staged.attempt_id}").is_dir()
