"""V2B §23 — the fresh V2B one-shot budget, protocol identity, and append-only registry chain.

The lifecycle is ``registered -> started -> completed|failed``: **R** appends exactly one
``registered`` event (governance only, no research); **P** appends ``started`` — which permanently
consumes the one-shot budget even if the run later ``failed`` — then a single terminal. The registry
reuses the accepted V2A chained-event serialization and hashing
(:class:`eth_research.v2.registry.RegistryEvent`) and the accepted one-shot budget
(:class:`eth_research.v2.budget.OneShotResearchBudget`) unchanged; V2B only adds the ``registered``
precursor state the V2A vocabulary lacks, plus its own append/read/verify for that lifecycle — the
per-line reader applies the *same* strict field validation as the accepted reader (exact key set,
``require_hex64`` fingerprint/hashes, choice-checked event, mapping payload), not a looser parse.
Appends are serialized behind an exclusive advisory lock and fsync'd, so two cannot both ``start``.

Every event references the frozen ``protocol_fingerprint`` — the combined identity binding the
candidate source freeze, the aligned partition, the execution scenarios, the fold structure, the
nomination rule, and the cumulative multiplicity state — so a registry entry cannot silently belong
to a different research design.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO, Any

from eth_research.v2.budget import OneShotResearchBudget, parse_budget
from eth_research.v2.registry import GENESIS_PREV_HASH, RegistryEvent
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    require_choice,
    require_exact_keys,
    require_hex64,
    require_int,
    require_mapping,
    require_nonempty_str,
    require_slug,
    sha256_bytes,
    strict_json_loads,
)
from eth_research.v2b.candidate_source_freeze import CANDIDATE_SOURCE_FREEZE_RELPATH
from eth_research.v2b.folds import OOS_FOLD_COUNT, WARMUP_ROWS
from eth_research.v2b.multiplicity import MULTIPLICITY_STATE_RELPATH
from eth_research.v2b.nomination import NOMINATION_SCHEMA_VERSION, TIE_BEHAVIOR
from eth_research.v2b.partition import JOINT_PARTITION_IDENTITY_RELPATH
from eth_research.v2b.scenarios import EXECUTION_SCENARIOS_RELPATH

try:  # pragma: no cover - platform dependent
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None  # type: ignore[assignment]

GOVERNANCE_SCHEMA_VERSION: int = 1
V2B_REGISTRY_RELPATH: str = "research/v2b/v2b_research_registry.jsonl"
V2B_BUDGET_RELPATH: str = "research/v2b/v2b_one_shot_budget.json"
V2B_PROTOCOL_RELPATH: str = "research/v2b/v2b_research_protocol.json"

REGISTERED: str = "registered"
STARTED: str = "started"
COMPLETED: str = "completed"
FAILED: str = "failed"
EVENT_TYPES: frozenset[str] = frozenset({REGISTERED, STARTED, COMPLETED, FAILED})
MAX_REGISTERED: int = 1
MAX_STARTED: int = 1


class V2BGovernanceError(V2ValidationError):
    """The V2B budget, protocol identity, or registry chain/lifecycle was violated."""


# --------------------------------------------------------------------------- #
# one-shot budget (reused, re-asserted)                                         #
# --------------------------------------------------------------------------- #
def build_budget_bytes() -> bytes:
    return canonical_json_bytes(OneShotResearchBudget.current().to_canonical())


def verify_budget(repo_root: str | Path) -> None:
    """The committed budget reproduces and re-asserts the fixed one-shot discipline."""
    raw = (Path(repo_root) / V2B_BUDGET_RELPATH).read_bytes()
    if raw != build_budget_bytes():
        raise V2BGovernanceError("committed v2b budget does not reproduce")
    parse_budget(strict_json_loads(raw))  # re-assert the fixed discipline (raises on drift)


# --------------------------------------------------------------------------- #
# protocol identity (binds the whole frozen research design)                    #
# --------------------------------------------------------------------------- #
def _file_sha256(repo_root: Path, relpath: str) -> str:
    try:
        return sha256_bytes((repo_root / relpath).read_bytes())
    except OSError as exc:
        raise V2BGovernanceError(f"{relpath}: unreadable ({exc})") from exc


def build_protocol_identity(repo_root: str | Path) -> dict[str, Any]:
    """The frozen, byte-reproducible V2B research-protocol identity (from committed artifacts only).

    Each frozen input is bound by the SHA-256 of its committed canonical bytes, so any change to the
    candidate freeze, partition, scenarios, or cumulative multiplicity state changes the protocol
    fingerprint and separates the registry from the altered design.
    """
    root = Path(repo_root)
    components = {
        "candidate_source_freeze_sha256": _file_sha256(root, CANDIDATE_SOURCE_FREEZE_RELPATH),
        "joint_partition_identity_sha256": _file_sha256(root, JOINT_PARTITION_IDENTITY_RELPATH),
        "execution_scenarios_sha256": _file_sha256(root, EXECUTION_SCENARIOS_RELPATH),
        "multiplicity_state_sha256": _file_sha256(root, MULTIPLICITY_STATE_RELPATH),
        "fold_structure": {"warmup_rows": WARMUP_ROWS, "oos_fold_count": OOS_FOLD_COUNT},
        "nomination": {"schema_version": NOMINATION_SCHEMA_VERSION, "tie_behavior": TIE_BEHAVIOR},
    }
    identity = {
        "schema_version": GOVERNANCE_SCHEMA_VERSION,
        "kind": "v2b_research_protocol_identity",
        "components": components,
    }
    identity["protocol_fingerprint"] = canonical_sha256(components)
    return identity


def render_protocol_identity_bytes(repo_root: str | Path) -> bytes:
    return canonical_json_bytes(build_protocol_identity(repo_root))


def protocol_fingerprint(repo_root: str | Path) -> str:
    fp = build_protocol_identity(repo_root)["protocol_fingerprint"]
    assert isinstance(fp, str)
    return fp


def verify_protocol_identity(repo_root: str | Path) -> None:
    committed = (Path(repo_root) / V2B_PROTOCOL_RELPATH).read_bytes()
    if committed != render_protocol_identity_bytes(repo_root):
        raise V2BGovernanceError("committed v2b protocol identity does not reproduce")


# --------------------------------------------------------------------------- #
# append-only, hash-chained registry (registered -> started -> terminal)        #
# --------------------------------------------------------------------------- #
_EVENT_KEYS: frozenset[str] = frozenset(
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
)


def _from_line(line: bytes, seq: int) -> RegistryEvent:
    # Mirror the accepted V2A reader's strictness exactly (:func:`eth_research.v2.registry.
    # read_events`): an exact key set, integer ``seq``, choice-checked ``event`` (over the V2B
    # vocabulary that adds ``registered``), slug ``run_id``, 64-hex ``protocol_fingerprint`` and
    # both chain hashes, a non-empty ``timestamp``, and a mapping ``payload`` — never a coerced
    # ``str(...)`` or a silently-emptied non-dict payload, which would let a forged line parse.
    obj = require_mapping(f"registry[{seq}]", strict_json_loads(line))
    require_exact_keys(f"registry[{seq}]", obj, _EVENT_KEYS)
    event = RegistryEvent(
        seq=require_int(f"registry[{seq}].seq", obj["seq"]),
        event=require_choice(f"registry[{seq}].event", obj["event"], EVENT_TYPES),
        run_id=require_slug(f"registry[{seq}].run_id", obj["run_id"]),
        protocol_fingerprint=require_hex64(
            f"registry[{seq}].protocol_fingerprint", obj["protocol_fingerprint"]
        ),
        timestamp=require_nonempty_str(f"registry[{seq}].timestamp", obj["timestamp"]),
        payload=require_mapping(f"registry[{seq}].payload", obj["payload"]),
        prev_entry_hash=require_hex64(f"registry[{seq}].prev_entry_hash", obj["prev_entry_hash"]),
        entry_hash=require_hex64(f"registry[{seq}].entry_hash", obj["entry_hash"]),
    )
    if event.recompute_hash() != event.entry_hash:
        raise V2BGovernanceError(f"registry[{seq}]: entry_hash does not match its body")
    return event


def read_events(path: str | Path) -> tuple[RegistryEvent, ...]:
    """Read and fully verify the V2B registry chain (empty if the file is absent or byte-empty)."""
    p = Path(path)
    if not p.exists():
        return ()
    raw = p.read_bytes()
    if not raw.strip():
        return ()
    events: list[RegistryEvent] = []
    prev = GENESIS_PREV_HASH
    for i, line in enumerate(raw.splitlines()):
        if not line.strip():
            raise V2BGovernanceError(f"registry[{i}]: blank line")
        event = _from_line(line, i)
        if event.seq != i:
            raise V2BGovernanceError(f"registry[{i}]: seq {event.seq} out of order")
        if event.prev_entry_hash != prev:
            raise V2BGovernanceError(f"registry[{i}]: prev_entry_hash breaks the chain")
        events.append(event)
        prev = event.entry_hash
    _assert_lifecycle(events)
    return tuple(events)


def _assert_lifecycle(events: list[RegistryEvent]) -> None:
    registered = sum(1 for e in events if e.event == REGISTERED)
    started = sum(1 for e in events if e.event == STARTED)
    if registered > MAX_REGISTERED:
        raise V2BGovernanceError(f"{registered} registered events exceed the maximum of 1")
    if started > MAX_STARTED:
        raise V2BGovernanceError(f"{started} started events exceed the one-shot budget of 1")
    registered_runs: set[str] = set()
    started_runs: set[str] = set()
    terminal_runs: set[str] = set()
    for event in events:
        if event.event == REGISTERED:
            registered_runs.add(event.run_id)
        elif event.event == STARTED:
            if event.run_id not in registered_runs:
                raise V2BGovernanceError(f"started run {event.run_id!r} has no prior registered")
            started_runs.add(event.run_id)
        elif event.event in (COMPLETED, FAILED):
            if event.run_id not in started_runs:
                raise V2BGovernanceError(f"{event.event} run {event.run_id!r} has no prior started")
            if event.run_id in terminal_runs:
                raise V2BGovernanceError(f"run {event.run_id!r} has more than one terminal event")
            terminal_runs.add(event.run_id)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[IO[bytes]]:
    fh = path.open("ab")
    try:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield fh
    finally:
        with suppress(OSError):  # pragma: no cover - best effort
            fh.flush()
            os.fsync(fh.fileno())
        if fcntl is not None:  # pragma: no cover
            with suppress(OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def append_event(
    path: str | Path,
    event: str,
    run_id: str,
    *,
    protocol_fingerprint: str,
    timestamp: str,
    payload: dict[str, object] | None = None,
) -> RegistryEvent:
    """Append a chained V2B event under an exclusive lock (enforces lifecycle + one-shot budget)."""
    if event not in EVENT_TYPES:
        raise V2BGovernanceError(f"unknown event {event!r}")
    require_slug("run_id", run_id)
    # A registry event may only carry a 64-hex protocol fingerprint and a non-empty timestamp, so a
    # written event can never round-trip through the strict reader as malformed (accepted-writer
    # parity).
    require_hex64("protocol_fingerprint", protocol_fingerprint)
    require_nonempty_str("timestamp", timestamp)
    body = dict(payload or {})
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(p) as fh:
        existing = read_events(p)
        _guard_append(existing, event, run_id)
        prev = existing[-1].entry_hash if existing else GENESIS_PREV_HASH
        partial = RegistryEvent(
            seq=len(existing),
            event=event,
            run_id=run_id,
            protocol_fingerprint=protocol_fingerprint,
            timestamp=timestamp,
            payload=body,
            prev_entry_hash=prev,
            entry_hash="",
        )
        entry = RegistryEvent(
            seq=partial.seq,
            event=event,
            run_id=run_id,
            protocol_fingerprint=protocol_fingerprint,
            timestamp=timestamp,
            payload=body,
            prev_entry_hash=prev,
            entry_hash=partial.recompute_hash(),
        )
        fh.write(entry.to_line())
    return entry


def _guard_append(existing: tuple[RegistryEvent, ...], event: str, run_id: str) -> None:
    if event == REGISTERED and any(e.event == REGISTERED for e in existing):
        raise V2BGovernanceError("a registered event already exists")
    if event == STARTED:
        if any(e.event == STARTED for e in existing):
            raise V2BGovernanceError("a started event already exists; the one-shot budget is spent")
        if not any(e.event == REGISTERED and e.run_id == run_id for e in existing):
            raise V2BGovernanceError(f"cannot start run {run_id!r} with no prior registered event")
    if event in (COMPLETED, FAILED):
        if not any(e.event == STARTED and e.run_id == run_id for e in existing):
            raise V2BGovernanceError(f"cannot append {event!r} for run {run_id!r} with no started")
        if any(e.event in (COMPLETED, FAILED) and e.run_id == run_id for e in existing):
            raise V2BGovernanceError(f"run {run_id!r} is already terminal")


def verify_registry(path: str | Path) -> list[str]:
    """Return every registry problem as a string (empty == a sound, within-lifecycle chain)."""
    try:
        read_events(path)
    except V2ValidationError as exc:
        return [str(exc)]
    return []


def verify_registry_bound(repo_root: str | Path) -> list[str]:
    """Every registry event must carry *this* committed protocol fingerprint (empty == bound).

    On top of :func:`verify_registry` (chain integrity + lifecycle), this binds the ledger to the
    frozen design: an event whose ``protocol_fingerprint`` differs from the committed protocol
    identity means the ledger belongs to a different — or since-altered — research design, so a
    registration can never be silently reused under a mutated protocol. An empty registry is
    vacuously bound.
    """
    root = Path(repo_root)
    registry_path = root / V2B_REGISTRY_RELPATH
    problems = verify_registry(registry_path)
    if problems:
        return problems
    try:
        expected = protocol_fingerprint(root)
        events = read_events(registry_path)
    except (OSError, V2ValidationError) as exc:
        return [f"registry binding could not be checked: {exc}"]
    return [
        f"registry[{event.seq}]: protocol_fingerprint {event.protocol_fingerprint!r} does not "
        f"match the committed protocol {expected!r}"
        for event in events
        if event.protocol_fingerprint != expected
    ]


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse

    parser = argparse.ArgumentParser(description="V2B governance artifacts (offline)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    if args.write:
        (root / V2B_BUDGET_RELPATH).parent.mkdir(parents=True, exist_ok=True)
        (root / V2B_BUDGET_RELPATH).write_bytes(build_budget_bytes())
        (root / V2B_PROTOCOL_RELPATH).write_bytes(render_protocol_identity_bytes(root))
        print(f"wrote {V2B_BUDGET_RELPATH} and {V2B_PROTOCOL_RELPATH}")
        return 0
    problems: list[str] = []
    for check in (verify_budget, verify_protocol_identity):
        try:
            check(root)
        except (OSError, V2ValidationError) as exc:
            problems.append(str(exc))
    # verify_registry_bound subsumes verify_registry (chain + lifecycle) and also binds each event
    # to the committed protocol fingerprint.
    problems.extend(verify_registry_bound(root))
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
