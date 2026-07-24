"""Prospective cohort manifest + maturity tests (M3D section 18/21).

The real committed manifest reproduces, binds every governance and acquisition
provenance hash, and holds the terminal governance state: immature, evaluation
not authorized, and all four evaluation flags false. Maturity is assessed from
committed evidence alone and never authorizes evaluation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
from eth_research.m3d.update_attempts import UPDATE_ATTEMPTS_PATH

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def _accepted_base() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((REPO_ROOT / "research/m3e/accepted_base.json").read_text())
    return doc


def _acceptance_documents() -> list[dict[str, Any]]:
    """Every committed acceptance record, in registry order, binding cross-checked."""
    registry = (REPO_ROOT / "research/m3e/acceptance_registry.jsonl").read_text()
    records = [json.loads(line) for line in registry.splitlines() if line]
    documents: list[dict[str, Any]] = []
    for entry in records:
        if entry.get("entry_kind") != "acceptance":
            continue
        proposal_id = str(entry["proposal_id"])
        doc = json.loads(
            (REPO_ROOT / "research/m3e/acceptances" / proposal_id / "acceptance.json").read_text()
        )
        assert doc["proposal_id"] == proposal_id
        assert doc["acceptance_sha256"] == entry["acceptance_sha256"]
        documents.append(doc)
    assert documents, "the acceptance registry must record the accepted growth"
    return documents


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
    assert provenance["update_attempts_ledger_sha256"] == up.hash_file(
        REPO_ROOT, UPDATE_ATTEMPTS_PATH
    )

    # The cohort fingerprint is the governance-accepted one, cross-sourced from the
    # accepted base and the newest committed acceptance record.
    acceptances = _acceptance_documents()
    assert (
        provenance["canonical_content_fingerprint"]
        == (_accepted_base()["canonical_content_fingerprint"])
    )
    assert (
        provenance["canonical_content_fingerprint"]
        == (acceptances[-1]["new_accepted"]["canonical_content_fingerprint"])
    )

    # Genesis history stays anchored: the first acceptance grew the 3-row genesis
    # cohort, whose fingerprint the committed genesis segment still carries.
    genesis_pins = acceptances[0]["previous_accepted"]
    assert genesis_pins["row_count"] == 3
    segment_records = [
        json.loads(line) for line in (REPO_ROOT / SEGMENTS_PATH).read_text().splitlines() if line
    ]
    genesis_segment = next(r for r in segment_records if r.get("entry_kind") == "segment")
    assert genesis_segment["row_count"] == 3
    assert (
        genesis_segment["canonical_content_fingerprint"]
        == genesis_pins["canonical_content_fingerprint"]
    )


def test_manifest_records_all_three_ledgers_empty() -> None:
    manifest = verify_cohort_manifest(REPO_ROOT)
    assert manifest["evaluation_ledger"]["byte_count"] == 0
    for facts in manifest["sealed_ledgers"].values():
        assert facts["byte_count"] == 0


def test_maturity_is_immature_with_remaining_rows() -> None:
    maturity = assess_prospective_maturity(REPO_ROOT)
    # The accepted row count is derived from the committed accepted base and
    # cross-checked against the newest governance acceptance record.
    row_count = int(_accepted_base()["row_count"])
    assert _acceptance_documents()[-1]["new_accepted"]["row_count"] == row_count
    assert maturity["maturity_state"] == "immature"
    assert maturity["row_count"] == row_count
    assert maturity["minimum_maturity_rows"] == 365
    assert row_count < 365
    assert maturity["remaining_rows"] == 365 - row_count
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
