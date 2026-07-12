"""Append-only test-access ledger: strict lines, sequencing, atomic appends."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from eth_research.ledger import (
    LEDGER_SCHEMA_VERSION,
    LedgerError,
    LedgerEvent,
    append_event,
    read_ledger,
)

T0 = pd.Timestamp("2026-07-11T19:00:00+00:00")


def make_event(
    event: str = "started",
    *,
    evaluation_id: str = "m2b-test-eval-001",
    minutes: int = 0,
    **overrides: Any,
) -> LedgerEvent:
    completed = event == "completed"
    fields: dict[str, Any] = {
        "ledger_schema_version": LEDGER_SCHEMA_VERSION,
        "event": event,
        "evaluation_id": evaluation_id,
        "holdout_id": "5" * 64,
        "dataset_content_fingerprint": "sha256:" + "1" * 64,
        "test_content_fingerprint": "sha256:" + "e" * 64,
        "symbol": "ETH-USD",
        "venue": "Coinbase Exchange",
        "candle_interval": pd.Timedelta(days=1),
        "test_first_open_time": pd.Timestamp("2024-01-09", tz="UTC"),
        "test_last_open_time": pd.Timestamp("2024-01-10", tz="UTC"),
        "test_row_count": 2,
        "dataset_lock_sha256": "2" * 64,
        "protocol_sha256": "3" * 64,
        "runtime_contract_sha256": "6" * 64,
        "code_commit_sha": "a" * 40,
        "reason": "authorized one-time Milestone 2B test evaluation",
        "event_time_utc": T0 + pd.Timedelta(minutes=minutes),
        "results_json_sha256": "4" * 64 if completed else None,
        "report_markdown_sha256": "7" * 64 if completed else None,
        "result_bundle_sha256": "8" * 64 if completed else None,
        "failure_description": "engine raised" if event == "failed" else None,
    }
    fields.update(overrides)
    return LedgerEvent(**fields)


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    path = tmp_path / "test_evaluations.jsonl"
    path.write_bytes(b"")
    return path


class TestEventModel:
    def test_line_round_trip(self) -> None:
        event = make_event("completed")
        line = event.to_json_line()
        assert line.endswith(b"\n")
        assert line.count(b"\n") == 1
        assert LedgerEvent.from_json_line(line[:-1]) == event

    def test_unknown_event_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="event must be one of"):
            make_event("rerun")

    def test_completed_requires_all_result_hashes(self) -> None:
        with pytest.raises(ValueError, match="results_json_sha256"):
            make_event("completed", results_json_sha256=None)
        with pytest.raises(ValueError, match="report_markdown_sha256"):
            make_event("completed", report_markdown_sha256=None)
        with pytest.raises(ValueError, match="result_bundle_sha256"):
            make_event("completed", result_bundle_sha256=None)

    def test_started_must_not_carry_result_hashes(self) -> None:
        with pytest.raises(ValueError, match="must be null on a 'started' event"):
            make_event("started", results_json_sha256="4" * 64)

    def test_failed_requires_description(self) -> None:
        with pytest.raises(ValueError, match="failure_description"):
            make_event("failed", failure_description=None)

    def test_completed_must_not_carry_failure_description(self) -> None:
        with pytest.raises(ValueError, match="failure_description must be null"):
            make_event("completed", failure_description="oops")

    def test_holdout_id_must_be_hex64(self) -> None:
        with pytest.raises(ValueError, match="holdout_id"):
            make_event(holdout_id="not-hex")

    def test_test_bounds_must_match_row_count(self) -> None:
        with pytest.raises(ValueError, match="inconsistent with test_first_open_time"):
            make_event(test_row_count=3)

    @pytest.mark.parametrize("identifier", ["short", "Bad-ID", "x" * 65])
    def test_malformed_evaluation_id_is_rejected(self, identifier: str) -> None:
        with pytest.raises(ValueError, match="evaluation_id must match"):
            make_event(evaluation_id=identifier)

    def test_boolean_schema_version_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="bool is rejected"):
            make_event(ledger_schema_version=True)

    def test_stale_v1_schema_version_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported ledger schema version"):
            make_event(ledger_schema_version=1)

    def test_naive_event_time_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            make_event(event_time_utc=pd.Timestamp("2026-07-11"))

    def test_reversed_test_bounds_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be after"):
            make_event(
                test_first_open_time=pd.Timestamp("2024-01-11", tz="UTC"),
                test_last_open_time=pd.Timestamp("2024-01-10", tz="UTC"),
                test_row_count=1,
            )

    def test_unknown_key_is_rejected(self) -> None:
        payload: dict[str, Any] = json.loads(make_event().to_json_line().decode("utf-8"))
        payload["note"] = "extra"
        with pytest.raises(ValueError, match=r"unknown=\['note'\]"):
            LedgerEvent.from_json_line(json.dumps(payload).encode("utf-8"))


class TestReadLedger:
    def test_missing_file_is_an_error_not_pristine(self, tmp_path: Path) -> None:
        with pytest.raises(LedgerError, match="does not exist"):
            read_ledger(tmp_path / "nowhere.jsonl")

    def test_empty_file_is_pristine(self, ledger_path: Path) -> None:
        assert read_ledger(ledger_path) == ()

    def test_valid_history_parses(self, ledger_path: Path) -> None:
        append_event(ledger_path, make_event("started"))
        append_event(ledger_path, make_event("completed", minutes=5))
        events = read_ledger(ledger_path)
        assert [event.event for event in events] == ["started", "completed"]

    def test_partial_final_line_is_contamination(self, ledger_path: Path) -> None:
        append_event(ledger_path, make_event("started"))
        raw = ledger_path.read_bytes()
        ledger_path.write_bytes(raw[:-10])
        with pytest.raises(LedgerError, match="does not end with a newline"):
            read_ledger(ledger_path)

    def test_malformed_line_is_contamination(self, ledger_path: Path) -> None:
        ledger_path.write_bytes(b'{"not": "an event"}\n')
        with pytest.raises(LedgerError, match="ledger line 1 is invalid"):
            read_ledger(ledger_path)

    def test_completed_before_started_is_rejected(self, ledger_path: Path) -> None:
        ledger_path.write_bytes(make_event("completed").to_json_line())
        with pytest.raises(LedgerError, match="without a preceding 'started'"):
            read_ledger(ledger_path)

    def test_duplicate_started_is_rejected(self, ledger_path: Path) -> None:
        ledger_path.write_bytes(
            make_event("started").to_json_line() + make_event("started", minutes=1).to_json_line()
        )
        with pytest.raises(LedgerError, match="duplicate 'started'"):
            read_ledger(ledger_path)

    def test_event_after_terminal_is_rejected(self, ledger_path: Path) -> None:
        ledger_path.write_bytes(
            make_event("started").to_json_line()
            + make_event("failed", minutes=1).to_json_line()
            + make_event("completed", minutes=2).to_json_line()
        )
        with pytest.raises(LedgerError, match="already reached a terminal event"):
            read_ledger(ledger_path)

    def test_field_disagreement_with_started_is_rejected(self, ledger_path: Path) -> None:
        completed = make_event("completed", minutes=1, protocol_sha256="9" * 64)
        ledger_path.write_bytes(make_event("started").to_json_line() + completed.to_json_line())
        with pytest.raises(LedgerError, match="'protocol_sha256' disagrees"):
            read_ledger(ledger_path)

    def test_holdout_id_disagreement_with_started_is_rejected(self, ledger_path: Path) -> None:
        completed = make_event("completed", minutes=1, holdout_id="f" * 64)
        ledger_path.write_bytes(make_event("started").to_json_line() + completed.to_json_line())
        with pytest.raises(LedgerError, match="'holdout_id' disagrees"):
            read_ledger(ledger_path)

    def test_time_regression_is_rejected(self, ledger_path: Path) -> None:
        ledger_path.write_bytes(
            make_event("started").to_json_line()
            + make_event("completed", minutes=-5).to_json_line()
        )
        with pytest.raises(LedgerError, match="event time precedes"):
            read_ledger(ledger_path)


class TestAppendEvent:
    def test_append_produces_exact_bytes(self, ledger_path: Path) -> None:
        started = make_event("started")
        completed = make_event("completed", minutes=5)
        append_event(ledger_path, started)
        append_event(ledger_path, completed)
        assert ledger_path.read_bytes() == started.to_json_line() + completed.to_json_line()

    def test_append_refuses_duplicate_started(self, ledger_path: Path) -> None:
        append_event(ledger_path, make_event("started"))
        with pytest.raises(LedgerError, match="duplicate 'started'"):
            append_event(ledger_path, make_event("started", minutes=1))
        assert len(read_ledger(ledger_path)) == 1

    def test_append_refuses_completion_for_unknown_id(self, ledger_path: Path) -> None:
        with pytest.raises(LedgerError, match="without a preceding 'started'"):
            append_event(ledger_path, make_event("completed", evaluation_id="m2b-other-eval-1"))
        assert ledger_path.read_bytes() == b""

    def test_append_to_missing_file_fails(self, tmp_path: Path) -> None:
        with pytest.raises(LedgerError, match="does not exist"):
            append_event(tmp_path / "nowhere.jsonl", make_event("started"))

    def test_append_to_contaminated_ledger_fails(self, ledger_path: Path) -> None:
        ledger_path.write_bytes(b"garbage\n")
        with pytest.raises(LedgerError, match="ledger line 1 is invalid"):
            append_event(ledger_path, make_event("started"))
        assert ledger_path.read_bytes() == b"garbage\n"

    def test_crash_after_started_reads_as_one_consumed_event(self, ledger_path: Path) -> None:
        # A crash: 'started' was written, no terminal event followed. The read
        # still surfaces the consumed access — never an empty, pristine ledger.
        append_event(ledger_path, make_event("started"))
        events = read_ledger(ledger_path)
        assert [event.event for event in events] == ["started"]


def test_dataclass_replace_reruns_validation() -> None:
    event = make_event("started")
    with pytest.raises(ValueError, match="must be null on a 'started' event"):
        dataclasses.replace(event, results_json_sha256="9" * 64)
