"""Append-only ledger of accepted prospective update attempts (V2D growth core).

``research/m3d/update_attempts.jsonl`` is the ordered, hash-chained enumeration of
every **landed** update acquisition attempt that extends the accepted prospective
cohort beyond its genesis. Every multi-attempt rebuild (segment chain, cohort
manifest, quality report, accepted base, update transition) derives its attempt
order from this one ledger:

* **absent file → zero update attempts** — every rebuild reduces byte-for-byte to
  the accepted genesis-only artifacts, so a tree without updates verifies exactly
  as it did before this module existed;
* when present, the file must be a valid chain (genesis sentinel pinned to the
  fixed cohort start) whose every entry names a committed update attempt directory
  under ``research/m3d/raw/coinbase/``; each entry's window facts are re-derived
  from the committed plan + receipt + raw bytes and must match exactly;
* attempts are strictly chronological and contiguous: the first begins exactly one
  day after the genesis window ends, and each later attempt begins exactly one day
  after the previous one ends — no gap, overlap, duplicate, or reorder.

The ledger records only acquisition provenance (ids, hashes, window bounds, row
counts) — never a candle value, and never any strategy/performance quantity. It is
written only by the reviewed update-proposal path and lands only through a human
merge.
"""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.m3d import _upstream as up
from eth_research.m3d.acquisition_plan import GENESIS_ATTEMPT_ID
from eth_research.m3d.chain import (
    PREVIOUS_FIELD,
    load_and_verify_chain,
    split_ledger_lines,
    verify_chain,
)
from eth_research.m3d.protocol import COHORT_START
from eth_research.m3d.raw_bundle import (
    ProspectiveRawBundle,
    build_raw_bundles,
    combined_canonical_rows,
)
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_jsonl_line,
    require_exact,
    require_mapping,
    require_positive_int,
    require_sha256_hex,
    require_str,
    sha256_bytes,
)

UPDATE_ATTEMPTS_PATH = "research/m3d/update_attempts.jsonl"
UPDATE_ATTEMPTS_SCHEMA_VERSION = 1
UPDATE_ATTEMPTS_KIND = "prospective_update_attempts"

#: Update attempt ids are deterministic: window bounds + idempotency-key prefix.
UPDATE_ATTEMPT_ID_RE = re.compile(
    r"^coinbase-eth-usd-prospective-update-[0-9]{8}-[0-9]{8}-[0-9a-f]{16}$"
)

_DAY = pd.Timedelta(days=1)
_INTERVAL_SECONDS = 86400

_ENTRY_KEYS = {
    "schema_version",
    "entry_kind",
    "ordinal",
    "attempt_id",
    "first_open",
    "last_open",
    "row_count",
    "plan_sha256",
    "receipt_sha256",
    "proposal_id",
    "created_at_utc",
    "package_version",
    PREVIOUS_FIELD,
}


def genesis_record() -> dict[str, Any]:
    """The fixed genesis sentinel (no update attempts precede it)."""
    from eth_research.m3d import M3D_PACKAGE_VERSION

    return {
        "schema_version": UPDATE_ATTEMPTS_SCHEMA_VERSION,
        "kind": UPDATE_ATTEMPTS_KIND,
        "entry_kind": "genesis",
        "package_version": M3D_PACKAGE_VERSION,
        "cohort_start": COHORT_START,
    }


def _require_utc_midnight(label: str, value: object) -> pd.Timestamp:
    ts = pd.Timestamp(require_str(label, value))
    if ts.tzinfo is None or ts != ts.floor("D"):
        raise M3DValidationError(f"{label} must be a UTC midnight, got {value!r}")
    return ts


def _validate_entry(index: int, record: dict[str, Any]) -> dict[str, Any]:
    label = f"update attempt entry {index}"
    mapping = require_mapping(label, record)
    if set(mapping) != _ENTRY_KEYS:
        raise M3DValidationError(f"{label} keys must be {sorted(_ENTRY_KEYS)}")
    require_exact(
        f"{label}.schema_version",
        require_positive_int("schema_version", mapping["schema_version"]),
        UPDATE_ATTEMPTS_SCHEMA_VERSION,
    )
    require_exact(
        f"{label}.entry_kind", require_str("entry_kind", mapping["entry_kind"]), "update_attempt"
    )
    ordinal = require_positive_int(f"{label}.ordinal", mapping["ordinal"])
    if ordinal != index:
        raise M3DValidationError(f"{label} ordinal must be {index}, got {ordinal}")
    attempt_id = require_str(f"{label}.attempt_id", mapping["attempt_id"])
    if not UPDATE_ATTEMPT_ID_RE.fullmatch(attempt_id):
        raise M3DValidationError(f"{label} attempt_id {attempt_id!r} is not a valid update id")
    first = _require_utc_midnight(f"{label}.first_open", mapping["first_open"])
    last = _require_utc_midnight(f"{label}.last_open", mapping["last_open"])
    if last < first:
        raise M3DValidationError(f"{label} last_open precedes first_open")
    rows = require_positive_int(f"{label}.row_count", mapping["row_count"])
    span = int((last - first) / _DAY) + 1
    if rows != span:
        raise M3DValidationError(f"{label} row_count {rows} does not equal the day span {span}")
    require_sha256_hex(f"{label}.plan_sha256", mapping["plan_sha256"])
    require_sha256_hex(f"{label}.receipt_sha256", mapping["receipt_sha256"])
    require_str(f"{label}.proposal_id", mapping["proposal_id"])
    require_str(f"{label}.created_at_utc", mapping["created_at_utc"])
    require_str(f"{label}.package_version", mapping["package_version"])
    return dict(mapping)


def load_update_attempt_entries(repo_root: str | Path) -> list[dict[str, Any]]:
    """Load + structurally verify the committed ledger; absent file → no entries.

    Verifies the hash chain, the pinned genesis sentinel, per-entry shape, and the
    strict chronological contiguity across entries. Content binding to committed
    raw evidence happens in :func:`build_accepted_raw_bundles`.
    """
    path = Path(repo_root) / UPDATE_ATTEMPTS_PATH
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise M3DValidationError(f"{UPDATE_ATTEMPTS_PATH} is not a regular file")
    _raw, records = load_and_verify_chain(repo_root, UPDATE_ATTEMPTS_PATH)
    genesis = require_mapping("update attempts genesis", records[0])
    if genesis.get("entry_kind") != "genesis" or genesis.get("kind") != UPDATE_ATTEMPTS_KIND:
        raise M3DValidationError("update attempts ledger is missing its genesis sentinel")
    if genesis.get("cohort_start") != COHORT_START:
        raise M3DValidationError("update attempts genesis cohort_start must be the fixed start")
    entries = [_validate_entry(index, record) for index, record in enumerate(records[1:], start=1)]
    for earlier, later in pairwise(entries):
        gap = pd.Timestamp(str(later["first_open"])) - pd.Timestamp(str(earlier["last_open"]))
        if gap != _DAY:
            raise M3DValidationError(
                "update attempts must be strictly contiguous (exactly one day apart)"
            )
    return entries


def accepted_attempt_ids(repo_root: str | Path) -> list[str]:
    """Genesis first, then every landed update attempt in ledger order."""
    entries = load_update_attempt_entries(repo_root)
    return [GENESIS_ATTEMPT_ID, *(str(e["attempt_id"]) for e in entries)]


def build_accepted_raw_bundles(
    repo_root: str | Path,
) -> tuple[list[ProspectiveRawBundle], list[dict[str, Any]]]:
    """Rebuild every accepted attempt's raw bundles, in order, fully cross-checked.

    Returns ``(all_bundles, update_entries)``. For each ledger entry the committed
    plan/receipt/raw bytes are re-derived and the entry's recorded window facts
    (bounds, row count, plan hash, receipt hash) must match exactly; cross-attempt
    contiguity (each attempt starts exactly one day after the previous last open)
    is enforced over the *derived* rows, never trusted from the ledger.
    """
    root = Path(repo_root)
    entries = load_update_attempt_entries(root)
    all_bundles: list[ProspectiveRawBundle] = list(build_raw_bundles(root, GENESIS_ATTEMPT_ID))
    previous_last = pd.Timestamp(all_bundles[-1].last_open)

    for entry in entries:
        attempt_id = str(entry["attempt_id"])
        raw_dir = f"research/m3d/raw/coinbase/{attempt_id}"
        bundles = build_raw_bundles(root, attempt_id)
        rows = combined_canonical_rows(bundles)
        first = pd.Timestamp(rows[0][0])
        last = pd.Timestamp(rows[-1][0])
        if first - previous_last != _DAY:
            raise M3DValidationError(
                f"update attempt {attempt_id} does not start exactly one day after the "
                "previous accepted window (gap/overlap/backfill refused)"
            )
        if pd.Timestamp(str(entry["first_open"])) != first:
            raise M3DValidationError(f"{attempt_id}: ledger first_open does not match the bytes")
        if pd.Timestamp(str(entry["last_open"])) != last:
            raise M3DValidationError(f"{attempt_id}: ledger last_open does not match the bytes")
        if int(entry["row_count"]) != len(rows):
            raise M3DValidationError(f"{attempt_id}: ledger row_count does not match the bytes")
        receipt_hash = up.hash_file(root, f"{raw_dir}/acquisition_receipt.json")
        if str(entry["receipt_sha256"]) != receipt_hash:
            raise M3DValidationError(f"{attempt_id}: ledger receipt hash does not match the file")
        plan_hash_stated = str(entry["plan_sha256"])
        from eth_research.m3d.receipt import load_prospective_attempt_receipt

        receipt = load_prospective_attempt_receipt(root / raw_dir / "acquisition_receipt.json")
        if receipt.plan_sha256 != plan_hash_stated:
            raise M3DValidationError(f"{attempt_id}: ledger plan hash does not match the receipt")
        all_bundles.extend(bundles)
        previous_last = last
    return all_bundles, entries


def extend_update_attempts_bytes(existing_raw: bytes | None, new_record: dict[str, Any]) -> bytes:
    """Append one new (un-chained) entry record, creating the ledger if absent.

    ``existing_raw`` is the committed file's exact bytes (``None`` when the ledger
    does not exist yet, in which case the genesis sentinel is created first). The
    existing bytes are verified as a chain and preserved as an exact prefix —
    this function can only append.
    """
    if PREVIOUS_FIELD in new_record:
        raise M3DValidationError(f"new record must not pre-set {PREVIOUS_FIELD}")
    if existing_raw is None:
        genesis_line = canonical_jsonl_line({**genesis_record(), PREVIOUS_FIELD: up.EMPTY_SHA256})
        lines = [genesis_line]
    else:
        lines = split_ledger_lines(existing_raw)
        verify_chain(lines)
    previous = sha256_bytes(lines[-1])
    lines.append(canonical_jsonl_line({**new_record, PREVIOUS_FIELD: previous}))
    return b"\n".join(lines) + b"\n"
