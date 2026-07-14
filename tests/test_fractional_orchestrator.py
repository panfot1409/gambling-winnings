"""End-to-end rehearsal of the fractional run lifecycle in a disposable clone.

``make_m3a_checkout`` clones the real repository (its committed raw data, frozen
dossier, development partition, walk-forward protocol, the committed M3B
fractional protocol, the pristine M3B registry, and both byte-empty sealed
ledgers) and overlays the current working ``src``, so the clone's HEAD is the
execution-source commit ``E`` carrying this branch's engine. The rehearsal
registers, commits the registry-only ``R`` commit, executes, publishes, and
replay-verifies run-001 — consuming the single-use id only in the throwaway
clone. The real repository is never touched.

The ``_running_package_root`` patch is the only accommodation: it points the
package-root pre-check at the clone's own ``src`` (byte-identical to the running
source, since the overlay was committed), so the fail-closed source binding is
still genuinely proven against the clone's HEAD.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import eth_research.fractional.orchestrator as orchestrator
from conftest import _git, make_m3a_checkout
from eth_research.fractional.archive import (
    FRACTIONAL_MANIFEST_RELPATH,
    verify_published_run,
)
from eth_research.fractional.orchestrator import (
    OrchestratorError,
    execute_and_publish_fractional_run,
    register_fractional_run,
)
from eth_research.fractional.registry import M3B_REGISTRY_RELPATH, read_registry
from eth_research.fractional.replay import check_replay
from eth_research.fractional.results import (
    FRACTIONAL_REPORT_RELPATH,
    FRACTIONAL_RESULTS_RELPATH,
    load_fractional_results,
)

_GATE_LEDGER = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER = "research/m2b/test_evaluations.jsonl"
_EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_RUN_TIME = pd.Timestamp("2026-07-14T00:00:00+00:00")


def _patch_package_root(mp: pytest.MonkeyPatch, clone: Path) -> None:
    mp.setattr(
        orchestrator, "_running_package_root", lambda: (clone / "src/eth_research").resolve()
    )


def _register_commit_execute(clone: Path) -> tuple[str, ...]:
    with pytest.MonkeyPatch.context() as mp:
        _patch_package_root(mp, clone)
        register_fractional_run(clone, event_time_utc=_RUN_TIME)
        _git(clone, "add", M3B_REGISTRY_RELPATH)
        _git(clone, "commit", "--quiet", "-m", "pre-register run-001 (registry only)")
        checks = execute_and_publish_fractional_run(clone, event_time_utc=_RUN_TIME)
        # Mirror the real P19 commit: the published artifacts + the two appended
        # registry lines are committed, leaving the tree clean.
        _git(clone, "add", "-A", "research/m3b")
        _git(clone, "commit", "--quiet", "-m", "execute + publish run-001")
        return checks


@pytest.fixture(scope="module")
def published(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, tuple[str, ...]]:
    clone = make_m3a_checkout(tmp_path_factory.mktemp("m3b_e2e"))
    checks = _register_commit_execute(clone)
    return clone, checks


class TestSuccessfulLifecycle:
    def test_replay_verification_passes(self, published: tuple[Path, tuple[str, ...]]) -> None:
        clone, checks = published
        assert "registry_lifecycle_complete" in checks
        assert "results_revalidate" in checks
        assert "report_rerenders" in checks
        # idempotent: a fresh replay verification also passes.
        assert verify_published_run(clone) == checks

    def test_registry_records_the_full_lifecycle(
        self, published: tuple[Path, tuple[str, ...]]
    ) -> None:
        clone, _ = published
        events = read_registry(clone / M3B_REGISTRY_RELPATH)
        assert [e.event for e in events] == ["registered", "started", "completed"]
        completed = events[-1]
        assert completed.results_json_sha256 is not None
        assert completed.result_bundle_sha256 is not None

    def test_artifacts_are_published(self, published: tuple[Path, tuple[str, ...]]) -> None:
        clone, _ = published
        for relpath in (
            FRACTIONAL_RESULTS_RELPATH,
            FRACTIONAL_REPORT_RELPATH,
            FRACTIONAL_MANIFEST_RELPATH,
        ):
            assert (clone / relpath).exists()
        results = load_fractional_results(str(clone / FRACTIONAL_RESULTS_RELPATH))
        assert len(results.fold_cells) == 75
        assert results.development_gate_event_count == 0
        assert results.final_holdout_event_count == 0

    def test_sealed_ledgers_stay_byte_empty(
        self, published: tuple[Path, tuple[str, ...]]
    ) -> None:
        from eth_research.data.provenance import sha256_file

        clone, _ = published
        for ledger in (_GATE_LEDGER, _HOLDOUT_LEDGER):
            assert sha256_file(clone / ledger) == _EMPTY_SHA

    def test_completed_state_replays_byte_for_byte(
        self, published: tuple[Path, tuple[str, ...]]
    ) -> None:
        clone, _ = published
        state, *checks = check_replay(clone)
        assert state == "completed"
        assert "results_reproduced" in checks
        assert "report_reproduced" in checks
        assert "archive_verified" in checks

    def test_second_execution_is_refused(
        self, published: tuple[Path, tuple[str, ...]]
    ) -> None:
        clone, _ = published
        with pytest.MonkeyPatch.context() as mp:
            _patch_package_root(mp, clone)
            # run-001 is completed; it can never be re-registered or re-run.
            with pytest.raises(OrchestratorError, match="single-use"):
                register_fractional_run(clone, event_time_utc=_RUN_TIME)
            with pytest.raises(OrchestratorError, match="must be exactly 'registered'"):
                execute_and_publish_fractional_run(clone, event_time_utc=_RUN_TIME)


class TestPreconditionRefusals:
    def test_dirty_tree_is_refused(self, tmp_path: Path) -> None:
        clone = make_m3a_checkout(tmp_path)
        # Modify a tracked file (untracked files are ignored by design).
        pyproject = clone / "pyproject.toml"
        pyproject.write_bytes(pyproject.read_bytes() + b"\n# dirty\n")
        with pytest.MonkeyPatch.context() as mp:
            _patch_package_root(mp, clone)
            with pytest.raises(OrchestratorError, match="tracked working tree is dirty"):
                register_fractional_run(clone, event_time_utc=_RUN_TIME)

    def test_nonempty_sealed_ledger_is_refused(self, tmp_path: Path) -> None:
        clone = make_m3a_checkout(tmp_path)
        (clone / _GATE_LEDGER).write_text('{"tampered": true}\n')
        _git(clone, "add", _GATE_LEDGER)
        _git(clone, "commit", "--quiet", "-m", "tamper: write to the sealed gate ledger")
        with pytest.MonkeyPatch.context() as mp:
            _patch_package_root(mp, clone)
            with pytest.raises(OrchestratorError, match="not byte-empty"):
                register_fractional_run(clone, event_time_utc=_RUN_TIME)

    def test_pristine_clone_replays_as_pristine(self, tmp_path: Path) -> None:
        clone = make_m3a_checkout(tmp_path)
        state, *checks = check_replay(clone)
        assert state == "pristine"
        assert "no_run_no_artifacts" in checks
