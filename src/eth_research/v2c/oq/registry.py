"""V2C: the append-only, hash-chained operational-qualification (OQ) registry -- lifecycle v2.

Records the OQ lifecycle as a strict, hash-chained JSONL ledger with a one-shot budget per
qualification id:

    registered -> started -> completed
    registered -> started -> failed

``registered`` fixes the qualification identity (protocol, source-freeze, fixture, fault-schedule,
SLO-contract, cash-control, runtime, package version). ``started`` **permanently consumes** the
qualification id -- no rerun is possible afterward. Exactly one terminal event (``completed`` xor
``failed``) closes the qualification: ``completed`` carries the result/report/evidence/archive/
bundle hashes and a closed-vocabulary verdict; ``failed`` carries a bounded failure description and
no success hashes. Every event of one qualification carries byte-identical shared-identity fields; a
drift, reorder, duplicate, skipped ordinal, broken chain, or illegal transition fails closed on each
read. The registry records *operational* qualification only -- never a strategy or a financial
result. It is separate from every research-experiment registry and sealed-access ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from eth_research.m3d.validation import M3DValidationError
from eth_research.v2.strict import (
    canonical_sha256,
    require_choice,
    require_exact_keys,
    require_hex64,
    require_mapping,
    require_nonempty_str,
    require_nonnegative_int,
    require_slug,
    require_utc_timestamp,
    strict_json_loads,
)

#: The canonical committed location of the OQ registry (a byte-empty genesis ledger until OQ-R).
OQ_REGISTRY_PATH: str = "governance/v2c/oq_registry.jsonl"
OQ_REGISTRY_SCHEMA_VERSION: int = 2

#: The genesis predecessor hash for the first chained entry.
GENESIS_PREV_HASH: str = "0" * 64

OQ_EVENT_REGISTERED: str = "registered"
OQ_EVENT_STARTED: str = "started"
OQ_EVENT_COMPLETED: str = "completed"
OQ_EVENT_FAILED: str = "failed"
_OQ_EVENTS: frozenset[str] = frozenset(
    {OQ_EVENT_REGISTERED, OQ_EVENT_STARTED, OQ_EVENT_COMPLETED, OQ_EVENT_FAILED}
)
_TERMINAL_EVENTS: frozenset[str] = frozenset({OQ_EVENT_COMPLETED, OQ_EVENT_FAILED})

#: The closed verdict vocabulary a ``completed`` event may carry.
OQ_VERDICT_QUALIFIED: str = "qualified"
OQ_VERDICT_NOT_QUALIFIED: str = "not_qualified"
_COMPLETED_VERDICTS: frozenset[str] = frozenset({OQ_VERDICT_QUALIFIED, OQ_VERDICT_NOT_QUALIFIED})

#: Durability / denial-of-service bounds.
MAX_REGISTRY_LINE_BYTES: int = 8192
MAX_REGISTRY_BYTES: int = 1_048_576
MAX_FAILURE_DESCRIPTION_CHARS: int = 2000

#: Shared-identity fields -- byte-identical across every event of one qualification.
_SHARED_FIELDS: tuple[str, ...] = (
    "qualification_id",
    "methodology_id",
    "protocol_sha256",
    "source_freeze_id",
    "source_freeze_sha256",
    "fixture_sha256",
    "fault_schedule_sha256",
    "slo_contract_sha256",
    "cash_control_identity",
    "runtime_contract_sha256",
    "package_version",
)
_TERMINAL_HASH_FIELDS: tuple[str, ...] = (
    "result_sha256",
    "report_sha256",
    "evidence_sha256",
    "archive_manifest_sha256",
    "result_bundle_sha256",
)
_LINE_KEYS: frozenset[str] = frozenset(
    (
        "schema_version",
        *_SHARED_FIELDS,
        "event",
        "event_time_utc",
        "event_ordinal",
        "reason",
        *_TERMINAL_HASH_FIELDS,
        "verdict",
        "failure_description",
        "prev_hash",
        "entry_hash",
    )
)


class OQRegistryError(M3DValidationError):
    """The OQ registry chain, budget, lifecycle, or a state invariant was violated."""


def _require_utc_iso(label: str, value: object) -> str:
    if isinstance(value, pd.Timestamp):
        ts: object = value
    elif isinstance(value, str):
        try:
            ts = pd.Timestamp(value)
        except (ValueError, TypeError) as exc:
            raise OQRegistryError(f"{label} is not a valid ISO-8601 timestamp: {value!r}") from exc
    else:
        raise OQRegistryError(f"{label} must be a timestamp string, got {type(value).__name__}")
    try:
        return require_utc_timestamp(label, ts).isoformat()
    except (ValueError, TypeError) as exc:
        raise OQRegistryError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class QualificationIdentity:
    """The shared identity fixed at ``registered`` and repeated byte-identically on every event."""

    qualification_id: str
    methodology_id: str
    protocol_sha256: str
    source_freeze_id: str
    source_freeze_sha256: str
    fixture_sha256: str
    fault_schedule_sha256: str
    slo_contract_sha256: str
    cash_control_identity: str
    runtime_contract_sha256: str
    package_version: str

    def as_map(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in _SHARED_FIELDS}

    @staticmethod
    def parse(label: str, obj: dict[str, object]) -> QualificationIdentity:
        return QualificationIdentity(
            qualification_id=require_slug(f"{label}.qualification_id", obj["qualification_id"]),
            methodology_id=require_slug(f"{label}.methodology_id", obj["methodology_id"]),
            protocol_sha256=require_hex64(f"{label}.protocol_sha256", obj["protocol_sha256"]),
            source_freeze_id=require_nonempty_str(
                f"{label}.source_freeze_id", obj["source_freeze_id"]
            ),
            source_freeze_sha256=require_hex64(
                f"{label}.source_freeze_sha256", obj["source_freeze_sha256"]
            ),
            fixture_sha256=require_hex64(f"{label}.fixture_sha256", obj["fixture_sha256"]),
            fault_schedule_sha256=require_hex64(
                f"{label}.fault_schedule_sha256", obj["fault_schedule_sha256"]
            ),
            slo_contract_sha256=require_hex64(
                f"{label}.slo_contract_sha256", obj["slo_contract_sha256"]
            ),
            cash_control_identity=require_hex64(
                f"{label}.cash_control_identity", obj["cash_control_identity"]
            ),
            runtime_contract_sha256=require_hex64(
                f"{label}.runtime_contract_sha256", obj["runtime_contract_sha256"]
            ),
            package_version=require_nonempty_str(
                f"{label}.package_version", obj["package_version"]
            ),
        )


@dataclass(frozen=True, slots=True)
class OQEvent:
    """One chained OQ lifecycle event."""

    identity: QualificationIdentity
    event: str
    event_time_utc: str
    event_ordinal: int
    reason: str
    result_sha256: str | None
    report_sha256: str | None
    evidence_sha256: str | None
    archive_manifest_sha256: str | None
    result_bundle_sha256: str | None
    verdict: str | None
    failure_description: str | None
    prev_hash: str
    entry_hash: str

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": OQ_REGISTRY_SCHEMA_VERSION,
            **self.identity.as_map(),
            "event": self.event,
            "event_time_utc": self.event_time_utc,
            "event_ordinal": self.event_ordinal,
            "reason": self.reason,
            "result_sha256": self.result_sha256,
            "report_sha256": self.report_sha256,
            "evidence_sha256": self.evidence_sha256,
            "archive_manifest_sha256": self.archive_manifest_sha256,
            "result_bundle_sha256": self.result_bundle_sha256,
            "verdict": self.verdict,
            "failure_description": self.failure_description,
            "prev_hash": self.prev_hash,
        }

    def recompute_hash(self) -> str:
        return canonical_sha256(self._body())

    def to_line(self) -> bytes:
        record = {**self._body(), "entry_hash": self.entry_hash}
        text = json.dumps(
            record, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        return (text + "\n").encode("utf-8")


def _validate_event_shape(
    *,
    event: str,
    result_sha256: object,
    report_sha256: object,
    evidence_sha256: object,
    archive_manifest_sha256: object,
    result_bundle_sha256: object,
    verdict: object,
    failure_description: object,
    label: str,
) -> dict[str, str | None]:
    """Validate the event-specific fields for one lifecycle event, returning the cleaned values."""
    terminal_raw = {
        "result_sha256": result_sha256,
        "report_sha256": report_sha256,
        "evidence_sha256": evidence_sha256,
        "archive_manifest_sha256": archive_manifest_sha256,
        "result_bundle_sha256": result_bundle_sha256,
    }
    cleaned: dict[str, str | None] = {}
    if event == OQ_EVENT_COMPLETED:
        for key, raw in terminal_raw.items():
            cleaned[key] = require_hex64(f"{label}.{key}", raw)
        if failure_description is not None:
            raise OQRegistryError(f"{label} completed event must not carry a failure description")
        cleaned["failure_description"] = None
        cleaned["verdict"] = require_choice(f"{label}.verdict", verdict, _COMPLETED_VERDICTS)
        return cleaned
    if event == OQ_EVENT_FAILED:
        for key, raw in terminal_raw.items():
            if raw is not None:
                raise OQRegistryError(f"{label} failed event must not carry {key}")
            cleaned[key] = None
        if verdict is not None:
            raise OQRegistryError(f"{label} failed event must not carry a verdict")
        cleaned["verdict"] = None
        text = require_nonempty_str(f"{label}.failure_description", failure_description)
        if len(text) > MAX_FAILURE_DESCRIPTION_CHARS:
            raise OQRegistryError(f"{label} failure_description exceeds the size bound")
        cleaned["failure_description"] = text
        return cleaned
    # registered / started: no terminal hashes, no verdict, no failure description.
    for key, raw in terminal_raw.items():
        if raw is not None:
            raise OQRegistryError(f"{label} {event} event must not carry {key}")
        cleaned[key] = None
    if verdict is not None:
        raise OQRegistryError(f"{label} {event} event must not carry a verdict")
    if failure_description is not None:
        raise OQRegistryError(f"{label} {event} event must not carry a failure description")
    cleaned["verdict"] = None
    cleaned["failure_description"] = None
    return cleaned


def build_oq_event(
    *,
    identity: QualificationIdentity,
    event: str,
    event_time_utc: str,
    event_ordinal: int,
    reason: str,
    prev_hash: str,
    result_sha256: str | None = None,
    report_sha256: str | None = None,
    evidence_sha256: str | None = None,
    archive_manifest_sha256: str | None = None,
    result_bundle_sha256: str | None = None,
    verdict: str | None = None,
    failure_description: str | None = None,
) -> OQEvent:
    """Build a chained OQ event, validating its shape and computing its entry hash."""
    if event not in _OQ_EVENTS:
        raise OQRegistryError(f"unknown OQ event {event!r}")
    cleaned = _validate_event_shape(
        event=event,
        result_sha256=result_sha256,
        report_sha256=report_sha256,
        evidence_sha256=evidence_sha256,
        archive_manifest_sha256=archive_manifest_sha256,
        result_bundle_sha256=result_bundle_sha256,
        verdict=verdict,
        failure_description=failure_description,
        label="oq_event",
    )
    partial = OQEvent(
        identity=identity,
        event=event,
        event_time_utc=_require_utc_iso("oq_event.event_time_utc", event_time_utc),
        event_ordinal=require_nonnegative_int("oq_event.event_ordinal", event_ordinal),
        reason=require_nonempty_str("oq_event.reason", reason),
        result_sha256=cleaned["result_sha256"],
        report_sha256=cleaned["report_sha256"],
        evidence_sha256=cleaned["evidence_sha256"],
        archive_manifest_sha256=cleaned["archive_manifest_sha256"],
        result_bundle_sha256=cleaned["result_bundle_sha256"],
        verdict=cleaned["verdict"],
        failure_description=cleaned["failure_description"],
        prev_hash=require_hex64("oq_event.prev_hash", prev_hash),
        entry_hash="",
    )
    return replace(partial, entry_hash=partial.recompute_hash())


def _parse_line(index: int, line: bytes) -> OQEvent:
    if len(line) > MAX_REGISTRY_LINE_BYTES:
        raise OQRegistryError(f"oq_registry[{index}] exceeds the max line size")
    obj = require_mapping(f"oq_registry[{index}]", strict_json_loads(line))
    require_exact_keys(f"oq_registry[{index}]", obj, _LINE_KEYS)
    schema = require_nonnegative_int(f"oq_registry[{index}].schema_version", obj["schema_version"])
    if schema != OQ_REGISTRY_SCHEMA_VERSION:
        raise OQRegistryError(f"oq_registry[{index}] unknown schema_version {schema}")
    event = require_nonempty_str(f"oq_registry[{index}].event", obj["event"])
    if event not in _OQ_EVENTS:
        raise OQRegistryError(f"oq_registry[{index}] unknown event {event!r}")
    parsed = build_oq_event(
        identity=QualificationIdentity.parse(f"oq_registry[{index}]", obj),
        event=event,
        event_time_utc=obj["event_time_utc"],
        event_ordinal=obj["event_ordinal"],
        reason=obj["reason"],
        prev_hash=obj["prev_hash"],
        result_sha256=obj["result_sha256"],
        report_sha256=obj["report_sha256"],
        evidence_sha256=obj["evidence_sha256"],
        archive_manifest_sha256=obj["archive_manifest_sha256"],
        result_bundle_sha256=obj["result_bundle_sha256"],
        verdict=obj["verdict"],
        failure_description=obj["failure_description"],
    )
    committed = require_hex64(f"oq_registry[{index}].entry_hash", obj["entry_hash"])
    if parsed.entry_hash != committed:
        raise OQRegistryError(f"oq_registry[{index}] entry_hash does not match its body")
    return parsed


def _assert_lifecycle(events: list[OQEvent]) -> None:
    seen_registered: dict[str, QualificationIdentity] = {}
    started: set[str] = set()
    terminal: set[str] = set()
    for index, event in enumerate(events):
        qid = event.identity.qualification_id
        if event.event_ordinal != index:
            raise OQRegistryError(
                f"oq_registry[{index}] ordinal {event.event_ordinal} out of order"
            )
        if qid in terminal:
            raise OQRegistryError(f"oq_registry[{index}] event after {qid!r} reached a terminal")
        if event.event == OQ_EVENT_REGISTERED:
            if qid in seen_registered:
                raise OQRegistryError(f"oq_registry[{index}] {qid!r} registered more than once")
            seen_registered[qid] = event.identity
            continue
        if qid not in seen_registered:
            raise OQRegistryError(f"oq_registry[{index}] {event.event} before {qid!r} registered")
        if event.identity != seen_registered[qid]:
            raise OQRegistryError(f"oq_registry[{index}] shared identity drifted for {qid!r}")
        if event.event == OQ_EVENT_STARTED:
            if qid in started:
                raise OQRegistryError(f"oq_registry[{index}] {qid!r} started more than once")
            started.add(qid)
        else:  # completed or failed
            if qid not in started:
                raise OQRegistryError(f"oq_registry[{index}] {event.event} before {qid!r} started")
            terminal.add(qid)


def read_oq_registry(path: str | Path) -> tuple[OQEvent, ...]:
    """Read + fully verify the OQ registry (chain, hashes, budget, lifecycle). Empty is valid."""
    file = Path(path)
    if file.is_symlink():
        raise OQRegistryError("the OQ registry must not be a symlink")
    if not file.exists() or file.stat().st_size == 0:
        return ()
    raw = file.read_bytes()
    if len(raw) > MAX_REGISTRY_BYTES:
        raise OQRegistryError("the OQ registry exceeds the max size")
    events: list[OQEvent] = []
    prev = GENESIS_PREV_HASH
    for index, line in enumerate(raw.splitlines()):
        if not line.strip():
            raise OQRegistryError(f"oq_registry[{index}] is a blank line")
        event = _parse_line(index, line)
        if event.prev_hash != prev:
            raise OQRegistryError(f"oq_registry[{index}] prev_hash breaks the chain")
        prev = event.entry_hash
        events.append(event)
    _assert_lifecycle(events)
    return tuple(events)


def append_oq_event(
    path: str | Path,
    *,
    identity: QualificationIdentity,
    event: str,
    event_time_utc: str,
    reason: str,
    result_sha256: str | None = None,
    report_sha256: str | None = None,
    evidence_sha256: str | None = None,
    archive_manifest_sha256: str | None = None,
    result_bundle_sha256: str | None = None,
    verdict: str | None = None,
    failure_description: str | None = None,
) -> OQEvent:
    """Append a chained OQ event with durable append semantics, re-verifying the whole ledger."""
    file = Path(path)
    existing = list(read_oq_registry(file))
    prev = existing[-1].entry_hash if existing else GENESIS_PREV_HASH
    new_event = build_oq_event(
        identity=identity,
        event=event,
        event_time_utc=event_time_utc,
        event_ordinal=len(existing),
        reason=reason,
        prev_hash=prev,
        result_sha256=result_sha256,
        report_sha256=report_sha256,
        evidence_sha256=evidence_sha256,
        archive_manifest_sha256=archive_manifest_sha256,
        result_bundle_sha256=result_bundle_sha256,
        verdict=verdict,
        failure_description=failure_description,
    )
    _assert_lifecycle([*existing, new_event])
    line = new_event.to_line()
    if len(line) > MAX_REGISTRY_LINE_BYTES:
        raise OQRegistryError("the new OQ event exceeds the max line size")
    file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    return new_event


def verify_oq_registry(path: str | Path) -> list[str]:
    """Return the list of OQ-registry problems (empty == OK); a byte-empty ledger is clean."""
    try:
        read_oq_registry(path)
    except (OQRegistryError, M3DValidationError, ValueError, TypeError) as exc:
        return [f"oq_registry: {exc}"]
    return []


def registry_state(path: str | Path) -> str:
    """The lifecycle state of the single-qualification registry (pristine/registered/…)."""
    events = read_oq_registry(path)
    if not events:
        return "pristine"
    last = events[-1].event
    return {OQ_EVENT_REGISTERED: "registered", OQ_EVENT_STARTED: "started"}.get(last, last)


def sha256_bytes(payload: bytes) -> str:
    """SHA-256 of raw bytes (a small local helper for callers computing artifact digests)."""
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "GENESIS_PREV_HASH",
    "MAX_FAILURE_DESCRIPTION_CHARS",
    "MAX_REGISTRY_BYTES",
    "MAX_REGISTRY_LINE_BYTES",
    "OQ_EVENT_COMPLETED",
    "OQ_EVENT_FAILED",
    "OQ_EVENT_REGISTERED",
    "OQ_EVENT_STARTED",
    "OQ_REGISTRY_PATH",
    "OQ_REGISTRY_SCHEMA_VERSION",
    "OQ_VERDICT_NOT_QUALIFIED",
    "OQ_VERDICT_QUALIFIED",
    "OQEvent",
    "OQRegistryError",
    "QualificationIdentity",
    "append_oq_event",
    "build_oq_event",
    "read_oq_registry",
    "registry_state",
    "sha256_bytes",
    "verify_oq_registry",
]
