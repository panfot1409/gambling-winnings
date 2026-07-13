"""Experiment registry: strict schema and registered->started->terminal order."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import eth_research
from eth_research.experiment_registry import (
    CORRECTION_METHODOLOGY_GOVERNANCE,
    EXPERIMENT_REGISTRY_RELPATH,
    REGISTRY_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION_V2,
    ExperimentEvent,
    ExperimentEventV2,
    RegistryError,
    append_registry_event,
    latest_registry_line_sha256,
    read_registry,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
T0 = pd.Timestamp("2026-07-13T12:00:00+00:00")


def make_event(
    event: str = "registered",
    *,
    experiment_id: str = "m3a-exp-001",
    minutes: int = 0,
    **over: Any,
) -> ExperimentEvent:
    completed = event == "completed"
    fields: dict[str, Any] = {
        "registry_schema_version": REGISTRY_SCHEMA_VERSION,
        "event": event,
        "experiment_id": experiment_id,
        "experiment_family": "m3a-fixed-baseline-comparison-v1",
        "hypothesis": "evaluate whether Donchian is more stable than SMA on research train",
        "strategies": ("cash", "buy_and_hold", "sma_20_50", "donchian_55_20"),
        "development_partition_sha256": "1" * 64,
        "walk_forward_protocol_sha256": "2" * 64,
        "package_version": "0.4.0",
        "registered_code_commit_sha": "a" * 40,
        "execution_code_commit_sha": "b" * 40,
        "event_time_utc": T0 + pd.Timedelta(minutes=minutes),
        "results_json_sha256": "3" * 64 if completed else None,
        "report_markdown_sha256": "4" * 64 if completed else None,
        "result_bundle_sha256": "5" * 64 if completed else None,
        "failure_description": "engine raised" if event == "failed" else None,
    }
    fields.update(over)
    return ExperimentEvent(**fields)


@pytest.fixture
def registry_path(tmp_path: Path) -> Path:
    path = tmp_path / "experiment_registry.jsonl"
    path.write_bytes(b"")
    return path


class TestCommittedRegistry:
    def test_committed_registry_reads(self) -> None:
        # Empty (pre-registration) or a valid registered/started/completed run.
        events = read_registry(REPO_ROOT / EXPERIMENT_REGISTRY_RELPATH)
        assert isinstance(events, tuple)


class TestEventModel:
    def test_round_trip(self) -> None:
        event = make_event("completed", minutes=2)
        assert ExperimentEvent.from_json_line(event.to_json_line()[:-1]) == event

    def test_unknown_event_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="event must be one of"):
            make_event("rerun")

    def test_completed_requires_hashes(self) -> None:
        with pytest.raises(ValueError, match="results_json_sha256"):
            make_event("completed", results_json_sha256=None)

    def test_registered_must_not_carry_hashes(self) -> None:
        with pytest.raises(ValueError, match="must be null on a 'registered' event"):
            make_event("registered", results_json_sha256="3" * 64)

    def test_empty_strategy_set_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="strategies must be"):
            make_event(strategies=())

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(make_event().to_json_line())
        payload["note"] = "x"
        with pytest.raises(ValueError, match=r"unknown=\['note'\]"):
            ExperimentEvent.from_json_line(json.dumps(payload).encode("utf-8"))


class TestSequencing:
    def test_started_before_registered_is_rejected(self, registry_path: Path) -> None:
        registry_path.write_bytes(make_event("started").to_json_line())
        with pytest.raises(RegistryError, match="must follow exactly one 'registered'"):
            read_registry(registry_path)

    def test_completed_before_started_is_rejected(self, registry_path: Path) -> None:
        registry_path.write_bytes(
            make_event("registered").to_json_line()
            + make_event("completed", minutes=1).to_json_line()
        )
        with pytest.raises(RegistryError, match="must follow 'registered' then 'started'"):
            read_registry(registry_path)

    def test_full_lifecycle_reads(self, registry_path: Path) -> None:
        append_registry_event(registry_path, make_event("registered"))
        append_registry_event(registry_path, make_event("started", minutes=1))
        append_registry_event(registry_path, make_event("completed", minutes=2))
        events = read_registry(registry_path)
        assert [e.event for e in events] == ["registered", "started", "completed"]

    def test_duplicate_registered_is_rejected(self, registry_path: Path) -> None:
        append_registry_event(registry_path, make_event("registered"))
        with pytest.raises(RegistryError, match="duplicate 'registered'"):
            append_registry_event(registry_path, make_event("registered", minutes=1))

    def test_field_disagreement_is_rejected(self, registry_path: Path) -> None:
        registry_path.write_bytes(
            make_event("registered").to_json_line()
            + make_event("started", minutes=1, package_version="9.9.9").to_json_line()
        )
        with pytest.raises(RegistryError, match="'package_version' disagrees"):
            read_registry(registry_path)

    def test_event_after_terminal_is_rejected(self, registry_path: Path) -> None:
        registry_path.write_bytes(
            make_event("registered").to_json_line()
            + make_event("started", minutes=1).to_json_line()
            + make_event("completed", minutes=2).to_json_line()
            + make_event("completed", minutes=3).to_json_line()
        )
        with pytest.raises(RegistryError, match="must follow 'registered' then 'started'"):
            read_registry(registry_path)

    def test_contaminated_registry_blocks_append(self, registry_path: Path) -> None:
        registry_path.write_bytes(b"garbage\n")
        with pytest.raises(RegistryError, match="line 1 is invalid"):
            append_registry_event(registry_path, make_event("registered"))


# --- Registry schema v2 -------------------------------------------------------

_ARCHIVE = "research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003"


def make_v2_event(
    event: str = "registered",
    *,
    experiment_id: str = "m3a-fixed-baseline-comparison-v2-run-003",
    previous_event_sha256: str,
    minutes: int = 0,
    **over: Any,
) -> ExperimentEventV2:
    completed = event == "completed"
    fields: dict[str, Any] = {
        "registry_schema_version": REGISTRY_SCHEMA_VERSION_V2,
        "event": event,
        "experiment_id": experiment_id,
        "experiment_family": "m3a-fixed-baseline-comparison-v2",
        "corrects_experiment_id": "m3a-fixed-baseline-comparison-v1-run-002",
        "correction_kind": CORRECTION_METHODOLOGY_GOVERNANCE,
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
        "event_time_utc": T0 + pd.Timedelta(minutes=minutes),
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


def _seed_v1_completed(path: Path, experiment_id: str = "m3a-exp-001") -> None:
    """Write a full v1 registered→started→completed lifecycle to chain v2 onto."""
    append_registry_event(path, make_event("registered", experiment_id=experiment_id))
    append_registry_event(path, make_event("started", experiment_id=experiment_id, minutes=1))
    append_registry_event(path, make_event("completed", experiment_id=experiment_id, minutes=2))


class TestRegistryV2:
    def test_v2_round_trip(self, registry_path: Path) -> None:
        ev = make_v2_event(previous_event_sha256="0" * 64)
        assert ExperimentEventV2.from_json_line(ev.to_json_line()) == ev

    def test_v1_and_v2_read_together(self, registry_path: Path) -> None:
        _seed_v1_completed(registry_path, experiment_id="m3a-fixed-baseline-comparison-v1-run-002")
        prev = latest_registry_line_sha256(registry_path)
        assert prev is not None
        append_registry_event(registry_path, make_v2_event(previous_event_sha256=prev, minutes=10))
        events = read_registry(registry_path)
        assert [e.registry_schema_version for e in events] == [1, 1, 1, 2]

    def test_v2_cannot_be_first_line(self, registry_path: Path) -> None:
        registry_path.write_bytes(make_v2_event(previous_event_sha256="0" * 64).to_json_line())
        with pytest.raises(RegistryError, match="cannot be the first registry line"):
            read_registry(registry_path)

    def test_broken_append_chain_is_rejected(self, registry_path: Path) -> None:
        _seed_v1_completed(registry_path)
        with pytest.raises(RegistryError, match="append-chain is broken"):
            append_registry_event(
                registry_path, make_v2_event(previous_event_sha256="f" * 64, minutes=10)
            )

    def test_correction_without_completed_parent_is_rejected(self, registry_path: Path) -> None:
        # Seed a v1 lifecycle whose id is NOT the one the correction names.
        _seed_v1_completed(registry_path, experiment_id="m3a-other-001")
        prev = latest_registry_line_sha256(registry_path)
        assert prev is not None
        with pytest.raises(RegistryError, match="has no prior 'completed' event"):
            append_registry_event(
                registry_path,
                make_v2_event(
                    previous_event_sha256=prev,
                    corrects_experiment_id="m3a-nonexistent-042",
                    minutes=10,
                ),
            )

    def test_correction_of_completed_parent_is_accepted(self, registry_path: Path) -> None:
        _seed_v1_completed(registry_path, experiment_id="m3a-fixed-baseline-comparison-v1-run-002")
        prev = latest_registry_line_sha256(registry_path)
        assert prev is not None
        append_registry_event(registry_path, make_v2_event(previous_event_sha256=prev, minutes=10))
        events = read_registry(registry_path)
        last = events[-1]
        assert isinstance(last, ExperimentEventV2)
        assert last.corrects_experiment_id == "m3a-fixed-baseline-comparison-v1-run-002"

    def test_correction_kind_requires_lineage(self) -> None:
        with pytest.raises(ValueError, match="correction_kind must be null"):
            make_v2_event(previous_event_sha256="0" * 64, corrects_experiment_id=None)

    def test_lineage_requires_correction_kind(self) -> None:
        with pytest.raises(ValueError, match="correction_kind must be one of"):
            make_v2_event(previous_event_sha256="0" * 64, correction_kind=None)

    def test_self_correction_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot correct itself"):
            make_v2_event(
                previous_event_sha256="0" * 64,
                corrects_experiment_id="m3a-fixed-baseline-comparison-v2-run-003",
            )

    def test_reused_id_across_versions_is_rejected(self, registry_path: Path) -> None:
        # A v2 registered event may not reuse a v1 experiment id.
        _seed_v1_completed(registry_path, experiment_id="m3a-exp-001")
        prev = latest_registry_line_sha256(registry_path)
        assert prev is not None
        with pytest.raises(RegistryError, match="duplicate 'registered'"):
            append_registry_event(
                registry_path,
                make_v2_event(experiment_id="m3a-exp-001", previous_event_sha256=prev, minutes=10),
            )

    def test_unsafe_artifact_path_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must live under"):
            make_v2_event(
                previous_event_sha256="0" * 64,
                immutable_results_path="research/m2b/secret.json",
            )

    def test_unknown_v2_key_is_rejected(self) -> None:
        line = make_v2_event(previous_event_sha256="0" * 64).to_json_line()
        payload = json.loads(line)
        payload["surprise"] = 1
        with pytest.raises(ValueError, match="v2 event keys do not match"):
            ExperimentEventV2.from_json_line((json.dumps(payload) + "\n").encode("utf-8"))

    def test_v2_completed_requires_all_four_hashes(self) -> None:
        with pytest.raises(ValueError, match="return_evidence_sha256"):
            make_v2_event("completed", previous_event_sha256="0" * 64, return_evidence_sha256=None)
