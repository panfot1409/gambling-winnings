"""Append-only experiment registry (Milestone 3A).

Every real-data M3A experiment — including a failure — is recorded here, in
an append-only JSONL registry committed to version control, so the research
history is public and permanent. Unlike the byte-empty access ledgers, this
registry **does** carry the real fixed-baseline experiment's events.

Per experiment id the sequence is exactly ``registered`` →
``started`` → (``completed`` | ``failed``):

* ``registered`` pre-registers the experiment (protocol + partition SHAs,
  hypothesis, exact strategy set) **before** any real computation;
* ``started`` is written before the real evaluation runs;
* ``completed`` carries the SHA-256 of the published results JSON, report
  Markdown, and result bundle — publication is verified before it is
  appended;
* ``failed`` carries an honest failure description.

Experiment ids are single-use, terminal events must match the registration
context, and a malformed or truncated line blocks further appends. There is
no repair or rewrite path.
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
)

REGISTRY_SCHEMA_VERSION: int = 1
EXPERIMENT_REGISTRY_RELPATH: str = "research/m3a/experiment_registry.jsonl"

EVENT_REGISTERED: str = "registered"
EVENT_STARTED: str = "started"
EVENT_COMPLETED: str = "completed"
EVENT_FAILED: str = "failed"
_EVENT_NAMES: tuple[str, ...] = (EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED, EVENT_FAILED)

_RESULT_FIELDS: tuple[str, ...] = (
    "results_json_sha256",
    "report_markdown_sha256",
    "result_bundle_sha256",
)

_EVENT_KEYS: frozenset[str] = frozenset(
    {
        "registry_schema_version",
        "event",
        "experiment_id",
        "experiment_family",
        "hypothesis",
        "strategies",
        "development_partition_sha256",
        "walk_forward_protocol_sha256",
        "package_version",
        "registered_code_commit_sha",
        "execution_code_commit_sha",
        "event_time_utc",
        "results_json_sha256",
        "report_markdown_sha256",
        "result_bundle_sha256",
        "failure_description",
    }
)

_SHARED_FIELDS: tuple[str, ...] = (
    "experiment_family",
    "hypothesis",
    "strategies",
    "development_partition_sha256",
    "walk_forward_protocol_sha256",
    "package_version",
    "registered_code_commit_sha",
    "execution_code_commit_sha",
)


class RegistryError(RuntimeError):
    """The experiment registry is invalid, corrupted, or the append is illegal."""


@dataclass(frozen=True)
class ExperimentEvent:
    """One experiment-registry event; every field validated on construction."""

    registry_schema_version: int
    event: str
    experiment_id: str
    experiment_family: str
    hypothesis: str
    strategies: tuple[str, ...]
    development_partition_sha256: str
    walk_forward_protocol_sha256: str
    package_version: str
    registered_code_commit_sha: str
    execution_code_commit_sha: str
    event_time_utc: pd.Timestamp
    results_json_sha256: str | None
    report_markdown_sha256: str | None
    result_bundle_sha256: str | None
    failure_description: str | None

    def __post_init__(self) -> None:
        version = require_int("registry_schema_version", self.registry_schema_version)
        if version != REGISTRY_SCHEMA_VERSION:
            raise ValueError(f"unsupported registry schema version {version!r}")
        event = require_str("event", self.event)
        if event not in _EVENT_NAMES:
            raise ValueError(f"event must be one of {_EVENT_NAMES}, got {event!r}")
        require_evaluation_id("experiment_id", self.experiment_id)
        require_evaluation_id("experiment_family", self.experiment_family)
        require_nonempty_str("hypothesis", self.hypothesis)
        if not self.strategies or any(not isinstance(s, str) or not s for s in self.strategies):
            raise ValueError("strategies must be a non-empty tuple of non-empty strings")
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        require_hex64("walk_forward_protocol_sha256", self.walk_forward_protocol_sha256)
        require_nonempty_str("package_version", self.package_version)
        require_commit_sha("registered_code_commit_sha", self.registered_code_commit_sha)
        require_commit_sha("execution_code_commit_sha", self.execution_code_commit_sha)
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
            "registry_schema_version": self.registry_schema_version,
            "event": self.event,
            "experiment_id": self.experiment_id,
            "experiment_family": self.experiment_family,
            "hypothesis": self.hypothesis,
            "strategies": list(self.strategies),
            "development_partition_sha256": self.development_partition_sha256,
            "walk_forward_protocol_sha256": self.walk_forward_protocol_sha256,
            "package_version": self.package_version,
            "registered_code_commit_sha": self.registered_code_commit_sha,
            "execution_code_commit_sha": self.execution_code_commit_sha,
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
    def from_json_line(cls, line: bytes) -> ExperimentEvent:
        try:
            payload: Any = strict_json_loads(line)
        except StrictJSONError as exc:
            raise ValueError(f"registry line is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("registry line must be a JSON object")
        keys = set(payload)
        if keys != _EVENT_KEYS:
            unknown = sorted(keys - _EVENT_KEYS)
            missing = sorted(_EVENT_KEYS - keys)
            raise ValueError(
                f"registry event keys do not match schema: unknown={unknown}, missing={missing}"
            )
        strategies = payload["strategies"]
        if not isinstance(strategies, list):
            raise ValueError("strategies must be a list")
        return cls(
            registry_schema_version=payload["registry_schema_version"],
            event=payload["event"],
            experiment_id=payload["experiment_id"],
            experiment_family=payload["experiment_family"],
            hypothesis=payload["hypothesis"],
            strategies=tuple(require_str("strategy", s) for s in strategies),
            development_partition_sha256=payload["development_partition_sha256"],
            walk_forward_protocol_sha256=payload["walk_forward_protocol_sha256"],
            package_version=payload["package_version"],
            registered_code_commit_sha=payload["registered_code_commit_sha"],
            execution_code_commit_sha=payload["execution_code_commit_sha"],
            event_time_utc=parse_timestamp_field("event_time_utc", payload["event_time_utc"]),
            results_json_sha256=payload["results_json_sha256"],
            report_markdown_sha256=payload["report_markdown_sha256"],
            result_bundle_sha256=payload["result_bundle_sha256"],
            failure_description=payload["failure_description"],
        )


def _check_sequencing(events: tuple[ExperimentEvent, ...]) -> None:
    """Per id: exactly [registered], [registered, started], or
    [registered, started, completed|failed]."""
    history: dict[str, list[ExperimentEvent]] = {}
    for position, event in enumerate(events):
        label = f"registry line {position + 1}"
        seen = history.setdefault(event.experiment_id, [])
        if event.event == EVENT_REGISTERED:
            if seen:
                raise RegistryError(
                    f"{label}: duplicate 'registered' for experiment id "
                    f"{event.experiment_id!r} — an experiment id is single-use"
                )
        elif event.event == EVENT_STARTED:
            if [e.event for e in seen] != [EVENT_REGISTERED]:
                raise RegistryError(
                    f"{label}: 'started' for {event.experiment_id!r} must follow exactly one "
                    "'registered' event"
                )
        else:  # completed | failed
            if [e.event for e in seen] != [EVENT_REGISTERED, EVENT_STARTED]:
                raise RegistryError(
                    f"{label}: {event.event!r} for {event.experiment_id!r} must follow "
                    "'registered' then 'started'"
                )
        if seen:
            registered = seen[0]
            for field in _SHARED_FIELDS:
                if getattr(event, field) != getattr(registered, field):
                    raise RegistryError(
                        f"{label}: field {field!r} disagrees with the 'registered' event for "
                        f"experiment id {event.experiment_id!r}"
                    )
            if event.event_time_utc < seen[-1].event_time_utc:
                raise RegistryError(
                    f"{label}: event time precedes the previous event for experiment id "
                    f"{event.experiment_id!r}"
                )
        seen.append(event)


def read_registry(path: str | Path) -> tuple[ExperimentEvent, ...]:
    """Strictly read and validate the whole registry (empty = pristine)."""
    file = Path(path)
    if not file.exists():
        raise RegistryError(
            f"registry file {file} does not exist; create an empty registry file explicitly"
        )
    raw = file.read_bytes()
    if raw == b"":
        return ()
    if not raw.endswith(b"\n"):
        raise RegistryError(
            f"registry file {file.name!r} does not end with a newline — the final line is "
            "partial; treat the registry as contaminated"
        )
    events: list[ExperimentEvent] = []
    for position, line in enumerate(raw.split(b"\n")[:-1]):
        try:
            events.append(ExperimentEvent.from_json_line(line))
        except ValueError as exc:
            raise RegistryError(
                f"registry line {position + 1} is invalid ({exc}); treat the registry as "
                "contaminated"
            ) from exc
    result = tuple(events)
    _check_sequencing(result)
    return result


def append_registry_event(path: str | Path, event: ExperimentEvent) -> None:
    """Validate the whole registry, then append one event atomically."""
    existing = read_registry(path)
    _check_sequencing((*existing, event))
    line = event.to_json_line()
    descriptor = os.open(str(path), os.O_WRONLY | os.O_APPEND)
    try:
        written = os.write(descriptor, line)
        if written != len(line):
            raise RegistryError(
                f"short write appending to the registry ({written} of {len(line)} bytes)"
            )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
