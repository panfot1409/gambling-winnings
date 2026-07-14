"""Legacy completion audit for run-001 (closure R1).

run-001 was registered, executed, and published *before* the durable
completion-intent mechanism (:mod:`eth_research.fractional.completion`) existed,
so — unlike any future run — it has no ``completion_intent.json`` and never went
through the calculation-free finalizer. That absence is expected, not a defect:
run-001's publication completeness is established independently by the
hash-chained registry ``completed`` event and by :func:`verify_published_run`.

This module records that fact as a small, additive, re-derivable JSON artifact
committed beside the run (it never touches the immutable manifest/results/report
bytes), and re-verifies it: the committed record must re-derive byte-for-byte from
the live registry and manifest, no completion intent may be present for the
completed run, and the full published-run replay must still pass. It is thus a
standing, checkable acknowledgement rather than a one-off note.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eth_research._json import require_canonical_file_bytes, strict_json_loads
from eth_research.fractional.archive import verify_published_run
from eth_research.fractional.completion import read_completion_intent
from eth_research.fractional.protocol import RUN_001_EXPERIMENT_ID
from eth_research.fractional.registry import (
    EVENT_COMPLETED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3B_REGISTRY_RELPATH,
    read_registry,
)

FRACTIONAL_LEGACY_AUDIT_RELPATH: str = "research/m3b/run001_legacy_completion_audit.json"
LEGACY_COMPLETION_AUDIT_SCHEMA_VERSION: int = 1

_LEGACY_NOTE: str = (
    "run-001 was registered, executed, and published before the durable "
    "completion-intent mechanism (closure R1) existed; it therefore has no "
    "completion_intent.json and never used the calculation-free finalizer. Its "
    "publication completeness is established by the hash-chained registry "
    "'completed' event and by verify_published_run, both re-checked here."
)


class LegacyCompletionAuditError(RuntimeError):
    """The committed run-001 legacy completion audit is missing or inconsistent."""


def build_legacy_completion_audit(repo_root: str | Path) -> dict[str, Any]:
    """Derive the run-001 legacy completion audit record from the live repository.

    Raises :class:`LegacyCompletionAuditError` if run-001's lifecycle is not the
    exact ``registered`` → ``started`` → ``completed`` sequence, if a completion
    intent is unexpectedly present, or if the published run does not replay.
    """
    root = Path(repo_root)
    events = read_registry(root / M3B_REGISTRY_RELPATH)
    run_events = [e for e in events if e.experiment_id == RUN_001_EXPERIMENT_ID]
    lifecycle = [e.event for e in run_events]
    if lifecycle != [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]:
        raise LegacyCompletionAuditError(
            f"run-001 lifecycle is {lifecycle!r}, expected registered/started/completed"
        )
    if read_completion_intent(root) is not None:
        raise LegacyCompletionAuditError(
            "a completion intent is present for a completed run — the legacy audit is only valid "
            "for run-001, which predates the mechanism"
        )
    completed = run_events[2]
    checks = verify_published_run(root)
    return {
        "legacy_completion_audit_schema_version": LEGACY_COMPLETION_AUDIT_SCHEMA_VERSION,
        "experiment_id": RUN_001_EXPERIMENT_ID,
        "note": _LEGACY_NOTE,
        "registry_lifecycle": list(lifecycle),
        "completion_intent_present": False,
        "results_json_sha256": completed.results_json_sha256,
        "report_markdown_sha256": completed.report_markdown_sha256,
        "result_bundle_sha256": completed.result_bundle_sha256,
        "verified_checks": list(checks),
    }


def render_legacy_completion_audit(repo_root: str | Path) -> bytes:
    """Canonical JSON bytes of the derived legacy completion audit record."""
    payload = build_legacy_completion_audit(repo_root)
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def verify_legacy_completion_audit(repo_root: str | Path) -> tuple[str, ...]:
    """Verify the committed legacy audit re-derives byte-for-byte from the repo.

    Returns the ordered passed checks; raises :class:`LegacyCompletionAuditError`
    on the first inconsistency. Read-only.
    """
    root = Path(repo_root)
    path = root / FRACTIONAL_LEGACY_AUDIT_RELPATH
    if not path.exists() or path.is_symlink() or not path.is_file():
        raise LegacyCompletionAuditError(
            f"legacy completion audit {FRACTIONAL_LEGACY_AUDIT_RELPATH} is missing or not a file"
        )
    committed = path.read_bytes()
    try:
        require_canonical_file_bytes(committed, "legacy completion audit")
        strict_json_loads(committed)
    except ValueError as exc:
        raise LegacyCompletionAuditError(
            f"legacy completion audit is not canonical: {exc}"
        ) from exc
    if committed != render_legacy_completion_audit(root):
        raise LegacyCompletionAuditError(
            "committed legacy completion audit does not re-derive from the live registry/manifest"
        )
    return (
        "legacy_audit_canonical",
        "legacy_audit_rederives",
        "run001_has_no_completion_intent",
        "published_run_replays",
    )
