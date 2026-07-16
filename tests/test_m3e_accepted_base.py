"""The accepted prospective base is M3E's verified trusted input (commit 3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eth_research
from eth_research.m3e.accepted_base import (
    ACCEPTED_BASE_PATH,
    build_accepted_base_bytes,
    build_accepted_base_document,
    load_accepted_base,
    verify_accepted_base,
)
from eth_research.m3e.validation import M3EValidationError, canonical_json_bytes

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def test_verify_accepted_base_binds_the_accepted_cohort() -> None:
    base = verify_accepted_base(REPO_ROOT)
    assert base.first_open == "2026-07-12T00:00:00Z"
    assert base.last_open == "2026-07-14T00:00:00Z"
    assert base.row_count == 3
    assert (
        base.canonical_content_fingerprint
        == "bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507"
    )
    assert base.document["maturity_state"] == "immature"
    assert base.document["evaluation_authorized"] is False


def test_build_is_deterministic_and_matches_committed() -> None:
    first = build_accepted_base_bytes(REPO_ROOT)
    second = build_accepted_base_bytes(REPO_ROOT)
    assert first == second
    assert first == (REPO_ROOT / ACCEPTED_BASE_PATH).read_bytes()


def test_the_three_ledgers_are_bound_byte_empty() -> None:
    base = verify_accepted_base(REPO_ROOT)
    ledgers = base.document["ledgers"]
    assert set(ledgers) == {"development_gate", "final_holdout", "prospective_evaluation"}
    empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    for facts in ledgers.values():
        assert facts["byte_count"] == 0
        assert facts["sha256"] == empty


def test_m3c_candidate_recorded_rejected_in_the_base() -> None:
    base = verify_accepted_base(REPO_ROOT)
    assert (
        base.document["provenance"]["m3c_candidate_decision_outcome"]
        == "rejected_for_development_gate_promotion"
    )


def test_load_round_trips_the_committed_snapshot() -> None:
    base = load_accepted_base(REPO_ROOT / ACCEPTED_BASE_PATH)
    assert base.base_sha256 == build_accepted_base_document(REPO_ROOT)["base_sha256"]


def test_a_tampered_base_hash_is_rejected(tmp_path: Path) -> None:
    doc = build_accepted_base_document(REPO_ROOT)
    doc["base_sha256"] = "0" * 64  # forge the self-hash
    path = tmp_path / "accepted_base.json"
    path.write_bytes(canonical_json_bytes(doc))
    with pytest.raises(M3EValidationError, match="base_sha256 does not match"):
        load_accepted_base(path)


def test_a_tampered_field_breaks_the_self_hash(tmp_path: Path) -> None:
    # Silently editing a bound field without recomputing the hash is caught.
    doc = build_accepted_base_document(REPO_ROOT)
    doc["row_count"] = 4  # a lie: the accepted cohort holds 3 rows
    path = tmp_path / "accepted_base.json"
    path.write_bytes(canonical_json_bytes(doc))
    with pytest.raises(M3EValidationError, match="base_sha256 does not match"):
        load_accepted_base(path)


def test_a_non_canonical_committed_snapshot_is_rejected(tmp_path: Path) -> None:
    doc = build_accepted_base_document(REPO_ROOT)
    path = tmp_path / "accepted_base.json"
    path.write_text(json.dumps(doc))  # compact, non-canonical bytes
    with pytest.raises(M3EValidationError):
        load_accepted_base(path)
