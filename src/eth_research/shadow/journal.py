"""The append-only, hash-chained shadow-run journal: the run's tamper-evident audit trail.

Every material step of a shadow run — a bar observed, a signal emitted, a risk decision, a
kill-switch trip or reset, a paper fill, an alert, a checkpoint, completion — is appended as a
chained event. Each entry commits to the previous entry's hash, so the journal cannot be silently
reordered or edited: a single changed byte breaks the chain at :func:`parse`.

Timestamps are the run's own as-of stamps (never wall-clock), so the journal is deterministic and a
re-run produces a byte-identical chain. The journal is the single source of truth a checkpoint or a
monitor reads from.

``EVENT_TYPES`` is the full accepted vocabulary. The single-pass :func:`run_shadow` runner emits a
subset of it; ``KILL_RESET`` (an operator clearing the latch) and ``CHECKPOINT_WRITTEN`` (an
out-of-band checkpoint stamp) are part of the schema so a journal from a longer-lived operator loop
parses under the same rules, but this package's runner never trips those two paths itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from eth_research.shadow.domain import ShadowDomainError, canonical_timestamp
from eth_research.v2.strict import (
    canonical_sha256,
    require_choice,
    require_exact_keys,
    require_hex64,
    require_int,
    require_mapping,
    strict_json_loads,
)

JOURNAL_SCHEMA_VERSION: int = 1
GENESIS_PREV_HASH: str = "0" * 64

RUN_STARTED: str = "run_started"
BAR_OBSERVED: str = "bar_observed"
SIGNAL_EMITTED: str = "signal_emitted"
RISK_DECIDED: str = "risk_decided"
KILL_TRIPPED: str = "kill_tripped"
KILL_RESET: str = "kill_reset"
FILL_RECORDED: str = "fill_recorded"
ALERT_RAISED: str = "alert_raised"
CHECKPOINT_WRITTEN: str = "checkpoint_written"
RUN_COMPLETED: str = "run_completed"

EVENT_TYPES: frozenset[str] = frozenset(
    {
        RUN_STARTED,
        BAR_OBSERVED,
        SIGNAL_EMITTED,
        RISK_DECIDED,
        KILL_TRIPPED,
        KILL_RESET,
        FILL_RECORDED,
        ALERT_RAISED,
        CHECKPOINT_WRITTEN,
        RUN_COMPLETED,
    }
)

_EVENT_KEYS = frozenset({"seq", "event_type", "as_of", "payload", "prev_hash", "entry_hash"})


class JournalError(ShadowDomainError):
    """The journal chain, ordering, or an entry's contents were invalid."""


@dataclass(frozen=True, slots=True)
class JournalEvent:
    """One chained journal entry."""

    seq: int
    event_type: str
    as_of: str
    payload: dict[str, object]
    prev_hash: str
    entry_hash: str

    def _body(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "event_type": self.event_type,
            "as_of": self.as_of,
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


def _make_event(
    seq: int, event_type: str, as_of: str, payload: dict[str, object], prev_hash: str
) -> JournalEvent:
    partial = JournalEvent(
        seq=seq,
        event_type=event_type,
        as_of=as_of,
        payload=payload,
        prev_hash=prev_hash,
        entry_hash="",
    )
    return JournalEvent(
        seq=seq,
        event_type=event_type,
        as_of=as_of,
        payload=payload,
        prev_hash=prev_hash,
        entry_hash=partial.recompute_hash(),
    )


@dataclass(slots=True)
class ShadowJournal:
    """An in-memory append-only chain that serializes to (and verifies from) JSONL bytes."""

    _events: list[JournalEvent]

    @staticmethod
    def empty() -> ShadowJournal:
        return ShadowJournal(_events=[])

    @property
    def events(self) -> tuple[JournalEvent, ...]:
        return tuple(self._events)

    @property
    def head_hash(self) -> str:
        return self._events[-1].entry_hash if self._events else GENESIS_PREV_HASH

    def append(
        self, event_type: str, *, as_of: object, payload: dict[str, object] | None = None
    ) -> JournalEvent:
        require_choice("event_type", event_type, EVENT_TYPES)
        stamp = canonical_timestamp("as_of", as_of)
        event = _make_event(
            len(self._events), event_type, stamp, dict(payload or {}), self.head_hash
        )
        self._events.append(event)
        return event

    def to_jsonl_bytes(self) -> bytes:
        return b"".join(event.to_line() for event in self._events)

    @staticmethod
    def parse(raw: bytes) -> ShadowJournal:
        """Decode + verify a JSONL journal (empty bytes -> empty journal)."""
        events: list[JournalEvent] = []
        prev = GENESIS_PREV_HASH
        if raw != b"":
            for i, line in enumerate(raw.splitlines()):
                obj = require_mapping(f"journal[{i}]", strict_json_loads(line))
                require_exact_keys(f"journal[{i}]", obj, _EVENT_KEYS)
                event = JournalEvent(
                    seq=require_int(f"journal[{i}].seq", obj["seq"]),
                    event_type=require_choice(
                        f"journal[{i}].event_type", obj["event_type"], EVENT_TYPES
                    ),
                    as_of=canonical_timestamp(f"journal[{i}].as_of", obj["as_of"]),
                    payload=require_mapping(f"journal[{i}].payload", obj["payload"]),
                    prev_hash=require_hex64(f"journal[{i}].prev_hash", obj["prev_hash"]),
                    entry_hash=require_hex64(f"journal[{i}].entry_hash", obj["entry_hash"]),
                )
                if event.seq != i:
                    raise JournalError(f"journal[{i}] seq {event.seq} out of order")
                if event.prev_hash != prev:
                    raise JournalError(f"journal[{i}] prev_hash breaks the chain")
                if event.recompute_hash() != event.entry_hash:
                    raise JournalError(f"journal[{i}] entry_hash does not match its contents")
                events.append(event)
                prev = event.entry_hash
        return ShadowJournal(_events=events)
