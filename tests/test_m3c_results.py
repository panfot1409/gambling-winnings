"""Strict M3C results model: byte-stable round-trips, reconciliation, rejection.

The 75-cell grid is computed once, in memory, from the real research-train
partition (research-train rows only — no sealed partition is ever touched) and
reused across assertions via a module-scoped fixture. This is a read-only
computation, not a registered run, and writes no artifact file.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import eth_research
from eth_research.fractional.dataset import verify_dataset_integrity_only
from eth_research.m3c.candidate import M3C_CANDIDATE_ID, M3C_STRATEGY_NAMES
from eth_research.m3c.decision import evaluate_candidate_decision
from eth_research.m3c.experiment import compute_m3c_cell_runs
from eth_research.m3c.results import (
    PRIMARY_SCENARIO,
    M3CBootstrapResult,
    M3CResults,
    M3CResultsError,
    build_m3c_aggregates,
    build_m3c_results,
    load_m3c_results,
    render_m3c_report,
)
from eth_research.m3c.statistics import (
    align_paired_by_fold,
    fold_stratified_block_bootstrap,
    probabilistic_sharpe_ratio,
)
from eth_research.walkforward import (
    INITIAL_CASH,
    WALK_FORWARD_PROTOCOL_RELPATH,
    load_walk_forward_protocol,
)

REPO = Path(eth_research.__file__).resolve().parents[2]
_REJECT = (ValueError, TypeError)
_COMPAT = "compatibility_v1"


def _build_real_results() -> M3CResults:
    research_train = verify_dataset_integrity_only(REPO).research_train
    wf = load_walk_forward_protocol(REPO / WALK_FORWARD_PROTOCOL_RELPATH)
    runs = compute_m3c_cell_runs(research_train, wf, initial_cash=INITIAL_CASH)
    cand = {
        r.fold_index: r.marked_daily_returns
        for r in runs
        if r.strategy == M3C_CANDIDATE_ID and r.cost_scenario == PRIMARY_SCENARIO
    }
    bnh = {
        r.fold_index: r.marked_daily_returns
        for r in runs
        if r.strategy == "buy_and_hold" and r.cost_scenario == PRIMARY_SCENARIO
    }
    folds = align_paired_by_fold(cand, bnh)
    bootstrap = fold_stratified_block_bootstrap(folds, resamples=2000)
    psr = probabilistic_sharpe_ratio(np.concatenate([f.log_excess for f in folds]))
    traces = {
        (r.strategy, r.cost_scenario, r.fold_index): hashlib.sha256(
            f"{r.strategy}|{r.cost_scenario}|{r.fold_index}".encode()
        ).hexdigest()
        for r in runs
    }
    return build_m3c_results(
        cell_runs=runs,
        wf_protocol=wf,
        package_version="0.6.0",
        execution_code_commit_sha="a" * 40,
        registered_code_commit_sha="b" * 40,
        execution_source_tree_fingerprint="sha256:" + "c" * 64,
        protocol_sha256="d" * 64,
        lineage_sha256="e" * 64,
        budget_sha256="f" * 64,
        frozen_m2_dossier_sha256="1" * 64,
        development_partition_sha256="2" * 64,
        research_train=research_train,
        primary_bootstrap=bootstrap,
        psr=psr,
        trace_commitments=traces,
    )


@pytest.fixture(scope="module")
def results() -> M3CResults:
    return _build_real_results()


def _payload(results: M3CResults) -> dict:
    return json.loads(results.to_json_bytes())


def _reparse(payload: dict) -> M3CResults:
    return M3CResults.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestRoundTrip:
    def test_bytes_round_trip_is_stable(self, results: M3CResults) -> None:
        raw = results.to_json_bytes()
        assert M3CResults.from_json_bytes(raw).to_json_bytes() == raw
        assert M3CResults.from_json_bytes(raw) == results

    def test_serialization_is_canonical(self, results: M3CResults) -> None:
        raw = results.to_json_bytes()
        assert raw.endswith(b"\n")
        reencoded = (
            json.dumps(json.loads(raw), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        assert raw == reencoded

    def test_covers_the_full_grid(self, results: M3CResults) -> None:
        assert len(results.fold_cells) == 75
        assert len(results.aggregates) == 15
        assert len(results.paired_comparisons) == 5
        assert results.strategies == M3C_STRATEGY_NAMES
        assert results.bootstrap.observation_count == sum(
            c.oos_row_count
            for c in results.fold_cells
            if c.strategy == M3C_CANDIDATE_ID and c.cost_scenario == PRIMARY_SCENARIO
        )


class TestReconciliation:
    def test_compatibility_v1_costs_reconcile_with_zero_spread_and_impact(
        self, results: M3CResults
    ) -> None:
        compat = [c for c in results.fold_cells if c.cost_scenario == _COMPAT]
        assert len(compat) == len(M3C_STRATEGY_NAMES) * 5
        for cell in compat:
            # compatibility_v1 has half_spread_rate == 0 and impact_coefficient == 0.
            assert cell.spread_cost == 0.0
            assert cell.liquidity_impact_cost == pytest.approx(0.0, abs=1e-6)
            components = (
                cell.total_fees
                + cell.spread_cost
                + cell.base_slippage_cost
                + cell.liquidity_impact_cost
            )
            assert cell.total_modeled_cost == pytest.approx(components, abs=1e-9)

    def test_aggregates_re_derive_from_cells(self, results: M3CResults) -> None:
        assert results.aggregates == build_m3c_aggregates(results.fold_cells)


class TestStrictParsing:
    def test_duplicate_key_is_rejected(self) -> None:
        with pytest.raises(_REJECT):
            M3CResults.from_json_bytes(b'{"experiment_id": "x", "experiment_id": "y"}')

    def test_non_finite_number_is_rejected(self) -> None:
        with pytest.raises(_REJECT):
            M3CResults.from_json_bytes(b'{"m3c_results_schema_version": 1e999}')

    def test_unknown_top_level_key_is_rejected(self, results: M3CResults) -> None:
        payload = _payload(results)
        payload["surprise"] = 1
        with pytest.raises(_REJECT):
            _reparse(payload)

    def test_missing_top_level_key_is_rejected(self, results: M3CResults) -> None:
        payload = _payload(results)
        del payload["bootstrap"]
        with pytest.raises(_REJECT):
            _reparse(payload)

    def test_unknown_cell_key_is_rejected(self, results: M3CResults) -> None:
        payload = _payload(results)
        payload["fold_cells"][0]["surprise"] = 1
        with pytest.raises(_REJECT):
            _reparse(payload)

    def test_bool_as_int_is_rejected(self, results: M3CResults) -> None:
        payload = _payload(results)
        payload["fold_cells"][0]["num_fills"] = True
        with pytest.raises(_REJECT):
            _reparse(payload)

    def test_tampered_cell_cost_total_fails_reconciliation(self, results: M3CResults) -> None:
        payload = _payload(results)
        payload["fold_cells"][0]["total_modeled_cost"] += 1.0
        with pytest.raises(M3CResultsError, match="reconcile"):
            _reparse(payload)

    def test_reordered_strategies_are_rejected(self, results: M3CResults) -> None:
        payload = _payload(results)
        payload["strategies"] = list(reversed(payload["strategies"]))
        with pytest.raises(M3CResultsError, match="strategies"):
            _reparse(payload)


class TestValidation:
    def test_dropped_losing_cell_breaks_the_grid(self, results: M3CResults) -> None:
        losing = next(
            c
            for c in results.fold_cells
            if c.strategy == M3C_CANDIDATE_ID
            and c.cost_scenario == PRIMARY_SCENARIO
            and c.marked_total_return < 0.0
        )
        kept = tuple(c for c in results.fold_cells if c is not losing)
        with pytest.raises(M3CResultsError, match="expected 75 fold cells"):
            dataclasses.replace(results, fold_cells=kept, aggregates=build_m3c_aggregates(kept))

    def test_duplicate_cell_breaks_the_grid(self, results: M3CResults) -> None:
        cells = (results.fold_cells[0], *results.fold_cells[:-1])
        with pytest.raises(M3CResultsError, match="exact"):
            dataclasses.replace(results, fold_cells=cells)

    def test_tampered_aggregate_fails_rederivation(self, results: M3CResults) -> None:
        original = results.aggregates[0]
        bad = dataclasses.replace(
            original, median_marked_return=original.median_marked_return + 1.0
        )
        with pytest.raises(M3CResultsError, match="re-derive"):
            dataclasses.replace(results, aggregates=(bad, *results.aggregates[1:]))

    def test_nonzero_sealed_ledger_is_rejected(self, results: M3CResults) -> None:
        with pytest.raises(M3CResultsError, match="sealed access ledgers"):
            dataclasses.replace(results, development_gate_event_count=1)

    def test_max_drawdown_out_of_range_is_rejected(self, results: M3CResults) -> None:
        bad = dataclasses.replace(results.fold_cells[0], max_drawdown=0.5)
        with pytest.raises(M3CResultsError, match="max_drawdown"):
            dataclasses.replace(results, fold_cells=(bad, *results.fold_cells[1:]))

    def test_paired_comparison_disagreeing_with_cell_is_rejected(self, results: M3CResults) -> None:
        pc0 = results.paired_comparisons[0]
        # Keep candidate_beats_bnh self-consistent but detach the return from the cell.
        bumped = pc0.candidate_marked_return + 100.0
        bad = dataclasses.replace(pc0, candidate_marked_return=bumped)
        with pytest.raises(M3CResultsError, match="disagrees"):
            dataclasses.replace(results, paired_comparisons=(bad, *results.paired_comparisons[1:]))

    def test_bootstrap_observation_count_must_match_candidate_days(
        self, results: M3CResults
    ) -> None:
        bad = dataclasses.replace(results.bootstrap, observation_count=7)
        with pytest.raises(M3CResultsError, match="observation_count"):
            dataclasses.replace(results, bootstrap=bad)

    def test_bootstrap_wrong_algorithm_is_rejected(self, results: M3CResults) -> None:
        with pytest.raises(M3CResultsError, match="algorithm"):
            M3CBootstrapResult(
                algorithm="iid-v0",
                seed=results.bootstrap.seed,
                resamples=results.bootstrap.resamples,
                confidence=results.bootstrap.confidence,
                observation_count=results.bootstrap.observation_count,
                fold_count=results.bootstrap.fold_count,
                block_lengths=results.bootstrap.block_lengths,
                point_estimate=results.bootstrap.point_estimate,
                ci_lower=results.bootstrap.ci_lower,
                ci_upper=results.bootstrap.ci_upper,
            )


class TestReport:
    def test_report_is_deterministic(self, results: M3CResults) -> None:
        decision = evaluate_candidate_decision(results, verification_passed=True)
        assert render_m3c_report(results, decision) == render_m3c_report(results, decision)

    def test_report_leads_with_decision_and_has_required_framing(self, results: M3CResults) -> None:
        decision = evaluate_candidate_decision(results, verification_passed=True)
        report = render_m3c_report(results, decision)
        assert report.index("## 1. Decision") < report.index("## 2. Research-only framing")
        for marker in (
            "research-train",
            "adaptively motivated",
            "No alpha is claimed",
            "sealed",
            "development gate",
            "final holdout",
            "PSR",
            "fragile",
            "## 9. Limitations",
        ):
            assert marker in report
        # every criterion P1..P7 appears with a verdict in the rule table
        for cid in ("P1", "P2", "P3", "P4", "P5", "P6", "P7"):
            assert f"| {cid} |" in report

    def test_report_avoids_overclaiming_language(self, results: M3CResults) -> None:
        decision = evaluate_candidate_decision(results, verification_passed=True)
        report = render_m3c_report(results, decision).lower()
        for banned in ("proven", "profitable", "validated", "robust", "significant"):
            assert banned not in report


class TestLoad:
    def test_load_requires_canonical_bytes(self, results: M3CResults, tmp_path: Path) -> None:
        path = tmp_path / "candidate_results.json"
        path.write_bytes(results.to_json_bytes())
        assert load_m3c_results(str(path)) == results

    def test_load_rejects_missing_trailing_newline(
        self, results: M3CResults, tmp_path: Path
    ) -> None:
        path = tmp_path / "candidate_results.json"
        path.write_bytes(results.to_json_bytes().rstrip(b"\n"))
        with pytest.raises(_REJECT):
            load_m3c_results(str(path))
