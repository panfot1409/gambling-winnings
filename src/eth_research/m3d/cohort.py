"""Prospective cohort manifest and maturity assessment.

``research/m3d/prospective_manifest.json`` is the single provenance anchor for the
prospective ETH-USD daily cohort. It binds the cohort's identity and boundaries,
its row count and the fixed 365-observation maturity floor, the nominal maturity
bounds, every governance and acquisition provenance hash (plans, receipts, raw
bundles, canonical content, quality, segment chain, reacquisition audit, protocol,
program snapshot, multiplicity, data-use, exhaustion), the three
evaluation/sealed-ledger facts, and the explicit governance flags. Its terminal
state is ``maturity_state: immature`` and ``evaluation_authorized: false``.

Maturity is a *necessary* condition for eligibility, never a sufficient one: M3D
contains no evaluation function, computes no strategy, metric, ranking, or
decision, and no override can make the cohort mature or authorized while it holds
fewer than 365 completed observations.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.m3d import _upstream as up
from eth_research.m3d.acquisition_plan import AUDIT_ATTEMPT_ID, GENESIS_ATTEMPT_ID
from eth_research.m3d.candidate_catalog import CATALOG_PATH
from eth_research.m3d.data_use import LEDGER_PATH as DATA_USE_PATH
from eth_research.m3d.exhaustion import DECISION_PATH as EXHAUSTION_PATH
from eth_research.m3d.multiplicity import LEDGER_PATH as MULTIPLICITY_PATH
from eth_research.m3d.program_history import SNAPSHOT_PATH
from eth_research.m3d.protocol import (
    COHORT_START,
    COINBASE_ENDPOINT,
    MINIMUM_MATURITY_ROWS,
    NOMINAL_MATURITY_EXCLUSIVE_END,
    NOMINAL_MATURITY_LAST_OPEN,
    PROTOCOL_PATH,
)
from eth_research.m3d.quality import QUALITY_PATH, build_prospective_quality_bytes
from eth_research.m3d.raw_bundle import (
    build_raw_bundles,
    cohort_canonical_fingerprint,
    combined_canonical_rows,
)
from eth_research.m3d.reacquisition_audit import (
    REACQUISITION_AUDIT_PATH,
    build_reacquisition_audit_bytes,
)
from eth_research.m3d.segment import SEGMENTS_PATH
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_json_bytes,
    canonical_sha256,
    load_canonical_json_bytes,
    require_exact,
    require_mapping,
    strict_json_loads,
)

MANIFEST_PATH = "research/m3d/prospective_manifest.json"
MANIFEST_SCHEMA_VERSION = 1
MANIFEST_KIND = "prospective_cohort_manifest"
_INTERVAL_SECONDS = 86400
_PRODUCT = "ETH-USD"
_VENUE = "coinbase-exchange"


def assess_prospective_maturity(repo_root: str | Path) -> dict[str, Any]:
    """Assess maturity from committed acquisition evidence alone (never authorizes).

    Maturity requires at least 365 completed observations, the fixed cohort start,
    a continuous daily cadence, zero structural quality errors, and a matching
    independent reacquisition. Even a mature cohort is **not** evaluation
    authorized — M3D authorizes nothing.
    """
    bundles = build_raw_bundles(repo_root, GENESIS_ATTEMPT_ID)
    rows = combined_canonical_rows(bundles)
    row_count = len(rows)
    opens = [pd.Timestamp(row[0]) for row in rows]
    contiguous = all(
        (later - earlier).total_seconds() == _INTERVAL_SECONDS for earlier, later in pairwise(opens)
    )
    quality = require_mapping(
        "quality", strict_json_loads(build_prospective_quality_bytes(repo_root))
    )
    audit = require_mapping(
        "reacquisition_audit", strict_json_loads(build_reacquisition_audit_bytes(repo_root))
    )
    conditions = {
        "row_count_at_least_floor": row_count >= MINIMUM_MATURITY_ROWS,
        "starts_at_cohort_start": bool(rows) and rows[0][0] == COHORT_START,
        "contiguous_daily": contiguous,
        "no_structural_errors": int(quality["total_errors"]) == 0,
        "canonical_reacquisition_match": audit["canonical_content_match"] is True,
    }
    return {
        "row_count": row_count,
        "minimum_maturity_rows": MINIMUM_MATURITY_ROWS,
        "remaining_rows": max(0, MINIMUM_MATURITY_ROWS - row_count),
        "maturity_conditions": {name: conditions[name] for name in sorted(conditions)},
        "maturity_state": "mature" if all(conditions.values()) else "immature",
        # M3D never authorizes evaluation; maturity is necessary, not sufficient.
        "evaluation_authorized": False,
    }


def _acquisition_provenance(repo_root: str | Path, attempt_id: str) -> dict[str, Any]:
    raw_dir = f"research/m3d/raw/coinbase/{attempt_id}"
    (bundle,) = build_raw_bundles(repo_root, attempt_id)
    return {
        "attempt_id": attempt_id,
        "plan_sha256": up.hash_file(repo_root, f"{raw_dir}/acquisition_plan.json"),
        "receipt_sha256": up.hash_file(repo_root, f"{raw_dir}/acquisition_receipt.json"),
        "raw_sha256": bundle.raw_sha256,
        "raw_bundle_fingerprint": bundle.canonical_content_fingerprint,
    }


def _build_document(repo_root: str | Path) -> dict[str, Any]:
    from eth_research.m3d import M3D_PACKAGE_VERSION

    bundles = build_raw_bundles(repo_root, GENESIS_ATTEMPT_ID)
    rows = combined_canonical_rows(bundles)
    if not rows:
        raise M3DValidationError("cannot build a cohort manifest with no rows")
    maturity = assess_prospective_maturity(repo_root)
    sealed = up.sealed_ledger_facts(repo_root)
    prospective_ledger = up.ledger_facts(repo_root, up.PROSPECTIVE_EVALUATION_LEDGER)
    if prospective_ledger["byte_count"] != 0:
        raise M3DValidationError("prospective evaluation ledger must be byte-empty (HARD STOP)")
    for name, facts in sealed.items():
        if facts["byte_count"] != 0:
            raise M3DValidationError(f"sealed ledger {name} must stay byte-empty (HARD STOP)")

    provenance = {
        "genesis_acquisition": _acquisition_provenance(repo_root, GENESIS_ATTEMPT_ID),
        "audit_acquisition": _acquisition_provenance(repo_root, AUDIT_ATTEMPT_ID),
        "canonical_content_fingerprint": cohort_canonical_fingerprint(bundles),
        "quality_report_sha256": up.hash_file(repo_root, QUALITY_PATH),
        "segment_chain_sha256": up.hash_file(repo_root, SEGMENTS_PATH),
        "reacquisition_audit_sha256": up.hash_file(repo_root, REACQUISITION_AUDIT_PATH),
        "protocol_sha256": up.hash_file(repo_root, PROTOCOL_PATH),
        "program_snapshot_sha256": up.hash_file(repo_root, SNAPSHOT_PATH),
        "specification_catalog_sha256": up.hash_file(repo_root, CATALOG_PATH),
        "multiplicity_ledger_sha256": up.hash_file(repo_root, MULTIPLICITY_PATH),
        "data_use_ledger_sha256": up.hash_file(repo_root, DATA_USE_PATH),
        "exhaustion_decision_sha256": up.hash_file(repo_root, EXHAUSTION_PATH),
    }

    document: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "package_version": M3D_PACKAGE_VERSION,
        "identity": {
            "product": _PRODUCT,
            "venue": _VENUE,
            "interval_seconds": _INTERVAL_SECONDS,
            "endpoint": COINBASE_ENDPOINT,
        },
        "cohort_start": COHORT_START,
        "first_open": rows[0][0],
        "last_open": rows[-1][0],
        "row_count": len(rows),
        "canonical_content_fingerprint": cohort_canonical_fingerprint(bundles),
        "m2b_final_open": up.M2B_LAST_OPEN,
        "minimum_maturity_rows": MINIMUM_MATURITY_ROWS,
        "nominal_maturity_last_open": NOMINAL_MATURITY_LAST_OPEN,
        "nominal_maturity_exclusive_end": NOMINAL_MATURITY_EXCLUSIVE_END,
        "remaining_rows": maturity["remaining_rows"],
        "maturity_conditions": maturity["maturity_conditions"],
        "maturity_state": maturity["maturity_state"],
        "evaluation_authorized": False,
        "strategy_evaluation_performed": False,
        "candidate_declared": False,
        "performance_metrics_computed": False,
        "promotion_decision_exists": False,
        "provenance": provenance,
        "evaluation_ledger": {
            "path": up.PROSPECTIVE_EVALUATION_LEDGER,
            "byte_count": prospective_ledger["byte_count"],
            "event_count": prospective_ledger["event_count"],
        },
        "sealed_ledgers": sealed,
    }
    return document


def build_cohort_manifest_bytes(repo_root: str | Path) -> bytes:
    """Deterministically render the prospective cohort manifest bytes."""
    return canonical_json_bytes(_build_document(repo_root))


def cohort_manifest_sha256(repo_root: str | Path) -> str:
    return canonical_sha256(_build_document(repo_root))


def verify_cohort_manifest(repo_root: str | Path) -> dict[str, Any]:
    """Verify the committed manifest reproduces and holds the terminal governance state."""
    raw, doc = load_canonical_json_bytes(Path(repo_root) / MANIFEST_PATH, "prospective_manifest")
    mapping = require_mapping("prospective_manifest", doc)
    if raw != build_cohort_manifest_bytes(repo_root):
        raise M3DValidationError("committed cohort manifest does not match the rebuilt manifest")
    require_exact("maturity_state", str(mapping["maturity_state"]), "immature")
    require_exact("evaluation_authorized", bool(mapping["evaluation_authorized"]), False)
    for flag in (
        "strategy_evaluation_performed",
        "candidate_declared",
        "performance_metrics_computed",
        "promotion_decision_exists",
    ):
        require_exact(flag, bool(mapping[flag]), False)
    return mapping


def build_prospective_publication_blobs(repo_root: str | Path) -> list[tuple[str, bytes]]:
    """The full ordered publication bundle (completeness marker last)."""
    from eth_research.m3d.publication import (
        PUBLICATION_MANIFEST_PATH,
        build_publication_manifest_bytes,
    )
    from eth_research.m3d.segment import build_prospective_segments_bytes

    bundle: list[tuple[str, bytes]] = [
        (SEGMENTS_PATH, build_prospective_segments_bytes(repo_root)),
        (REACQUISITION_AUDIT_PATH, build_reacquisition_audit_bytes(repo_root)),
        (QUALITY_PATH, build_prospective_quality_bytes(repo_root)),
        (MANIFEST_PATH, build_cohort_manifest_bytes(repo_root)),
    ]
    return [*bundle, (PUBLICATION_MANIFEST_PATH, build_publication_manifest_bytes(bundle))]


def publish_prospective_cohort(repo_root: str | Path) -> list[tuple[str, str]]:
    """Transactionally (re)publish the whole prospective evidence bundle."""
    from eth_research.m3d.publication import publish_bundle

    return publish_bundle(repo_root, build_prospective_publication_blobs(repo_root))


def verify_prospective_publication(repo_root: str | Path) -> dict[str, Any]:
    """Verify every published artifact rebuilds and the completeness marker binds them."""
    from eth_research.m3d.publication import verify_publication_manifest
    from eth_research.m3d.quality import verify_prospective_quality
    from eth_research.m3d.reacquisition_audit import verify_reacquisition_audit
    from eth_research.m3d.segment import verify_prospective_segments

    verify_prospective_segments(repo_root)
    verify_reacquisition_audit(repo_root)
    verify_prospective_quality(repo_root)
    manifest = verify_cohort_manifest(repo_root)
    non_marker = build_prospective_publication_blobs(repo_root)[:-1]
    verify_publication_manifest(repo_root, non_marker)
    return manifest
