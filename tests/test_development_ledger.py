"""Development-gate access ledger: strict schema, sequencing, byte-empty in M3A."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import eth_research
from eth_research.development_ledger import (
    DEVELOPMENT_GATE_LEDGER_RELPATH,
    GATE_LEDGER_SCHEMA_VERSION,
    GateAccessEvent,
    GateLedgerError,
    append_gate_event,
    read_gate_ledger,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
T0 = pd.Timestamp("2026-07-13T12:00:00+00:00")
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def make_event(
    event: str = "started", *, candidate_id: str = "m3a-candidate-001", **over: Any
) -> GateAccessEvent:
    completed = event == "completed"
    fields: dict[str, Any] = {
        "gate_ledger_schema_version": GATE_LEDGER_SCHEMA_VERSION,
        "event": event,
        "experiment_family_id": "m3a-fixed-baseline-comparison-v1",
        "candidate_id": candidate_id,
        "development_partition_sha256": "1" * 64,
        "development_gate_content_fingerprint": "sha256:" + "2" * 64,
        "protocol_sha256": "3" * 64,
        "registered_code_commit_sha": "a" * 40,
        "execution_code_commit_sha": "b" * 40,
        "reason": "pre-registered development-gate spend",
        "event_time_utc": T0,
        "results_json_sha256": "4" * 64 if completed else None,
        "report_markdown_sha256": "5" * 64 if completed else None,
        "result_bundle_sha256": "6" * 64 if completed else None,
        "failure_description": "engine raised" if event == "failed" else None,
    }
    fields.update(over)
    return GateAccessEvent(**fields)


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    path = tmp_path / "development_gate_access.jsonl"
    path.write_bytes(b"")
    return path


class TestCommittedGateLedgerIsPristine:
    def test_committed_ledger_is_byte_empty(self) -> None:
        path = REPO_ROOT / DEVELOPMENT_GATE_LEDGER_RELPATH
        assert path.is_file()
        assert path.read_bytes() == b""
        assert read_gate_ledger(path) == ()


class TestEventModel:
    def test_line_round_trip(self) -> None:
        event = make_event("completed")
        line = event.to_json_line()
        assert line.endswith(b"\n")
        assert GateAccessEvent.from_json_line(line[:-1]) == event

    def test_unknown_event_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="event must be one of"):
            make_event("rerun")

    def test_completed_requires_result_hashes(self) -> None:
        with pytest.raises(ValueError, match="results_json_sha256"):
            make_event("completed", results_json_sha256=None)

    def test_started_must_not_carry_result_hashes(self) -> None:
        with pytest.raises(ValueError, match="must be null on a 'started' event"):
            make_event("started", results_json_sha256="4" * 64)

    def test_failed_requires_description(self) -> None:
        with pytest.raises(ValueError, match="failure_description"):
            make_event("failed", failure_description=None)

    def test_bool_schema_version_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="bool is rejected"):
            make_event(gate_ledger_schema_version=True)

    def test_malformed_candidate_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="candidate_id must match"):
            make_event(candidate_id="Bad ID")

    def test_naive_event_time_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            make_event(event_time_utc=pd.Timestamp("2026-07-13"))

    def test_unknown_key_is_rejected(self) -> None:
        payload: dict[str, Any] = json.loads(make_event().to_json_line().decode("utf-8"))
        payload["note"] = "x"
        with pytest.raises(ValueError, match=r"unknown=\['note'\]"):
            GateAccessEvent.from_json_line(json.dumps(payload).encode("utf-8"))


class TestSequencing:
    def test_missing_file_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(GateLedgerError, match="does not exist"):
            read_gate_ledger(tmp_path / "nowhere.jsonl")

    def test_empty_is_pristine(self, ledger_path: Path) -> None:
        assert read_gate_ledger(ledger_path) == ()

    def test_partial_final_line_is_contamination(self, ledger_path: Path) -> None:
        append_gate_event(ledger_path, make_event("started"))
        raw = ledger_path.read_bytes()
        ledger_path.write_bytes(raw[:-5])
        with pytest.raises(GateLedgerError, match="does not end with a newline"):
            read_gate_ledger(ledger_path)

    def test_completed_before_started_is_rejected(self, ledger_path: Path) -> None:
        ledger_path.write_bytes(make_event("completed").to_json_line())
        with pytest.raises(GateLedgerError, match="without a preceding 'started'"):
            read_gate_ledger(ledger_path)

    def test_duplicate_started_is_rejected(self, ledger_path: Path) -> None:
        append_gate_event(ledger_path, make_event("started"))
        with pytest.raises(GateLedgerError, match="duplicate 'started'"):
            append_gate_event(ledger_path, make_event("started"))
        assert len(read_gate_ledger(ledger_path)) == 1

    def test_event_after_terminal_is_rejected(self, ledger_path: Path) -> None:
        ledger_path.write_bytes(
            make_event("started").to_json_line()
            + make_event("failed").to_json_line()
            + make_event("completed").to_json_line()
        )
        with pytest.raises(GateLedgerError, match="already reached a terminal event"):
            read_gate_ledger(ledger_path)

    def test_field_disagreement_with_started_is_rejected(self, ledger_path: Path) -> None:
        started = make_event("started")
        completed = make_event("completed", protocol_sha256="9" * 64)
        ledger_path.write_bytes(started.to_json_line() + completed.to_json_line())
        with pytest.raises(GateLedgerError, match="'protocol_sha256' disagrees"):
            read_gate_ledger(ledger_path)

    def test_append_produces_exact_bytes(self, ledger_path: Path) -> None:
        started = make_event("started")
        completed = make_event("completed")
        append_gate_event(ledger_path, started)
        append_gate_event(ledger_path, completed)
        assert ledger_path.read_bytes() == started.to_json_line() + completed.to_json_line()

    def test_append_to_contaminated_ledger_fails(self, ledger_path: Path) -> None:
        ledger_path.write_bytes(b"garbage\n")
        with pytest.raises(GateLedgerError, match="line 1 is invalid"):
            append_gate_event(ledger_path, make_event("started"))
        assert ledger_path.read_bytes() == b"garbage\n"
