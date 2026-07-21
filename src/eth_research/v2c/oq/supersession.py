"""V2C: the append-only OQ source-freeze SUPERSESSION ledger.

A pre-registration sequencing correction. The first OQ source freeze (``e4b3cc3``) was a valid
green checkpoint, but it froze only the qualification-defining source -- not the execution scaffold
(orchestrator, virtual-time runner, transactional publication, recovery, immutable archive, the
independent OQ-Q oracle, and the replay surface), which did not yet exist. Because OQ-R must add no
source, that checkpoint cannot honestly be the freeze that authorizes qualification execution.

This ledger records that supersession append-only (a hash-chained JSONL ledger, mirroring the OQ
registry) **before the first registry mutation**, while the OQ registry is still byte-empty and the
qualification budget is unconsumed. A superseded freeze can never authorize registration or
execution: :func:`assert_freeze_not_superseded` refuses it. A supersession is only recorded while
the registry is pristine and every sealed ledger is byte-empty, so this ledger cannot be used to
rewrite history after a qualification has begun. Nothing here evaluates a strategy or touches a
sealed partition; it corrects the freeze provenance only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from eth_research.m3d.validation import M3DValidationError
from eth_research.v2.strict import (
    canonical_sha256,
    require_bool,
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
from eth_research.v2c.oq.registry import read_oq_registry

#: The committed location of the append-only supersession ledger (governance, not a frozen root).
OQ_SUPERSESSION_PATH: str = "governance/v2c/oq_source_freeze_supersession.jsonl"
OQ_SUPERSESSION_SCHEMA_VERSION: int = 1

#: The genesis predecessor hash for the first chained record.
GENESIS_PREV_HASH: str = "0" * 64
#: The SHA-256 of zero bytes -- a byte-empty registry or sealed ledger hashes to this.
EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: The only reason a supersession may record (bound into the entry hash, so it cannot be re-worded).
SUPERSESSION_REASON: str = (
    "qualification protocol/registry/orchestrator/replay source was incomplete"
)

#: A replacement freeze is pending until OQ-E2 exists; a bound record names the replacement commit.
REPLACEMENT_PENDING: str = "pending"
REPLACEMENT_BOUND: str = "bound"
_REPLACEMENT_STATES: frozenset[str] = frozenset({REPLACEMENT_PENDING, REPLACEMENT_BOUND})

#: The three sealed access ledgers that must be byte-empty for a supersession to be admissible.
SEALED_LEDGER_RELPATHS: tuple[str, ...] = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)

_GIT_SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")
_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "supersession_id",
        "superseded_commit",
        "superseded_freeze_relpath",
        "superseded_freeze_artifact_sha256",
        "reason",
        "registry_relpath",
        "registry_byte_count",
        "registry_sha256",
        "registry_event_count",
        "no_qualification_started",
        "no_strategy_ran",
        "sealed_ledgers_empty",
        "sealed_ledger_sha256",
        "replacement_freeze_status",
        "replacement_freeze_commit",
        "generated_utc",
        "package_version",
        "prev_hash",
        "entry_hash",
    }
)


class OQSupersessionError(M3DValidationError):
    """The supersession ledger chain, lifecycle, or pristine-state precondition was violated."""


def _require_git_sha(label: str, value: object) -> str:
    text = require_nonempty_str(label, value)
    if not _GIT_SHA_RE.match(text):
        raise OQSupersessionError(f"{label} must be a 40-hex git commit sha, got {text!r}")
    return text


def _require_empty_sha(label: str, value: object) -> str:
    digest = require_hex64(label, value)
    if digest != EMPTY_SHA256:
        raise OQSupersessionError(f"{label} must be the empty-file sha (a byte-empty file)")
    return digest


def _require_utc_iso(label: str, value: object) -> str:
    """Decode an ISO-8601 string (or a pd.Timestamp) to a canonical UTC ISO-8601 string."""
    if isinstance(value, pd.Timestamp):
        ts: object = value
    elif isinstance(value, str):
        try:
            ts = pd.Timestamp(value)
        except (ValueError, TypeError) as exc:
            raise OQSupersessionError(
                f"{label} is not a valid ISO-8601 timestamp: {value!r}"
            ) from exc
    else:
        raise OQSupersessionError(f"{label} must be a timestamp string, got {type(value).__name__}")
    try:
        return require_utc_timestamp(label, ts).isoformat()
    except (ValueError, TypeError) as exc:
        raise OQSupersessionError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class SupersessionRecord:
    """One chained record: a freeze superseded while the OQ registry was byte-empty and clean."""

    schema_version: int
    supersession_id: str
    superseded_commit: str
    superseded_freeze_relpath: str
    superseded_freeze_artifact_sha256: str
    reason: str
    registry_relpath: str
    registry_byte_count: int
    registry_sha256: str
    registry_event_count: int
    no_qualification_started: bool
    no_strategy_ran: bool
    sealed_ledgers_empty: bool
    sealed_ledger_sha256: dict[str, str]
    replacement_freeze_status: str
    replacement_freeze_commit: str | None
    generated_utc: str
    package_version: str
    prev_hash: str
    entry_hash: str

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "supersession_id": self.supersession_id,
            "superseded_commit": self.superseded_commit,
            "superseded_freeze_relpath": self.superseded_freeze_relpath,
            "superseded_freeze_artifact_sha256": self.superseded_freeze_artifact_sha256,
            "reason": self.reason,
            "registry_relpath": self.registry_relpath,
            "registry_byte_count": self.registry_byte_count,
            "registry_sha256": self.registry_sha256,
            "registry_event_count": self.registry_event_count,
            "no_qualification_started": self.no_qualification_started,
            "no_strategy_ran": self.no_strategy_ran,
            "sealed_ledgers_empty": self.sealed_ledgers_empty,
            "sealed_ledger_sha256": dict(sorted(self.sealed_ledger_sha256.items())),
            "replacement_freeze_status": self.replacement_freeze_status,
            "replacement_freeze_commit": self.replacement_freeze_commit,
            "generated_utc": self.generated_utc,
            "package_version": self.package_version,
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


def _validated(
    *,
    supersession_id: object,
    superseded_commit: object,
    superseded_freeze_relpath: object,
    superseded_freeze_artifact_sha256: object,
    reason: object,
    registry_relpath: object,
    registry_byte_count: object,
    registry_sha256: object,
    registry_event_count: object,
    no_qualification_started: object,
    no_strategy_ran: object,
    sealed_ledgers_empty: object,
    sealed_ledger_sha256: object,
    replacement_freeze_status: object,
    replacement_freeze_commit: object,
    generated_utc: object,
    package_version: object,
    prev_hash: object,
) -> SupersessionRecord:
    """Validate raw inputs into typed locals and return a hash-finalized record (fail closed)."""
    reason_text = require_nonempty_str("supersession.reason", reason)
    if reason_text != SUPERSESSION_REASON:
        raise OQSupersessionError("supersession.reason drifted from the fixed reason")
    byte_count = require_nonnegative_int("supersession.registry_byte_count", registry_byte_count)
    event_count = require_nonnegative_int("supersession.registry_event_count", registry_event_count)
    if byte_count != 0 or event_count != 0:
        raise OQSupersessionError(
            "a supersession is admissible only while the OQ registry is byte-empty and unconsumed"
        )
    started = require_bool("supersession.no_qualification_started", no_qualification_started)
    strategy = require_bool("supersession.no_strategy_ran", no_strategy_ran)
    sealed = require_bool("supersession.sealed_ledgers_empty", sealed_ledgers_empty)
    if not (started and strategy and sealed):
        raise OQSupersessionError(
            "a supersession requires no started qualification, no strategy run, and empty ledgers"
        )
    sealed_raw = require_mapping("supersession.sealed_ledger_sha256", sealed_ledger_sha256)
    require_exact_keys(
        "supersession.sealed_ledger_sha256", sealed_raw, frozenset(SEALED_LEDGER_RELPATHS)
    )
    sealed_map: dict[str, str] = {
        rel: _require_empty_sha(f"supersession.sealed_ledger_sha256[{rel}]", sealed_raw[rel])
        for rel in SEALED_LEDGER_RELPATHS
    }
    status = require_choice(
        "supersession.replacement_freeze_status", replacement_freeze_status, _REPLACEMENT_STATES
    )
    commit: str | None
    if status == REPLACEMENT_PENDING:
        if replacement_freeze_commit is not None:
            raise OQSupersessionError("a pending supersession must not name a replacement commit")
        commit = None
    else:
        commit = _require_git_sha(
            "supersession.replacement_freeze_commit", replacement_freeze_commit
        )
    partial = SupersessionRecord(
        schema_version=OQ_SUPERSESSION_SCHEMA_VERSION,
        supersession_id=require_slug("supersession.supersession_id", supersession_id),
        superseded_commit=_require_git_sha("supersession.superseded_commit", superseded_commit),
        superseded_freeze_relpath=require_nonempty_str(
            "supersession.superseded_freeze_relpath", superseded_freeze_relpath
        ),
        superseded_freeze_artifact_sha256=require_hex64(
            "supersession.superseded_freeze_artifact_sha256", superseded_freeze_artifact_sha256
        ),
        reason=reason_text,
        registry_relpath=require_nonempty_str("supersession.registry_relpath", registry_relpath),
        registry_byte_count=byte_count,
        registry_sha256=_require_empty_sha("supersession.registry_sha256", registry_sha256),
        registry_event_count=event_count,
        no_qualification_started=started,
        no_strategy_ran=strategy,
        sealed_ledgers_empty=sealed,
        sealed_ledger_sha256=sealed_map,
        replacement_freeze_status=status,
        replacement_freeze_commit=commit,
        generated_utc=_require_utc_iso("supersession.generated_utc", generated_utc),
        package_version=require_nonempty_str("supersession.package_version", package_version),
        prev_hash=require_hex64("supersession.prev_hash", prev_hash),
        entry_hash="",
    )
    return replace(partial, entry_hash=partial.recompute_hash())


def build_supersession_record(
    *,
    supersession_id: str,
    superseded_commit: str,
    superseded_freeze_relpath: str,
    superseded_freeze_artifact_sha256: str,
    registry_relpath: str,
    registry_byte_count: int,
    registry_sha256: str,
    registry_event_count: int,
    sealed_ledger_sha256: dict[str, str],
    generated_utc: str,
    package_version: str,
    prev_hash: str,
    replacement_freeze_status: str = REPLACEMENT_PENDING,
    replacement_freeze_commit: str | None = None,
) -> SupersessionRecord:
    """Build a chained supersession record, validating the pristine-state preconditions."""
    return _validated(
        supersession_id=supersession_id,
        superseded_commit=superseded_commit,
        superseded_freeze_relpath=superseded_freeze_relpath,
        superseded_freeze_artifact_sha256=superseded_freeze_artifact_sha256,
        reason=SUPERSESSION_REASON,
        registry_relpath=registry_relpath,
        registry_byte_count=registry_byte_count,
        registry_sha256=registry_sha256,
        registry_event_count=registry_event_count,
        no_qualification_started=True,
        no_strategy_ran=True,
        sealed_ledgers_empty=True,
        sealed_ledger_sha256=sealed_ledger_sha256,
        replacement_freeze_status=replacement_freeze_status,
        replacement_freeze_commit=replacement_freeze_commit,
        generated_utc=generated_utc,
        package_version=package_version,
        prev_hash=prev_hash,
    )


def _parse_line(index: int, line: bytes) -> SupersessionRecord:
    obj = require_mapping(f"supersession[{index}]", strict_json_loads(line))
    require_exact_keys(f"supersession[{index}]", obj, _RECORD_KEYS)
    schema = require_nonnegative_int(f"supersession[{index}].schema_version", obj["schema_version"])
    if schema != OQ_SUPERSESSION_SCHEMA_VERSION:
        raise OQSupersessionError(f"supersession[{index}] unknown schema_version {schema}")
    parsed = _validated(
        supersession_id=obj["supersession_id"],
        superseded_commit=obj["superseded_commit"],
        superseded_freeze_relpath=obj["superseded_freeze_relpath"],
        superseded_freeze_artifact_sha256=obj["superseded_freeze_artifact_sha256"],
        reason=obj["reason"],
        registry_relpath=obj["registry_relpath"],
        registry_byte_count=obj["registry_byte_count"],
        registry_sha256=obj["registry_sha256"],
        registry_event_count=obj["registry_event_count"],
        no_qualification_started=obj["no_qualification_started"],
        no_strategy_ran=obj["no_strategy_ran"],
        sealed_ledgers_empty=obj["sealed_ledgers_empty"],
        sealed_ledger_sha256=obj["sealed_ledger_sha256"],
        replacement_freeze_status=obj["replacement_freeze_status"],
        replacement_freeze_commit=obj["replacement_freeze_commit"],
        generated_utc=obj["generated_utc"],
        package_version=obj["package_version"],
        prev_hash=obj["prev_hash"],
    )
    committed = require_hex64(f"supersession[{index}].entry_hash", obj["entry_hash"])
    if parsed.entry_hash != committed:
        raise OQSupersessionError(f"supersession[{index}] entry_hash does not match its body")
    return parsed


def _assert_lifecycle(records: list[SupersessionRecord]) -> None:
    ids: set[str] = set()
    superseded: set[str] = set()
    for index, record in enumerate(records):
        if record.supersession_id in ids:
            raise OQSupersessionError(
                f"supersession[{index}] duplicate id {record.supersession_id!r}"
            )
        ids.add(record.supersession_id)
        if record.superseded_commit in superseded:
            raise OQSupersessionError(
                f"supersession[{index}] commit {record.superseded_commit!r} superseded twice"
            )
        # A bound record's replacement must not itself already be superseded -- a second replacement
        # cannot silently supersede an authoritative freeze through this ledger.
        if (
            record.replacement_freeze_status == REPLACEMENT_BOUND
            and record.replacement_freeze_commit in superseded
        ):
            raise OQSupersessionError(
                f"supersession[{index}] binds a replacement that is itself superseded"
            )
        superseded.add(record.superseded_commit)


def read_supersession(path: str | Path) -> tuple[SupersessionRecord, ...]:
    """Read + fully verify the supersession ledger (chain, hashes, lifecycle). Empty is valid."""
    file = Path(path)
    if file.is_symlink():
        raise OQSupersessionError("the supersession ledger must not be a symlink")
    if not file.exists() or file.stat().st_size == 0:
        return ()
    records: list[SupersessionRecord] = []
    prev = GENESIS_PREV_HASH
    for index, raw in enumerate(file.read_bytes().splitlines()):
        if not raw.strip():
            raise OQSupersessionError(f"supersession[{index}] is a blank line")
        record = _parse_line(index, raw)
        if record.prev_hash != prev:
            raise OQSupersessionError(f"supersession[{index}] prev_hash breaks the chain")
        prev = record.entry_hash
        records.append(record)
    _assert_lifecycle(records)
    return tuple(records)


def superseded_commits(path: str | Path) -> frozenset[str]:
    """The set of commit shas recorded as superseded (a fully verified read)."""
    return frozenset(record.superseded_commit for record in read_supersession(path))


def assert_freeze_not_superseded(path: str | Path, freeze_commit: str) -> None:
    """Refuse a freeze commit that the ledger records as superseded (cannot authorize OQ-R/OQ-P)."""
    commit = _require_git_sha("freeze_commit", freeze_commit)
    if commit in superseded_commits(path):
        raise OQSupersessionError(
            f"freeze commit {commit} is superseded and cannot authorize registration or execution"
        )


def assert_freeze_superseded(path: str | Path, freeze_commit: str) -> None:
    """Require a freeze commit to be recorded as superseded (a deleted/missing ledger is detected).

    The orchestrator uses this to confirm the premature ``e4b3cc3`` freeze is recorded as superseded
    before proceeding under the replacement; if the ledger was deleted or never written, it raises.
    """
    commit = _require_git_sha("freeze_commit", freeze_commit)
    if commit not in superseded_commits(path):
        raise OQSupersessionError(f"freeze commit {commit} is not recorded as superseded in {path}")


def append_supersession(
    path: str | Path,
    *,
    supersession_id: str,
    superseded_commit: str,
    superseded_freeze_relpath: str,
    superseded_freeze_artifact_sha256: str,
    registry_relpath: str,
    registry_byte_count: int,
    registry_sha256: str,
    registry_event_count: int,
    sealed_ledger_sha256: dict[str, str],
    generated_utc: str,
    package_version: str,
    replacement_freeze_status: str = REPLACEMENT_PENDING,
    replacement_freeze_commit: str | None = None,
) -> SupersessionRecord:
    """Append a chained supersession record, re-verifying the ledger and pristine precondition."""
    file = Path(path)
    existing = list(read_supersession(file))
    prev = existing[-1].entry_hash if existing else GENESIS_PREV_HASH
    record = build_supersession_record(
        supersession_id=supersession_id,
        superseded_commit=superseded_commit,
        superseded_freeze_relpath=superseded_freeze_relpath,
        superseded_freeze_artifact_sha256=superseded_freeze_artifact_sha256,
        registry_relpath=registry_relpath,
        registry_byte_count=registry_byte_count,
        registry_sha256=registry_sha256,
        registry_event_count=registry_event_count,
        sealed_ledger_sha256=sealed_ledger_sha256,
        generated_utc=generated_utc,
        package_version=package_version,
        prev_hash=prev,
        replacement_freeze_status=replacement_freeze_status,
        replacement_freeze_commit=replacement_freeze_commit,
    )
    _assert_lifecycle([*existing, record])
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("ab") as handle:
        handle.write(record.to_line())
        handle.flush()
    return record


def _sha256_of(path: Path) -> str:
    if path.is_symlink():
        raise OQSupersessionError(f"{path} is a symlink")
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def record_supersession(
    repo_root: str | Path,
    *,
    supersession_id: str,
    superseded_commit: str,
    superseded_freeze_relpath: str,
    generated_utc: str,
    package_version: str,
    registry_relpath: str = "governance/v2c/oq_registry.jsonl",
) -> SupersessionRecord:
    """Record a supersession bound to *live* state: the OQ registry and every sealed ledger must be
    byte-empty right now, and the superseded freeze artifact + sealed-ledger SHAs are read from disk
    (never caller-supplied), so the record cannot claim a pristine state that does not hold."""
    root = Path(repo_root)
    registry_path = root / registry_relpath
    if registry_path.is_symlink():
        raise OQSupersessionError("the OQ registry must not be a symlink")
    # The live registry must be byte-empty (checked before parsing, so any content is refused).
    registry_bytes = registry_path.read_bytes() if registry_path.exists() else b""
    if registry_bytes != b"":
        raise OQSupersessionError(
            "the OQ registry is not byte-empty; a supersession is inadmissible"
        )
    events = read_oq_registry(registry_path)  # byte-empty -> () (defensive re-check)
    if events:
        raise OQSupersessionError("the OQ registry already carries events; supersession refused")
    sealed_sha = {rel: _sha256_of(root / rel) for rel in SEALED_LEDGER_RELPATHS}
    for rel, digest in sealed_sha.items():
        if digest != EMPTY_SHA256:
            raise OQSupersessionError(f"sealed ledger {rel} is not byte-empty")
    freeze_sha = _sha256_of(root / superseded_freeze_relpath)
    return append_supersession(
        root / OQ_SUPERSESSION_PATH,
        supersession_id=supersession_id,
        superseded_commit=superseded_commit,
        superseded_freeze_relpath=superseded_freeze_relpath,
        superseded_freeze_artifact_sha256=freeze_sha,
        registry_relpath=registry_relpath,
        registry_byte_count=len(registry_bytes),
        registry_sha256=hashlib.sha256(registry_bytes).hexdigest(),
        registry_event_count=len(events),
        sealed_ledger_sha256=sealed_sha,
        generated_utc=generated_utc,
        package_version=package_version,
    )


def verify_supersession(path: str | Path) -> list[str]:
    """Return the supersession-ledger problems (empty == OK); a byte-empty ledger is clean."""
    try:
        read_supersession(path)
    except (OQSupersessionError, M3DValidationError, ValueError, TypeError) as exc:
        return [f"oq_supersession: {exc}"]
    return []


__all__ = [
    "EMPTY_SHA256",
    "GENESIS_PREV_HASH",
    "OQ_SUPERSESSION_PATH",
    "OQ_SUPERSESSION_SCHEMA_VERSION",
    "REPLACEMENT_BOUND",
    "REPLACEMENT_PENDING",
    "SEALED_LEDGER_RELPATHS",
    "SUPERSESSION_REASON",
    "OQSupersessionError",
    "SupersessionRecord",
    "append_supersession",
    "assert_freeze_not_superseded",
    "assert_freeze_superseded",
    "build_supersession_record",
    "read_supersession",
    "record_supersession",
    "superseded_commits",
    "verify_supersession",
]
