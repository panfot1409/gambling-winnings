"""The append-only, hash-chained V2A research registry: proof of exactly one execution.

The registry (``research/v2a/research_registry.jsonl``) records the lifecycle of the single governed
research run as a tamper-evident hash chain. Its one job is to make "evaluated exactly once"
mechanical and irreversible:

* at most one ``started`` event may ever exist — a ``started`` consumes the one-shot budget even if
  the run later ``failed``; there is no second attempt, no repair, no reset;
* every entry is chained to the previous by SHA-256, so the log cannot be silently rewritten;
* ``completed`` binds the results fingerprint; ``failed`` records a reason.

Timestamps are supplied by the caller (never wall-clock here), so the chain is reproducible and the
module stays free of hidden nondeterminism.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from eth_research.v2.budget import MAX_RESEARCH_EXECUTIONS
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_choice,
    require_exact_keys,
    require_hex64,
    require_int,
    require_mapping,
    require_nonempty_str,
    require_slug,
    strict_json_loads,
)

REGISTRY_SCHEMA_VERSION: int = 1
GENESIS_PREV_HASH: str = "0" * 64

STARTED: str = "started"
COMPLETED: str = "completed"
FAILED: str = "failed"
EVENT_TYPES: frozenset[str] = frozenset({STARTED, COMPLETED, FAILED})


class RegistryError(V2ValidationError):
    """The registry chain, budget, or lifecycle was violated."""


@dataclass(frozen=True, slots=True)
class RegistryEvent:
    """One chained lifecycle event."""

    seq: int
    event: str
    run_id: str
    protocol_fingerprint: str
    timestamp: str
    payload: dict[str, object]
    prev_entry_hash: str
    entry_hash: str

    def _body(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "event": self.event,
            "run_id": self.run_id,
            "protocol_fingerprint": self.protocol_fingerprint,
            "timestamp": self.timestamp,
            "payload": dict(sorted(self.payload.items())),
            "prev_entry_hash": self.prev_entry_hash,
        }

    def recompute_hash(self) -> str:
        return canonical_sha256(self._body())

    def to_line(self) -> bytes:
        # One compact JSON object per line (JSONL). The hash is over the canonical ``_body()``, so
        # the on-disk line format is independent of the chained digest.
        record = {**self._body(), "entry_hash": self.entry_hash}
        text = json.dumps(
            record, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        return (text + "\n").encode("utf-8")


def _make_event(
    seq: int,
    event: str,
    run_id: str,
    protocol_fingerprint: str,
    timestamp: str,
    payload: dict[str, object],
    prev_entry_hash: str,
) -> RegistryEvent:
    partial = RegistryEvent(
        seq=seq,
        event=event,
        run_id=run_id,
        protocol_fingerprint=protocol_fingerprint,
        timestamp=timestamp,
        payload=payload,
        prev_entry_hash=prev_entry_hash,
        entry_hash="",
    )
    return RegistryEvent(
        seq=seq,
        event=event,
        run_id=run_id,
        protocol_fingerprint=protocol_fingerprint,
        timestamp=timestamp,
        payload=payload,
        prev_entry_hash=prev_entry_hash,
        entry_hash=partial.recompute_hash(),
    )


def read_events(path: str | Path) -> tuple[RegistryEvent, ...]:
    """Read + verify the registry chain (empty tuple if the file is absent or byte-empty)."""
    p = Path(path)
    if not p.exists():
        return ()
    raw = p.read_bytes()
    if raw == b"":
        return ()
    events: list[RegistryEvent] = []
    prev = GENESIS_PREV_HASH
    for i, line in enumerate(raw.splitlines()):
        obj = require_mapping(f"registry[{i}]", strict_json_loads(line))
        require_exact_keys(
            f"registry[{i}]",
            obj,
            frozenset(
                {
                    "seq",
                    "event",
                    "run_id",
                    "protocol_fingerprint",
                    "timestamp",
                    "payload",
                    "prev_entry_hash",
                    "entry_hash",
                }
            ),
        )
        event = RegistryEvent(
            seq=require_int(f"registry[{i}].seq", obj["seq"]),
            event=require_choice(f"registry[{i}].event", obj["event"], EVENT_TYPES),
            run_id=require_slug(f"registry[{i}].run_id", obj["run_id"]),
            protocol_fingerprint=require_hex64(
                f"registry[{i}].protocol_fingerprint", obj["protocol_fingerprint"]
            ),
            timestamp=require_nonempty_str(f"registry[{i}].timestamp", obj["timestamp"]),
            payload=require_mapping(f"registry[{i}].payload", obj["payload"]),
            prev_entry_hash=require_hex64(f"registry[{i}].prev_entry_hash", obj["prev_entry_hash"]),
            entry_hash=require_hex64(f"registry[{i}].entry_hash", obj["entry_hash"]),
        )
        if event.seq != i:
            raise RegistryError(f"registry[{i}] seq {event.seq} out of order")
        if event.prev_entry_hash != prev:
            raise RegistryError(f"registry[{i}] prev_entry_hash breaks the chain")
        if event.recompute_hash() != event.entry_hash:
            raise RegistryError(f"registry[{i}] entry_hash does not match its contents")
        events.append(event)
        prev = event.entry_hash

    _assert_budget(events)
    return tuple(events)


def _assert_budget(events: list[RegistryEvent]) -> None:
    started = sum(1 for e in events if e.event == STARTED)
    if started > MAX_RESEARCH_EXECUTIONS:
        raise RegistryError(
            f"{started} started events exceed the one-shot budget of {MAX_RESEARCH_EXECUTIONS}"
        )


def append_event(
    path: str | Path,
    event: str,
    run_id: str,
    *,
    protocol_fingerprint: str,
    timestamp: str,
    payload: dict[str, object] | None = None,
) -> RegistryEvent:
    """Append a chained event, enforcing the one-shot budget and lifecycle (append-only)."""
    require_choice("event", event, EVENT_TYPES)
    require_slug("run_id", run_id)
    require_hex64("protocol_fingerprint", protocol_fingerprint)
    require_nonempty_str("timestamp", timestamp)
    body = dict(payload or {})

    existing = read_events(path)
    if event == STARTED and any(e.event == STARTED for e in existing):
        raise RegistryError(
            "a started event already exists; the one-shot research budget is consumed"
        )
    if event in (COMPLETED, FAILED):
        if not any(e.event == STARTED and e.run_id == run_id for e in existing):
            raise RegistryError(f"cannot append {event!r} for run {run_id!r} with no started event")
        if any(e.event in (COMPLETED, FAILED) and e.run_id == run_id for e in existing):
            raise RegistryError(f"run {run_id!r} is already terminal")

    prev = existing[-1].entry_hash if existing else GENESIS_PREV_HASH
    entry = _make_event(len(existing), event, run_id, protocol_fingerprint, timestamp, body, prev)

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("ab") as fh:
        fh.write(entry.to_line())
    return entry


def verify_registry(path: str | Path) -> list[str]:
    """Return every registry problem as a string (empty == a sound, within-budget chain)."""
    try:
        read_events(path)
    except V2ValidationError as exc:
        return [str(exc)]
    return []


def started_run_ids(path: str | Path) -> tuple[str, ...]:
    return tuple(e.run_id for e in read_events(path) if e.event == STARTED)
