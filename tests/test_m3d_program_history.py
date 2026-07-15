"""Tests for the M3D research-program snapshot (build/verify + strict schema)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from eth_research.m3d import _upstream as up
from eth_research.m3d.program_history import (
    SNAPSHOT_PATH,
    ResearchProgramSnapshot,
    build_research_program_snapshot,
    verify_research_program_snapshot,
)
from eth_research.m3d.validation import canonical_json_bytes

_REPO = Path(__file__).resolve().parents[1]


def _built_doc() -> dict:
    return copy.deepcopy(build_research_program_snapshot(_REPO).document)


def test_build_is_deterministic() -> None:
    a = build_research_program_snapshot(_REPO).to_json_bytes()
    b = build_research_program_snapshot(_REPO).to_json_bytes()
    assert a == b


def test_committed_snapshot_matches_build_and_verifies() -> None:
    committed = (_REPO / SNAPSHOT_PATH).read_bytes()
    assert committed == build_research_program_snapshot(_REPO).to_json_bytes()
    v = verify_research_program_snapshot(_REPO)
    assert v.document["milestones"]["m3c"]["outcome"] == up.M3C_REJECTED_OUTCOME
    assert v.document["conclusions"]["promotable_strategy_exists"] is False


def test_snapshot_binds_all_upstream_anchor_hashes() -> None:
    doc = _built_doc()
    for milestone, anchors in up.ANCHORS.items():
        assert set(doc["milestones"][milestone]["artifacts"]) == set(anchors)


def test_from_mapping_rejects_unknown_key() -> None:
    doc = _built_doc()
    doc["surprise"] = 1
    with pytest.raises(ValueError, match="unknown keys"):
        ResearchProgramSnapshot.from_mapping(doc)


def test_from_mapping_rejects_missing_key() -> None:
    doc = _built_doc()
    del doc["conclusions"]
    with pytest.raises(ValueError, match="missing keys"):
        ResearchProgramSnapshot.from_mapping(doc)


def test_from_mapping_rejects_changed_m3c_outcome() -> None:
    doc = _built_doc()
    doc["milestones"]["m3c"]["outcome"] = "promoted"
    with pytest.raises(ValueError, match="M3C outcome must remain"):
        ResearchProgramSnapshot.from_mapping(doc)


def test_from_mapping_rejects_false_promotability() -> None:
    doc = _built_doc()
    doc["conclusions"]["promotable_strategy_exists"] = True
    with pytest.raises(ValueError, match="must be exactly False"):
        ResearchProgramSnapshot.from_mapping(doc)


def test_from_mapping_rejects_gate_access_claim() -> None:
    doc = _built_doc()
    doc["milestones"]["m3a"]["gate_accessed"] = True
    with pytest.raises(ValueError, match="must be exactly False"):
        ResearchProgramSnapshot.from_mapping(doc)


def test_from_mapping_rejects_nonempty_sealed_ledger() -> None:
    doc = _built_doc()
    doc["sealed_ledgers"]["development_gate"]["byte_count"] = 12
    with pytest.raises(ValueError, match="byte-empty"):
        ResearchProgramSnapshot.from_mapping(doc)


def test_from_mapping_rejects_bool_as_int() -> None:
    doc = _built_doc()
    doc["sealed_ledgers"]["final_holdout"]["event_count"] = True
    with pytest.raises(ValueError, match="must be an integer"):
        ResearchProgramSnapshot.from_mapping(doc)


def test_from_mapping_rejects_wrong_empty_sha() -> None:
    doc = _built_doc()
    doc["sealed_ledgers"]["final_holdout"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="empty SHA-256"):
        ResearchProgramSnapshot.from_mapping(doc)


def test_verify_detects_committed_drift() -> None:
    path = _REPO / SNAPSHOT_PATH
    original = path.read_bytes()
    try:
        doc = json.loads(original)
        name = sorted(doc["milestones"]["m2b"]["artifacts"])[0]
        current = doc["milestones"]["m2b"]["artifacts"][name]
        doc["milestones"]["m2b"]["artifacts"][name] = "0" * 64 if current[0] != "0" else "f" * 64
        path.write_bytes(canonical_json_bytes(doc))
        with pytest.raises(ValueError, match="does not match the rebuilt"):
            verify_research_program_snapshot(_REPO)
    finally:
        path.write_bytes(original)
