"""N9: a successful end-to-end orchestration of the real production lifecycle.

The existing orchestrator tests prove only *refusals* against the real repo. N9
proves the happy path: inside a disposable ``--local`` clone that carries the
full real M2B+M3A layer (real 3702-row data, partition, v1 protocol, v2
methodology, six-line v1 registry prefix, both byte-empty ledgers), it registers
run-003 with the production CLI, commits the registry-only ``R`` commit, and
drives ``develop_m3a --run-experiment`` — the exact code path the real run-003
will use — via subprocess so ``eth_research`` imports the clone's own source. The
id is consumed only in the throwaway clone; the real repository is never touched.

Because the walk-forward hard-pins the real 2221-row research train, this runs
the genuine evaluation and both fold-aware bootstraps (~20s). It is the terminal
rehearsal that must pass before the real registration.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import eth_research
from conftest import _git, make_m3a_checkout
from eth_research.experiment_archive import verify_experiment_archive
from eth_research.experiment_registry import read_registry

RUN_ID = "m3a-fixed-baseline-comparison-v2-run-003"
_REGISTRY_REL = "research/m3a/experiment_registry.jsonl"
_GATE_LEDGER_REL = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER_REL = "research/m2b/test_evaluations.jsonl"
_INTENT_REL = "research/m3a/completion_intent.json"
_ALIAS_RESULTS_REL = "research/m3a/development_results.json"


def _on_frozen_runtime() -> bool:
    """True iff the active runtime satisfies the frozen numerical contract.

    The orchestrator (and the registration CLI, which shares preconditions)
    proceeds only under the frozen runtime, so run-002 and run-003 stay
    bit-identical. On any other runtime it fail-closes — correct behavior that
    makes the driven-lifecycle rehearsal meaningful only here (e.g. it runs on
    the authoritative CPython 3.12.3 job, not the 3.13 compatibility job).
    """
    from eth_research.environment import (
        CANONICAL_RUNTIME_CONTRACT_RELPATH,
        RuntimeVerificationError,
        load_runtime_contract,
        verify_runtime_snapshot,
    )

    repo = Path(eth_research.__file__).resolve().parents[2]
    try:
        verify_runtime_snapshot(load_runtime_contract(repo / CANONICAL_RUNTIME_CONTRACT_RELPATH))
    except RuntimeVerificationError:
        return False
    return True


def _run003_state_in_real_repo() -> str:
    """run-003's lifecycle stage in the real repository: absent/registered/completed."""
    from eth_research.experiment_registry import EXPERIMENT_REGISTRY_RELPATH, read_registry

    repo = Path(eth_research.__file__).resolve().parents[2]
    stages = [
        e.event
        for e in read_registry(repo / EXPERIMENT_REGISTRY_RELPATH)
        if e.experiment_id == RUN_ID
    ]
    if not stages:
        return "absent"
    return "completed" if "completed" in stages else "registered"


# The rehearsal registers and runs run-003 inside a disposable clone under the
# frozen runtime. It is STANDING: it restores the clone's M3A artifact state to
# the recorded execution-source commit E (before run-003) regardless of run-003's
# state in the real repository, so the successful production lifecycle is
# exercised on the authoritative runtime even after run-003 is completed. It
# skips ONLY off the frozen runtime, where the orchestrator fail-closes by design
# (e.g. the 3.13 compatibility job) — never because run-003 is complete.
_REHEARSABLE = pytest.mark.skipif(
    not _on_frozen_runtime(),
    reason="the driven run-003 lifecycle runs only on the frozen CPython 3.12.3 runtime; "
    "off it the orchestrator fail-closes by design",
)


def _pre_run003_execution_source() -> str:
    """Commit E: the real run-003 registered event's execution_code_commit_sha."""
    from eth_research.experiment_registry import EXPERIMENT_REGISTRY_RELPATH, read_registry

    repo = Path(eth_research.__file__).resolve().parents[2]
    for event in read_registry(repo / EXPERIMENT_REGISTRY_RELPATH):
        if event.experiment_id == RUN_ID and event.event == "registered":
            return event.execution_code_commit_sha
    raise AssertionError("run-003 is not registered in the real repository")


def _restore_clone_to_pre_run003(clone: Path) -> str:
    """Restore the clone's ``research/m3a`` subtree to commit E (before run-003).

    Resolves E from the real run-003 registered event, asserts E is an ancestor of
    the clone HEAD, then resets ``research/m3a`` to E's exact bytes: the six-line
    v1 registry prefix, run-002 v1 aliases, the run-001/002 archives only (no
    run-003 archive), and no errata. The current production source was overlaid
    and committed by :func:`make_m3a_checkout`, so the clone runs the *current*
    package against E's pre-run-003 artifact state. The clone is disposable; the
    real repository is never touched. Returns E.
    """
    e_commit = _pre_run003_execution_source()
    ancestor = subprocess.run(
        ["git", "-C", str(clone), "merge-base", "--is-ancestor", e_commit, "HEAD"],
        capture_output=True,
        check=False,
    )
    assert ancestor.returncode == 0, f"E {e_commit} is not an ancestor of the clone HEAD"
    # Reset the whole M3A subtree to E (removing the completed run-003 archive,
    # migrated v2 aliases, and errata that postdate E), then commit so the tree is
    # clean before the rehearsal registers run-003 itself.
    _git(clone, "rm", "-rf", "--quiet", "research/m3a")
    _git(clone, "checkout", e_commit, "--", "research/m3a")
    _git(clone, "add", "-A", "research/m3a")
    _git(clone, "commit", "--quiet", "-m", "restore clone M3A artifact state to E (pre-run-003)")
    return e_commit


def _run(clone: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m <args>`` inside the clone with its src on PYTHONPATH."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(clone / "src")
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=str(clone),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_script(clone: Path, relpath: str) -> subprocess.CompletedProcess[str]:
    """Run a repo script (e.g. the CI registry verifier) inside the clone."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(clone / "src")
    return subprocess.run(
        [sys.executable, relpath],
        cwd=str(clone),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _register_and_commit_r(clone: Path) -> None:
    """Append the run-003 registered event and commit the registry-only R commit."""
    appended = _run(clone, "eth_research.m3a_register", "--repo-root", str(clone), "--append")
    assert appended.returncode == 0, f"register --append failed: {appended.stderr}"
    _git(clone, "add", _REGISTRY_REL)
    _git(clone, "commit", "--quiet", "-m", "pre-register run-003 (registry only)")


@_REHEARSABLE
class TestSuccessfulEndToEnd:
    def test_full_production_lifecycle(self, tmp_path: Path) -> None:
        clone = make_m3a_checkout(tmp_path)
        _restore_clone_to_pre_run003(clone)

        # The package under PYTHONPATH is the clone's own source, not the real repo.
        probe = subprocess.run(
            [sys.executable, "-c", "import eth_research; print(eth_research.__file__)"],
            cwd=str(clone),
            env={**os.environ, "PYTHONPATH": str(clone / "src")},
            capture_output=True,
            text=True,
            check=True,
        )
        assert str(clone) in probe.stdout, probe.stdout

        # 12A — register run-003, commit registry-only R.
        _register_and_commit_r(clone)
        changed = _git(clone, "diff", "--name-only", "HEAD~1", "HEAD").split()
        assert changed == [_REGISTRY_REL], f"E..R must be registry-only, changed: {changed}"
        registered = read_registry(clone / _REGISTRY_REL)
        assert [e.event for e in registered if e.experiment_id == RUN_ID] == ["registered"]
        # Aliases are still run-002 v1 and no run-003 archive exists yet (State A).
        assert not (clone / f"research/m3a/experiments/{RUN_ID}").exists()
        # State A: the CI registry verifier accepts a registered-only run-003
        # (latest completed is still v1 run-002, binding the v1 aliases).
        state_a = _run_script(clone, ".github/scripts/verify_m3a_registry.py")
        assert state_a.returncode == 0, state_a.stderr
        assert "verified (v1)" in state_a.stdout

        # 12B — execute run-003 exactly once through the production orchestrator.
        run = _run(
            clone,
            "eth_research.develop_m3a",
            "--repo-root",
            str(clone),
            "--run-experiment",
            RUN_ID,
        )
        assert run.returncode == 0, f"orchestrated run failed: {run.stderr}"
        assert "completed m3a-fixed-baseline-comparison-v2-run-003" in run.stdout

        # Registry is registered -> started -> completed for run-003.
        events = read_registry(clone / _REGISTRY_REL)
        run3 = [e for e in events if e.experiment_id == RUN_ID]
        assert [e.event for e in run3] == ["registered", "started", "completed"]

        # All three archives verify against the registry + index (State B).
        verified = verify_experiment_archive(clone)
        assert RUN_ID in verified
        assert "m3a-fixed-baseline-comparison-v1-run-001" in verified
        assert "m3a-fixed-baseline-comparison-v1-run-002" in verified

        # The run-003 immutable archive exists with all four artifacts.
        archive = clone / "research/m3a/experiments" / RUN_ID
        for name in (
            "development_results.json",
            "development_report.md",
            "return_evidence.json",
            "artifact_manifest.json",
        ):
            assert (archive / name).is_file(), f"missing {name}"

        # Completion intent was cleared on the clean completion.
        assert not (clone / _INTENT_REL).exists()

        # Both sealed access ledgers are still byte-empty — no gate/holdout access.
        assert (clone / _GATE_LEDGER_REL).read_bytes() == b""
        assert (clone / _HOLDOUT_LEDGER_REL).read_bytes() == b""

        # The compatibility alias migrated to run-003's v2 results.
        from eth_research.development_results_v2 import load_development_results_v2

        alias = load_development_results_v2(clone / _ALIAS_RESULTS_REL)
        assert alias.experiment_id == RUN_ID

        # Section 16: run-003's financial cells are bit-identical to run-002's.
        from eth_research.financial_equivalence import assert_financial_equivalence

        run002_results = (
            clone
            / "research/m3a/experiments/m3a-fixed-baseline-comparison-v1-run-002"
            / "development_results.json"
        )
        summary = assert_financial_equivalence(run002_results, archive / "development_results.json")
        assert summary.fold_cells == 60
        assert summary.independent_fold_summaries == 12
        assert summary.pooled_reset_oos == 12
        assert summary.full_train_exploratory == 12

        # State B: develop_m3a --check dispatches to v2 replay and reproduces the
        # v2 archive byte-for-byte from the committed raw bytes.
        state_b_check = _run(
            clone, "eth_research.develop_m3a", "--repo-root", str(clone), "--check"
        )
        assert state_b_check.returncode == 0, state_b_check.stderr
        assert "reproducible (v2" in state_b_check.stdout
        # State B: the CI registry verifier binds the migrated v2 aliases.
        state_b_verify = _run_script(clone, ".github/scripts/verify_m3a_registry.py")
        assert state_b_verify.returncode == 0, state_b_verify.stderr
        assert "verified (v2)" in state_b_verify.stdout

        # Recovery reports nothing pending after a clean completion.
        status = _run(clone, "eth_research.m3a_recovery", "--repo-root", str(clone), "--status")
        assert status.returncode == 0
        assert "no-intent" in status.stdout

        # Commit the run outputs (P) so the tree is clean, then prove the consumed
        # id cannot be re-run: preflight now refuses for the single-use reason.
        _git(clone, "add", "-A")
        _git(clone, "commit", "--quiet", "-m", "record run-003 outputs (P)")
        rerun = _run(
            clone, "eth_research.develop_m3a", "--repo-root", str(clone), "--run-experiment", RUN_ID
        )
        assert rerun.returncode == 1
        assert "not awaiting execution" in rerun.stderr


@_REHEARSABLE
class TestFailureTransitions:
    """End-to-end refusal proof. The publication-rollback, started->failed, and
    crash-recovery transitions run against the real models in the focused
    ``test_publication.py`` and ``test_m3a_recovery.py`` suites."""

    def test_unregistered_run_refuses_before_any_started(self, tmp_path: Path) -> None:
        clone = make_m3a_checkout(tmp_path)
        _restore_clone_to_pre_run003(clone)
        # No registration: the orchestrator refuses and appends no 'started'.
        run = _run(
            clone, "eth_research.develop_m3a", "--repo-root", str(clone), "--run-experiment", RUN_ID
        )
        assert run.returncode == 1
        assert "no registered experiment" in run.stderr
        events = read_registry(clone / _REGISTRY_REL)
        assert all(e.experiment_id != RUN_ID for e in events)
        assert (clone / _GATE_LEDGER_REL).read_bytes() == b""
        assert (clone / _HOLDOUT_LEDGER_REL).read_bytes() == b""
