"""Append-only, hash-chained proposal registry.

``research/m3e/proposal_registry.jsonl`` is an append-only, hash-chained ledger of
review-only update-automation events: a genesis sentinel followed by one record per
event. It leaks no OHLCV, no return, no metric — only governance facts (idempotency
keys, proposal branches, manifest hashes, run ids, dates).

At the milestone's terminal state the facility has run live exactly once, at
2026-07-15, and correctly produced a **no-op** (no new completed day was due), so the
registry holds the genesis sentinel and a single ``audit_noop`` record — no proposal
has been recorded. The registry is a deterministic function of these committed facts,
so :func:`verify_registry` rebuilds it and requires a byte-for-byte match.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research.m3d.chain import chained_line_bytes, load_and_verify_chain, render_ledger_bytes
from eth_research.m3e import M3E_PACKAGE_VERSION
from eth_research.m3e.validation import (
    M3EValidationError,
    require_bool,
    require_mapping,
    require_str,
)

REGISTRY_PATH = "research/m3e/proposal_registry.jsonl"
REGISTRY_SCHEMA_VERSION = 1
REGISTRY_KIND = "m3e_proposal_registry"

# Substrings that would betray a smuggled strategy/performance quantity in a record.
_FORBIDDEN_SUBSTRINGS = (
    "sharpe",
    "sortino",
    "return",
    "pnl",
    "drawdown",
    "signal",
    "weight",
    "position",
    "metric",
    "ranking",
    "alpha",
)

# The single live event this milestone recorded: the 2026-07-15 audit-mode run of the
# standing update workflow, which correctly no-opped (see AUDIT_MODE_EVIDENCE.md).
_AUDIT_NOOP_RECORD: dict[str, Any] = {
    "schema_version": REGISTRY_SCHEMA_VERSION,
    "entry_kind": "audit_noop",
    "workflow_run_id": "29441490761",
    "as_of_date": "2026-07-15",
    "reason": "no new completed day is due (first missing open equals the completed-day cutoff)",
    "proposal_created": False,
    "package_version": M3E_PACKAGE_VERSION,
}


def _records() -> list[dict[str, Any]]:
    genesis = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "kind": REGISTRY_KIND,
        "entry_kind": "genesis",
        "package_version": M3E_PACKAGE_VERSION,
    }
    return [genesis, dict(_AUDIT_NOOP_RECORD)]


def build_registry_bytes() -> bytes:
    """Deterministically render the proposal registry chain file bytes."""
    return render_ledger_bytes(chained_line_bytes(_records()))


def _scan_forbidden(record: dict[str, Any]) -> None:
    for key, value in record.items():
        for token in (str(key), str(value)):
            lowered = token.lower()
            for sub in _FORBIDDEN_SUBSTRINGS:
                if sub in lowered:
                    raise M3EValidationError(f"registry record carries a forbidden token {sub!r}")


def verify_registry(repo_root: str | Path) -> list[dict[str, Any]]:
    """Verify the committed registry reproduces and satisfies the structural rules."""
    raw, records = load_and_verify_chain(repo_root, REGISTRY_PATH)
    if not records:
        raise M3EValidationError("proposal registry is empty (missing genesis)")
    genesis = require_mapping("registry genesis", records[0])
    if genesis.get("entry_kind") != "genesis" or genesis.get("kind") != REGISTRY_KIND:
        raise M3EValidationError("proposal registry is missing its genesis sentinel")
    for record in records[1:]:
        mapping = require_mapping("registry record", record)
        kind = require_str("entry_kind", mapping.get("entry_kind"))
        if kind == "audit_noop":
            if require_bool("proposal_created", mapping.get("proposal_created")):
                raise M3EValidationError("an audit_noop record must not claim a proposal")
        elif kind == "proposal":
            for field in ("idempotency_key", "proposal_branch", "manifest_sha256"):
                require_str(field, mapping.get(field))
        else:
            raise M3EValidationError(f"unknown registry entry_kind {kind!r}")
        _scan_forbidden(mapping)
    if raw != build_registry_bytes():
        raise M3EValidationError("committed proposal registry does not match the rebuild")
    return records
