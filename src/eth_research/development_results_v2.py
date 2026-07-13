"""Strict, symmetric development-results schema v2 (Milestone 3A closure, Phase 8).

The v1 :class:`~eth_research.development_evaluation.DevelopmentResults` loaded
through a lightly-checked dict. Results v2 is a fully typed model whose
construction and JSON parsing share one invariant surface: a model that
constructs is a model that parses, and vice versa, and every nested cell is
strictly validated.

Financial content is deliberately reused from the v1 cell dataclasses
(:class:`FoldStrategyResult`, :class:`IndependentFoldSummary`,
:class:`PooledResetOOS`, :class:`FullTrainExploratory`), so the corrective
run-003's per-fold financials, full-train metrics, and aggregations serialize
**byte-identically** to run-002. What v2 adds is: the exact experiment
identity (``experiment_id`` + ``methodology_id`` + source-tree fingerprint),
the immutable methodology/protocol binding, the fold-aware bootstrap v2 cells
(primary + hierarchical sensitivity), and a reference to the per-run return
evidence. The pooled and bootstrap numbers are additionally reconcilable
against that return evidence by :func:`reconcile_results_v2_with_evidence`.

Invariants validated on both construct and parse include: schema version 2;
exact key sets at every nesting level; 40-hex commit ids and lowercase
SHA-256/fingerprints; the exact four strategies and three cost scenarios; the
complete 5x4x3 fold grid with non-overlapping ordered OOS windows; per-cell
accounting (liquidation <= marked equity, total-return identities, cash has
no fills/turnover/return and zero exposure, buy-and-hold funds exactly once
per fold, exposure in [0,1], drawdown in [-1,0], positive equity); the twelve
independent summaries rederived from the fold rows; twelve pooled and twelve
full-train cells; nine bootstrap cells carrying the pinned primary and
sensitivity algorithms; the exact data-access declaration; and both sealed
event counts equal to zero.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.bootstrap_v2 import (
    FOLD_STRATIFIED_ALGORITHM,
    HIERARCHICAL_ALGORITHM,
    FoldAwareBootstrapConfig,
    FoldAwareInterval,
    fold_stratified_moving_block_bootstrap,
    hierarchical_fold_block_bootstrap,
    paired_excess_returns_from_folds,
)
from eth_research.data.provenance import (
    require_bool,
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
)
from eth_research.data.validation import (
    parse_timestamp_field,
    require_commit_sha,
    require_evaluation_id,
    require_fingerprint,
    require_finite_float,
)
from eth_research.development_evaluation import (
    FoldStrategyResult,
    FullTrainExploratory,
    IndependentFoldSummary,
    PooledResetOOS,
    _pooled_reset_oos,
    _summarize_independent_folds,
)
from eth_research.methodology_v2 import (
    EXPERIMENT_FAMILY_V2,
    METHODOLOGY_ID,
    METHODOLOGY_PROTOCOL_V2_RELPATH,
)
from eth_research.return_evidence import ReturnEvidence
from eth_research.walkforward import STRATEGY_NAMES, WALK_FORWARD_PROTOCOL_RELPATH

DEVELOPMENT_RESULTS_SCHEMA_VERSION_V2: int = 2

_CASH: str = "cash"
_BUY_AND_HOLD: str = "buy_and_hold"
_COST_SCENARIOS: tuple[str, ...] = ("base", "stressed", "severe")

DATA_ACCESS_DECLARATION: dict[str, str] = {
    "research_train": "evaluated (permitted)",
    "development_gate": "not evaluated (forbidden in M3A)",
    "final_holdout": "not evaluated (forbidden in M3A)",
}


class DevelopmentResultsV2Error(RuntimeError):
    """The v2 development results are invalid or fail an invariant."""


# --- Nested-cell strict parsers (exact keys, exact types) ---------------------

_FOLD_KEYS: frozenset[str] = frozenset(
    {
        "fold_index",
        "strategy",
        "cost_scenario",
        "training_row_count",
        "context_row_count",
        "oos_row_count",
        "oos_first_open_time",
        "oos_last_open_time",
        "initial_cash",
        "marked_terminal_equity",
        "terminal_liquidation_equity",
        "marked_total_return",
        "liquidation_total_return",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "turnover",
        "total_traded_notional",
        "num_fills",
        "exposure_fraction",
        "worst_daily_return",
        "expected_shortfall_5pct",
        "longest_drawdown_duration_bars",
        "equity_positive",
    }
)
_SUMMARY_KEYS: frozenset[str] = frozenset(
    {
        "strategy",
        "cost_scenario",
        "fold_count",
        "median_marked_return",
        "median_liquidation_return",
        "worst_liquidation_fold_return",
        "best_marked_fold_return",
        "median_sharpe",
        "worst_max_drawdown",
        "total_fills",
        "median_turnover",
        "fraction_positive_folds",
        "fraction_beating_buy_and_hold",
        "fraction_beating_cash",
    }
)
_POOLED_KEYS: frozenset[str] = frozenset(
    {
        "strategy",
        "cost_scenario",
        "observation_count",
        "mean_daily_return",
        "volatility",
        "sharpe",
        "sortino",
        "worst_daily_return",
        "expected_shortfall_5pct",
        "reset_path_max_drawdown",
    }
)
_FULL_TRAIN_KEYS: frozenset[str] = frozenset(
    {
        "strategy",
        "cost_scenario",
        "row_count",
        "marked_total_return",
        "liquidation_total_return",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "turnover",
        "num_fills",
        "exposure_fraction",
    }
)
_BOOTSTRAP_KEYS: frozenset[str] = frozenset({"strategy", "cost_scenario", "primary", "sensitivity"})


def _opt_float(label: str, value: object) -> float | None:
    return None if value is None else require_finite_float(label, value)


def _parse_fold_cell(payload: Any) -> FoldStrategyResult:
    if not isinstance(payload, dict) or set(payload) != _FOLD_KEYS:
        raise ValueError("fold-result cell keys do not match schema")
    return FoldStrategyResult(
        fold_index=require_int("fold_index", payload["fold_index"]),
        strategy=require_nonempty_str("strategy", payload["strategy"]),
        cost_scenario=require_nonempty_str("cost_scenario", payload["cost_scenario"]),
        training_row_count=require_int("training_row_count", payload["training_row_count"]),
        context_row_count=require_int("context_row_count", payload["context_row_count"]),
        oos_row_count=require_int("oos_row_count", payload["oos_row_count"]),
        oos_first_open_time=parse_timestamp_field(
            "oos_first_open_time", payload["oos_first_open_time"]
        ),
        oos_last_open_time=parse_timestamp_field(
            "oos_last_open_time", payload["oos_last_open_time"]
        ),
        initial_cash=require_finite_float("initial_cash", payload["initial_cash"]),
        marked_terminal_equity=require_finite_float(
            "marked_terminal_equity", payload["marked_terminal_equity"]
        ),
        terminal_liquidation_equity=require_finite_float(
            "terminal_liquidation_equity", payload["terminal_liquidation_equity"]
        ),
        marked_total_return=require_finite_float(
            "marked_total_return", payload["marked_total_return"]
        ),
        liquidation_total_return=require_finite_float(
            "liquidation_total_return", payload["liquidation_total_return"]
        ),
        cagr=require_finite_float("cagr", payload["cagr"]),
        sharpe=_opt_float("sharpe", payload["sharpe"]),
        sortino=_opt_float("sortino", payload["sortino"]),
        max_drawdown=require_finite_float("max_drawdown", payload["max_drawdown"]),
        turnover=require_finite_float("turnover", payload["turnover"]),
        total_traded_notional=require_finite_float(
            "total_traded_notional", payload["total_traded_notional"]
        ),
        num_fills=require_int("num_fills", payload["num_fills"]),
        exposure_fraction=require_finite_float("exposure_fraction", payload["exposure_fraction"]),
        worst_daily_return=require_finite_float(
            "worst_daily_return", payload["worst_daily_return"]
        ),
        expected_shortfall_5pct=require_finite_float(
            "expected_shortfall_5pct", payload["expected_shortfall_5pct"]
        ),
        longest_drawdown_duration_bars=require_int(
            "longest_drawdown_duration_bars", payload["longest_drawdown_duration_bars"]
        ),
        equity_positive=require_bool("equity_positive", payload["equity_positive"]),
    )


def _parse_summary_cell(payload: Any) -> IndependentFoldSummary:
    if not isinstance(payload, dict) or set(payload) != _SUMMARY_KEYS:
        raise ValueError("summary cell keys do not match schema")
    return IndependentFoldSummary(
        strategy=require_nonempty_str("strategy", payload["strategy"]),
        cost_scenario=require_nonempty_str("cost_scenario", payload["cost_scenario"]),
        fold_count=require_int("fold_count", payload["fold_count"]),
        median_marked_return=require_finite_float(
            "median_marked_return", payload["median_marked_return"]
        ),
        median_liquidation_return=require_finite_float(
            "median_liquidation_return", payload["median_liquidation_return"]
        ),
        worst_liquidation_fold_return=require_finite_float(
            "worst_liquidation_fold_return", payload["worst_liquidation_fold_return"]
        ),
        best_marked_fold_return=require_finite_float(
            "best_marked_fold_return", payload["best_marked_fold_return"]
        ),
        median_sharpe=_opt_float("median_sharpe", payload["median_sharpe"]),
        worst_max_drawdown=require_finite_float(
            "worst_max_drawdown", payload["worst_max_drawdown"]
        ),
        total_fills=require_int("total_fills", payload["total_fills"]),
        median_turnover=require_finite_float("median_turnover", payload["median_turnover"]),
        fraction_positive_folds=require_finite_float(
            "fraction_positive_folds", payload["fraction_positive_folds"]
        ),
        fraction_beating_buy_and_hold=require_finite_float(
            "fraction_beating_buy_and_hold", payload["fraction_beating_buy_and_hold"]
        ),
        fraction_beating_cash=require_finite_float(
            "fraction_beating_cash", payload["fraction_beating_cash"]
        ),
    )


def _parse_pooled_cell(payload: Any) -> PooledResetOOS:
    if not isinstance(payload, dict) or set(payload) != _POOLED_KEYS:
        raise ValueError("pooled cell keys do not match schema")
    return PooledResetOOS(
        strategy=require_nonempty_str("strategy", payload["strategy"]),
        cost_scenario=require_nonempty_str("cost_scenario", payload["cost_scenario"]),
        observation_count=require_int("observation_count", payload["observation_count"]),
        mean_daily_return=require_finite_float("mean_daily_return", payload["mean_daily_return"]),
        volatility=require_finite_float("volatility", payload["volatility"]),
        sharpe=_opt_float("sharpe", payload["sharpe"]),
        sortino=_opt_float("sortino", payload["sortino"]),
        worst_daily_return=require_finite_float(
            "worst_daily_return", payload["worst_daily_return"]
        ),
        expected_shortfall_5pct=require_finite_float(
            "expected_shortfall_5pct", payload["expected_shortfall_5pct"]
        ),
        reset_path_max_drawdown=require_finite_float(
            "reset_path_max_drawdown", payload["reset_path_max_drawdown"]
        ),
    )


def _parse_full_train_cell(payload: Any) -> FullTrainExploratory:
    if not isinstance(payload, dict) or set(payload) != _FULL_TRAIN_KEYS:
        raise ValueError("full-train cell keys do not match schema")
    return FullTrainExploratory(
        strategy=require_nonempty_str("strategy", payload["strategy"]),
        cost_scenario=require_nonempty_str("cost_scenario", payload["cost_scenario"]),
        row_count=require_int("row_count", payload["row_count"]),
        marked_total_return=require_finite_float(
            "marked_total_return", payload["marked_total_return"]
        ),
        liquidation_total_return=require_finite_float(
            "liquidation_total_return", payload["liquidation_total_return"]
        ),
        cagr=require_finite_float("cagr", payload["cagr"]),
        sharpe=_opt_float("sharpe", payload["sharpe"]),
        sortino=_opt_float("sortino", payload["sortino"]),
        max_drawdown=require_finite_float("max_drawdown", payload["max_drawdown"]),
        turnover=require_finite_float("turnover", payload["turnover"]),
        num_fills=require_int("num_fills", payload["num_fills"]),
        exposure_fraction=require_finite_float("exposure_fraction", payload["exposure_fraction"]),
    )


@dataclass(frozen=True)
class BootstrapCellV2:
    """One non-B&H strategy/scenario cell: primary + sensitivity intervals."""

    strategy: str
    cost_scenario: str
    primary: FoldAwareInterval
    sensitivity: FoldAwareInterval

    def __post_init__(self) -> None:
        require_nonempty_str("strategy", self.strategy)
        require_nonempty_str("cost_scenario", self.cost_scenario)
        if self.primary.algorithm != FOLD_STRATIFIED_ALGORITHM:
            raise ValueError(f"primary algorithm must be {FOLD_STRATIFIED_ALGORITHM!r}")
        if self.sensitivity.algorithm != HIERARCHICAL_ALGORITHM:
            raise ValueError(f"sensitivity algorithm must be {HIERARCHICAL_ALGORITHM!r}")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "primary": self.primary.to_json_dict(),
            "sensitivity": self.sensitivity.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, payload: Any) -> BootstrapCellV2:
        if not isinstance(payload, dict) or set(payload) != _BOOTSTRAP_KEYS:
            raise ValueError("bootstrap cell keys do not match schema")
        return cls(
            strategy=require_nonempty_str("strategy", payload["strategy"]),
            cost_scenario=require_nonempty_str("cost_scenario", payload["cost_scenario"]),
            primary=FoldAwareInterval.from_json_dict(payload["primary"]),
            sensitivity=FoldAwareInterval.from_json_dict(payload["sensitivity"]),
        )


_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "development_results_schema_version",
        "experiment_id",
        "experiment_family_id",
        "methodology_id",
        "package_version",
        "execution_code_commit_sha",
        "registered_code_commit_sha",
        "execution_source_tree_fingerprint",
        "frozen_m2_dossier_sha256",
        "development_partition_sha256",
        "walk_forward_protocol_path",
        "walk_forward_protocol_sha256",
        "methodology_protocol_path",
        "methodology_protocol_sha256",
        "dataset_content_fingerprint",
        "research_train_content_fingerprint",
        "strategies",
        "cost_scenarios",
        "fold_results",
        "independent_fold_summaries",
        "pooled_reset_oos",
        "full_train_exploratory",
        "bootstrap_cells",
        "return_evidence_path",
        "return_evidence_sha256",
        "data_access_declaration",
        "development_gate_event_count",
        "final_holdout_event_count",
    }
)


@dataclass(frozen=True)
class DevelopmentResultsV2:
    """The complete strict v2 development result; construct == parse invariants."""

    development_results_schema_version: int
    experiment_id: str
    experiment_family_id: str
    methodology_id: str
    package_version: str
    execution_code_commit_sha: str
    registered_code_commit_sha: str
    execution_source_tree_fingerprint: str
    frozen_m2_dossier_sha256: str
    development_partition_sha256: str
    walk_forward_protocol_path: str
    walk_forward_protocol_sha256: str
    methodology_protocol_path: str
    methodology_protocol_sha256: str
    dataset_content_fingerprint: str
    research_train_content_fingerprint: str
    strategies: tuple[str, ...]
    cost_scenarios: tuple[str, ...]
    fold_results: tuple[FoldStrategyResult, ...]
    independent_fold_summaries: tuple[IndependentFoldSummary, ...]
    pooled_reset_oos: tuple[PooledResetOOS, ...]
    full_train_exploratory: tuple[FullTrainExploratory, ...]
    bootstrap_cells: tuple[BootstrapCellV2, ...]
    return_evidence_path: str
    return_evidence_sha256: str
    development_gate_event_count: int
    final_holdout_event_count: int

    def __post_init__(self) -> None:
        if self.development_results_schema_version != DEVELOPMENT_RESULTS_SCHEMA_VERSION_V2:
            raise ValueError(
                f"schema version must be {DEVELOPMENT_RESULTS_SCHEMA_VERSION_V2}, "
                f"got {self.development_results_schema_version!r}"
            )
        require_evaluation_id("experiment_id", self.experiment_id)
        require_evaluation_id("experiment_family_id", self.experiment_family_id)
        if self.experiment_family_id != EXPERIMENT_FAMILY_V2:
            raise ValueError(f"experiment_family_id must be {EXPERIMENT_FAMILY_V2!r}")
        if not self.experiment_id.startswith(self.experiment_family_id):
            raise ValueError("experiment_id must extend its experiment_family_id")
        if self.methodology_id != METHODOLOGY_ID:
            raise ValueError(f"methodology_id must be {METHODOLOGY_ID!r}")
        require_nonempty_str("package_version", self.package_version)
        require_commit_sha("execution_code_commit_sha", self.execution_code_commit_sha)
        require_commit_sha("registered_code_commit_sha", self.registered_code_commit_sha)
        require_hex64("execution_source_tree_fingerprint", self.execution_source_tree_fingerprint)
        require_hex64("frozen_m2_dossier_sha256", self.frozen_m2_dossier_sha256)
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        if self.walk_forward_protocol_path != WALK_FORWARD_PROTOCOL_RELPATH:
            raise ValueError(
                f"walk_forward_protocol_path must be {WALK_FORWARD_PROTOCOL_RELPATH!r}"
            )
        require_hex64("walk_forward_protocol_sha256", self.walk_forward_protocol_sha256)
        if self.methodology_protocol_path != METHODOLOGY_PROTOCOL_V2_RELPATH:
            raise ValueError(
                f"methodology_protocol_path must be {METHODOLOGY_PROTOCOL_V2_RELPATH!r}"
            )
        require_hex64("methodology_protocol_sha256", self.methodology_protocol_sha256)
        require_fingerprint("dataset_content_fingerprint", self.dataset_content_fingerprint)
        require_fingerprint(
            "research_train_content_fingerprint", self.research_train_content_fingerprint
        )
        if tuple(self.strategies) != STRATEGY_NAMES:
            raise ValueError(f"strategies must be exactly {STRATEGY_NAMES}")
        if tuple(self.cost_scenarios) != _COST_SCENARIOS:
            raise ValueError(f"cost_scenarios must be exactly {_COST_SCENARIOS}")
        _require_safe_evidence_path(self.return_evidence_path, self.experiment_id)
        require_hex64("return_evidence_sha256", self.return_evidence_sha256)
        if self.development_gate_event_count != 0:
            raise ValueError("development-gate event count must be 0 in Milestone 3A")
        if self.final_holdout_event_count != 0:
            raise ValueError("final-holdout event count must be 0 in Milestone 3A")
        self._validate_grid_and_accounting()

    def _validate_grid_and_accounting(self) -> None:
        strategies, scenarios = self.strategies, self.cost_scenarios
        fold_count = 5
        # Complete, unique 5x(strategy)x(scenario) fold grid.
        seen: set[tuple[int, str, str]] = set()
        by_cell: dict[tuple[int, str, str], FoldStrategyResult] = {}
        for cell in self.fold_results:
            key = (cell.fold_index, cell.strategy, cell.cost_scenario)
            if key in seen:
                raise ValueError(f"duplicate fold cell {key}")
            if cell.strategy not in strategies or cell.cost_scenario not in scenarios:
                raise ValueError(f"fold cell {key} has an unknown strategy/scenario")
            if not 0 <= cell.fold_index < fold_count:
                raise ValueError(f"fold_index out of range in {key}")
            seen.add(key)
            by_cell[key] = cell
            _validate_fold_accounting(cell)
        expected = {(f, st, sc) for sc in scenarios for st in strategies for f in range(fold_count)}
        if seen != expected:
            raise ValueError("fold_results are not the complete 5x4x3 grid")
        # Per (strategy, scenario): ordered non-overlapping OOS windows.
        for sc in scenarios:
            for st in strategies:
                folds = [by_cell[(f, st, sc)] for f in range(fold_count)]
                previous_last = None
                for fold in folds:
                    if fold.oos_last_open_time < fold.oos_first_open_time:
                        raise ValueError(f"({st},{sc}) fold {fold.fold_index}: OOS bounds reversed")
                    if previous_last is not None and fold.oos_first_open_time <= previous_last:
                        raise ValueError(f"({st},{sc}) fold {fold.fold_index}: OOS windows overlap")
                    previous_last = fold.oos_last_open_time
        # Aggregations: exactly 12 each, one per (strategy, scenario).
        _require_cell_grid(self.independent_fold_summaries, strategies, scenarios, "summaries")
        _require_cell_grid(self.pooled_reset_oos, strategies, scenarios, "pooled")
        _require_cell_grid(self.full_train_exploratory, strategies, scenarios, "full-train")
        # Independent summaries must rederive exactly from the fold rows.
        rederived = {
            (s.strategy, s.cost_scenario): s
            for s in _summarize_independent_folds(list(self.fold_results), by_cell)
        }
        for summary in self.independent_fold_summaries:
            if rederived[(summary.strategy, summary.cost_scenario)] != summary:
                raise ValueError(
                    f"independent summary ({summary.strategy},{summary.cost_scenario}) does not "
                    "rederive from the fold rows"
                )
        # Pooled observation_count must equal the fold-row OOS-count sum.
        pooled_by = {(p.strategy, p.cost_scenario): p for p in self.pooled_reset_oos}
        for sc in scenarios:
            for st in strategies:
                total = sum(by_cell[(f, st, sc)].oos_row_count for f in range(fold_count))
                if pooled_by[(st, sc)].observation_count != total:
                    raise ValueError(
                        f"pooled ({st},{sc}) observation_count != sum of fold OOS counts"
                    )
        # Bootstrap: exactly 9 (non-B&H strategies x scenarios), unique.
        expected_boot = {(st, sc) for sc in scenarios for st in strategies if st != _BUY_AND_HOLD}
        actual_boot = {(b.strategy, b.cost_scenario) for b in self.bootstrap_cells}
        if actual_boot != expected_boot or len(self.bootstrap_cells) != len(expected_boot):
            raise ValueError("bootstrap_cells are not the exact non-B&H strategy x scenario grid")

    # --- Serialization --------------------------------------------------------

    def to_json_bytes(self) -> bytes:
        payload = {
            "development_results_schema_version": self.development_results_schema_version,
            "experiment_id": self.experiment_id,
            "experiment_family_id": self.experiment_family_id,
            "methodology_id": self.methodology_id,
            "package_version": self.package_version,
            "execution_code_commit_sha": self.execution_code_commit_sha,
            "registered_code_commit_sha": self.registered_code_commit_sha,
            "execution_source_tree_fingerprint": self.execution_source_tree_fingerprint,
            "frozen_m2_dossier_sha256": self.frozen_m2_dossier_sha256,
            "development_partition_sha256": self.development_partition_sha256,
            "walk_forward_protocol_path": self.walk_forward_protocol_path,
            "walk_forward_protocol_sha256": self.walk_forward_protocol_sha256,
            "methodology_protocol_path": self.methodology_protocol_path,
            "methodology_protocol_sha256": self.methodology_protocol_sha256,
            "dataset_content_fingerprint": self.dataset_content_fingerprint,
            "research_train_content_fingerprint": self.research_train_content_fingerprint,
            "strategies": list(self.strategies),
            "cost_scenarios": list(self.cost_scenarios),
            "fold_results": [c.to_json_dict() for c in self.fold_results],
            "independent_fold_summaries": [
                c.to_json_dict() for c in self.independent_fold_summaries
            ],
            "pooled_reset_oos": [c.to_json_dict() for c in self.pooled_reset_oos],
            "full_train_exploratory": [c.to_json_dict() for c in self.full_train_exploratory],
            "bootstrap_cells": [c.to_json_dict() for c in self.bootstrap_cells],
            "return_evidence_path": self.return_evidence_path,
            "return_evidence_sha256": self.return_evidence_sha256,
            "data_access_declaration": DATA_ACCESS_DECLARATION,
            "development_gate_event_count": self.development_gate_event_count,
            "final_holdout_event_count": self.final_holdout_event_count,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> DevelopmentResultsV2:
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"development results v2 is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("development results v2 JSON must be an object")
        keys = set(payload)
        if keys != _TOP_LEVEL_KEYS:
            unknown = sorted(keys - _TOP_LEVEL_KEYS)
            missing = sorted(_TOP_LEVEL_KEYS - keys)
            raise ValueError(f"top-level keys do not match: unknown={unknown}, missing={missing}")
        if payload["data_access_declaration"] != DATA_ACCESS_DECLARATION:
            raise ValueError("data_access_declaration must be exactly the pinned declaration")
        for listy in (
            "fold_results",
            "independent_fold_summaries",
            "pooled_reset_oos",
            "full_train_exploratory",
            "bootstrap_cells",
            "strategies",
            "cost_scenarios",
        ):
            if not isinstance(payload[listy], list):
                raise ValueError(f"{listy} must be a JSON array")
        return cls(
            development_results_schema_version=require_int(
                "development_results_schema_version",
                payload["development_results_schema_version"],
            ),
            experiment_id=require_str("experiment_id", payload["experiment_id"]),
            experiment_family_id=require_str(
                "experiment_family_id", payload["experiment_family_id"]
            ),
            methodology_id=require_str("methodology_id", payload["methodology_id"]),
            package_version=require_str("package_version", payload["package_version"]),
            execution_code_commit_sha=require_str(
                "execution_code_commit_sha", payload["execution_code_commit_sha"]
            ),
            registered_code_commit_sha=require_str(
                "registered_code_commit_sha", payload["registered_code_commit_sha"]
            ),
            execution_source_tree_fingerprint=require_str(
                "execution_source_tree_fingerprint", payload["execution_source_tree_fingerprint"]
            ),
            frozen_m2_dossier_sha256=require_str(
                "frozen_m2_dossier_sha256", payload["frozen_m2_dossier_sha256"]
            ),
            development_partition_sha256=require_str(
                "development_partition_sha256", payload["development_partition_sha256"]
            ),
            walk_forward_protocol_path=require_str(
                "walk_forward_protocol_path", payload["walk_forward_protocol_path"]
            ),
            walk_forward_protocol_sha256=require_str(
                "walk_forward_protocol_sha256", payload["walk_forward_protocol_sha256"]
            ),
            methodology_protocol_path=require_str(
                "methodology_protocol_path", payload["methodology_protocol_path"]
            ),
            methodology_protocol_sha256=require_str(
                "methodology_protocol_sha256", payload["methodology_protocol_sha256"]
            ),
            dataset_content_fingerprint=require_str(
                "dataset_content_fingerprint", payload["dataset_content_fingerprint"]
            ),
            research_train_content_fingerprint=require_str(
                "research_train_content_fingerprint",
                payload["research_train_content_fingerprint"],
            ),
            strategies=tuple(require_str("strategy", s) for s in payload["strategies"]),
            cost_scenarios=tuple(
                require_str("cost_scenario", s) for s in payload["cost_scenarios"]
            ),
            fold_results=tuple(_parse_fold_cell(c) for c in payload["fold_results"]),
            independent_fold_summaries=tuple(
                _parse_summary_cell(c) for c in payload["independent_fold_summaries"]
            ),
            pooled_reset_oos=tuple(_parse_pooled_cell(c) for c in payload["pooled_reset_oos"]),
            full_train_exploratory=tuple(
                _parse_full_train_cell(c) for c in payload["full_train_exploratory"]
            ),
            bootstrap_cells=tuple(
                BootstrapCellV2.from_json_dict(c) for c in payload["bootstrap_cells"]
            ),
            return_evidence_path=require_str(
                "return_evidence_path", payload["return_evidence_path"]
            ),
            return_evidence_sha256=require_str(
                "return_evidence_sha256", payload["return_evidence_sha256"]
            ),
            development_gate_event_count=require_int(
                "development_gate_event_count", payload["development_gate_event_count"]
            ),
            final_holdout_event_count=require_int(
                "final_holdout_event_count", payload["final_holdout_event_count"]
            ),
        )


def _require_safe_evidence_path(path: str, experiment_id: str) -> None:
    prefix = f"research/m3a/experiments/{experiment_id}/"
    require_nonempty_str("return_evidence_path", path)
    if path != f"{prefix}return_evidence.json":
        raise ValueError(f"return_evidence_path must be {prefix}return_evidence.json, got {path!r}")


def _require_cell_grid(
    cells: tuple[Any, ...], strategies: tuple[str, ...], scenarios: tuple[str, ...], label: str
) -> None:
    got = {(c.strategy, c.cost_scenario) for c in cells}
    want = {(st, sc) for sc in scenarios for st in strategies}
    if got != want or len(cells) != len(want):
        raise ValueError(f"{label} cells are not the exact strategy x scenario grid")


def _validate_fold_accounting(cell: FoldStrategyResult) -> None:
    key = f"({cell.strategy},{cell.cost_scenario},fold {cell.fold_index})"
    if cell.initial_cash <= 0.0:
        raise ValueError(f"{key}: initial_cash must be positive")
    if cell.oos_row_count <= 0:
        raise ValueError(f"{key}: oos_row_count must be positive")
    if cell.num_fills < 0 or cell.turnover < 0.0 or cell.total_traded_notional < 0.0:
        raise ValueError(f"{key}: negative fills/turnover/notional")
    if cell.terminal_liquidation_equity > cell.marked_terminal_equity:
        raise ValueError(f"{key}: liquidation equity exceeds marked equity")
    if cell.marked_total_return != cell.marked_terminal_equity / cell.initial_cash - 1.0:
        raise ValueError(f"{key}: marked_total_return identity violated")
    if cell.liquidation_total_return != cell.terminal_liquidation_equity / cell.initial_cash - 1.0:
        raise ValueError(f"{key}: liquidation_total_return identity violated")
    if not 0.0 <= cell.exposure_fraction <= 1.0:
        raise ValueError(f"{key}: exposure_fraction out of [0,1]")
    if not -1.0 <= cell.max_drawdown <= 0.0:
        raise ValueError(f"{key}: max_drawdown out of [-1,0]")
    if not cell.equity_positive:
        raise ValueError(f"{key}: equity_positive must be true")
    if cell.strategy == _CASH:
        if cell.num_fills != 0 or cell.turnover != 0.0 or cell.total_traded_notional != 0.0:
            raise ValueError(f"{key}: cash must not trade")
        if cell.marked_total_return != 0.0 or cell.exposure_fraction != 0.0:
            raise ValueError(f"{key}: cash must hold constant equity with zero exposure")
    if cell.strategy == _BUY_AND_HOLD and cell.num_fills != 1:
        raise ValueError(f"{key}: buy-and-hold must fund exactly one entry per fold")


def reconcile_results_v2_with_evidence(
    results: DevelopmentResultsV2, evidence: ReturnEvidence
) -> None:
    """Recompute pooled diagnostics and bootstrap points from the return evidence.

    The return evidence must belong to this run, and every pooled cell and both
    bootstrap intervals (primary + sensitivity) must recompute exactly from the
    evidence's raw daily observations. Raises on any mismatch.
    """
    if evidence.experiment_id != results.experiment_id:
        raise DevelopmentResultsV2Error("return evidence experiment id disagrees with results")
    if tuple(evidence.strategies) != tuple(results.strategies):
        raise DevelopmentResultsV2Error("return evidence strategies disagree")
    if tuple(evidence.cost_scenarios) != tuple(results.cost_scenarios):
        raise DevelopmentResultsV2Error("return evidence cost scenarios disagree")
    ppy = evidence.periods_per_year
    pooled_by = {(p.strategy, p.cost_scenario): p for p in results.pooled_reset_oos}
    for sc in results.cost_scenarios:
        for st in results.strategies:
            rederived = _pooled_reset_oos(st, sc, list(evidence.fold_series(st, sc)), ppy)
            if rederived != pooled_by[(st, sc)]:
                raise DevelopmentResultsV2Error(
                    f"pooled ({st},{sc}) does not recompute from the return evidence"
                )
    for cell in results.bootstrap_cells:
        # Recompute with the exact configuration the cell declares (self-describing).
        config = FoldAwareBootstrapConfig(
            seed=cell.primary.base_seed,
            block_length=cell.primary.block_length,
            resamples=cell.primary.resamples,
            confidence=cell.primary.confidence,
        )
        if cell.sensitivity.base_seed != cell.primary.base_seed:
            raise DevelopmentResultsV2Error(
                f"sensitivity/primary base seed ({cell.strategy},{cell.cost_scenario}) disagree"
            )
        if (
            cell.primary.effective_rng_seed != cell.primary.base_seed
            or cell.sensitivity.effective_rng_seed != cell.sensitivity.base_seed + 1
        ):
            raise DevelopmentResultsV2Error(
                f"recorded effective RNG seeds ({cell.strategy},{cell.cost_scenario}) are wrong"
            )
        fold_excess = paired_excess_returns_from_folds(
            evidence.fold_series(cell.strategy, cell.cost_scenario),
            evidence.fold_series(_BUY_AND_HOLD, cell.cost_scenario),
        )
        primary = fold_stratified_moving_block_bootstrap(fold_excess, config)
        sensitivity = hierarchical_fold_block_bootstrap(fold_excess, config)
        if primary != cell.primary:
            raise DevelopmentResultsV2Error(
                f"primary bootstrap ({cell.strategy},{cell.cost_scenario}) does not recompute"
            )
        if sensitivity != cell.sensitivity:
            raise DevelopmentResultsV2Error(
                f"sensitivity bootstrap ({cell.strategy},{cell.cost_scenario}) does not recompute"
            )


def load_development_results_v2(path: str | Path) -> DevelopmentResultsV2:
    """Strictly parse a committed v2 development-results file into the typed model."""
    raw = Path(path).read_bytes()
    try:
        return DevelopmentResultsV2.from_json_bytes(raw)
    except ValueError as exc:
        raise DevelopmentResultsV2Error(f"invalid v2 development results: {exc}") from exc


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _interval_str(iv: FoldAwareInterval) -> str:
    return f"[{_pct(iv.ci_lower)}, {_pct(iv.ci_upper)}] (point {_pct(iv.point_estimate)})"


def render_development_report_v2(results: DevelopmentResultsV2) -> str:
    """Render the run-003 Markdown report purely from the validated v2 model.

    Deterministic: a fresh clone renders the identical bytes from the committed
    results, so replay byte-compares it. Reports the fold-aware bootstrap v2
    (primary + hierarchical sensitivity) intervals and states the correction
    lineage honestly.
    """
    lines: list[str] = []
    add = lines.append
    scenarios = list(results.cost_scenarios)
    pooled_by = {(p.strategy, p.cost_scenario): p for p in results.pooled_reset_oos}
    boot_by = {(b.strategy, b.cost_scenario): b for b in results.bootstrap_cells}
    summ_by = {(s.strategy, s.cost_scenario): s for s in results.independent_fold_summaries}

    add("# Milestone 3A development walk-forward report (run-003, corrected inference)")
    add("")
    add("## 1. Research-only disclaimer")
    add("")
    add(
        "> Research observations on historical data — **not** a profitability claim, "
        "**not** expected future returns, and **not** investment advice. No alpha is "
        "claimed; the fixed parameters were never optimized. This run corrects "
        "**methodology and publication governance only** — every per-fold financial "
        "result is bit-identical to run-002; no strategy parameter changed."
    )
    add("")
    add(f"- Experiment id: `{results.experiment_id}`")
    add(f"- Methodology: `{results.methodology_id}` (`{results.methodology_protocol_path}`)")
    add(f"- Execution source-tree fingerprint: `{results.execution_source_tree_fingerprint}`")
    add("")
    add("## 2. Data-access boundaries")
    add("")
    add("| level | dates (UTC) | rows | M3A access |")
    add("| --- | --- | ---: | --- |")
    add("| research train | 2016-05-23 .. 2022-06-21 | 2221 | evaluated |")
    add("| development gate | 2022-06-22 .. 2024-06-30 | 740 | **not evaluated (forbidden)** |")
    add("| final holdout | 2024-07-01 .. 2026-07-11 | 741 | **not evaluated (forbidden)** |")
    add("")
    add(
        f"- Development-gate ledger events: **{results.development_gate_event_count}** "
        f"(byte-empty). Final-holdout ledger events: **{results.final_holdout_event_count}** "
        "(byte-empty). This is fixed-rule rolling-origin OOS evaluation with expanding "
        "information sets — no estimator is fit."
    )
    add("")
    add("## 3. Corrected fold-aware bootstrap (v2)")
    add("")
    add(
        "Run-001 and run-002 used the historical moving-block bootstrap v1, whose blocks "
        "could cross independent-reset fold seams. Run-003 uses the **primary** "
        "fold-stratified bootstrap v2 (blocks drawn strictly within a fold) and reports a "
        "**hierarchical** fold-block sensitivity bootstrap. All intervals are in-sample "
        "research diagnostics on five folds — weak evidence — and every one is reported, "
        "including inconvenient results. Intervals are of mean daily paired excess return "
        "versus buy-and-hold."
    )
    add("")
    add("| strategy | scenario | primary 95% CI | sensitivity 95% CI |")
    add("| --- | --- | --- | --- |")
    for sc in scenarios:
        for st in results.strategies:
            if (st, sc) not in boot_by:
                continue
            cell = boot_by[(st, sc)]
            primary = _interval_str(cell.primary)
            sens = _interval_str(cell.sensitivity)
            add(f"| {st} | {sc} | {primary} | {sens} |")
    add("")
    add("## 4. Pooled reset-OOS diagnostics (mean daily return)")
    add("")
    add("| strategy | scenario | obs | mean daily | beats B&H (folds) |")
    add("| --- | --- | ---: | --- | --- |")
    for sc in scenarios:
        for st in results.strategies:
            pooled = pooled_by[(st, sc)]
            summary = summ_by[(st, sc)]
            add(
                f"| {st} | {sc} | {pooled.observation_count} | {_pct(pooled.mean_daily_return)} | "
                f"{summary.fraction_beating_buy_and_hold:.0%} |"
            )
    add("")
    add("## 5. Honest finding")
    add("")
    add(
        "Over the research-train period — an ETH bull market — buy-and-hold dominates "
        "median return; the active strategies beat buy-and-hold in a minority of folds, "
        "and every fold-aware bootstrap interval of mean daily paired excess return versus "
        "buy-and-hold straddles zero. No alpha is claimed, nothing was tuned, and losing "
        "folds and severe-cost failures are retained exactly as computed. This is in-sample "
        "development evidence, not live performance and not test performance. No candidate "
        "is promoted; the development gate and the final holdout remain sealed."
    )
    add("")
    return "\n".join(lines) + "\n"
