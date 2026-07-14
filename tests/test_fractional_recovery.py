"""Failure-injection matrix for the fractional-run completion intent + recovery.

These exercise defect R1: a crash in the window after the three immutable
artifacts are durably published but before the ``completed`` registry event is
appended must be finalizable *calculation-free* and must never be mislabeled as a
``failed`` run. The crashed state is produced once in a disposable clone (the
orchestrator's ``append_registry_event`` is patched to die on the ``completed``
append, after publication has durably landed), and the whole recovery lifecycle
is then walked in a single test to avoid re-running the ~25s experiment.

A separate fast test proves the complementary branch: a genuine *pre*-publication
failure still records an honest ``failed`` event and leaks no completion intent.
None of these touch the real repository's ``research/m3b`` tree — every mutation
happens in a throwaway checkout.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

import eth_research.fractional.orchestrator as orchestrator
import eth_research.fractional.recovery as recovery
from conftest import _git, make_m3a_checkout
from eth_research.fractional.archive import verify_published_run
from eth_research.fractional.completion import (
    CompletionIntent,
    CompletionIntentError,
    read_completion_intent,
    write_completion_intent,
)
from eth_research.fractional.orchestrator import (
    OrchestratorError,
    execute_and_publish_fractional_run,
    register_fractional_run,
)
from eth_research.fractional.protocol import RUN_001_EXPERIMENT_ID
from eth_research.fractional.registry import (
    EVENT_COMPLETED,
    EVENT_FAILED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3B_REGISTRY_RELPATH,
    read_registry,
)
from eth_research.fractional.registry import append_registry_event as _real_append
from eth_research.fractional.replay import check_replay
from eth_research.fractional.results import FRACTIONAL_REPORT_RELPATH, FRACTIONAL_RESULTS_RELPATH
from eth_research.publication import durable_write_bytes

_RUN_TIME = pd.Timestamp("2026-07-14T00:00:00+00:00")


def _patch_package_root(mp: pytest.MonkeyPatch, clone: Path) -> None:
    mp.setattr(
        orchestrator, "_running_package_root", lambda: (clone / "src/eth_research").resolve()
    )


def _restore_clone_to_pristine(clone: Path) -> None:
    """Reset the clone's ``research/m3b`` tree to the pre-run (pristine) state."""
    (clone / M3B_REGISTRY_RELPATH).write_bytes(b"")
    for rel in (FRACTIONAL_RESULTS_RELPATH, FRACTIONAL_REPORT_RELPATH):
        (clone / rel).unlink(missing_ok=True)
    shutil.rmtree(clone / "research/m3b/experiments", ignore_errors=True)
    _git(clone, "add", "-A", "research/m3b")
    if _git(clone, "status", "--porcelain"):
        _git(clone, "commit", "--quiet", "-m", "restore clone M3B tree to pristine (pre-run)")


def _register_and_commit(clone: Path) -> None:
    _restore_clone_to_pristine(clone)
    register_fractional_run(clone, event_time_utc=_RUN_TIME)
    _git(clone, "add", M3B_REGISTRY_RELPATH)
    _git(clone, "commit", "--quiet", "-m", "pre-register run-001 (registry only)")


def _stages(clone: Path) -> list[str]:
    return [
        e.event
        for e in read_registry(clone / M3B_REGISTRY_RELPATH)
        if e.experiment_id == RUN_001_EXPERIMENT_ID
    ]


@pytest.fixture(scope="module")
def crashed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A clone whose run published its artifacts but crashed before 'completed'."""
    clone = make_m3a_checkout(tmp_path_factory.mktemp("m3b_recovery"))
    with pytest.MonkeyPatch.context() as mp:
        _patch_package_root(mp, clone)
        _register_and_commit(clone)

        def _crash_on_completed(path: object, event: object) -> None:
            if getattr(event, "event", None) == EVENT_COMPLETED:
                raise RuntimeError("injected crash: process died before 'completed' was appended")
            return _real_append(path, event)  # type: ignore[arg-type]

        mp.setattr(orchestrator, "append_registry_event", _crash_on_completed)
        with pytest.raises(OrchestratorError, match="finalize calculation-free"):
            execute_and_publish_fractional_run(clone, event_time_utc=_RUN_TIME)
    return clone


class TestPublishCrashRecovery:
    def test_recovers_calculation_free_and_is_never_mislabeled_failed(self, crashed: Path) -> None:
        clone = crashed
        # R1: the crash left the run published-but-not-finalized, NOT failed.
        assert _stages(clone) == [EVENT_REGISTERED, EVENT_STARTED]
        intent = read_completion_intent(clone)
        assert intent is not None
        assert recovery.assess(clone).state == recovery.STATE_FINALIZABLE

        # The recorded intent round-trips and is cross-validated against its event.
        assert CompletionIntent.from_json_bytes(intent.to_json_bytes()) == intent
        with pytest.raises(CompletionIntentError):
            dataclasses.replace(intent, experiment_id=f"{RUN_001_EXPERIMENT_ID}-x")
        with pytest.raises(CompletionIntentError):
            dataclasses.replace(intent, previous_event_sha256="0" * 64)
        tampered = json.loads(intent.to_json_bytes())
        tampered["completed_event_sha256"] = "0" * 64
        with pytest.raises(CompletionIntentError):
            CompletionIntent.from_json_bytes((json.dumps(tampered) + "\n").encode("utf-8"))

        # A missing published artifact is NOT finalizable — recovery never rebuilds.
        results_path = clone / FRACTIONAL_RESULTS_RELPATH
        saved = results_path.read_bytes()
        results_path.unlink()
        assert recovery.assess(clone).state == recovery.STATE_NOT_FINALIZABLE
        durable_write_bytes(results_path, saved)
        assert recovery.assess(clone).state == recovery.STATE_FINALIZABLE

        # Finalize appends the recorded 'completed' event with no recomputation.
        assert recovery.finalize(clone).state == recovery.STATE_FINALIZED
        assert _stages(clone) == [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]
        assert read_completion_intent(clone) is None
        assert verify_published_run(clone)  # internally consistent
        assert check_replay(clone)[0] == "completed"  # replays byte-for-byte

        # Re-finalizing is a safe no-op; re-writing the intent detects completion.
        assert recovery.finalize(clone).state == recovery.STATE_NO_INTENT
        write_completion_intent(clone, intent)
        assert recovery.assess(clone).state == recovery.STATE_ALREADY_FINALIZED
        assert recovery.finalize(clone).state == recovery.STATE_ALREADY_FINALIZED
        assert read_completion_intent(clone) is None

        # The CLI is safe to invoke unconditionally on a finalized tree.
        assert recovery.main(["--repo-root", str(clone), "--status"]) == 0
        assert recovery.main(["--repo-root", str(clone), "--finalize"]) == 0


def test_pre_publication_failure_records_failed_and_leaks_no_intent(tmp_path: Path) -> None:
    clone = make_m3a_checkout(tmp_path)
    with pytest.MonkeyPatch.context() as mp:
        _patch_package_root(mp, clone)
        _register_and_commit(clone)

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("injected pre-publication failure")

        mp.setattr(orchestrator, "_run_and_publish", _boom)
        with pytest.raises(OrchestratorError, match="failed after 'started'"):
            execute_and_publish_fractional_run(clone, event_time_utc=_RUN_TIME)
    assert _stages(clone) == [EVENT_REGISTERED, EVENT_STARTED, EVENT_FAILED]
    assert read_completion_intent(clone) is None
