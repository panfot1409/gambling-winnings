"""Append-only development-gate access ledger (Milestone 3A).

The development gate (the M2 validation segment, 2022-06-22 .. 2024-06-30)
is a scarce resource: evaluating a candidate on it is a future-use event
that must be pre-registered and recorded permanently, separately from the
one-time final-holdout ledger. This module defines that strict ledger.

Milestone 3A **never appends a real event** — the file begins and ends
byte-empty. The schema exists so a future, pre-registered development-gate
spend is recorded honestly:

* a ``started`` event is written **before** any development-gate signal is
  computed;
* ``completed`` carries the SHA-256 of the published results JSON, report
  Markdown, and domain-separated result bundle;
* ``failed`` carries an honest failure description;
* nothing is erased or rewritten — a malformed or truncated line is loud
  contamination evidence, never silently skipped;
* candidate ids are single-use — a gate access, once recorded, is
  permanently consumed.

There is no repair path. ``append_gate_event`` re-validates the whole
ledger before appending with a single ``O_APPEND`` write and fsync.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.provenance import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
)
from eth_research.data.validation import (
    parse_timestamp_field,
    require_aware_timestamp,
    require_commit_sha,
    require_evaluation_id,
    require_fingerprint,
)

GATE_LEDGER_SCHEMA_VERSION: int = 1
DEVELOPMENT_GATE_LEDGER_RELPATH: str = "research/m3a/development_gate_access.jsonl"

EVENT_STARTED: str = "started"
EVENT_COMPLETED: str = "completed"
EVENT_FAILED: str = "failed"
_EVENT_NAMES: tuple[str, ...] = (EVENT_STARTED, EVENT_COMPLETED, EVENT_FAILED)

_RESULT_FIELDS: tuple[str, ...] = (
    "results_json_sha256",
    "report_markdown_sha256",
    "result_bundle_sha256",
)

_EVENT_KEYS: frozenset[str] = frozenset(
    {
        "gate_ledger_schema_version",
        "event",
        "experiment_family_id",
        "candidate_id",
        "development_partition_sha256",
        "development_gate_content_fingerprint",
        "protocol_sha256",
        "registered_code_commit_sha",
        "execution_code_commit_sha",
        "reason",
        "event_time_utc",
        "results_json_sha256",
        "report_markdown_sha256",
        "result_bundle_sha256",
        "failure_description",
    }
)

_SHARED_FIELDS: tuple[str, ...] = (
    "experiment_family_id",
    "development_partition_sha256",
    "development_gate_content_fingerprint",
    "protocol_sha256",
    "registered_code_commit_sha",
    "execution_code_commit_sha",
    "reason",
)


class GateLedgerError(RuntimeError):
    """The gate ledger is invalid, corrupted, or the append is illegal."""


@dataclass(frozen=True)
class GateAccessEvent:
    """One development-gate access event; every field validated on build."""

    gate_ledger_schema_version: int
    event: str
    experiment_family_id: str
    candidate_id: str
    development_partition_sha256: str
    development_gate_content_fingerprint: str
    protocol_sha256: str
    registered_code_commit_sha: str
    execution_code_commit_sha: str
    reason: str
    event_time_utc: pd.Timestamp
    results_json_sha256: str | None
    report_markdown_sha256: str | None
    result_bundle_sha256: str | None
    failure_description: str | None

    def __post_init__(self) -> None:
        version = require_int("gate_ledger_schema_version", self.gate_ledger_schema_version)
        if version != GATE_LEDGER_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported gate ledger schema version {version!r}; this package reads "
                f"version {GATE_LEDGER_SCHEMA_VERSION}"
            )
        event = require_str("event", self.event)
        if event not in _EVENT_NAMES:
            raise ValueError(f"event must be one of {_EVENT_NAMES}, got {event!r}")
        require_evaluation_id("experiment_family_id", self.experiment_family_id)
        require_evaluation_id("candidate_id", self.candidate_id)
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        require_fingerprint(
            "development_gate_content_fingerprint", self.development_gate_content_fingerprint
        )
        require_hex64("protocol_sha256", self.protocol_sha256)
        require_commit_sha("registered_code_commit_sha", self.registered_code_commit_sha)
        require_commit_sha("execution_code_commit_sha", self.execution_code_commit_sha)
        require_nonempty_str("reason", self.reason)
        require_aware_timestamp("event_time_utc", self.event_time_utc)
        if event == EVENT_COMPLETED:
            for label in _RESULT_FIELDS:
                require_hex64(label, getattr(self, label))
        else:
            for label in _RESULT_FIELDS:
                if getattr(self, label) is not None:
                    raise ValueError(f"{label} must be null on a {event!r} event")
        if event == EVENT_FAILED:
            require_nonempty_str("failure_description", self.failure_description)
        elif self.failure_description is not None:
            raise ValueError(f"failure_description must be null on a {event!r} event")

    def to_json_line(self) -> bytes:
        payload = {
            "gate_ledger_schema_version": self.gate_ledger_schema_version,
            "event": self.event,
            "experiment_family_id": self.experiment_family_id,
            "candidate_id": self.candidate_id,
            "development_partition_sha256": self.development_partition_sha256,
            "development_gate_content_fingerprint": self.development_gate_content_fingerprint,
            "protocol_sha256": self.protocol_sha256,
            "registered_code_commit_sha": self.registered_code_commit_sha,
            "execution_code_commit_sha": self.execution_code_commit_sha,
            "reason": self.reason,
            "event_time_utc": self.event_time_utc.isoformat(),
            "results_json_sha256": self.results_json_sha256,
            "report_markdown_sha256": self.report_markdown_sha256,
            "result_bundle_sha256": self.result_bundle_sha256,
            "failure_description": self.failure_description,
        }
        text = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_line(cls, line: bytes) -> GateAccessEvent:
        try:
            payload: Any = strict_json_loads(line)
        except StrictJSONError as exc:
            raise ValueError(f"gate ledger line is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("gate ledger line must be a JSON object")
        keys = set(payload)
        if keys != _EVENT_KEYS:
            unknown = sorted(keys - _EVENT_KEYS)
            missing = sorted(_EVENT_KEYS - keys)
            raise ValueError(
                f"gate event keys do not match schema: unknown={unknown}, missing={missing}"
            )
        return cls(
            gate_ledger_schema_version=payload["gate_ledger_schema_version"],
            event=payload["event"],
            experiment_family_id=payload["experiment_family_id"],
            candidate_id=payload["candidate_id"],
            development_partition_sha256=payload["development_partition_sha256"],
            development_gate_content_fingerprint=payload["development_gate_content_fingerprint"],
            protocol_sha256=payload["protocol_sha256"],
            registered_code_commit_sha=payload["registered_code_commit_sha"],
            execution_code_commit_sha=payload["execution_code_commit_sha"],
            reason=payload["reason"],
            event_time_utc=parse_timestamp_field("event_time_utc", payload["event_time_utc"]),
            results_json_sha256=payload["results_json_sha256"],
            report_markdown_sha256=payload["report_markdown_sha256"],
            result_bundle_sha256=payload["result_bundle_sha256"],
            failure_description=payload["failure_description"],
        )


def _check_sequencing(events: tuple[GateAccessEvent, ...]) -> None:
    """Per candidate id: exactly [started] or [started, completed|failed]."""
    history: dict[str, list[GateAccessEvent]] = {}
    for position, event in enumerate(events):
        label = f"gate ledger line {position + 1}"
        seen = history.setdefault(event.candidate_id, [])
        if event.event == EVENT_STARTED:
            if seen:
                raise GateLedgerError(
                    f"{label}: duplicate 'started' for candidate id {event.candidate_id!r} — "
                    "a candidate id is single-use"
                )
        else:
            if not seen:
                raise GateLedgerError(
                    f"{label}: {event.event!r} for candidate id {event.candidate_id!r} "
                    "without a preceding 'started'"
                )
            if len(seen) > 1:
                raise GateLedgerError(
                    f"{label}: candidate id {event.candidate_id!r} already reached a terminal "
                    "event; nothing may follow it"
                )
            started = seen[0]
            for field in _SHARED_FIELDS:
                if getattr(event, field) != getattr(started, field):
                    raise GateLedgerError(
                        f"{label}: field {field!r} disagrees with the 'started' event for "
                        f"candidate id {event.candidate_id!r}"
                    )
            if event.event_time_utc < started.event_time_utc:
                raise GateLedgerError(
                    f"{label}: event time precedes the 'started' event for candidate id "
                    f"{event.candidate_id!r}"
                )
        seen.append(event)


def read_gate_ledger(path: str | Path) -> tuple[GateAccessEvent, ...]:
    """Strictly read and validate the whole gate ledger (empty = pristine)."""
    file = Path(path)
    if not file.exists():
        raise GateLedgerError(
            f"gate ledger file {file} does not exist; create an empty ledger file explicitly "
            "(a missing ledger must never be mistaken for a pristine one)"
        )
    raw = file.read_bytes()
    if raw == b"":
        return ()
    if not raw.endswith(b"\n"):
        raise GateLedgerError(
            f"gate ledger file {file.name!r} does not end with a newline — the final line is "
            "partial; treat the ledger as contaminated and investigate before proceeding"
        )
    events: list[GateAccessEvent] = []
    for position, line in enumerate(raw.split(b"\n")[:-1]):
        try:
            events.append(GateAccessEvent.from_json_line(line))
        except ValueError as exc:
            raise GateLedgerError(
                f"gate ledger line {position + 1} is invalid ({exc}); treat the ledger as "
                "contaminated and investigate before proceeding"
            ) from exc
    result = tuple(events)
    _check_sequencing(result)
    return result


def append_gate_event(path: str | Path, event: GateAccessEvent) -> None:
    """Validate the whole gate ledger, then append one event atomically."""
    existing = read_gate_ledger(path)
    _check_sequencing((*existing, event))
    line = event.to_json_line()
    descriptor = os.open(str(path), os.O_WRONLY | os.O_APPEND)
    try:
        written = os.write(descriptor, line)
        if written != len(line):
            raise GateLedgerError(
                f"short write appending to the gate ledger ({written} of {len(line)} bytes); "
                "inspect the ledger for a partial final line before proceeding"
            )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
