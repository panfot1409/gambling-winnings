"""N6: crash-recoverable completion intent + the calculation-free finalizer.

These prove the promised recovery finalizer actually exists and works: a run
that published its archive but crashed before appending ``completed`` can be
finalized without recomputation, and the finalizer refuses every state where
finalization would be unsound (missing/tampered artifacts, a registry not at
``registered`` -> ``started``, a failed run, or an intent that names one run and
carries another's completion).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from eth_research.data.provenance import sha256_bytes
from eth_research.development_completion import (
    COMPLETION_INTENT_RELPATH,
    CompletionArtifact,
    CompletionIntent,
    CompletionIntentError,
    read_completion_intent,
    write_completion_intent,
)
from eth_research.experiment_registry import (
    EXPERIMENT_REGISTRY_RELPATH,
    ExperimentEvent,
    ExperimentEventV2,
    append_registry_event,
    latest_registry_line_sha256,
    read_registry,
)
from eth_research.m3a_recovery import (
    STATE_ALREADY_FINALIZED,
    STATE_FAILED,
    STATE_FINALIZABLE,
    STATE_FINALIZED,
    STATE_NO_INTENT,
    STATE_NOT_FINALIZABLE,
    assess,
    finalize,
)

_RUN_ID = "m3a-fixed-baseline-comparison-v2-run-003"
_ARCHIVE = f"research/m3a/experiments/{_RUN_ID}"
_RESULTS_REL = f"{_ARCHIVE}/development_results.json"
_REPORT_REL = f"{_ARCHIVE}/development_report.md"
_T0 = pd.Timestamp("2026-07-13T12:00:00+00:00")


def _v1_seed(experiment_id: str = "m3a-seed-001") -> ExperimentEvent:
    """A lone v1 ``registered`` line so a v2 event can chain onto the v1 prefix."""
    return ExperimentEvent(
        registry_schema_version=1,
        event="registered",
        experiment_id=experiment_id,
        experiment_family="m3a-fixed-baseline-comparison-v1",
        hypothesis="seed prefix so a v2 event can chain onto the immutable v1 prefix",
        strategies=("cash", "buy_and_hold", "sma_20_50", "donchian_55_20"),
        development_partition_sha256="1" * 64,
        walk_forward_protocol_sha256="2" * 64,
        package_version="0.4.0",
        registered_code_commit_sha="a" * 40,
        execution_code_commit_sha="b" * 40,
        event_time_utc=_T0,
        results_json_sha256=None,
        report_markdown_sha256=None,
        result_bundle_sha256=None,
        failure_description=None,
    )


def _v2_event(
    event: str, *, previous_event_sha256: str, minutes: int = 0, **over: Any
) -> ExperimentEventV2:
    """A synthetic run-003 v2 event (correction lineage omitted — not under test)."""
    completed = event == "completed"
    fields: dict[str, Any] = {
        "registry_schema_version": 2,
        "event": event,
        "experiment_id": _RUN_ID,
        "experiment_family": "m3a-fixed-baseline-comparison-v2",
        "corrects_experiment_id": None,
        "correction_kind": None,
        "hypothesis": "corrects methodology and publication governance; parameters unchanged",
        "strategies": ("cash", "buy_and_hold", "sma_20_50", "donchian_55_20"),
        "cost_scenarios": ("base", "stressed", "severe"),
        "methodology_id": "walk-forward-fold-stratified-bootstrap-v2",
        "development_partition_sha256": "1" * 64,
        "walk_forward_protocol_path": "research/m3a/walk_forward_protocol_v2.json",
        "walk_forward_protocol_sha256": "2" * 64,
        "package_version": "0.4.0",
        "registered_code_commit_sha": "a" * 40,
        "execution_code_commit_sha": "b" * 40,
        "execution_source_tree_fingerprint": "c" * 64,
        "event_time_utc": _T0 + pd.Timedelta(minutes=minutes),
        "immutable_results_path": f"{_ARCHIVE}/development_results.json",
        "immutable_report_path": f"{_ARCHIVE}/development_report.md",
        "return_evidence_path": f"{_ARCHIVE}/return_evidence.json",
        "artifact_manifest_path": f"{_ARCHIVE}/artifact_manifest.json",
        "results_json_sha256": "3" * 64 if completed else None,
        "report_markdown_sha256": "4" * 64 if completed else None,
        "return_evidence_sha256": "5" * 64 if completed else None,
        "result_bundle_sha256": "6" * 64 if completed else None,
        "failure_description": "engine raised" if event == "failed" else None,
        "previous_event_sha256": previous_event_sha256,
    }
    fields.update(over)
    return ExperimentEventV2(**fields)


def _stage_published_not_completed(root: Path) -> CompletionIntent:
    """Build a temp repo left exactly as a crash between publish and complete.

    A v1 prefix line to chain onto, then run-003 registered -> started, two
    published artifacts on disk, and a durable completion intent recording the
    exact ``completed`` event and both artifact hashes. The ``completed`` event
    is *not* appended, matching the crash window.
    """
    (root / "research/m3a").mkdir(parents=True)
    registry = root / EXPERIMENT_REGISTRY_RELPATH
    registry.write_bytes(b"")
    append_registry_event(registry, _v1_seed())
    prev = latest_registry_line_sha256(registry)
    assert prev is not None
    append_registry_event(registry, _v2_event("registered", previous_event_sha256=prev))
    prev = latest_registry_line_sha256(registry)
    assert prev is not None
    append_registry_event(registry, _v2_event("started", previous_event_sha256=prev, minutes=1))
    started_sha = latest_registry_line_sha256(registry)
    assert started_sha is not None

    completed = _v2_event("completed", previous_event_sha256=started_sha, minutes=2)

    (root / _ARCHIVE).mkdir(parents=True)
    results_bytes = b'{"results":"v2"}'
    report_bytes = b"# report\n"
    (root / _RESULTS_REL).write_bytes(results_bytes)
    (root / _REPORT_REL).write_bytes(report_bytes)

    intent = CompletionIntent(
        experiment_id=_RUN_ID,
        completed_event_line=completed.to_json_line()[:-1],
        previous_event_sha256=started_sha,
        artifacts=(
            CompletionArtifact(_RESULTS_REL, sha256_bytes(results_bytes)),
            CompletionArtifact(_REPORT_REL, sha256_bytes(report_bytes)),
        ),
    )
    write_completion_intent(root, intent)
    return intent


class TestCompletionIntentModel:
    def _valid(self, tmp_path: Path) -> CompletionIntent:
        return _stage_published_not_completed(tmp_path)

    def test_round_trips_exactly(self, tmp_path: Path) -> None:
        intent = self._valid(tmp_path)
        assert CompletionIntent.from_json_bytes(intent.to_json_bytes()) == intent

    def test_reader_reparses_the_written_file(self, tmp_path: Path) -> None:
        intent = self._valid(tmp_path)
        assert read_completion_intent(tmp_path) == intent

    def test_absent_intent_reads_as_none(self, tmp_path: Path) -> None:
        assert read_completion_intent(tmp_path) is None

    def test_completed_line_experiment_id_must_agree(self, tmp_path: Path) -> None:
        intent = self._valid(tmp_path)
        with pytest.raises(CompletionIntentError, match="experiment id disagrees"):
            CompletionIntent(
                experiment_id="m3a-some-other-id-001",
                completed_event_line=intent.completed_event_line,
                previous_event_sha256=intent.previous_event_sha256,
                artifacts=intent.artifacts,
            )

    def test_a_non_completed_event_line_is_rejected(self, tmp_path: Path) -> None:
        started = _v2_event("started", previous_event_sha256="0" * 64)
        with pytest.raises(CompletionIntentError, match="not a v2 'completed' event"):
            CompletionIntent(
                experiment_id=_RUN_ID,
                completed_event_line=started.to_json_line()[:-1],
                previous_event_sha256="0" * 64,
                artifacts=(CompletionArtifact(_RESULTS_REL, "3" * 64),),
            )

    def test_tampered_completed_hash_is_rejected_on_read(self, tmp_path: Path) -> None:
        intent = self._valid(tmp_path)
        payload = json.loads(intent.to_json_bytes())
        payload["completed_event_sha256"] = "0" * 64
        with pytest.raises(CompletionIntentError, match="does not match the recorded"):
            CompletionIntent.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_non_base64_line_is_rejected_on_read(self, tmp_path: Path) -> None:
        intent = self._valid(tmp_path)
        payload = json.loads(intent.to_json_bytes())
        payload["completed_event_line_b64"] = "not*base64*"
        with pytest.raises(CompletionIntentError, match="not valid base64"):
            CompletionIntent.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_unknown_key_is_rejected_on_read(self, tmp_path: Path) -> None:
        intent = self._valid(tmp_path)
        payload = json.loads(intent.to_json_bytes())
        payload["note"] = "x"
        with pytest.raises(CompletionIntentError, match="keys do not match"):
            CompletionIntent.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_the_completed_line_must_chain_onto_the_recorded_previous(self, tmp_path: Path) -> None:
        completed = _v2_event("completed", previous_event_sha256="a" * 64)
        with pytest.raises(CompletionIntentError, match="previous_event_sha256 disagrees"):
            CompletionIntent(
                experiment_id=_RUN_ID,
                completed_event_line=completed.to_json_line()[:-1],
                previous_event_sha256="b" * 64,
                artifacts=(CompletionArtifact(_RESULTS_REL, "3" * 64),),
            )


class TestAssess:
    def test_no_intent(self, tmp_path: Path) -> None:
        (tmp_path / "research/m3a").mkdir(parents=True)
        (tmp_path / EXPERIMENT_REGISTRY_RELPATH).write_bytes(b"")
        assert assess(tmp_path).state == STATE_NO_INTENT

    def test_finalizable(self, tmp_path: Path) -> None:
        _stage_published_not_completed(tmp_path)
        assert assess(tmp_path).state == STATE_FINALIZABLE

    def test_missing_artifact_is_not_finalizable(self, tmp_path: Path) -> None:
        _stage_published_not_completed(tmp_path)
        (tmp_path / _RESULTS_REL).unlink()
        status = assess(tmp_path)
        assert status.state == STATE_NOT_FINALIZABLE
        assert "incomplete" in status.detail

    def test_tampered_artifact_is_not_finalizable(self, tmp_path: Path) -> None:
        _stage_published_not_completed(tmp_path)
        (tmp_path / _REPORT_REL).write_bytes(b"tampered\n")
        assert assess(tmp_path).state == STATE_NOT_FINALIZABLE

    def test_already_completed_run_reports_already_finalized(self, tmp_path: Path) -> None:
        intent = _stage_published_not_completed(tmp_path)
        append_registry_event(tmp_path / EXPERIMENT_REGISTRY_RELPATH, intent.completed_event)
        assert assess(tmp_path).state == STATE_ALREADY_FINALIZED

    def test_failed_run_is_reported_failed(self, tmp_path: Path) -> None:
        _stage_published_not_completed(tmp_path)
        registry = tmp_path / EXPERIMENT_REGISTRY_RELPATH
        prev = latest_registry_line_sha256(registry)
        assert prev is not None
        append_registry_event(
            registry,
            _v2_event("failed", previous_event_sha256=prev, minutes=3, failure_description="boom"),
        )
        assert assess(tmp_path).state == STATE_FAILED


class TestFinalize:
    def test_finalize_appends_completed_and_clears_intent(self, tmp_path: Path) -> None:
        intent = _stage_published_not_completed(tmp_path)
        registry = tmp_path / EXPERIMENT_REGISTRY_RELPATH
        before = [e.event for e in read_registry(registry)]
        assert before[-1] == "started"

        status = finalize(tmp_path)
        assert status.state == STATE_FINALIZED

        after = read_registry(registry)
        run_events = [e.event for e in after if e.experiment_id == _RUN_ID]
        assert run_events == ["registered", "started", "completed"]
        # The appended event is byte-identical to the recorded intent.
        appended = next(e for e in reversed(after) if e.experiment_id == _RUN_ID)
        assert appended.to_json_line()[:-1] == intent.completed_event_line
        # The intent is cleared, so a re-run of the finalizer is a no-op.
        assert not (tmp_path / COMPLETION_INTENT_RELPATH).exists()

    def test_finalize_is_idempotent(self, tmp_path: Path) -> None:
        _stage_published_not_completed(tmp_path)
        assert finalize(tmp_path).state == STATE_FINALIZED
        # No intent remains; a second finalize does nothing and does not raise.
        assert finalize(tmp_path).state == STATE_NO_INTENT

    def test_finalize_refuses_a_run_with_a_missing_artifact(self, tmp_path: Path) -> None:
        _stage_published_not_completed(tmp_path)
        (tmp_path / _RESULTS_REL).unlink()
        registry = tmp_path / EXPERIMENT_REGISTRY_RELPATH
        before = read_registry(registry)
        status = finalize(tmp_path)
        assert status.state == STATE_NOT_FINALIZABLE
        # Nothing was appended and the intent is left in place for diagnosis.
        assert read_registry(registry) == before
        assert (tmp_path / COMPLETION_INTENT_RELPATH).exists()


class TestFinalizerIsCalculationFree:
    """The finalizer must never reconstruct data or recompute a result."""

    def test_recovery_module_imports_no_calculation_entry_points(self) -> None:
        src = (Path(__file__).resolve().parents[1] / "src/eth_research/m3a_recovery.py").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "reconstruct_dataset",
            "evaluate_development",
            "evaluate_development_detailed",
            "fold_stratified_moving_block_bootstrap",
            "hierarchical_fold_block_bootstrap",
            "render_run_artifacts",
            "build_return_evidence",
        ):
            assert forbidden not in src, (
                f"m3a_recovery references calculation entry point {forbidden}"
            )

    def test_base64_line_decodes_to_the_exact_completed_event(self, tmp_path: Path) -> None:
        intent = _stage_published_not_completed(tmp_path)
        payload = json.loads(intent.to_json_bytes())
        decoded = base64.b64decode(payload["completed_event_line_b64"], validate=True)
        assert decoded == intent.completed_event_line
