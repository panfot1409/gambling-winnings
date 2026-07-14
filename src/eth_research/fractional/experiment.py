"""The one preregistered Milestone 3B fractional experiment (Phase 16/19).

``compute_fractional_fold_cells`` is the pure, deterministic core of the single
preregistered run: it materializes the five research-train OOS folds, runs the
causal fractional engine for every (strategy, cost-scenario, fold) triple,
reconciles each result against its primitives, and reduces it to an immutable
:class:`FractionalFoldCell`. No parameter is fitted, no cell is dropped, no
bootstrap or significance test is run, and the order is fixed (fold-major, then
scenario, then strategy) so the serialized results are byte-stable.

``build_fractional_results`` assembles the strict top-level model from the fold
cells plus the run's provenance, re-deriving the aggregates from the cells and
binding the frozen protocol, partition, and dossier. The orchestrator supplies
the provenance (commit identities, source fingerprint) and publishes the model;
this module never writes a file, touches the network, or reads a sealed row.
"""

from __future__ import annotations

import math

import pandas as pd

from eth_research.data.provenance import content_fingerprint
from eth_research.data.schema import frame_interval
from eth_research.fractional.accounting import DEFAULT_TOLERANCES, Tolerances
from eth_research.fractional.cost_model import SCENARIOS, CostScenario
from eth_research.fractional.engine import FractionalBacktestResult, run_fractional_backtest
from eth_research.fractional.metrics import FractionalMetrics, compute_fractional_metrics
from eth_research.fractional.protocol import (
    EXPERIMENT_FAMILY,
    FRACTIONAL_PROTOCOL_RELPATH,
    RUN_001_EXPERIMENT_ID,
    FractionalProtocol,
)
from eth_research.fractional.reconciliation import reconcile_result
from eth_research.fractional.results import (
    FRACTIONAL_RESULTS_SCHEMA_VERSION,
    FractionalFoldCell,
    FractionalResults,
    build_aggregates,
)
from eth_research.fractional.strategies import STRATEGY_NAMES, FractionalStrategy, build_strategies
from eth_research.metrics import periods_per_year_from_interval
from eth_research.walkforward import (
    FoldFrames,
    WalkForwardProtocol,
    build_fold_frames,
)


class ExperimentError(RuntimeError):
    """The fractional experiment disagreed with the frozen protocol or data."""


def _finite_or_none(value: float) -> float | None:
    """NaN performance ratios (zero-volatility folds) serialize as ``null``."""
    return None if math.isnan(value) else float(value)


def _fold_cell(
    fold: FoldFrames,
    strategy: FractionalStrategy,
    scenario: CostScenario,
    result: FractionalBacktestResult,
    metrics: FractionalMetrics,
) -> FractionalFoldCell:
    """Reduce one reconciled backtest to its immutable fold-cell record."""
    liquidation_total_return = result.terminal_liquidation_equity / result.initial_cash - 1.0
    return FractionalFoldCell(
        fold_index=fold.fold_index,
        strategy=strategy.name,
        cost_scenario=scenario.name,
        oos_row_count=len(fold.oos),
        oos_first_open_time=fold.oos.index[0],
        oos_last_open_time=fold.oos.index[-1],
        initial_cash=result.initial_cash,
        marked_terminal_equity=metrics.terminal_equity,
        terminal_liquidation_equity=metrics.terminal_liquidation_equity,
        marked_total_return=metrics.total_return,
        liquidation_total_return=liquidation_total_return,
        annualized_return=metrics.annualized_return,
        annualized_volatility=metrics.annualized_volatility,
        sharpe_ratio=_finite_or_none(metrics.sharpe_ratio),
        sortino_ratio=_finite_or_none(metrics.sortino_ratio),
        max_drawdown=metrics.max_drawdown,
        num_fills=metrics.num_fills,
        num_partial_fills=metrics.num_partial_fills,
        total_traded_notional=metrics.total_traded_notional,
        turnover=metrics.turnover,
        total_fees=metrics.total_fees,
        average_achieved_exposure=metrics.average_achieved_exposure,
        time_in_market=metrics.time_in_market,
    )


def compute_fractional_fold_cells(
    research_train: pd.DataFrame,
    wf_protocol: WalkForwardProtocol,
    *,
    initial_cash: float,
    strategies: tuple[FractionalStrategy, ...] | None = None,
    scenarios: tuple[CostScenario, ...] = SCENARIOS,
    tol: Tolerances = DEFAULT_TOLERANCES,
) -> tuple[FractionalFoldCell, ...]:
    """Run the full (fold x scenario x strategy) grid on the research train.

    Each fold's warm-up ``context`` (the pre-registered pre-OOS prefix) feeds
    signal / liquidity / volatility estimation only and creates no P&L; every
    result is reconciled against its own primitives before it is reduced to a
    cell, so a silent accounting drift fails the run rather than being reported.
    The iteration order is fixed for byte-stable serialization.
    """
    fold_frames = build_fold_frames(research_train, wf_protocol)
    resolved = build_strategies() if strategies is None else strategies
    periods_per_year = periods_per_year_from_interval(frame_interval(research_train))
    cells: list[FractionalFoldCell] = []
    for fold in fold_frames:
        for scenario in scenarios:
            for strategy in resolved:
                result = run_fractional_backtest(
                    fold.oos,
                    strategy,
                    scenario,
                    initial_cash=initial_cash,
                    context=fold.context,
                    tol=tol,
                )
                # Fail closed: a result that does not re-derive from its
                # primitives must never reach the published record.
                reconcile_result(result, scenario, tol=tol)
                metrics = compute_fractional_metrics(result, periods_per_year=periods_per_year)
                cells.append(_fold_cell(fold, strategy, scenario, result, metrics))
    return tuple(cells)


def build_fractional_results(
    *,
    fractional_protocol: FractionalProtocol,
    research_train: pd.DataFrame,
    fold_cells: tuple[FractionalFoldCell, ...],
    package_version: str,
    execution_code_commit_sha: str,
    registered_code_commit_sha: str,
    execution_source_tree_fingerprint: str,
    fractional_protocol_sha256: str,
) -> FractionalResults:
    """Assemble the strict results model from the fold cells and run provenance.

    Re-derives the research-train content fingerprint from the data actually
    evaluated and fails closed if it disagrees with the frozen protocol, then
    re-derives the aggregates from the cells (the model re-checks this on
    construction). Both sealed access-ledger counts are pinned at zero.
    """
    fingerprint = content_fingerprint(research_train)
    if fingerprint != fractional_protocol.research_train_content_fingerprint:
        raise ExperimentError(
            "research-train content fingerprint disagrees with the frozen protocol"
        )
    return FractionalResults(
        fractional_results_schema_version=FRACTIONAL_RESULTS_SCHEMA_VERSION,
        experiment_id=RUN_001_EXPERIMENT_ID,
        experiment_family=EXPERIMENT_FAMILY,
        package_version=package_version,
        execution_code_commit_sha=execution_code_commit_sha,
        registered_code_commit_sha=registered_code_commit_sha,
        execution_source_tree_fingerprint=execution_source_tree_fingerprint,
        fractional_protocol_path=FRACTIONAL_PROTOCOL_RELPATH,
        fractional_protocol_sha256=fractional_protocol_sha256,
        frozen_m2_dossier_sha256=fractional_protocol.frozen_m2_dossier_sha256,
        development_partition_sha256=fractional_protocol.development_partition_sha256,
        research_train_content_fingerprint=fingerprint,
        strategies=STRATEGY_NAMES,
        cost_scenarios=tuple(s.name for s in SCENARIOS),
        fold_cells=fold_cells,
        aggregates=build_aggregates(fold_cells),
        development_gate_event_count=0,
        final_holdout_event_count=0,
    )
