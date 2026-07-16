"""The M3C promotion decision is mechanical, strict, and byte-stable.

The decision logic is exercised on hand-built synthetic results (no engine) so
each criterion P1..P7 can be driven to a known pass/fail independently; the
real-grid path through ``evaluate_candidate_decision`` is covered in
``test_m3c_results``.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest

from eth_research.fractional.cost_model import SCENARIOS
from eth_research.m3c.candidate import M3C_CANDIDATE_ID, M3C_STRATEGY_NAMES
from eth_research.m3c.decision import (
    OUTCOME_ELIGIBLE,
    OUTCOME_REJECTED,
    PROMOTION_CRITERIA,
    CandidateDecision,
    DecisionError,
    evaluate_candidate_decision,
    load_m3c_decision,
)
from eth_research.m3c.results import (
    M3C_BUDGET_RELPATH as _BUDGET_RELPATH,
)
from eth_research.m3c.results import (
    M3C_EXPERIMENT_FAMILY,
    M3C_EXPERIMENT_ID,
    M3C_LINEAGE_RELPATH,
    M3C_PROTOCOL_RELPATH,
    M3C_RESULTS_SCHEMA_VERSION,
    PRIMARY_COMPARATOR,
    PRIMARY_SCENARIO,
    M3CBootstrapResult,
    M3CFoldCell,
    M3CFoldPairedComparison,
    M3CPSRDiagnostic,
    M3CResults,
    build_m3c_aggregates,
    render_m3c_report,
)
from eth_research.m3c.statistics import (
    M3C_BOOTSTRAP_ALGORITHM,
    M3C_BOOTSTRAP_CONFIDENCE,
    M3C_BOOTSTRAP_SEED,
)

_REJECT = (ValueError, TypeError)
_SCEN = tuple(s.name for s in SCENARIOS)
_BASE = PRIMARY_SCENARIO
_STRESSED = "causal_proxy_stressed"
_COMPAT = "compatibility_v1"
_BNH = "buy_and_hold"
_EPOCH = pd.Timestamp("2020-01-01", tz="UTC")

# Candidate base marked returns: 3 folds beat B&H (0.1), 2 do not -> P2 passes at exactly 3.
_CAND_BASE = (0.5, 0.5, 0.5, -0.1, -0.1)


def _marked_and_dd(strategy: str, scenario: str, fold: int) -> tuple[float, float]:
    if strategy == M3C_CANDIDATE_ID and scenario == _BASE:
        return _CAND_BASE[fold], -0.10
    if strategy == M3C_CANDIDATE_ID and scenario == _STRESSED:
        return 0.20, -0.12  # median > 0 -> P4 passes
    if strategy == M3C_CANDIDATE_ID and scenario == _COMPAT:
        return 0.30, -0.08
    if strategy == _BNH and scenario == _BASE:
        return 0.10, -0.30  # deeper drawdown than the candidate -> P3 passes
    return 0.0, 0.0


def _cell(strategy: str, scenario: str, fold: int) -> M3CFoldCell:
    marked, drawdown = _marked_and_dd(strategy, scenario, fold)
    rows = 226 if fold == 0 else 225
    equity = 10_000.0 * (1.0 + marked)
    return M3CFoldCell(
        strategy=strategy,
        cost_scenario=scenario,
        fold_index=fold,
        oos_first_open_time=_EPOCH + pd.Timedelta(days=fold * 225),
        oos_last_open_time=_EPOCH + pd.Timedelta(days=fold * 225 + rows - 1),
        oos_row_count=rows,
        context_row_count=252,
        initial_cash=10_000.0,
        marked_terminal_equity=equity,
        terminal_liquidation_equity=equity,
        marked_total_return=marked,
        liquidation_total_return=marked,
        annualized_return=marked * 0.5,
        annualized_volatility=0.4,
        sharpe_ratio=None,
        sortino_ratio=None,
        max_drawdown=drawdown,
        num_fills=0,
        num_partial_fills=0,
        num_no_fill_bars=0,
        average_requested_exposure=0.5,
        average_achieved_exposure=0.5,
        gross_notional=0.0,
        total_fees=0.0,
        spread_cost=0.0,
        base_slippage_cost=0.0,
        liquidity_impact_cost=0.0,
        total_modeled_cost=0.0,
        trace_commitment="0" * 64,
    )


def _synthetic_results(*, ci_lower: float = 0.001) -> M3CResults:
    """A fully valid M3CResults tuned so all seven criteria pass by construction."""
    cells = tuple(
        _cell(strategy, scenario, fold)
        for fold in range(5)
        for scenario in _SCEN
        for strategy in M3C_STRATEGY_NAMES
    )
    by = {(c.strategy, c.cost_scenario, c.fold_index): c for c in cells}
    paired = tuple(
        M3CFoldPairedComparison(
            fold_index=fold,
            oos_row_count=by[(M3C_CANDIDATE_ID, _BASE, fold)].oos_row_count,
            candidate_marked_return=by[(M3C_CANDIDATE_ID, _BASE, fold)].marked_total_return,
            buy_and_hold_marked_return=by[(_BNH, _BASE, fold)].marked_total_return,
            mean_daily_paired_log_excess=0.001,
            candidate_beats_bnh=(
                by[(M3C_CANDIDATE_ID, _BASE, fold)].marked_total_return
                > by[(_BNH, _BASE, fold)].marked_total_return
            ),
        )
        for fold in range(5)
    )
    observations = sum(by[(M3C_CANDIDATE_ID, _BASE, fold)].oos_row_count for fold in range(5))
    bootstrap = M3CBootstrapResult(
        algorithm=M3C_BOOTSTRAP_ALGORITHM,
        seed=M3C_BOOTSTRAP_SEED,
        resamples=20_000,
        confidence=M3C_BOOTSTRAP_CONFIDENCE,
        observation_count=observations,
        fold_count=5,
        block_lengths=(6, 6, 6, 6, 6),
        point_estimate=0.002,
        ci_lower=ci_lower,
        ci_upper=0.005,
    )
    psr = M3CPSRDiagnostic(
        observed_sharpe=0.1,
        benchmark_sharpe=0.0,
        sample_size=observations,
        skewness=0.0,
        kurtosis=3.0,
        psr=0.7,
    )
    return M3CResults(
        m3c_results_schema_version=M3C_RESULTS_SCHEMA_VERSION,
        experiment_id=M3C_EXPERIMENT_ID,
        experiment_family=M3C_EXPERIMENT_FAMILY,
        package_version="0.6.0",
        execution_code_commit_sha="a" * 40,
        registered_code_commit_sha="b" * 40,
        execution_source_tree_fingerprint="sha256:" + "c" * 64,
        protocol_path=M3C_PROTOCOL_RELPATH,
        protocol_sha256="d" * 64,
        lineage_path=M3C_LINEAGE_RELPATH,
        lineage_sha256="e" * 64,
        budget_path=_BUDGET_RELPATH,
        budget_sha256="f" * 64,
        frozen_m2_dossier_sha256="1" * 64,
        development_partition_sha256="2" * 64,
        research_train_content_fingerprint="sha256:" + "3" * 64,
        strategies=M3C_STRATEGY_NAMES,
        cost_scenarios=_SCEN,
        fold_cells=cells,
        aggregates=build_m3c_aggregates(cells),
        primary_scenario=PRIMARY_SCENARIO,
        primary_comparator=PRIMARY_COMPARATOR,
        paired_comparisons=paired,
        bootstrap=bootstrap,
        psr_diagnostic=psr,
        development_gate_event_count=0,
        final_holdout_event_count=0,
    )


class TestMechanicalOutcome:
    def test_all_criteria_pass_is_eligible(self) -> None:
        decision = evaluate_candidate_decision(_synthetic_results(), verification_passed=True)
        assert decision.outcome == OUTCOME_ELIGIBLE
        assert decision.eligible is True
        assert tuple(c.criterion_id for c in decision.criteria) == PROMOTION_CRITERIA
        assert all(c.passed for c in decision.criteria)
        assert decision.candidate_count == 1
        assert decision.verification_passed is True

    def test_p1_failure_rejects(self) -> None:
        decision = evaluate_candidate_decision(
            _synthetic_results(ci_lower=-0.001), verification_passed=True
        )
        assert decision.outcome == OUTCOME_REJECTED
        p1 = next(c for c in decision.criteria if c.criterion_id == "P1")
        assert p1.passed is False
        # the other criteria are unaffected -> only P1 flips the outcome
        assert [c.passed for c in decision.criteria if c.criterion_id != "P1"] == [True] * 6

    def test_p6_defaults_to_false_and_rejects(self) -> None:
        decision = evaluate_candidate_decision(_synthetic_results())
        assert decision.outcome == OUTCOME_REJECTED
        p6 = next(c for c in decision.criteria if c.criterion_id == "P6")
        assert p6.passed is False
        assert decision.verification_passed is False

    def test_records_no_sealed_access(self) -> None:
        decision = evaluate_candidate_decision(_synthetic_results(), verification_passed=True)
        assert decision.test_accessed is False
        assert decision.development_gate_accessed is False
        assert decision.final_holdout_accessed is False
        assert decision.parameter_changes == "none"


class TestRoundTrip:
    def test_bytes_round_trip_is_stable(self) -> None:
        decision = evaluate_candidate_decision(_synthetic_results(), verification_passed=True)
        raw = decision.to_json_bytes()
        assert CandidateDecision.from_json_bytes(raw).to_json_bytes() == raw
        assert CandidateDecision.from_json_bytes(raw) == decision

    def test_serialization_is_canonical(self) -> None:
        decision = evaluate_candidate_decision(_synthetic_results(), verification_passed=True)
        raw = decision.to_json_bytes()
        assert raw.endswith(b"\n")
        reencoded = (
            json.dumps(json.loads(raw), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        assert raw == reencoded

    def test_load_round_trips(self, tmp_path: Path) -> None:
        decision = evaluate_candidate_decision(_synthetic_results(), verification_passed=True)
        path = tmp_path / "candidate_decision.json"
        path.write_bytes(decision.to_json_bytes())
        assert load_m3c_decision(str(path)) == decision


class TestStrictParsing:
    def _payload(self) -> dict[str, Any]:
        decision = evaluate_candidate_decision(_synthetic_results(), verification_passed=True)
        return cast(dict[str, Any], json.loads(decision.to_json_bytes()))

    def test_forged_eligible_outcome_is_rejected(self) -> None:
        # A rejected decision (P6 false) whose outcome is hand-edited to eligible must
        # fail the mechanical outcome-vs-criteria cross-check on parse.
        decision = evaluate_candidate_decision(_synthetic_results())
        payload = json.loads(decision.to_json_bytes())
        assert payload["outcome"] == OUTCOME_REJECTED
        payload["outcome"] = OUTCOME_ELIGIBLE
        with pytest.raises(DecisionError, match="does not match"):
            CandidateDecision.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_unknown_key_is_rejected(self) -> None:
        payload = self._payload()
        payload["surprise"] = 1
        with pytest.raises(_REJECT):
            CandidateDecision.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_duplicate_key_is_rejected(self) -> None:
        with pytest.raises(_REJECT):
            CandidateDecision.from_json_bytes(b'{"outcome": "a", "outcome": "b"}')

    def test_bool_as_string_flag_is_rejected(self) -> None:
        payload = self._payload()
        payload["development_gate_accessed"] = "false"
        with pytest.raises(_REJECT):
            CandidateDecision.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_criteria_out_of_order_is_rejected(self) -> None:
        payload = self._payload()
        payload["criteria"][0], payload["criteria"][1] = (
            payload["criteria"][1],
            payload["criteria"][0],
        )
        with pytest.raises(DecisionError, match="criteria"):
            CandidateDecision.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestConstructionInvariants:
    def _decision(self, **overrides: Any) -> CandidateDecision:
        base = evaluate_candidate_decision(_synthetic_results(), verification_passed=True)
        return dataclasses.replace(base, **overrides)

    def test_sealed_access_flag_true_is_rejected(self) -> None:
        with pytest.raises(DecisionError, match="sealed partition"):
            self._decision(development_gate_accessed=True)

    def test_parameter_change_is_rejected(self) -> None:
        with pytest.raises(DecisionError, match="parameter_changes"):
            self._decision(parameter_changes="widened horizons")

    def test_candidate_count_other_than_one_is_rejected(self) -> None:
        with pytest.raises(DecisionError, match="one candidate"):
            self._decision(candidate_count=2)

    def test_verification_flag_must_match_p6(self) -> None:
        # flip the recorded flag without re-evaluating P6 -> inconsistency
        base = evaluate_candidate_decision(_synthetic_results(), verification_passed=True)
        with pytest.raises(DecisionError, match="verification_passed"):
            dataclasses.replace(base, verification_passed=False)


class TestReport:
    def test_eligible_report_uses_gate_review_language_only(self) -> None:
        results = _synthetic_results()
        decision = evaluate_candidate_decision(results, verification_passed=True)
        report = render_m3c_report(results, decision)
        assert "ELIGIBLE FOR INDEPENDENT DEVELOPMENT-GATE REVIEW" in report
        assert "only** eligibility" in report
        lowered = report.lower()
        for banned in ("proven", "profitable", "validated", "robust", "significant"):
            assert banned not in lowered
