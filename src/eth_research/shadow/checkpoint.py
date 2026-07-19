"""Deterministic checkpoints and recovery for a shadow run.

A checkpoint is a self-describing snapshot of everything needed to resume a shadow run: the mode and
instrument, the as-of frontier, the paper account and its peak equity, the latching kill-switch
state, how many bars have been processed, and — crucially — the journal head hash at the moment of
the snapshot. Binding the journal head means a checkpoint can only be resumed against the exact
journal that produced it: :func:`recover` rejects a checkpoint/journal pair whose hashes disagree.

Checkpoints are strict and hashable, carry no wall-clock time, and are written atomically, so a
recovered run is byte-identical to one that never paused.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from eth_research.shadow.domain import (
    InstrumentId,
    ShadowDomainError,
    canonical_timestamp,
    require_shadow_mode,
)
from eth_research.shadow.journal import ShadowJournal
from eth_research.shadow.paper import PaperAccount
from eth_research.v2.strict import (
    canonical_json_bytes,
    canonical_sha256,
    load_canonical_json,
    require_bool,
    require_exact_keys,
    require_hex64,
    require_int,
    require_mapping,
    require_nonnegative_int,
    require_positive_real,
    require_str,
)

CHECKPOINT_SCHEMA_VERSION: int = 1

_CHECKPOINT_KEYS = frozenset(
    {
        "schema_version",
        "mode",
        "instrument",
        "as_of",
        "account",
        "peak_equity",
        "kill_tripped",
        "kill_reason",
        "bars_processed",
        "journal_head_hash",
    }
)


class CheckpointError(ShadowDomainError):
    """A checkpoint was malformed or does not match the journal it claims to snapshot."""


@dataclass(frozen=True, slots=True)
class ShadowCheckpoint:
    """A resumable snapshot of a shadow run, bound to the journal head that produced it."""

    mode: str
    instrument: InstrumentId
    as_of: str
    account: PaperAccount
    peak_equity: float
    kill_tripped: bool
    kill_reason: str
    bars_processed: int
    journal_head_hash: str

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "mode": self.mode,
            "instrument": self.instrument.to_canonical(),
            "as_of": self.as_of,
            "account": self.account.to_canonical(),
            "peak_equity": self.peak_equity,
            "kill_tripped": self.kill_tripped,
            "kill_reason": self.kill_reason,
            "bars_processed": self.bars_processed,
            "journal_head_hash": self.journal_head_hash,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @staticmethod
    def parse(label: str, value: object) -> ShadowCheckpoint:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _CHECKPOINT_KEYS)
        version = require_int(f"{label}.schema_version", obj["schema_version"])
        if version != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointError(f"{label}: unsupported checkpoint schema_version {version}")
        return ShadowCheckpoint(
            mode=require_shadow_mode(f"{label}.mode", obj["mode"]),
            instrument=InstrumentId.parse(f"{label}.instrument", obj["instrument"]),
            as_of=canonical_timestamp(f"{label}.as_of", obj["as_of"]),
            account=PaperAccount.parse(f"{label}.account", obj["account"]),
            peak_equity=require_positive_real(f"{label}.peak_equity", obj["peak_equity"]),
            kill_tripped=require_bool(f"{label}.kill_tripped", obj["kill_tripped"]),
            kill_reason=require_str(f"{label}.kill_reason", obj["kill_reason"]),
            bars_processed=require_nonnegative_int(
                f"{label}.bars_processed", obj["bars_processed"]
            ),
            journal_head_hash=require_hex64(f"{label}.journal_head_hash", obj["journal_head_hash"]),
        )


def write_checkpoint(path: str | Path, checkpoint: ShadowCheckpoint) -> None:
    """Atomically write a checkpoint to ``path`` (canonical JSON)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(canonical_json_bytes(checkpoint.to_canonical()))
    os.replace(tmp, target)


def load_checkpoint(path: str | Path) -> ShadowCheckpoint:
    """Read + strictly decode a committed checkpoint."""
    return ShadowCheckpoint.parse("checkpoint", load_canonical_json(path))


def recover(checkpoint: ShadowCheckpoint, journal: ShadowJournal) -> ShadowCheckpoint:
    """Return the checkpoint only if ``journal``'s head hash matches it (else fail closed)."""
    if journal.head_hash != checkpoint.journal_head_hash:
        raise CheckpointError(
            "journal head hash does not match the checkpoint; recovery is unsafe "
            f"({journal.head_hash} != {checkpoint.journal_head_hash})"
        )
    return checkpoint
