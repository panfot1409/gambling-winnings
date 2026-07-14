"""Append-only, hash-chained experiment registry for Milestone 3B (Phase 15).

Every fractional experiment — including a failure — is recorded here in an
append-only JSONL registry committed to version control, so the research history
is public and permanent. Unlike the two byte-empty sealed access ledgers, this
registry **does** carry the one preregistered fractional run's events.

Per experiment id the sequence is exactly ``registered`` → ``started`` →
(``completed`` | ``failed``):

* ``registered`` pre-registers the experiment (protocol / partition / dossier
  SHAs, hypothesis, exact strategy and cost-scenario sets, frozen commit) before
  any real computation;
* ``started`` is written before the real evaluation runs;
* ``completed`` carries the SHA-256 of the published results JSON, report
  Markdown, and result bundle — publication is verified before it is appended;
* ``failed`` carries an honest failure description.

Every line is bound to the exact bytes of the line before it through
``previous_event_sha256``; the first line chains onto the empty-content sentinel
:data:`EMPTY_CONTENT_SHA256` (the SHA-256 of zero bytes), so the whole file is a
single tamper-evident chain from line 1. Experiment ids are single-use, terminal
events must match the registration context, and a malformed or truncated line
blocks every further append. There is no repair or rewrite path — this is a
brand-new, single-schema registry, distinct from the Milestone 3A registry.
"""

from __future__ import annotations

import json
import os
import re
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
    sha256_bytes,
)
from eth_research.data.validation import (
    parse_timestamp_field,
    require_aware_timestamp,
    require_commit_sha,
    require_evaluation_id,
)

M3B_REGISTRY_SCHEMA_VERSION: int = 1
M3B_REGISTRY_RELPATH: str = "research/m3b/experiment_registry.jsonl"

# SHA-256 of zero bytes: the "previous" hash the first registry line chains onto,
# so the append-chain is well-defined from line 1 (the empty registry file has
# exactly this content hash).
EMPTY_CONTENT_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

EVENT_REGISTERED: str = "registered"
EVENT_STARTED: str = "started"
EVENT_COMPLETED: str = "completed"
EVENT_FAILED: str = "failed"
_EVENT_NAMES: frozenset[str] = frozenset(
    {EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED, EVENT_FAILED}
)

_RESULT_FIELDS: tuple[str, ...] = (
    "results_json_sha256",
    "report_markdown_sha256",
    "result_bundle_sha256",
)

_M3B_PREFIX: str = "research/m3b/"
_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")

_EVENT_KEYS: frozenset[str] = frozenset(
    {
        "registry_schema_version",
        "event",
        "experiment_id",
        "experiment_family",
        "hypothesis",
        "strategies",
        "cost_scenarios",
        "fractional_protocol_path",
        "fractional_protocol_sha256",
        "development_partition_sha256",
        "frozen_m2_dossier_sha256",
        "package_version",
        "registered_code_commit_sha",
        "execution_code_commit_sha",
        "execution_source_tree_fingerprint",
        "event_time_utc",
        "immutable_results_path",
        "immutable_report_path",
        "artifact_manifest_path",
        "results_json_sha256",
        "report_markdown_sha256",
        "result_bundle_sha256",
        "failure_description",
        "previous_event_sha256",
    }
)

# Fields that must stay byte-identical across every event of one experiment id;
# they are fixed at registration and can never drift on a later lifecycle event.
_SHARED_FIELDS: tuple[str, ...] = (
    "experiment_family",
    "hypothesis",
    "strategies",
    "cost_scenarios",
    "fractional_protocol_path",
    "fractional_protocol_sha256",
    "development_partition_sha256",
    "frozen_m2_dossier_sha256",
    "package_version",
    "registered_code_commit_sha",
    "execution_code_commit_sha",
    "execution_source_tree_fingerprint",
    "immutable_results_path",
    "immutable_report_path",
    "artifact_manifest_path",
)


class RegistryError(RuntimeError):
    """The fractional experiment registry is invalid or an append is illegal."""


def _require_safe_relpath(label: str, value: object, *, prefix: str) -> str:
    """A clean repository-relative path strictly under ``prefix``."""
    text = require_nonempty_str(label, value)
    if text != text.strip() or text.startswith("/") or "\\" in text or "\x00" in text:
        raise ValueError(f"{label} must be a clean relative path, got {text!r}")
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"{label} must have no empty or dot components, got {text!r}")
    if any(not _SAFE_PATH_COMPONENT.match(part) for part in parts):
        raise ValueError(f"{label} has an unsafe path component, got {text!r}")
    if not text.startswith(prefix):
        raise ValueError(f"{label} must live under {prefix!r}, got {text!r}")
    return text


@dataclass(frozen=True)
class FractionalRegistryEvent:
    """One hash-chained registry event; every field validated on construction."""

    registry_schema_version: int
    event: str
    experiment_id: str
    experiment_family: str
    hypothesis: str
    strategies: tuple[str, ...]
    cost_scenarios: tuple[str, ...]
    fractional_protocol_path: str
    fractional_protocol_sha256: str
    development_partition_sha256: str
    frozen_m2_dossier_sha256: str
    package_version: str
    registered_code_commit_sha: str
    execution_code_commit_sha: str
    execution_source_tree_fingerprint: str
    event_time_utc: pd.Timestamp
    immutable_results_path: str
    immutable_report_path: str
    artifact_manifest_path: str
    results_json_sha256: str | None
    report_markdown_sha256: str | None
    result_bundle_sha256: str | None
    failure_description: str | None
    previous_event_sha256: str

    def __post_init__(self) -> None:
        version = require_int("registry_schema_version", self.registry_schema_version)
        if version != M3B_REGISTRY_SCHEMA_VERSION:
            raise ValueError(f"unsupported registry schema version {version!r}")
        if self.event not in _EVENT_NAMES:
            raise ValueError(f"event must be one of {sorted(_EVENT_NAMES)}, got {self.event!r}")
        require_evaluation_id("experiment_id", self.experiment_id)
        require_evaluation_id("experiment_family", self.experiment_family)
        if not self.experiment_id.startswith(self.experiment_family):
            raise ValueError("experiment_id must belong to the experiment_family")
        require_nonempty_str("hypothesis", self.hypothesis)
        for label, names in (
            ("strategies", self.strategies),
            ("cost_scenarios", self.cost_scenarios),
        ):
            if not names or any(not isinstance(s, str) or not s for s in names):
                raise ValueError(f"{label} must be a non-empty tuple of non-empty strings")
        _require_safe_relpath(
            "fractional_protocol_path", self.fractional_protocol_path, prefix=_M3B_PREFIX
        )
        require_hex64("fractional_protocol_sha256", self.fractional_protocol_sha256)
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        require_hex64("frozen_m2_dossier_sha256", self.frozen_m2_dossier_sha256)
        require_nonempty_str("package_version", self.package_version)
        require_commit_sha("registered_code_commit_sha", self.registered_code_commit_sha)
        require_commit_sha("execution_code_commit_sha", self.execution_code_commit_sha)
        require_hex64("execution_source_tree_fingerprint", self.execution_source_tree_fingerprint)
        require_aware_timestamp("event_time_utc", self.event_time_utc)
        for label, value in (
            ("immutable_results_path", self.immutable_results_path),
            ("immutable_report_path", self.immutable_report_path),
            ("artifact_manifest_path", self.artifact_manifest_path),
        ):
            _require_safe_relpath(label, value, prefix=_M3B_PREFIX)
        if self.event == EVENT_COMPLETED:
            for label in _RESULT_FIELDS:
                require_hex64(label, getattr(self, label))
        else:
            for label in _RESULT_FIELDS:
                if getattr(self, label) is not None:
                    raise ValueError(f"{label} must be null on a {self.event!r} event")
        if self.event == EVENT_FAILED:
            require_nonempty_str("failure_description", self.failure_description)
        elif self.failure_description is not None:
            raise ValueError(f"failure_description must be null on a {self.event!r} event")
        require_hex64("previous_event_sha256", self.previous_event_sha256)

    def lifecycle_identity(self) -> dict[str, object]:
        """The fields that must stay constant across this id's events."""
        out: dict[str, object] = {}
        for field_name in _SHARED_FIELDS:
            value = getattr(self, field_name)
            out[field_name] = tuple(value) if isinstance(value, tuple) else value
        return out

    def to_json_line(self) -> bytes:
        payload = {
            "registry_schema_version": self.registry_schema_version,
            "event": self.event,
            "experiment_id": self.experiment_id,
            "experiment_family": self.experiment_family,
            "hypothesis": self.hypothesis,
            "strategies": list(self.strategies),
            "cost_scenarios": list(self.cost_scenarios),
            "fractional_protocol_path": self.fractional_protocol_path,
            "fractional_protocol_sha256": self.fractional_protocol_sha256,
            "development_partition_sha256": self.development_partition_sha256,
            "frozen_m2_dossier_sha256": self.frozen_m2_dossier_sha256,
            "package_version": self.package_version,
            "registered_code_commit_sha": self.registered_code_commit_sha,
            "execution_code_commit_sha": self.execution_code_commit_sha,
            "execution_source_tree_fingerprint": self.execution_source_tree_fingerprint,
            "event_time_utc": self.event_time_utc.isoformat(),
            "immutable_results_path": self.immutable_results_path,
            "immutable_report_path": self.immutable_report_path,
            "artifact_manifest_path": self.artifact_manifest_path,
            "results_json_sha256": self.results_json_sha256,
            "report_markdown_sha256": self.report_markdown_sha256,
            "result_bundle_sha256": self.result_bundle_sha256,
            "failure_description": self.failure_description,
            "previous_event_sha256": self.previous_event_sha256,
        }
        text = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_line(cls, line: bytes) -> FractionalRegistryEvent:
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
        for listy in ("strategies", "cost_scenarios"):
            if not isinstance(payload[listy], list):
                raise ValueError(f"{listy} must be a list")
        return cls(
            registry_schema_version=payload["registry_schema_version"],
            event=require_str("event", payload["event"]),
            experiment_id=payload["experiment_id"],
            experiment_family=payload["experiment_family"],
            hypothesis=payload["hypothesis"],
            strategies=tuple(require_str("strategy", s) for s in payload["strategies"]),
            cost_scenarios=tuple(
                require_str("cost_scenario", s) for s in payload["cost_scenarios"]
            ),
            fractional_protocol_path=payload["fractional_protocol_path"],
            fractional_protocol_sha256=payload["fractional_protocol_sha256"],
            development_partition_sha256=payload["development_partition_sha256"],
            frozen_m2_dossier_sha256=payload["frozen_m2_dossier_sha256"],
            package_version=payload["package_version"],
            registered_code_commit_sha=payload["registered_code_commit_sha"],
            execution_code_commit_sha=payload["execution_code_commit_sha"],
            execution_source_tree_fingerprint=payload["execution_source_tree_fingerprint"],
            event_time_utc=parse_timestamp_field("event_time_utc", payload["event_time_utc"]),
            immutable_results_path=payload["immutable_results_path"],
            immutable_report_path=payload["immutable_report_path"],
            artifact_manifest_path=payload["artifact_manifest_path"],
            results_json_sha256=payload["results_json_sha256"],
            report_markdown_sha256=payload["report_markdown_sha256"],
            result_bundle_sha256=payload["result_bundle_sha256"],
            failure_description=payload["failure_description"],
            previous_event_sha256=payload["previous_event_sha256"],
        )


def _check_sequencing(lines: tuple[tuple[bytes, FractionalRegistryEvent], ...]) -> None:
    """Validate the whole registry as a single hash-chained lifecycle log.

    Enforces: single-use experiment ids; per-id lifecycle
    ``registered`` → ``started`` → ``completed`` | ``failed``; shared
    lifecycle-identity fields constant across an id's events; non-decreasing
    per-id timestamps; and the append-chain — line 0 chains onto
    :data:`EMPTY_CONTENT_SHA256` and line ``i`` chains onto the SHA-256 of line
    ``i-1``'s exact JSON bytes.
    """
    history: dict[str, list[FractionalRegistryEvent]] = {}
    for position, (_raw_line, event) in enumerate(lines):
        label = f"registry line {position + 1}"
        expected_previous = (
            EMPTY_CONTENT_SHA256 if position == 0 else sha256_bytes(lines[position - 1][0])
        )
        if event.previous_event_sha256 != expected_previous:
            raise RegistryError(
                f"{label}: previous_event_sha256 {event.previous_event_sha256[:12]} does not match "
                f"the expected chain hash {expected_previous[:12]} — the append-chain is broken"
            )
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
            identity = event.lifecycle_identity()
            registered_identity = seen[0].lifecycle_identity()
            for field in identity:
                if identity[field] != registered_identity[field]:
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


def _read_registry_lines(path: str | Path) -> tuple[tuple[bytes, FractionalRegistryEvent], ...]:
    """Parse every registry line with its exact bytes (empty file = pristine)."""
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
    lines: list[tuple[bytes, FractionalRegistryEvent]] = []
    for position, line in enumerate(raw.split(b"\n")[:-1]):
        try:
            lines.append((line, FractionalRegistryEvent.from_json_line(line)))
        except ValueError as exc:
            raise RegistryError(
                f"registry line {position + 1} is invalid ({exc}); treat the registry as "
                "contaminated"
            ) from exc
    return tuple(lines)


def read_registry(path: str | Path) -> tuple[FractionalRegistryEvent, ...]:
    """Strictly read and validate the whole registry (empty = pristine)."""
    lines = _read_registry_lines(path)
    _check_sequencing(lines)
    return tuple(event for _, event in lines)


def latest_registry_line_sha256(path: str | Path) -> str:
    """SHA-256 of the last registry line's bytes, or the empty-content sentinel.

    The event appended next must carry this value as ``previous_event_sha256``,
    so a pristine (byte-empty) registry yields :data:`EMPTY_CONTENT_SHA256`.
    """
    lines = _read_registry_lines(path)
    if not lines:
        return EMPTY_CONTENT_SHA256
    return sha256_bytes(lines[-1][0])


def append_registry_event(path: str | Path, event: FractionalRegistryEvent) -> None:
    """Validate the whole registry, then append one event atomically."""
    lines = _read_registry_lines(path)
    _check_sequencing(lines)  # the existing registry must be sound before appending
    new_line = event.to_json_line()
    new_raw = new_line[:-1]  # exact JSON bytes, no trailing newline
    _check_sequencing((*lines, (new_raw, event)))
    descriptor = os.open(str(path), os.O_WRONLY | os.O_APPEND)
    try:
        written = os.write(descriptor, new_line)
        if written != len(new_line):
            raise RegistryError(
                f"short write appending to the registry ({written} of {len(new_line)} bytes)"
            )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
