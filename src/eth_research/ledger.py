"""Append-only test-access ledger for the one-time test evaluation.

Every access to the real test segment — attempted, completed, or failed —
is recorded as one strict JSON line in an append-only ledger file. The
ledger is committed to version control so the research history of test-set
access is public and permanent:

* a ``started`` event is written **before** any test signal or P&L is
  computed — a crash after that point is a consumed access, not a do-over;
* ``completed`` carries the SHA-256 of the published results;
* ``failed`` carries an honest failure description;
* nothing is ever erased or rewritten — the file only grows, and a
  malformed or truncated line is loud contamination evidence, never
  silently skipped.

``append_event`` strictly re-validates the entire ledger before every
append, then appends the new line with a single write and fsync, so a
malformed ledger can never accumulate further events and a partial line
cannot be produced by this writer short of a mid-write crash — which the
next read reports as corruption instead of ignoring.
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

LEDGER_SCHEMA_VERSION: int = 1

EVENT_STARTED: str = "started"
EVENT_COMPLETED: str = "completed"
EVENT_FAILED: str = "failed"
_EVENT_NAMES: tuple[str, ...] = (EVENT_STARTED, EVENT_COMPLETED, EVENT_FAILED)

_EVENT_KEYS: frozenset[str] = frozenset(
    {
        "ledger_schema_version",
        "event",
        "evaluation_id",
        "dataset_content_fingerprint",
        "dataset_lock_sha256",
        "protocol_sha256",
        "code_commit_sha",
        "test_first_open_time",
        "test_last_open_time",
        "reason",
        "event_time_utc",
        "result_report_sha256",
        "failure_description",
    }
)

_SHARED_FIELDS: tuple[str, ...] = (
    "evaluation_id",
    "dataset_content_fingerprint",
    "dataset_lock_sha256",
    "protocol_sha256",
    "code_commit_sha",
    "test_first_open_time",
    "test_last_open_time",
    "reason",
)
"""Fields that must be identical across all events of one evaluation id."""


class LedgerError(RuntimeError):
    """The ledger is invalid, corrupted, or the requested append is illegal."""


@dataclass(frozen=True)
class LedgerEvent:
    """One test-access event; every field validated in ``__post_init__``."""

    ledger_schema_version: int
    event: str
    evaluation_id: str
    dataset_content_fingerprint: str
    dataset_lock_sha256: str
    protocol_sha256: str
    code_commit_sha: str
    test_first_open_time: pd.Timestamp
    test_last_open_time: pd.Timestamp
    reason: str
    event_time_utc: pd.Timestamp
    result_report_sha256: str | None
    failure_description: str | None

    def __post_init__(self) -> None:
        version = require_int("ledger_schema_version", self.ledger_schema_version)
        if version != LEDGER_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported ledger schema version {version!r}; "
                f"this package reads version {LEDGER_SCHEMA_VERSION}"
            )
        event = require_str("event", self.event)
        if event not in _EVENT_NAMES:
            raise ValueError(f"event must be one of {_EVENT_NAMES}, got {event!r}")
        require_evaluation_id("evaluation_id", self.evaluation_id)
        require_fingerprint("dataset_content_fingerprint", self.dataset_content_fingerprint)
        require_hex64("dataset_lock_sha256", self.dataset_lock_sha256)
        require_hex64("protocol_sha256", self.protocol_sha256)
        require_commit_sha("code_commit_sha", self.code_commit_sha)
        require_aware_timestamp("test_first_open_time", self.test_first_open_time)
        require_aware_timestamp("test_last_open_time", self.test_last_open_time)
        if self.test_first_open_time > self.test_last_open_time:
            raise ValueError(
                f"test_first_open_time {self.test_first_open_time} must not be after "
                f"test_last_open_time {self.test_last_open_time}"
            )
        require_nonempty_str("reason", self.reason)
        require_aware_timestamp("event_time_utc", self.event_time_utc)
        if event == EVENT_COMPLETED:
            require_hex64("result_report_sha256", self.result_report_sha256)
        elif self.result_report_sha256 is not None:
            raise ValueError(f"result_report_sha256 must be null on a {event!r} event")
        if event == EVENT_FAILED:
            require_nonempty_str("failure_description", self.failure_description)
        elif self.failure_description is not None:
            raise ValueError(f"failure_description must be null on a {event!r} event")

    def to_json_line(self) -> bytes:
        """One compact, deterministic JSON line with a trailing newline."""
        payload = {
            "ledger_schema_version": self.ledger_schema_version,
            "event": self.event,
            "evaluation_id": self.evaluation_id,
            "dataset_content_fingerprint": self.dataset_content_fingerprint,
            "dataset_lock_sha256": self.dataset_lock_sha256,
            "protocol_sha256": self.protocol_sha256,
            "code_commit_sha": self.code_commit_sha,
            "test_first_open_time": self.test_first_open_time.isoformat(),
            "test_last_open_time": self.test_last_open_time.isoformat(),
            "reason": self.reason,
            "event_time_utc": self.event_time_utc.isoformat(),
            "result_report_sha256": self.result_report_sha256,
            "failure_description": self.failure_description,
        }
        text = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_line(cls, line: bytes) -> LedgerEvent:
        """Strict parse of one ledger line feeding the shared constructor."""
        try:
            payload: Any = strict_json_loads(line)
        except StrictJSONError as exc:
            raise ValueError(f"ledger line is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("ledger line must be a JSON object")
        keys = set(payload)
        if keys != _EVENT_KEYS:
            unknown = sorted(keys - _EVENT_KEYS)
            missing = sorted(_EVENT_KEYS - keys)
            raise ValueError(
                f"ledger event keys do not match schema: unknown={unknown}, missing={missing}"
            )
        return cls(
            ledger_schema_version=payload["ledger_schema_version"],
            event=payload["event"],
            evaluation_id=payload["evaluation_id"],
            dataset_content_fingerprint=payload["dataset_content_fingerprint"],
            dataset_lock_sha256=payload["dataset_lock_sha256"],
            protocol_sha256=payload["protocol_sha256"],
            code_commit_sha=payload["code_commit_sha"],
            test_first_open_time=parse_timestamp_field(
                "test_first_open_time", payload["test_first_open_time"]
            ),
            test_last_open_time=parse_timestamp_field(
                "test_last_open_time", payload["test_last_open_time"]
            ),
            reason=payload["reason"],
            event_time_utc=parse_timestamp_field("event_time_utc", payload["event_time_utc"]),
            result_report_sha256=payload["result_report_sha256"],
            failure_description=payload["failure_description"],
        )


def _check_sequencing(events: tuple[LedgerEvent, ...]) -> None:
    """Per evaluation id: exactly [started] or [started, completed|failed]."""
    history: dict[str, list[LedgerEvent]] = {}
    for position, event in enumerate(events):
        label = f"ledger line {position + 1}"
        seen = history.setdefault(event.evaluation_id, [])
        if event.event == EVENT_STARTED:
            if seen:
                raise LedgerError(
                    f"{label}: duplicate 'started' for evaluation id {event.evaluation_id!r} — "
                    "an evaluation id is single-use"
                )
        else:
            if not seen:
                raise LedgerError(
                    f"{label}: {event.event!r} for evaluation id {event.evaluation_id!r} "
                    "without a preceding 'started'"
                )
            if len(seen) > 1:
                raise LedgerError(
                    f"{label}: evaluation id {event.evaluation_id!r} already reached a "
                    f"terminal event; nothing may follow it"
                )
            started = seen[0]
            for field in _SHARED_FIELDS:
                if getattr(event, field) != getattr(started, field):
                    raise LedgerError(
                        f"{label}: field {field!r} disagrees with the 'started' event for "
                        f"evaluation id {event.evaluation_id!r}"
                    )
            if event.event_time_utc < started.event_time_utc:
                raise LedgerError(
                    f"{label}: event time precedes the 'started' event for "
                    f"evaluation id {event.evaluation_id!r}"
                )
        seen.append(event)


def read_ledger(path: str | Path) -> tuple[LedgerEvent, ...]:
    """Strictly read and validate the whole ledger.

    The file must exist (commit an empty file to start a ledger — a wrong
    path must fail loudly, not appear pristine). Every line must parse,
    the file must end with a newline, and per-id sequencing must be valid.
    """
    file = Path(path)
    if not file.exists():
        raise LedgerError(
            f"ledger file {file} does not exist; create an empty ledger file explicitly "
            "(a missing ledger must never be mistaken for a pristine one)"
        )
    raw = file.read_bytes()
    if raw == b"":
        return ()
    if not raw.endswith(b"\n"):
        raise LedgerError(
            f"ledger file {file.name!r} does not end with a newline — the final line is "
            "partial; treat the ledger as contaminated and investigate before proceeding"
        )
    events: list[LedgerEvent] = []
    for position, line in enumerate(raw.split(b"\n")[:-1]):
        try:
            events.append(LedgerEvent.from_json_line(line))
        except ValueError as exc:
            raise LedgerError(
                f"ledger line {position + 1} is invalid ({exc}); treat the ledger as "
                "contaminated and investigate before proceeding"
            ) from exc
    result = tuple(events)
    _check_sequencing(result)
    return result


def append_event(path: str | Path, event: LedgerEvent) -> None:
    """Validate the whole ledger, then append one event atomically.

    The new event must be legal after the existing history (fresh id for
    ``started``; exactly one prior ``started`` with matching fields for
    ``completed``/``failed``). The line is appended with a single write
    to an ``O_APPEND`` descriptor and fsynced.
    """
    existing = read_ledger(path)
    _check_sequencing((*existing, event))
    line = event.to_json_line()
    descriptor = os.open(str(path), os.O_WRONLY | os.O_APPEND)
    try:
        written = os.write(descriptor, line)
        if written != len(line):
            raise LedgerError(
                f"short write appending to the ledger ({written} of {len(line)} bytes); "
                "inspect the ledger for a partial final line before proceeding"
            )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def accesses_for(
    events: tuple[LedgerEvent, ...],
    *,
    dataset_lock_sha256: str,
    protocol_sha256: str,
) -> tuple[LedgerEvent, ...]:
    """Every recorded access for one (dataset lock, protocol) pair.

    Any returned event — started, completed, or failed — means the
    one-time test evaluation for that pair has been consumed.
    """
    return tuple(
        event
        for event in events
        if event.dataset_lock_sha256 == dataset_lock_sha256
        and event.protocol_sha256 == protocol_sha256
    )
