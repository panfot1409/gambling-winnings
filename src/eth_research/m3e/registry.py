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


def _proposal_records(repo_root: str | Path) -> list[dict[str, Any]]:
    """One ``proposal`` record per committed proposal directory, in window order.

    Every committed proposal under ``research/m3e/proposals/`` (enumerated by the
    closed-set walker, manifest self-hash re-checked) yields exactly one record,
    ordered by its new window's first open — the same strictly-increasing order the
    append-only cohort growth enforces, so the registry rebuild is deterministic.
    """
    from eth_research.m3e.proposal import PROPOSAL_MANIFEST_NAME, load_proposal_manifest
    from eth_research.m3e.verify_m3e_program import verify_proposals_root

    dated: list[tuple[str, dict[str, Any]]] = []
    for directory in verify_proposals_root(repo_root):
        manifest = load_proposal_manifest(directory / PROPOSAL_MANIFEST_NAME)
        window = require_mapping("new_window", manifest["new_window"])
        dated.append(
            (
                require_str("first_open", window.get("first_open")),
                {
                    "schema_version": REGISTRY_SCHEMA_VERSION,
                    "entry_kind": "proposal",
                    "proposal_created": True,
                    "proposal_id": directory.name,
                    "idempotency_key": require_str("idempotency_key", manifest["idempotency_key"]),
                    "proposal_branch": require_str("proposal_branch", manifest["proposal_branch"]),
                    "manifest_sha256": require_str("manifest_sha256", manifest["manifest_sha256"]),
                    "package_version": M3E_PACKAGE_VERSION,
                },
            )
        )
    dated.sort(key=lambda item: item[0])
    return [record for _open, record in dated]


def _records(repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    genesis = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "kind": REGISTRY_KIND,
        "entry_kind": "genesis",
        "package_version": M3E_PACKAGE_VERSION,
    }
    records = [genesis, dict(_AUDIT_NOOP_RECORD)]
    if repo_root is not None:
        records.extend(_proposal_records(repo_root))
    return records


def build_registry_bytes(repo_root: str | Path | None = None) -> bytes:
    """Deterministically render the proposal registry chain file bytes.

    With a ``repo_root``, the rebuild covers the committed production proposals
    (one ``proposal`` record per committed proposal directory, window-ordered)
    after the frozen genesis + audit-noop prefix; without one, it renders exactly
    that historical prefix. A tree with zero committed proposals therefore rebuilds
    byte-for-byte to the accepted pre-activation registry either way.
    """
    return render_ledger_bytes(chained_line_bytes(_records(repo_root)))


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
            if require_bool("proposal_created", mapping.get("proposal_created")) is not True:
                raise M3EValidationError("a proposal record must state proposal_created true")
            for field in ("proposal_id", "idempotency_key", "proposal_branch", "manifest_sha256"):
                require_str(field, mapping.get(field))
        else:
            raise M3EValidationError(f"unknown registry entry_kind {kind!r}")
        _scan_forbidden(mapping)
    if raw != build_registry_bytes(repo_root):
        raise M3EValidationError("committed proposal registry does not match the rebuild")
    return records
