"""Strict, symmetric development-results schema v2 + return-evidence reconciliation."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from eth_research.bootstrap_v2 import (
    FoldAwareBootstrapConfig,
    fold_stratified_moving_block_bootstrap,
    hierarchical_fold_block_bootstrap,
    paired_excess_returns_from_folds,
)
from eth_research.development_evaluation import (
    FoldStrategyResult,
    FullTrainExploratory,
    _pooled_reset_oos,
    _summarize_independent_folds,
)
from eth_research.development_results_v2 import (
    BootstrapCellV2,
    DevelopmentResultsV2,
    DevelopmentResultsV2Error,
    reconcile_results_v2_with_evidence,
)
from eth_research.return_evidence import ReturnEvidence, build_return_evidence

_STRATEGIES = ("cash", "buy_and_hold", "sma_20_50", "donchian_55_20")
_SCENARIOS = ("base", "stressed", "severe")
_FOLD_LENS = (4, 5, 6, 7, 8)
_EXP_ID = "m3a-fixed-baseline-comparison-v2-run-003"
_ARCHIVE = f"research/m3a/experiments/{_EXP_ID}"
_CFG = FoldAwareBootstrapConfig(block_length=2, resamples=60)


def _returns(strategy: str, scenario: str, fold: int) -> np.ndarray:
    if strategy == "cash":
        return np.zeros(_FOLD_LENS[fold], dtype=float)
    seed = abs(hash((strategy, scenario, fold))) % (2**31)
    return np.random.default_rng(seed).normal(0.0, 0.01, size=_FOLD_LENS[fold])


def _fold_ts(fold: int) -> pd.DatetimeIndex:
    start = pd.Timestamp("2016-06-01", tz="UTC") + pd.Timedelta(days=fold * 300)
    return pd.date_range(start, periods=_FOLD_LENS[fold], freq="D", tz="UTC")


def _fold_cell(strategy: str, scenario: str, fold: int, r: np.ndarray) -> FoldStrategyResult:
    initial = 10_000.0
    marked = initial * float(np.prod(1.0 + r))
    ts = _fold_ts(fold)
    trades = strategy != "cash"
    return FoldStrategyResult(
        fold_index=fold,
        strategy=strategy,
        cost_scenario=scenario,
        training_row_count=100 + fold,
        context_row_count=0,
        oos_row_count=len(r),
        oos_first_open_time=ts[0],
        oos_last_open_time=ts[-1],
        initial_cash=initial,
        marked_terminal_equity=marked,
        terminal_liquidation_equity=marked,
        marked_total_return=marked / initial - 1.0,
        liquidation_total_return=marked / initial - 1.0,
        cagr=0.0,
        sharpe=None,
        sortino=None,
        max_drawdown=0.0,
        turnover=1.0 if trades else 0.0,
        total_traded_notional=100.0 if trades else 0.0,
        num_fills=(1 if strategy == "buy_and_hold" else (2 if trades else 0)),
        exposure_fraction=1.0 if trades else 0.0,
        worst_daily_return=float(r.min()),
        expected_shortfall_5pct=float(r.min()),
        longest_drawdown_duration_bars=0,
        equity_positive=True,
    )


def _full_train_cell(strategy: str, scenario: str) -> FullTrainExploratory:
    trades = strategy != "cash"
    return FullTrainExploratory(
        strategy=strategy,
        cost_scenario=scenario,
        row_count=1000,
        marked_total_return=0.0,
        liquidation_total_return=0.0,
        cagr=0.0,
        sharpe=None,
        sortino=None,
        max_drawdown=0.0,
        turnover=1.0 if trades else 0.0,
        num_fills=5 if trades else 0,
        exposure_fraction=0.5 if trades else 0.0,
    )


def _build_consistent() -> tuple[DevelopmentResultsV2, ReturnEvidence]:
    fold_returns: dict[tuple[str, str], list[pd.Series]] = {}
    fold_cells: list[FoldStrategyResult] = []
    for sc in _SCENARIOS:
        for st in _STRATEGIES:
            series_list = []
            for f in range(5):
                r = _returns(st, sc, f)
                series_list.append(pd.Series(r, index=_fold_ts(f), dtype=float))
                fold_cells.append(_fold_cell(st, sc, f, r))
            fold_returns[(st, sc)] = series_list

    evidence = build_return_evidence(
        experiment_id=_EXP_ID,
        periods_per_year=365.25,
        research_train_last_open_time=pd.Timestamp("2022-06-21T00:00:00+00:00"),
        strategies=_STRATEGIES,
        cost_scenarios=_SCENARIOS,
        fold_returns=fold_returns,
    )
    by_cell = {(c.fold_index, c.strategy, c.cost_scenario): c for c in fold_cells}
    summaries = _summarize_independent_folds(fold_cells, by_cell)
    pooled = [
        _pooled_reset_oos(st, sc, list(evidence.fold_series(st, sc)), 365.25)
        for sc in _SCENARIOS
        for st in _STRATEGIES
    ]
    full_train = [_full_train_cell(st, sc) for sc in _SCENARIOS for st in _STRATEGIES]
    bootstrap = []
    for sc in _SCENARIOS:
        for st in _STRATEGIES:
            if st == "buy_and_hold":
                continue
            excess = paired_excess_returns_from_folds(
                evidence.fold_series(st, sc), evidence.fold_series("buy_and_hold", sc)
            )
            bootstrap.append(
                BootstrapCellV2(
                    strategy=st,
                    cost_scenario=sc,
                    primary=fold_stratified_moving_block_bootstrap(excess, _CFG),
                    sensitivity=hierarchical_fold_block_bootstrap(excess, _CFG),
                )
            )
    results = DevelopmentResultsV2(
        development_results_schema_version=2,
        experiment_id=_EXP_ID,
        experiment_family_id="m3a-fixed-baseline-comparison-v2",
        methodology_id="walk-forward-fold-stratified-bootstrap-v2",
        package_version="0.4.0",
        execution_code_commit_sha="a" * 40,
        registered_code_commit_sha="b" * 40,
        execution_source_tree_fingerprint="c" * 64,
        frozen_m2_dossier_sha256="d" * 64,
        development_partition_sha256="e" * 64,
        walk_forward_protocol_path="research/m3a/walk_forward_protocol.json",
        walk_forward_protocol_sha256="f" * 64,
        methodology_protocol_path="research/m3a/walk_forward_protocol_v2.json",
        methodology_protocol_sha256="1" * 64,
        dataset_content_fingerprint="sha256:" + "2" * 64,
        research_train_content_fingerprint="sha256:" + "3" * 64,
        strategies=_STRATEGIES,
        cost_scenarios=_SCENARIOS,
        fold_results=tuple(fold_cells),
        independent_fold_summaries=tuple(summaries),
        pooled_reset_oos=tuple(pooled),
        full_train_exploratory=tuple(full_train),
        bootstrap_cells=tuple(bootstrap),
        return_evidence_path=f"{_ARCHIVE}/return_evidence.json",
        return_evidence_sha256=evidence.content_sha256(),
        development_gate_event_count=0,
        final_holdout_event_count=0,
    )
    return results, evidence


class TestSymmetry:
    def test_round_trip(self) -> None:
        results, _ = _build_consistent()
        assert DevelopmentResultsV2.from_json_bytes(results.to_json_bytes()) == results

    def test_unknown_top_level_key_is_rejected(self) -> None:
        results, _ = _build_consistent()
        payload = json.loads(results.to_json_bytes())
        payload["surprise"] = 1
        with pytest.raises(ValueError, match="top-level keys do not match"):
            DevelopmentResultsV2.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_forged_data_access_declaration_is_rejected(self) -> None:
        results, _ = _build_consistent()
        payload = json.loads(results.to_json_bytes())
        payload["data_access_declaration"]["development_gate"] = "evaluated"
        with pytest.raises(ValueError, match="data_access_declaration"):
            DevelopmentResultsV2.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestInvariants:
    def test_liquidation_exceeding_marked_is_rejected(self) -> None:
        results, _ = _build_consistent()
        payload = json.loads(results.to_json_bytes())
        payload["fold_results"][10]["terminal_liquidation_equity"] += 1.0
        with pytest.raises(ValueError, match="liquidation equity exceeds marked"):
            DevelopmentResultsV2.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_cash_with_a_fill_is_rejected(self) -> None:
        results, _ = _build_consistent()
        payload = json.loads(results.to_json_bytes())
        cash = next(c for c in payload["fold_results"] if c["strategy"] == "cash")
        cash["num_fills"] = 1
        with pytest.raises(ValueError, match="cash must not trade"):
            DevelopmentResultsV2.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_incomplete_fold_grid_is_rejected(self) -> None:
        results, _ = _build_consistent()
        payload = json.loads(results.to_json_bytes())
        payload["fold_results"] = payload["fold_results"][:-1]
        with pytest.raises(ValueError, match="complete 5x4x3 grid"):
            DevelopmentResultsV2.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_bad_experiment_family_is_rejected(self) -> None:
        results, _ = _build_consistent()
        payload = json.loads(results.to_json_bytes())
        payload["experiment_family_id"] = "m3a-fixed-baseline-comparison-v1"
        with pytest.raises(ValueError, match="experiment_family_id must be"):
            DevelopmentResultsV2.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_tampered_summary_does_not_rederive(self) -> None:
        results, _ = _build_consistent()
        payload = json.loads(results.to_json_bytes())
        payload["independent_fold_summaries"][0]["total_fills"] += 1
        with pytest.raises(ValueError, match="does not rederive"):
            DevelopmentResultsV2.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestReconciliation:
    def test_pooled_and_bootstrap_recompute_from_evidence(self) -> None:
        results, evidence = _build_consistent()
        reconcile_results_v2_with_evidence(results, evidence)  # must not raise

    def test_mismatched_experiment_id_is_rejected(self) -> None:
        results, evidence = _build_consistent()
        other = ReturnEvidence.from_json_bytes(
            json.dumps(
                {**json.loads(evidence.to_json_bytes()), "experiment_id": "m3a-other-run-999"}
            ).encode("utf-8")
        )
        with pytest.raises(DevelopmentResultsV2Error, match="experiment id disagrees"):
            reconcile_results_v2_with_evidence(results, other)

    def test_tampered_pooled_fails_reconciliation(self) -> None:
        results, evidence = _build_consistent()
        payload = json.loads(results.to_json_bytes())
        payload["pooled_reset_oos"][5]["mean_daily_return"] += 0.001
        # Rebuild via a bypass: construct with the tampered pooled cell but valid grid.
        tampered = DevelopmentResultsV2.from_json_bytes(_repair_grid(payload))
        with pytest.raises(DevelopmentResultsV2Error, match="does not recompute"):
            reconcile_results_v2_with_evidence(tampered, evidence)


def _repair_grid(payload: dict) -> bytes:
    """Serialize a payload whose pooled mean was nudged (observation_count intact)."""
    return json.dumps(payload).encode("utf-8")
