"""V2C section 33: the append-only, hash-chained operational-qualification (OQ) registry.

Records the operational-qualification lifecycle as a hash-chained JSONL ledger with a one-shot
budget per protocol: at most one ``registered`` event (the qualification protocol identity is frozen
-- its fixture, fault-schedule, and criteria digests) and at most one ``qualified`` event (the
result), and a ``qualified`` event requires a prior ``registered`` for the same protocol. The chain
and budget are re-asserted on every read, so a tampered, reordered, or double-registered ledger
fails closed. The registry records *operational* qualification only; never a strategy result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from eth_research.m3d.validation import M3DValidationError
from eth_research.v2.strict import (
    canonical_sha256,
    require_bool,
    require_exact_keys,
    require_hex64,
    require_mapping,
    require_nonempty_str,
    require_nonnegative_int,
    require_slug,
    strict_json_loads,
)

#: The canonical committed location of the OQ registry (a byte-empty genesis ledger until OQ-R).
OQ_REGISTRY_PATH: str = "governance/v2c/oq_registry.jsonl"

#: The genesis predecessor hash for the first chained entry.
GENESIS_PREV_HASH: str = "0" * 64

OQ_EVENT_REGISTERED: str = "registered"
OQ_EVENT_QUALIFIED: str = "qualified"
_OQ_EVENTS: frozenset[str] = frozenset({OQ_EVENT_REGISTERED, OQ_EVENT_QUALIFIED})

_REGISTERED_PAYLOAD_KEYS = frozenset({"fixture_digest", "fault_schedule_digest", "criteria_digest"})
_QUALIFIED_PAYLOAD_KEYS = frozenset({"qualified", "result_digest"})
_LINE_KEYS = frozenset(
    {"seq", "event", "protocol_id", "package_version", "payload", "prev_hash", "entry_hash"}
)


class OQRegistryError(M3DValidationError):
    """The OQ registry chain, budget, or lifecycle was violated."""


def _validate_payload(event: str, payload: dict[str, object]) -> dict[str, object]:
    if event == OQ_EVENT_REGISTERED:
        require_exact_keys("oq_event.payload", payload, _REGISTERED_PAYLOAD_KEYS)
        return {
            "fixture_digest": require_hex64("payload.fixture_digest", payload["fixture_digest"]),
            "fault_schedule_digest": require_hex64(
                "payload.fault_schedule_digest", payload["fault_schedule_digest"]
            ),
            "criteria_digest": require_hex64("payload.criteria_digest", payload["criteria_digest"]),
        }
    require_exact_keys("oq_event.payload", payload, _QUALIFIED_PAYLOAD_KEYS)
    return {
        "qualified": require_bool("payload.qualified", payload["qualified"]),
        "result_digest": require_hex64("payload.result_digest", payload["result_digest"]),
    }


@dataclass(frozen=True, slots=True)
class OQEvent:
    """One chained operational-qualification lifecycle event."""

    seq: int
    event: str
    protocol_id: str
    package_version: str
    payload: dict[str, object]
    prev_hash: str
    entry_hash: str

    def _body(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "event": self.event,
            "protocol_id": self.protocol_id,
            "package_version": self.package_version,
            "payload": dict(sorted(self.payload.items())),
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


def build_oq_event(
    *,
    seq: int,
    event: str,
    protocol_id: str,
    package_version: str,
    payload: dict[str, object],
    prev_hash: str,
) -> OQEvent:
    """Build a chained OQ event, computing its entry hash over the canonical body."""
    if event not in _OQ_EVENTS:
        raise OQRegistryError(f"unknown OQ event {event!r}")
    clean_payload = _validate_payload(event, payload)
    partial = OQEvent(
        seq=require_nonnegative_int("oq_event.seq", seq),
        event=event,
        protocol_id=require_slug("oq_event.protocol_id", protocol_id),
        package_version=require_nonempty_str("oq_event.package_version", package_version),
        payload=clean_payload,
        prev_hash=require_hex64("oq_event.prev_hash", prev_hash),
        entry_hash="",
    )
    return OQEvent(
        seq=partial.seq,
        event=partial.event,
        protocol_id=partial.protocol_id,
        package_version=partial.package_version,
        payload=partial.payload,
        prev_hash=partial.prev_hash,
        entry_hash=partial.recompute_hash(),
    )


def _parse_line(index: int, line: bytes) -> OQEvent:
    obj = require_mapping(f"oq_registry[{index}]", strict_json_loads(line))
    require_exact_keys(f"oq_registry[{index}]", obj, _LINE_KEYS)
    event = require_nonempty_str(f"oq_registry[{index}].event", obj["event"])
    if event not in _OQ_EVENTS:
        raise OQRegistryError(f"oq_registry[{index}] has unknown event {event!r}")
    raw_payload = require_mapping(f"oq_registry[{index}].payload", obj["payload"])
    payload = _validate_payload(event, raw_payload)
    parsed = OQEvent(
        seq=require_nonnegative_int(f"oq_registry[{index}].seq", obj["seq"]),
        event=event,
        protocol_id=require_slug(f"oq_registry[{index}].protocol_id", obj["protocol_id"]),
        package_version=require_nonempty_str(
            f"oq_registry[{index}].package_version", obj["package_version"]
        ),
        payload=payload,
        prev_hash=require_hex64(f"oq_registry[{index}].prev_hash", obj["prev_hash"]),
        entry_hash=require_hex64(f"oq_registry[{index}].entry_hash", obj["entry_hash"]),
    )
    if parsed.recompute_hash() != parsed.entry_hash:
        raise OQRegistryError(f"oq_registry[{index}] entry_hash does not match its body")
    return parsed


def _assert_lifecycle(events: list[OQEvent]) -> None:
    registered: set[str] = set()
    qualified: set[str] = set()
    for index, event in enumerate(events):
        if event.seq != index:
            raise OQRegistryError(f"oq_registry[{index}] seq {event.seq} is out of order")
        if event.event == OQ_EVENT_REGISTERED:
            if event.protocol_id in registered:
                raise OQRegistryError(
                    f"protocol {event.protocol_id!r} registered more than once (one-shot budget)"
                )
            registered.add(event.protocol_id)
        else:  # qualified
            if event.protocol_id not in registered:
                raise OQRegistryError(
                    f"protocol {event.protocol_id!r} qualified with no prior registration"
                )
            if event.protocol_id in qualified:
                raise OQRegistryError(
                    f"protocol {event.protocol_id!r} qualified more than once (one-shot budget)"
                )
            qualified.add(event.protocol_id)


def read_oq_registry(path: str | Path) -> tuple[OQEvent, ...]:
    """Read + fully verify the OQ registry (chain, hashes, budget, lifecycle). Empty is valid."""
    file = Path(path)
    if not file.exists() or file.stat().st_size == 0:
        return ()
    events: list[OQEvent] = []
    prev = GENESIS_PREV_HASH
    for index, raw in enumerate(file.read_bytes().splitlines()):
        if not raw.strip():
            raise OQRegistryError(f"oq_registry[{index}] is a blank line")
        event = _parse_line(index, raw)
        if event.prev_hash != prev:
            raise OQRegistryError(f"oq_registry[{index}] prev_hash breaks the chain")
        prev = event.entry_hash
        events.append(event)
    _assert_lifecycle(events)
    return tuple(events)


def append_oq_event(
    path: str | Path,
    *,
    event: str,
    protocol_id: str,
    package_version: str,
    payload: dict[str, object],
) -> OQEvent:
    """Append a chained OQ event, re-verifying the ledger and enforcing the one-shot budget."""
    file = Path(path)
    existing = list(read_oq_registry(file))
    prev = existing[-1].entry_hash if existing else GENESIS_PREV_HASH
    new_event = build_oq_event(
        seq=len(existing),
        event=event,
        protocol_id=protocol_id,
        package_version=package_version,
        payload=payload,
        prev_hash=prev,
    )
    # Re-assert the whole lifecycle including the new event before writing (fail closed).
    _assert_lifecycle([*existing, new_event])
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("ab") as handle:
        handle.write(new_event.to_line())
    return new_event


def verify_oq_registry(path: str | Path) -> list[str]:
    """Return the list of OQ-registry problems (empty == OK); a byte-empty ledger is clean."""
    try:
        read_oq_registry(path)
    except (OQRegistryError, M3DValidationError, ValueError, TypeError) as exc:
        return [f"oq_registry: {exc}"]
    return []


__all__ = [
    "GENESIS_PREV_HASH",
    "OQ_EVENT_QUALIFIED",
    "OQ_EVENT_REGISTERED",
    "OQ_REGISTRY_PATH",
    "OQEvent",
    "OQRegistryError",
    "append_oq_event",
    "build_oq_event",
    "read_oq_registry",
    "verify_oq_registry",
]
