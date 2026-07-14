"""Strictness + honesty of the adaptive research lineage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.m3c.candidate import CANDIDATE_FINGERPRINT, M3C_CANDIDATE_ID
from eth_research.m3c.lineage import (
    EXPECTED_CANDIDATE_FAMILY_COUNT,
    ResearchLineage,
    build_m3c_lineage,
)
from eth_research.m3c.validation import canonical_json_bytes, load_canonical_json

REPO = Path(eth_research.__file__).resolve().parents[2]
_REJECT = (ValueError, TypeError)


def test_committed_lineage_round_trips_byte_identically() -> None:
    lin = ResearchLineage.from_dict(
        load_canonical_json(REPO / "research/m3c/research_lineage.json")
    )
    assert (
        canonical_json_bytes(lin.to_dict())
        == (REPO / "research/m3c/research_lineage.json").read_bytes()
    )
    assert lin == build_m3c_lineage()


def test_exactly_five_candidate_families_and_two_benchmarks() -> None:
    lin = build_m3c_lineage()
    assert lin.candidate_family_count == EXPECTED_CANDIDATE_FAMILY_COUNT == 5
    assert sum(e.kind == "candidate" for e in lin.entries) == 5
    assert sum(e.kind == "benchmark" for e in lin.entries) == 2


def test_new_candidate_entry_binds_the_composed_fingerprint_and_is_m3c() -> None:
    entry = next(e for e in build_m3c_lineage().entries if e.family_id == M3C_CANDIDATE_ID)
    assert entry.canonical_fingerprint == CANDIDATE_FINGERPRINT
    assert entry.first_evaluation_milestone == "M3C"
    assert "ADAPTIVELY MOTIVATED" in entry.adaptive_relationship


def test_historical_bindings_use_full_hashes_and_real_commits() -> None:
    lin = build_m3c_lineage()
    for e in lin.entries:
        assert len(e.immutable_result_sha256) == 64  # full sha256, never abbreviated
        assert len(e.first_evaluation_commit) == 40  # full git sha-1 (or zero sentinel)
        assert e.immutable_result_path.startswith("research/")


def test_wrong_candidate_family_count_is_rejected() -> None:
    data = build_m3c_lineage().to_dict()
    data["candidate_family_count"] = 4
    with pytest.raises(_REJECT):
        ResearchLineage.from_dict(data)


def test_duplicate_fingerprint_is_rejected() -> None:
    data: Any = build_m3c_lineage().to_dict()
    data["entries"][2]["canonical_fingerprint"] = data["entries"][3]["canonical_fingerprint"]
    with pytest.raises(_REJECT):
        ResearchLineage.from_dict(data)


def test_forged_new_candidate_fingerprint_is_rejected() -> None:
    data = build_m3c_lineage().to_dict()
    data["new_candidate_fingerprint"] = "0" * 64
    with pytest.raises(_REJECT):
        ResearchLineage.from_dict(data)


def test_benchmark_cannot_be_a_budgeted_candidate() -> None:
    data: Any = build_m3c_lineage().to_dict()
    bench = next(e for e in data["entries"] if e["kind"] == "benchmark")
    bench["counts_against_candidate_budget"] = True
    with pytest.raises(_REJECT):
        ResearchLineage.from_dict(data)


def test_unknown_or_missing_key_is_rejected() -> None:
    data = build_m3c_lineage().to_dict()
    data["extra"] = 1
    with pytest.raises(_REJECT):
        ResearchLineage.from_dict(data)
    data2 = build_m3c_lineage().to_dict()
    del data2["candidate_family_count"]
    with pytest.raises(_REJECT):
        ResearchLineage.from_dict(data2)


def test_bool_as_int_and_abbreviated_hash_are_rejected() -> None:
    data: Any = build_m3c_lineage().to_dict()
    data["entries"][0]["immutable_result_sha256"] = "abc123"  # too short
    with pytest.raises(_REJECT):
        ResearchLineage.from_dict(data)
    data2: Any = build_m3c_lineage().to_dict()
    data2["entries"][2]["formally_promotion_tested"] = 1  # bool expected, int rejected
    with pytest.raises(_REJECT):
        ResearchLineage.from_dict(data2)
