"""Experiment registry: strict schema and registered->started->terminal order."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import eth_research
from eth_research.experiment_registry import (
    EXPERIMENT_REGISTRY_RELPATH,
    REGISTRY_SCHEMA_VERSION,
    ExperimentEvent,
    RegistryError,
    append_registry_event,
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
