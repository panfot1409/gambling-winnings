"""Append-only test-access ledger for the one-time test evaluation.

Every access to the real test segment — attempted, completed, or failed —
is recorded as one strict JSON line in an append-only ledger file. The
ledger is committed to version control so the research history of test-set
access is public and permanent:

* a ``started`` event is written **before** any test signal or P&L is
  computed — a crash after that point is a consumed access, not a do-over;
* ``completed`` carries the SHA-256 of the published results JSON, the
  report Markdown, and the domain-separated result bundle;
* ``failed`` carries an honest failure description;
* nothing is ever erased or rewritten — the file only grows, and a
  malformed or truncated line is loud contamination evidence, never
  silently skipped.

Schema v3 records the **holdout identity** the access consumed
(``holdout_id``, ``test_content_fingerprint``, instrument, test window) so
that freshness is a property of the candles evaluated, plus the complete
authorization context: the frozen dossier-manifest hash, the committed
holdout-identity/validation-decision/train-validation-results hashes, and
the two distinct commit concepts — ``protocol_registration_commit_sha``
(the immutable registration fact) and
``authorized_evaluation_code_commit_sha`` (the reviewed revision the
evaluation actually ran at). The production ledger is byte-empty, so v3 is
adopted before the first real event; there is no migration or repair path.

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
    require_positive_int,
)

LEDGER_SCHEMA_VERSION: int = 3

EVENT_STARTED: str = "started"
EVENT_COMPLETED: str = "completed"
EVENT_FAILED: str = "failed"
_EVENT_NAMES: tuple[str, ...] = (EVENT_STARTED, EVENT_COMPLETED, EVENT_FAILED)

_RESULT_FIELDS: tuple[str, ...] = (
    "results_json_sha256",
    "report_markdown_sha256",
    "result_bundle_sha256",
)
"""Present together on ``completed``; all null otherwise."""

_EVENT_KEYS: frozenset[str] = frozenset(
    {
        "ledger_schema_version",
        "event",
        "evaluation_id",
        "holdout_id",
        "dataset_content_fingerprint",
        "test_content_fingerprint",
        "symbol",
        "venue",
        "candle_interval",
        "test_first_open_time",
        "test_last_open_time",
        "test_row_count",
        "dataset_lock_sha256",
        "protocol_sha256",
        "runtime_contract_sha256",
        "frozen_dossier_sha256",
        "holdout_identity_sha256",
        "validation_decision_sha256",
        "train_validation_results_sha256",
        "protocol_registration_commit_sha",
        "authorized_evaluation_code_commit_sha",
        "reason",
        "event_time_utc",
        "results_json_sha256",
        "report_markdown_sha256",
        "result_bundle_sha256",
        "failure_description",
    }
)

_SHARED_FIELDS: tuple[str, ...] = (
    "evaluation_id",
    "holdout_id",
    "dataset_content_fingerprint",
    "test_content_fingerprint",
    "symbol",
    "venue",
    "candle_interval",
    "test_first_open_time",
    "test_last_open_time",
    "test_row_count",
    "dataset_lock_sha256",
    "protocol_sha256",
    "runtime_contract_sha256",
    "frozen_dossier_sha256",
    "holdout_identity_sha256",
    "validation_decision_sha256",
    "train_validation_results_sha256",
    "protocol_registration_commit_sha",
    "authorized_evaluation_code_commit_sha",
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
    holdout_id: str
    dataset_content_fingerprint: str
    test_content_fingerprint: str
    symbol: str
    venue: str
    candle_interval: pd.Timedelta
    test_first_open_time: pd.Timestamp
    test_last_open_time: pd.Timestamp
    test_row_count: int
    dataset_lock_sha256: str
    protocol_sha256: str
    runtime_contract_sha256: str
    frozen_dossier_sha256: str
    holdout_identity_sha256: str
    validation_decision_sha256: str
    train_validation_results_sha256: str
    protocol_registration_commit_sha: str
    authorized_evaluation_code_commit_sha: str
    reason: str
    event_time_utc: pd.Timestamp
    results_json_sha256: str | None
    report_markdown_sha256: str | None
    result_bundle_sha256: str | None
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
        require_hex64("holdout_id", self.holdout_id)
        require_fingerprint("dataset_content_fingerprint", self.dataset_content_fingerprint)
        require_fingerprint("test_content_fingerprint", self.test_content_fingerprint)
        for label in ("symbol", "venue"):
            require_nonempty_str(label, getattr(self, label))
        if (
            not isinstance(self.candle_interval, pd.Timedelta)
            or pd.isna(self.candle_interval)
            or self.candle_interval <= pd.Timedelta(0)
        ):
            raise ValueError(
                f"candle_interval must be a positive Timedelta, got {self.candle_interval!r}"
            )
        require_aware_timestamp("test_first_open_time", self.test_first_open_time)
        require_aware_timestamp("test_last_open_time", self.test_last_open_time)
        row_count = require_positive_int("test_row_count", self.test_row_count)
        if self.test_first_open_time > self.test_last_open_time:
            raise ValueError(
                f"test_first_open_time {self.test_first_open_time} must not be after "
                f"test_last_open_time {self.test_last_open_time}"
            )
        expected_last = self.test_first_open_time + (row_count - 1) * self.candle_interval
        if self.test_last_open_time != expected_last:
            raise ValueError(
                "test_last_open_time is inconsistent with test_first_open_time + "
                f"(test_row_count - 1) * candle_interval: expected {expected_last}, "
                f"got {self.test_last_open_time}"
            )
        require_hex64("dataset_lock_sha256", self.dataset_lock_sha256)
        require_hex64("protocol_sha256", self.protocol_sha256)
        require_hex64("runtime_contract_sha256", self.runtime_contract_sha256)
        require_hex64("frozen_dossier_sha256", self.frozen_dossier_sha256)
        require_hex64("holdout_identity_sha256", self.holdout_identity_sha256)
        require_hex64("validation_decision_sha256", self.validation_decision_sha256)
        require_hex64("train_validation_results_sha256", self.train_validation_results_sha256)
        require_commit_sha(
            "protocol_registration_commit_sha", self.protocol_registration_commit_sha
        )
        require_commit_sha(
            "authorized_evaluation_code_commit_sha", self.authorized_evaluation_code_commit_sha
        )
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
        """One compact, deterministic JSON line with a trailing newline."""
        payload = {
            "ledger_schema_version": self.ledger_schema_version,
            "event": self.event,
            "evaluation_id": self.evaluation_id,
            "holdout_id": self.holdout_id,
            "dataset_content_fingerprint": self.dataset_content_fingerprint,
            "test_content_fingerprint": self.test_content_fingerprint,
            "symbol": self.symbol,
            "venue": self.venue,
            "candle_interval": self.candle_interval.isoformat(),
            "test_first_open_time": self.test_first_open_time.isoformat(),
            "test_last_open_time": self.test_last_open_time.isoformat(),
            "test_row_count": self.test_row_count,
            "dataset_lock_sha256": self.dataset_lock_sha256,
            "protocol_sha256": self.protocol_sha256,
            "runtime_contract_sha256": self.runtime_contract_sha256,
            "frozen_dossier_sha256": self.frozen_dossier_sha256,
            "holdout_identity_sha256": self.holdout_identity_sha256,
            "validation_decision_sha256": self.validation_decision_sha256,
            "train_validation_results_sha256": self.train_validation_results_sha256,
            "protocol_registration_commit_sha": self.protocol_registration_commit_sha,
            "authorized_evaluation_code_commit_sha": self.authorized_evaluation_code_commit_sha,
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
        interval_text = require_str("candle_interval", payload["candle_interval"])
        try:
            interval = pd.Timedelta(interval_text)
        except ValueError as exc:
            raise ValueError(f"candle_interval is unparseable: {interval_text!r}") from exc
        return cls(
            ledger_schema_version=payload["ledger_schema_version"],
            event=payload["event"],
            evaluation_id=payload["evaluation_id"],
            holdout_id=payload["holdout_id"],
            dataset_content_fingerprint=payload["dataset_content_fingerprint"],
            test_content_fingerprint=payload["test_content_fingerprint"],
            symbol=payload["symbol"],
            venue=payload["venue"],
            candle_interval=interval,
            test_first_open_time=parse_timestamp_field(
                "test_first_open_time", payload["test_first_open_time"]
            ),
            test_last_open_time=parse_timestamp_field(
                "test_last_open_time", payload["test_last_open_time"]
            ),
            test_row_count=payload["test_row_count"],
            dataset_lock_sha256=payload["dataset_lock_sha256"],
            protocol_sha256=payload["protocol_sha256"],
            runtime_contract_sha256=payload["runtime_contract_sha256"],
            frozen_dossier_sha256=payload["frozen_dossier_sha256"],
            holdout_identity_sha256=payload["holdout_identity_sha256"],
            validation_decision_sha256=payload["validation_decision_sha256"],
            train_validation_results_sha256=payload["train_validation_results_sha256"],
            protocol_registration_commit_sha=payload["protocol_registration_commit_sha"],
            authorized_evaluation_code_commit_sha=payload["authorized_evaluation_code_commit_sha"],
            reason=payload["reason"],
            event_time_utc=parse_timestamp_field("event_time_utc", payload["event_time_utc"]),
            results_json_sha256=payload["results_json_sha256"],
            report_markdown_sha256=payload["report_markdown_sha256"],
            result_bundle_sha256=payload["result_bundle_sha256"],
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
