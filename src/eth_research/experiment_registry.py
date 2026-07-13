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

REGISTRY_SCHEMA_VERSION: int = 1
REGISTRY_SCHEMA_VERSION_V2: int = 2
SUPPORTED_REGISTRY_SCHEMA_VERSIONS: frozenset[int] = frozenset({1, 2})
EXPERIMENT_REGISTRY_RELPATH: str = "research/m3a/experiment_registry.jsonl"

# A v2 correction must name the machine-checkable kind of correction it makes.
# The closure run-003 corrects methodology and publication governance only — it
# does NOT change any strategy parameter — so this is the only permitted kind; a
# correction may never masquerade as a fresh scientific hypothesis.
CORRECTION_METHODOLOGY_GOVERNANCE: str = "methodology_and_publication_governance"
_CORRECTION_KINDS: frozenset[str] = frozenset({CORRECTION_METHODOLOGY_GOVERNANCE})

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


_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_M3A_PREFIX: str = "research/m3a/"
_EXPERIMENTS_PREFIX: str = "research/m3a/experiments/"


def _require_safe_relpath(label: str, value: object, *, prefix: str) -> str:
    """A clean repository-relative path strictly under ``prefix``.

    Rejects absolute paths, backslashes, NUL, empty/``.``/``..`` components,
    surrounding whitespace, unsafe component characters, and anything outside
    ``prefix`` — so a registry event can never point a result, report,
    protocol, or manifest at a foreign or traversed location. Duplicated (not
    imported from :mod:`eth_research.experiment_archive`) to avoid a circular
    import, since the archive imports the registry event types.
    """
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


_EVENT_KEYS_V2: frozenset[str] = frozenset(
    {
        "registry_schema_version",
        "event",
        "experiment_id",
        "experiment_family",
        "corrects_experiment_id",
        "correction_kind",
        "hypothesis",
        "strategies",
        "cost_scenarios",
        "methodology_id",
        "development_partition_sha256",
        "walk_forward_protocol_path",
        "walk_forward_protocol_sha256",
        "package_version",
        "registered_code_commit_sha",
        "execution_code_commit_sha",
        "execution_source_tree_fingerprint",
        "event_time_utc",
        "immutable_results_path",
        "immutable_report_path",
        "return_evidence_path",
        "artifact_manifest_path",
        "results_json_sha256",
        "report_markdown_sha256",
        "return_evidence_sha256",
        "result_bundle_sha256",
        "failure_description",
        "previous_event_sha256",
    }
)

# Fields that must stay byte-identical across an experiment id's lifecycle
# events (registered → started → completed|failed).
_SHARED_FIELDS_V2: tuple[str, ...] = (
    "experiment_family",
    "corrects_experiment_id",
    "correction_kind",
    "hypothesis",
    "strategies",
    "cost_scenarios",
    "methodology_id",
    "development_partition_sha256",
    "walk_forward_protocol_path",
    "walk_forward_protocol_sha256",
    "package_version",
    "registered_code_commit_sha",
    "execution_code_commit_sha",
    "execution_source_tree_fingerprint",
    "immutable_results_path",
    "immutable_report_path",
    "return_evidence_path",
    "artifact_manifest_path",
)

_RESULT_FIELDS_V2: tuple[str, ...] = (
    "results_json_sha256",
    "report_markdown_sha256",
    "return_evidence_sha256",
    "result_bundle_sha256",
)


@dataclass(frozen=True)
class ExperimentEventV2:
    """One registry-schema-v2 event; every field validated on construction.

    V2 extends v1 with the corrected-run provenance the closure requires:
    correction lineage, the exact cost scenarios and methodology identifier,
    the immutable artifact paths (results / report / return-evidence /
    manifest), the execution source-tree fingerprint, and an append-chain
    binding (``previous_event_sha256``) to the exact bytes of the preceding
    registry line — so v2 events cannot be reordered or detached from the
    immutable v1 prefix.
    """

    registry_schema_version: int
    event: str
    experiment_id: str
    experiment_family: str
    corrects_experiment_id: str | None
    correction_kind: str | None
    hypothesis: str
    strategies: tuple[str, ...]
    cost_scenarios: tuple[str, ...]
    methodology_id: str
    development_partition_sha256: str
    walk_forward_protocol_path: str
    walk_forward_protocol_sha256: str
    package_version: str
    registered_code_commit_sha: str
    execution_code_commit_sha: str
    execution_source_tree_fingerprint: str
    event_time_utc: pd.Timestamp
    immutable_results_path: str
    immutable_report_path: str
    return_evidence_path: str
    artifact_manifest_path: str
    results_json_sha256: str | None
    report_markdown_sha256: str | None
    return_evidence_sha256: str | None
    result_bundle_sha256: str | None
    failure_description: str | None
    previous_event_sha256: str

    def __post_init__(self) -> None:
        version = require_int("registry_schema_version", self.registry_schema_version)
        if version != REGISTRY_SCHEMA_VERSION_V2:
            raise ValueError(f"unsupported v2 registry schema version {version!r}")
        event = require_str("event", self.event)
        if event not in _EVENT_NAMES:
            raise ValueError(f"event must be one of {_EVENT_NAMES}, got {event!r}")
        require_evaluation_id("experiment_id", self.experiment_id)
        require_evaluation_id("experiment_family", self.experiment_family)
        if self.corrects_experiment_id is not None:
            require_evaluation_id("corrects_experiment_id", self.corrects_experiment_id)
            if self.corrects_experiment_id == self.experiment_id:
                raise ValueError("an experiment cannot correct itself")
            if self.correction_kind not in _CORRECTION_KINDS:
                raise ValueError(
                    f"correction_kind must be one of {sorted(_CORRECTION_KINDS)} when "
                    f"corrects_experiment_id is set, got {self.correction_kind!r}"
                )
        elif self.correction_kind is not None:
            raise ValueError("correction_kind must be null when corrects_experiment_id is null")
        require_nonempty_str("hypothesis", self.hypothesis)
        if not self.strategies or any(not isinstance(s, str) or not s for s in self.strategies):
            raise ValueError("strategies must be a non-empty tuple of non-empty strings")
        if not self.cost_scenarios or any(
            not isinstance(s, str) or not s for s in self.cost_scenarios
        ):
            raise ValueError("cost_scenarios must be a non-empty tuple of non-empty strings")
        require_nonempty_str("methodology_id", self.methodology_id)
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        _require_safe_relpath(
            "walk_forward_protocol_path", self.walk_forward_protocol_path, prefix=_M3A_PREFIX
        )
        require_hex64("walk_forward_protocol_sha256", self.walk_forward_protocol_sha256)
        require_nonempty_str("package_version", self.package_version)
        require_commit_sha("registered_code_commit_sha", self.registered_code_commit_sha)
        require_commit_sha("execution_code_commit_sha", self.execution_code_commit_sha)
        require_hex64("execution_source_tree_fingerprint", self.execution_source_tree_fingerprint)
        require_aware_timestamp("event_time_utc", self.event_time_utc)
        for label, value in (
            ("immutable_results_path", self.immutable_results_path),
            ("immutable_report_path", self.immutable_report_path),
            ("return_evidence_path", self.return_evidence_path),
            ("artifact_manifest_path", self.artifact_manifest_path),
        ):
            _require_safe_relpath(label, value, prefix=_EXPERIMENTS_PREFIX)
        if event == EVENT_COMPLETED:
            for label in _RESULT_FIELDS_V2:
                require_hex64(label, getattr(self, label))
        else:
            for label in _RESULT_FIELDS_V2:
                if getattr(self, label) is not None:
                    raise ValueError(f"{label} must be null on a {event!r} event")
        if event == EVENT_FAILED:
            require_nonempty_str("failure_description", self.failure_description)
        elif self.failure_description is not None:
            raise ValueError(f"failure_description must be null on a {event!r} event")
        require_hex64("previous_event_sha256", self.previous_event_sha256)

    def lifecycle_identity(self) -> dict[str, object]:
        """The fields that must stay constant across this id's events."""
        out: dict[str, object] = {}
        for field_name in _SHARED_FIELDS_V2:
            value = getattr(self, field_name)
            out[field_name] = tuple(value) if isinstance(value, tuple) else value
        return out

    def to_json_line(self) -> bytes:
        payload = {
            "registry_schema_version": self.registry_schema_version,
            "event": self.event,
            "experiment_id": self.experiment_id,
            "experiment_family": self.experiment_family,
            "corrects_experiment_id": self.corrects_experiment_id,
            "correction_kind": self.correction_kind,
            "hypothesis": self.hypothesis,
            "strategies": list(self.strategies),
            "cost_scenarios": list(self.cost_scenarios),
            "methodology_id": self.methodology_id,
            "development_partition_sha256": self.development_partition_sha256,
            "walk_forward_protocol_path": self.walk_forward_protocol_path,
            "walk_forward_protocol_sha256": self.walk_forward_protocol_sha256,
            "package_version": self.package_version,
            "registered_code_commit_sha": self.registered_code_commit_sha,
            "execution_code_commit_sha": self.execution_code_commit_sha,
            "execution_source_tree_fingerprint": self.execution_source_tree_fingerprint,
            "event_time_utc": self.event_time_utc.isoformat(),
            "immutable_results_path": self.immutable_results_path,
            "immutable_report_path": self.immutable_report_path,
            "return_evidence_path": self.return_evidence_path,
            "artifact_manifest_path": self.artifact_manifest_path,
            "results_json_sha256": self.results_json_sha256,
            "report_markdown_sha256": self.report_markdown_sha256,
            "return_evidence_sha256": self.return_evidence_sha256,
            "result_bundle_sha256": self.result_bundle_sha256,
            "failure_description": self.failure_description,
            "previous_event_sha256": self.previous_event_sha256,
        }
        text = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_line(cls, line: bytes) -> ExperimentEventV2:
        try:
            payload: Any = strict_json_loads(line)
        except StrictJSONError as exc:
            raise ValueError(f"registry line is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("registry line must be a JSON object")
        keys = set(payload)
        if keys != _EVENT_KEYS_V2:
            unknown = sorted(keys - _EVENT_KEYS_V2)
            missing = sorted(_EVENT_KEYS_V2 - keys)
            raise ValueError(
                f"registry v2 event keys do not match schema: unknown={unknown}, missing={missing}"
            )
        strategies = payload["strategies"]
        cost_scenarios = payload["cost_scenarios"]
        if not isinstance(strategies, list):
            raise ValueError("strategies must be a list")
        if not isinstance(cost_scenarios, list):
            raise ValueError("cost_scenarios must be a list")
        return cls(
            registry_schema_version=payload["registry_schema_version"],
            event=payload["event"],
            experiment_id=payload["experiment_id"],
            experiment_family=payload["experiment_family"],
            corrects_experiment_id=payload["corrects_experiment_id"],
            correction_kind=payload["correction_kind"],
            hypothesis=payload["hypothesis"],
            strategies=tuple(require_str("strategy", s) for s in strategies),
            cost_scenarios=tuple(require_str("cost_scenario", s) for s in cost_scenarios),
            methodology_id=payload["methodology_id"],
            development_partition_sha256=payload["development_partition_sha256"],
            walk_forward_protocol_path=payload["walk_forward_protocol_path"],
            walk_forward_protocol_sha256=payload["walk_forward_protocol_sha256"],
            package_version=payload["package_version"],
            registered_code_commit_sha=payload["registered_code_commit_sha"],
            execution_code_commit_sha=payload["execution_code_commit_sha"],
            execution_source_tree_fingerprint=payload["execution_source_tree_fingerprint"],
            event_time_utc=parse_timestamp_field("event_time_utc", payload["event_time_utc"]),
            immutable_results_path=payload["immutable_results_path"],
            immutable_report_path=payload["immutable_report_path"],
            return_evidence_path=payload["return_evidence_path"],
            artifact_manifest_path=payload["artifact_manifest_path"],
            results_json_sha256=payload["results_json_sha256"],
            report_markdown_sha256=payload["report_markdown_sha256"],
            return_evidence_sha256=payload["return_evidence_sha256"],
            result_bundle_sha256=payload["result_bundle_sha256"],
            failure_description=payload["failure_description"],
            previous_event_sha256=payload["previous_event_sha256"],
        )


RegistryEvent = ExperimentEvent | ExperimentEventV2


def _v1_lifecycle_identity(event: ExperimentEvent) -> dict[str, object]:
    out: dict[str, object] = {}
    for field_name in _SHARED_FIELDS:
        value = getattr(event, field_name)
        out[field_name] = tuple(value) if isinstance(value, tuple) else value
    return out


def _lifecycle_identity(event: RegistryEvent) -> dict[str, object]:
    if isinstance(event, ExperimentEventV2):
        return event.lifecycle_identity()
    return _v1_lifecycle_identity(event)


def _peek_schema_version(line: bytes) -> int:
    try:
        payload: Any = strict_json_loads(line)
    except StrictJSONError as exc:
        raise ValueError(f"registry line is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "registry_schema_version" not in payload:
        raise ValueError("registry line must be a JSON object with a registry_schema_version")
    version = payload["registry_schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(f"registry_schema_version must be an int, got {version!r}")
    if version not in SUPPORTED_REGISTRY_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported registry_schema_version {version!r}")
    return version


def parse_registry_line(line: bytes) -> RegistryEvent:
    """Version-dispatched strict parse of one registry line."""
    version = _peek_schema_version(line)
    if version == REGISTRY_SCHEMA_VERSION:
        return ExperimentEvent.from_json_line(line)
    return ExperimentEventV2.from_json_line(line)


def _check_sequencing(lines: tuple[tuple[bytes, RegistryEvent], ...]) -> None:
    """Validate the whole registry across schema versions.

    Each entry pairs a line's exact JSON bytes (no trailing newline) with its
    parsed event. Enforces: globally single-use experiment ids across v1 and
    v2; per-id lifecycle registered → started → completed|failed; shared
    lifecycle-identity fields constant across an id's events; non-decreasing
    per-id timestamps; the v2 append-chain (``previous_event_sha256`` equals
    the SHA-256 of the preceding line's exact JSON bytes); and correction
    lineage (a v2 correction must name an experiment already ``completed``).
    """
    history: dict[str, list[RegistryEvent]] = {}
    completed_ids: set[str] = set()
    for position, (_raw_line, event) in enumerate(lines):
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
            identity = _lifecycle_identity(event)
            registered_identity = _lifecycle_identity(seen[0])
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
        # V2 append-chain: bind this line to the exact bytes of the previous line.
        if isinstance(event, ExperimentEventV2):
            if position == 0:
                raise RegistryError(
                    f"{label}: a v2 event cannot be the first registry line; it must chain onto "
                    "the immutable v1 prefix"
                )
            expected = sha256_bytes(lines[position - 1][0])
            if event.previous_event_sha256 != expected:
                raise RegistryError(
                    f"{label}: previous_event_sha256 {event.previous_event_sha256[:12]} does not "
                    f"match the preceding line's hash {expected[:12]} — the append-chain is broken"
                )
            if (
                event.event == EVENT_REGISTERED
                and event.corrects_experiment_id is not None
                and event.corrects_experiment_id not in completed_ids
            ):
                raise RegistryError(
                    f"{label}: correction names {event.corrects_experiment_id!r}, which has no "
                    "prior 'completed' event in the registry"
                )
        if event.event == EVENT_COMPLETED:
            completed_ids.add(event.experiment_id)
        seen.append(event)


def _read_registry_lines(path: str | Path) -> tuple[tuple[bytes, RegistryEvent], ...]:
    """Parse every registry line (version-dispatched) with its exact bytes."""
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
    lines: list[tuple[bytes, RegistryEvent]] = []
    for position, line in enumerate(raw.split(b"\n")[:-1]):
        try:
            lines.append((line, parse_registry_line(line)))
        except ValueError as exc:
            raise RegistryError(
                f"registry line {position + 1} is invalid ({exc}); treat the registry as "
                "contaminated"
            ) from exc
    return tuple(lines)


def read_registry(path: str | Path) -> tuple[RegistryEvent, ...]:
    """Strictly read and validate the whole registry (empty = pristine)."""
    lines = _read_registry_lines(path)
    _check_sequencing(lines)
    return tuple(event for _, event in lines)


def latest_registry_line_sha256(path: str | Path) -> str | None:
    """SHA-256 of the last registry line's exact JSON bytes, or ``None`` if empty.

    A v2 event appended next must carry this value as ``previous_event_sha256``.
    """
    lines = _read_registry_lines(path)
    if not lines:
        return None
    return sha256_bytes(lines[-1][0])


def append_registry_event(path: str | Path, event: RegistryEvent) -> None:
    """Validate the whole registry, then append one event atomically."""
    lines = _read_registry_lines(path)
    _check_sequencing(lines)  # existing registry must be sound before appending
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
