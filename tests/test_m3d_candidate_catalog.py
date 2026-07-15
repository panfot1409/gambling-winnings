"""Tests for the M3D research specification catalog (anti-orphan + strict schema)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from eth_research.m3d import candidate_catalog as cc
from eth_research.m3d.candidate_catalog import (
    CATALOG_PATH,
    ResearchSpecificationCatalog,
    build_research_specification_catalog,
    verify_research_specification_catalog,
)

_REPO = Path(__file__).resolve().parents[1]


def _built() -> dict:
    return copy.deepcopy(build_research_specification_catalog(_REPO).document)


def _entry(doc: dict, identifier: str) -> dict:
    return next(s for s in doc["strategies"] if s["identifier"] == identifier)


def test_build_is_deterministic_and_committed_matches() -> None:
    a = build_research_specification_catalog(_REPO).to_json_bytes()
    b = build_research_specification_catalog(_REPO).to_json_bytes()
    assert a == b
    assert (_REPO / CATALOG_PATH).read_bytes() == a
    verify_research_specification_catalog(_REPO)


def test_all_eight_identifiers_present_exactly_once() -> None:
    doc = _built()
    ids = [s["identifier"] for s in doc["strategies"]]
    assert len(ids) == len(set(ids)) == 8


def test_candidate_is_rejected_and_ineligible() -> None:
    cand = _entry(_built(), "dual_horizon_trend_63_252_vol_target_30d_50pct")
    assert cand["role"] == "candidate"
    assert cand["status"] == "rejected_for_development_gate_promotion"
    assert cand["promotion_eligible"] is False
    assert cand["may_evaluate_again"] is False
    assert cand["rejection_reason"] == "rejected_for_development_gate_promotion"


def test_cash_and_buy_and_hold_are_benchmarks() -> None:
    doc = _built()
    assert _entry(doc, "cash")["role"] == "benchmark"
    assert _entry(doc, "buy_and_hold")["role"] == "benchmark"
    assert _entry(doc, "cash")["promotion_eligible"] is False


def test_no_strategy_is_promotion_eligible() -> None:
    assert all(not s["promotion_eligible"] for s in _built()["strategies"])


def test_anti_orphan_missing_classification_fails(monkeypatch) -> None:
    reduced = dict(cc._CLASSIFICATION)
    reduced.pop("donchian_55_20")
    monkeypatch.setattr(cc, "_CLASSIFICATION", reduced)
    with pytest.raises(ValueError, match="discovered but not classified"):
        build_research_specification_catalog(_REPO)


def test_reverse_invariant_extra_classification_fails(monkeypatch) -> None:
    extra = dict(cc._CLASSIFICATION)
    extra["ghost_strategy"] = dict(extra["cash"])
    monkeypatch.setattr(cc, "_CLASSIFICATION", extra)
    with pytest.raises(ValueError, match="not found in artifacts"):
        build_research_specification_catalog(_REPO)


def test_from_mapping_rejects_unknown_key() -> None:
    doc = _built()
    doc["strategies"][0]["surprise"] = 1
    with pytest.raises(ValueError, match="unknown keys"):
        ResearchSpecificationCatalog.from_mapping(doc)


def test_from_mapping_rejects_benchmark_relabeled_as_candidate() -> None:
    doc = _built()
    _entry(doc, "cash")["role"] = "candidate"
    with pytest.raises(ValueError, match="must be a benchmark"):
        ResearchSpecificationCatalog.from_mapping(doc)


def test_from_mapping_rejects_fingerprint_tamper() -> None:
    doc = _built()
    _entry(doc, "donchian_55_20")["parameters"]["entry_channel"] = 999
    with pytest.raises(ValueError, match="specification_fingerprint mismatch"):
        ResearchSpecificationCatalog.from_mapping(doc)


def test_from_mapping_rejects_summary_mismatch() -> None:
    doc = _built()
    doc["summary"]["candidate_count"] = 0
    with pytest.raises(ValueError, match="candidate_count mismatch"):
        ResearchSpecificationCatalog.from_mapping(doc)


def test_from_mapping_rejects_unsorted_strategies() -> None:
    doc = _built()
    doc["strategies"].reverse()
    with pytest.raises(ValueError, match="sorted by identifier"):
        ResearchSpecificationCatalog.from_mapping(doc)


def test_from_mapping_rejects_bool_as_int_count() -> None:
    doc = _built()
    _entry(doc, "cash")["completed_experiment_count"] = True
    with pytest.raises(ValueError, match="must be an integer"):
        ResearchSpecificationCatalog.from_mapping(doc)
