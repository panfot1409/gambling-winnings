"""Independent reacquisition audit (genesis vs audit-002).

Binds the two independent prospective acquisitions — the genesis attempt and the
audit reacquisition over the identical request window — and records that their
canonical cohort content is reproducible: identical row count, zero differing
candles or fields, and matching canonical-content fingerprints, under distinct
plan hashes, source commits, and workflow runs. This is an integrity cross-check,
never a performance comparison; it computes and reports no strategy, return,
metric, ranking, or decision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3d.acquisition_plan import AUDIT_ATTEMPT_ID, GENESIS_ATTEMPT_ID
from eth_research.m3d.raw_bundle import (
    build_raw_bundles,
    cohort_canonical_fingerprint,
    combined_canonical_rows,
)
from eth_research.m3d.receipt import load_prospective_attempt_receipt
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_json_bytes,
    canonical_sha256,
    load_canonical_json_bytes,
    require_exact,
    require_mapping,
    require_str,
)

REACQUISITION_AUDIT_PATH = "research/m3d/reacquisition_audit.json"
REACQUISITION_AUDIT_SCHEMA_VERSION = 1
REACQUISITION_AUDIT_KIND = "prospective_reacquisition_audit"


def _attempt_facts(repo_root: str | Path, attempt_id: str) -> dict[str, Any]:
    raw_dir = f"research/m3d/raw/coinbase/{attempt_id}"
    receipt = load_prospective_attempt_receipt(
        Path(repo_root) / raw_dir / "acquisition_receipt.json"
    )
    bundles = build_raw_bundles(repo_root, attempt_id)
    return {
        "attempt_id": attempt_id,
        "plan_sha256": require_str("plan_sha256", receipt.plan_sha256),
        "receipt_sha256": up.hash_file(repo_root, f"{raw_dir}/acquisition_receipt.json"),
        "source_commit": require_str("source_commit", receipt.document["source_commit"]),
        "workflow_run_id": require_str("workflow_run_id", receipt.document["workflow_run_id"]),
        "canonical_content_fingerprint": cohort_canonical_fingerprint(bundles),
        "row_count": len(combined_canonical_rows(bundles)),
    }


def _build_document(repo_root: str | Path) -> dict[str, Any]:
    from eth_research.m3d import M3D_PACKAGE_VERSION

    genesis = _attempt_facts(repo_root, GENESIS_ATTEMPT_ID)
    audit = _attempt_facts(repo_root, AUDIT_ATTEMPT_ID)

    genesis_rows = combined_canonical_rows(build_raw_bundles(repo_root, GENESIS_ATTEMPT_ID))
    audit_rows = combined_canonical_rows(build_raw_bundles(repo_root, AUDIT_ATTEMPT_ID))
    row_count_match = len(genesis_rows) == len(audit_rows)
    if not row_count_match:
        raise M3DValidationError("genesis and audit row counts differ (HARD STOP)")
    differing = sum(
        1
        for g_row, a_row in zip(genesis_rows, audit_rows, strict=True)
        for g_field, a_field in zip(g_row, a_row, strict=True)
        if g_field != a_field
    )
    fingerprint_match = (
        genesis["canonical_content_fingerprint"] == audit["canonical_content_fingerprint"]
    )
    if not (row_count_match and fingerprint_match and differing == 0):
        raise M3DValidationError(
            "genesis and audit canonical content differ (HARD STOP): "
            f"row_count_match={row_count_match} fingerprint_match={fingerprint_match} "
            f"differing_fields={differing}"
        )
    # Independence is not established by distinct plan hashes alone — those differ
    # by attempt_id by construction. The two attempts must come from distinct
    # source commits and distinct workflow runs, which an offline verifier records
    # as the external-audit hook (the runs are separately reviewable in CI).
    if genesis["plan_sha256"] == audit["plan_sha256"]:
        raise M3DValidationError("genesis and audit must be independent attempts (distinct plans)")
    if genesis["source_commit"] == audit["source_commit"]:
        raise M3DValidationError(
            "genesis and audit must come from distinct source commits (not independent)"
        )
    if genesis["workflow_run_id"] == audit["workflow_run_id"]:
        raise M3DValidationError(
            "genesis and audit must come from distinct workflow runs (not independent)"
        )

    return {
        "schema_version": REACQUISITION_AUDIT_SCHEMA_VERSION,
        "kind": REACQUISITION_AUDIT_KIND,
        "package_version": M3D_PACKAGE_VERSION,
        "genesis": genesis,
        "audit": audit,
        "canonical_content_match": True,
        "row_count_match": True,
        "differing_fields": 0,
        "independent_plans": True,
    }


def build_reacquisition_audit_bytes(repo_root: str | Path) -> bytes:
    """Deterministically render the reacquisition-audit artifact bytes."""
    return canonical_json_bytes(_build_document(repo_root))


def reacquisition_audit_sha256(repo_root: str | Path) -> str:
    return canonical_sha256(_build_document(repo_root))


def verify_reacquisition_audit(repo_root: str | Path) -> dict[str, Any]:
    """Verify the committed reacquisition audit reproduces and asserts a match."""
    raw, doc = load_canonical_json_bytes(
        Path(repo_root) / REACQUISITION_AUDIT_PATH, "reacquisition_audit"
    )
    mapping = require_mapping("reacquisition_audit", doc)
    if raw != build_reacquisition_audit_bytes(repo_root):
        raise M3DValidationError("committed reacquisition audit does not match the rebuilt audit")
    require_exact("canonical_content_match", bool(mapping["canonical_content_match"]), True)
    require_exact("differing_fields", int(mapping["differing_fields"]), 0)
    return mapping
