"""Append-only prospective segment chain.

``research/m3d/prospective_segments.jsonl`` is a hash-chained ledger of prospective
cohort segments. Each segment binds its source plan hash, attempt/receipt hash,
raw-bundle fingerprint, canonical-content fingerprint, first/last open, row count,
interval, created-at, package version, source commit, and a self-contained
publication-bundle hash. The genesis segment starts exactly at the fixed cohort
start with contiguous candles and a positive row count; future segments (fixtures
only this milestone) start exactly one interval after the prior last open with no
overlap, gap, duplicate, or boundary rewrite, and the chain verifies from genesis.

The chain is a deterministic function of committed acquisition evidence (plan +
receipt + retained raw bytes), so :func:`verify_prospective_segments` rebuilds it
and requires a byte-for-byte match.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.m3d import _upstream as up
from eth_research.m3d.chain import chained_line_bytes, load_and_verify_chain, render_ledger_bytes
from eth_research.m3d.protocol import COHORT_START
from eth_research.m3d.raw_bundle import (
    build_raw_bundles,
    cohort_canonical_fingerprint,
    combined_canonical_rows,
)
from eth_research.m3d.receipt import load_prospective_attempt_receipt
from eth_research.m3d.validation import (
    M3DValidationError,
    domain_sha256,
    require_mapping,
    require_str,
)

SEGMENTS_PATH = "research/m3d/prospective_segments.jsonl"
SEGMENTS_SCHEMA_VERSION = 1
SEGMENTS_KIND = "prospective_segment_chain"
GENESIS_SEGMENT_ID = "prospective-segment-000"
_INTERVAL_SECONDS = 86400

# The single acquisition attempt whose segment this milestone publishes; the audit
# reacquisition is a cross-check, not a second chronological extension.
PRIMARY_ATTEMPT_ID = "coinbase-eth-usd-prospective-genesis-001"


def _build_records(repo_root: str | Path) -> list[dict[str, Any]]:
    from eth_research.m3d import M3D_PACKAGE_VERSION

    bundles = build_raw_bundles(repo_root, PRIMARY_ATTEMPT_ID)
    rows = combined_canonical_rows(bundles)
    if not rows:
        raise M3DValidationError("prospective segment has no rows")
    if rows[0][0] != COHORT_START:
        raise M3DValidationError("genesis segment must start at the fixed cohort start")

    receipt = load_prospective_attempt_receipt(
        Path(repo_root) / f"research/m3d/raw/coinbase/{PRIMARY_ATTEMPT_ID}/acquisition_receipt.json"
    )
    receipt_hash = up.hash_file(
        repo_root, f"research/m3d/raw/coinbase/{PRIMARY_ATTEMPT_ID}/acquisition_receipt.json"
    )
    plan_hash = require_str("plan_sha256", receipt.plan_sha256)
    canonical_fp = cohort_canonical_fingerprint(bundles)
    raw_bundle_fp = domain_sha256(
        "prospective_segment_raw_bundle",
        {"attempt_id": PRIMARY_ATTEMPT_ID, "bundles": [b.to_dict() for b in bundles]},
    )
    publication_bundle_hash = domain_sha256(
        "prospective_segment_publication",
        {
            "segment_id": GENESIS_SEGMENT_ID,
            "attempt_receipt_hash": receipt_hash,
            "raw_bundle_fingerprint": raw_bundle_fp,
            "canonical_content_fingerprint": canonical_fp,
        },
    )

    genesis = {
        "schema_version": SEGMENTS_SCHEMA_VERSION,
        "kind": SEGMENTS_KIND,
        "entry_kind": "genesis",
        "package_version": M3D_PACKAGE_VERSION,
        "cohort_start": COHORT_START,
    }
    segment = {
        "schema_version": SEGMENTS_SCHEMA_VERSION,
        "entry_kind": "segment",
        "segment_id": GENESIS_SEGMENT_ID,
        "source_plan_hash": plan_hash,
        "attempt_receipt_hash": receipt_hash,
        "raw_bundle_fingerprint": raw_bundle_fp,
        "canonical_content_fingerprint": canonical_fp,
        "first_open": rows[0][0],
        "last_open": rows[-1][0],
        "row_count": len(rows),
        "interval_seconds": _INTERVAL_SECONDS,
        "created_at_utc": require_str("created_at_utc", receipt.document["created_at_utc"]),
        "package_version": M3D_PACKAGE_VERSION,
        "source_commit": require_str("source_commit", receipt.document["source_commit"]),
        "publication_bundle_hash": publication_bundle_hash,
    }
    return [genesis, segment]


def build_prospective_segments_bytes(repo_root: str | Path) -> bytes:
    """Deterministically render the prospective segment chain file bytes."""
    return render_ledger_bytes(chained_line_bytes(_build_records(repo_root)))


def verify_segment_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Structural chain rules, independent of the real-data rebuild.

    Usable on any candidate chain, including future-append fixtures: the genesis
    sentinel is present and pinned to the fixed cohort start; the first segment
    starts exactly at the cohort start with a positive row count and the fixed
    daily interval; and every later segment begins exactly one interval after the
    prior segment's last open — no overlap, gap, duplicate, or reorder. This
    encodes the incremental-append rules even though no second chronological
    segment is materialized this milestone.
    """
    if not records:
        raise M3DValidationError("segment chain is empty")
    genesis = require_mapping("segment genesis", records[0])
    if genesis.get("entry_kind") != "genesis" or genesis.get("kind") != SEGMENTS_KIND:
        raise M3DValidationError("segment chain is missing its genesis sentinel")
    if genesis.get("cohort_start") != COHORT_START:
        raise M3DValidationError("segment genesis cohort_start must be the fixed cohort start")
    segments = [require_mapping("segment", r) for r in records[1:]]
    if not segments:
        raise M3DValidationError("segment chain has no segment")
    first = segments[0]
    if require_str("first_open", first["first_open"]) != COHORT_START:
        raise M3DValidationError("genesis segment must start at the fixed cohort start")
    if int(first["row_count"]) <= 0:
        raise M3DValidationError("genesis segment must have a positive row count")
    for segment in segments:
        if int(segment["interval_seconds"]) != _INTERVAL_SECONDS:
            raise M3DValidationError("segments must use the fixed daily interval")
    for earlier, later in pairwise(segments):
        if pd.Timestamp(later["first_open"]) <= pd.Timestamp(earlier["last_open"]):
            raise M3DValidationError("segments must not overlap, duplicate, or reorder")
        gap = pd.Timestamp(later["first_open"]) - pd.Timestamp(earlier["last_open"])
        if gap != pd.Timedelta(seconds=_INTERVAL_SECONDS):
            raise M3DValidationError("segments must extend by exactly one interval, no gap")
    return records


def verify_prospective_segments(repo_root: str | Path) -> list[dict[str, Any]]:
    """Verify the committed segment chain reproduces and satisfies the genesis rules."""
    raw, records = load_and_verify_chain(repo_root, SEGMENTS_PATH)
    verify_segment_records(records)
    if raw != build_prospective_segments_bytes(repo_root):
        raise M3DValidationError("committed segment chain does not match the rebuilt chain")
    return records
