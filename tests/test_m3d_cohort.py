"""Prospective cohort manifest + maturity tests (M3D section 18/21).

The real committed manifest reproduces, binds every governance and acquisition
provenance hash, and holds the terminal governance state: immature, evaluation
not authorized, and all four evaluation flags false. Maturity is assessed from
committed evidence alone and never authorizes evaluation.
"""

from __future__ import annotations

from pathlib import Path

import eth_research
from eth_research.m3d import _upstream as up
from eth_research.m3d.cohort import (
    MANIFEST_PATH,
    assess_prospective_maturity,
    build_prospective_publication_blobs,
    verify_cohort_manifest,
    verify_prospective_publication,
)
from eth_research.m3d.data_use import LEDGER_PATH as DATA_USE_PATH
from eth_research.m3d.publication import PUBLICATION_MANIFEST_PATH
from eth_research.m3d.quality import QUALITY_PATH
from eth_research.m3d.segment import SEGMENTS_PATH

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def test_real_publication_verifies_the_terminal_governance_state() -> None:
    manifest = verify_prospective_publication(REPO_ROOT)
    assert manifest["maturity_state"] == "immature"
    assert manifest["evaluation_authorized"] is False
    assert manifest["strategy_evaluation_performed"] is False
    assert manifest["candidate_declared"] is False
    assert manifest["performance_metrics_computed"] is False
    assert manifest["promotion_decision_exists"] is False


def test_manifest_binds_committed_governance_hashes() -> None:
    manifest = verify_cohort_manifest(REPO_ROOT)
    provenance = manifest["provenance"]
    assert provenance["data_use_ledger_sha256"] == up.hash_file(REPO_ROOT, DATA_USE_PATH)
    assert provenance["quality_report_sha256"] == up.hash_file(REPO_ROOT, QUALITY_PATH)
    assert provenance["segment_chain_sha256"] == up.hash_file(REPO_ROOT, SEGMENTS_PATH)
    assert (
        provenance["canonical_content_fingerprint"]
        == "bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507"
    )


def test_manifest_records_all_three_ledgers_empty() -> None:
    manifest = verify_cohort_manifest(REPO_ROOT)
    assert manifest["evaluation_ledger"]["byte_count"] == 0
    for facts in manifest["sealed_ledgers"].values():
        assert facts["byte_count"] == 0


def test_maturity_is_immature_with_remaining_rows() -> None:
    maturity = assess_prospective_maturity(REPO_ROOT)
    assert maturity["maturity_state"] == "immature"
    assert maturity["row_count"] == 3
    assert maturity["minimum_maturity_rows"] == 365
    assert maturity["remaining_rows"] == 362
    assert maturity["evaluation_authorized"] is False
    assert maturity["maturity_conditions"]["row_count_at_least_floor"] is False
    # The other conditions already hold — only the observation count is missing.
    assert maturity["maturity_conditions"]["starts_at_cohort_start"] is True
    assert maturity["maturity_conditions"]["canonical_reacquisition_match"] is True


def test_publication_bundle_has_five_ordered_artifacts_with_marker_last() -> None:
    blobs = build_prospective_publication_blobs(REPO_ROOT)
    relpaths = [rel for rel, _ in blobs]
    assert relpaths == [
        SEGMENTS_PATH,
        "research/m3d/reacquisition_audit.json",
        QUALITY_PATH,
        MANIFEST_PATH,
        PUBLICATION_MANIFEST_PATH,
    ]
