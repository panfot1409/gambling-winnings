"""Validation-stage research decision: strict model + honest, reproducible record."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.decision import (
    REJECTED_FOR_TEST_PROMOTION,
    ResearchDecision,
    build_research_decision_from_results,
    load_research_decision,
    render_research_decision,
)
from eth_research.protocol import BenchmarkResults

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
RESULTS_PATH = REPO_ROOT / "research/m2b/train_validation_results.json"
DECISION_JSON = REPO_ROOT / "research/m2b/validation_decision.json"
DECISION_MD = REPO_ROOT / "research/m2b/validation_decision.md"

pytestmark = pytest.mark.skipif(
    not RESULTS_PATH.is_file(), reason="committed train/validation results not present"
)


def committed_results() -> BenchmarkResults:
    return BenchmarkResults.from_json_bytes(RESULTS_PATH.read_bytes())


def make_decision(**overrides: Any) -> ResearchDecision:
    base = build_research_decision_from_results(committed_results())
    if not overrides:
        return base
    payload = json.loads(base.to_json_bytes())
    payload.update(overrides)
    return ResearchDecision.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestDecisionContent:
    def test_rejects_sma_for_test_promotion_without_touching_test(self) -> None:
        decision = build_research_decision_from_results(committed_results())
        assert decision.decision == REJECTED_FOR_TEST_PROMOTION
        assert decision.test_accessed is False
        assert decision.parameter_changes == "none"
        assert decision.validation_candidate_return < decision.validation_benchmark_return

    def test_binds_the_results_provenance(self) -> None:
        results = committed_results()
        decision = build_research_decision_from_results(results)
        assert decision.protocol_sha256 == results.protocol_sha256
        assert decision.dataset_content_fingerprint == results.dataset_content_fingerprint
        assert decision.pre_registered_commit_sha == results.pre_registered_commit_sha

    def test_wording_is_specific_not_universal(self) -> None:
        rationale = build_research_decision_from_results(committed_results()).rationale
        assert "materially underperformed buy-and-hold in the validation period" in rationale
        # It must not overclaim that moving averages fail in general.
        assert "in general" in rationale  # the disclaimer, phrased as a negation
        assert "fail in general" in rationale
        assert "fails to generalize" not in rationale


class TestReproducibility:
    def test_committed_json_matches(self) -> None:
        generated = build_research_decision_from_results(committed_results()).to_json_bytes()
        assert DECISION_JSON.read_bytes() == generated

    def test_committed_markdown_matches(self) -> None:
        decision = build_research_decision_from_results(committed_results())
        assert DECISION_MD.read_text(encoding="utf-8") == render_research_decision(decision)

    def test_round_trips_byte_stably(self) -> None:
        decision = load_research_decision(DECISION_JSON)
        assert decision.to_json_bytes() == DECISION_JSON.read_bytes()


class TestStrictValidation:
    def test_tampered_gap_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="validation_gap_pp"):
            make_decision(validation_gap_pp=0.0)

    def test_test_accessed_true_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="test_accessed must be false"):
            make_decision(test_accessed=True)

    def test_parameter_change_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="parameter_changes is pinned to 'none'"):
            make_decision(parameter_changes="fast=10")

    def test_rejection_requires_underperformance(self) -> None:
        # Swap the returns so the candidate "beats" the benchmark: a rejection
        # decision then makes no sense and must be refused.
        results = committed_results()
        base = build_research_decision_from_results(results)
        payload = json.loads(base.to_json_bytes())
        payload["validation_candidate_return"] = base.validation_benchmark_return
        payload["validation_benchmark_return"] = base.validation_candidate_return
        payload["validation_gap_pp"] = (
            payload["validation_candidate_return"] - payload["validation_benchmark_return"]
        ) * 100.0
        with pytest.raises(ValueError, match="requires the candidate to underperform"):
            ResearchDecision.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(DECISION_JSON.read_bytes())
        payload["extra"] = 1
        with pytest.raises(ValueError, match=r"unknown=\['extra'\]"):
            ResearchDecision.from_json_bytes(json.dumps(payload).encode("utf-8"))
