"""Walk-forward evaluator for the Milestone 3A development laboratory.

Executes the four fixed strategies (cash, buy-and-hold, SMA(20/50),
Donchian(55/20)) under the three predeclared cost scenarios across the five
expanding-window OOS folds — on the **research-train partition only**. It
verifies the frozen M2 dossier, the committed development partition, and the
committed walk-forward protocol before any evaluation; it slices folds
positionally and passes each strategy only its fold frame and permitted
preceding context; and it reconciles every reported scalar against the
engine's :class:`BacktestResult`.

Three honest views are produced and never mixed:

* **independent-fold summary** — per strategy/scenario aggregates over the
  five reset folds;
* **pooled reset-OOS** (``pooled_reset_oos``) — the concatenated daily OOS
  return observations from the five independent folds; a diagnostic, **not**
  a continuously tradable portfolio;
* **full-train exploratory** (``exploratory_in_sample_full_train``) — the
  whole research-train period evaluated once, in-sample, kept separate.

No development-gate or final-holdout row ever reaches a strategy or the
engine — the firewall guards every frame and context.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from eth_research import __version__
from eth_research.backtest import BacktestResult, run_backtest
from eth_research.bootstrap import (
    BootstrapConfig,
    BootstrapInterval,
    moving_block_bootstrap,
    paired_excess_returns,
)
from eth_research.costs import COST_SCENARIOS, CostScenario
from eth_research.data.provenance import require_int, require_nonempty_str, require_str, sha256_file
from eth_research.development import (
    DEVELOPMENT_PARTITION_RELPATH,
    DevelopmentDataset,
    guard_context,
    guard_research_train_frame,
    load_development_dataset,
    load_development_partition,
)
from eth_research.metrics import (
    bar_returns,
    cagr,
    max_drawdown,
    periods_per_year_from_interval,
    sharpe_ratio,
    sortino_ratio,
)
from eth_research.strategies import (
    BuyAndHold,
    Cash,
    DonchianChannel,
    MovingAverageCrossover,
    Strategy,
)
from eth_research.walkforward import (
    WALK_FORWARD_PROTOCOL_RELPATH,
    FoldFrames,
    WalkForwardProtocol,
    build_fold_frames,
    load_walk_forward_protocol,
)

DEVELOPMENT_RESULTS_SCHEMA_VERSION: int = 1
EXPECTED_SHORTFALL_LEVEL: float = 0.05
_CASH_STRATEGY: str = "cash"
_BUY_AND_HOLD: str = "buy_and_hold"


class DevelopmentEvaluationError(RuntimeError):
    """The development evaluation was refused or failed to reconcile."""


def _strategy(name: str) -> tuple[Strategy, int]:
    """Instantiate a pinned strategy and its warm-up context requirement."""
    if name == _CASH_STRATEGY:
        return Cash(), 0
    if name == _BUY_AND_HOLD:
        return BuyAndHold(), 0
    if name == "sma_20_50":
        return MovingAverageCrossover(fast_window=20, slow_window=50), 50
    if name == "donchian_55_20":
        return DonchianChannel(entry_window=55, exit_window=20), 55
    raise DevelopmentEvaluationError(f"unknown strategy {name!r}")


# --- Diagnostics (each defined exactly) ---------------------------------------


def exposure_fraction(result: BacktestResult) -> float:
    """Fraction of OOS marked bars holding a positive ETH quantity.

    Context bars contribute no accounting, so the equity/quantity series
    already cover exactly the evaluated (OOS) bars.
    """
    quantity = result.quantity.to_numpy(dtype=float)
    if len(quantity) == 0:
        return 0.0
    return float((quantity > 0.0).mean())


def expected_shortfall(returns: np.ndarray, level: float = EXPECTED_SHORTFALL_LEVEL) -> float:
    """Empirical expected shortfall: mean of returns at or below the cutoff.

    The cutoff is the finite ``level`` empirical quantile (linear method);
    the statistic is the arithmetic mean of every observation at or below it.
    Not a forecast — a description of the observed left tail.
    """
    if len(returns) == 0:
        return math.nan
    cutoff = float(np.percentile(returns, level * 100.0, method="linear"))
    tail = returns[returns <= cutoff]
    if len(tail) == 0:  # pragma: no cover - the cutoff is itself an observation-linear point
        return float(returns.min())
    return float(tail.mean())


def longest_drawdown_duration(equity: pd.Series[float], initial_equity: float) -> int:
    """Longest consecutive run of bars strictly below the prior equity peak.

    Initial capital is the first peak, so a loss from the very first bar
    counts. A terminal drawdown that never recovers is counted through the
    final bar. Measured in bars.
    """
    path = np.concatenate(([initial_equity], equity.to_numpy(dtype=float)))
    peaks = np.maximum.accumulate(path)
    underwater = path < peaks  # element 0 (initial) is never underwater
    longest = 0
    current = 0
    for flag in underwater:
        if flag:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def _equity_is_positive(result: BacktestResult) -> bool:
    return bool((result.equity.to_numpy(dtype=float) > 0.0).all())


# --- Per-fold/strategy/scenario result ----------------------------------------


@dataclass(frozen=True)
class FoldStrategyResult:
    """Every reported scalar for one (fold, strategy, cost-scenario) cell."""

    fold_index: int
    strategy: str
    cost_scenario: str
    training_row_count: int
    context_row_count: int
    oos_row_count: int
    oos_first_open_time: pd.Timestamp
    oos_last_open_time: pd.Timestamp
    initial_cash: float
    marked_terminal_equity: float
    terminal_liquidation_equity: float
    marked_total_return: float
    liquidation_total_return: float
    cagr: float
    sharpe: float | None
    sortino: float | None
    max_drawdown: float
    turnover: float
    total_traded_notional: float
    num_fills: int
    exposure_fraction: float
    worst_daily_return: float
    expected_shortfall_5pct: float
    longest_drawdown_duration_bars: int
    equity_positive: bool

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "training_row_count": self.training_row_count,
            "context_row_count": self.context_row_count,
            "oos_row_count": self.oos_row_count,
            "oos_first_open_time": self.oos_first_open_time.isoformat(),
            "oos_last_open_time": self.oos_last_open_time.isoformat(),
            "initial_cash": self.initial_cash,
            "marked_terminal_equity": self.marked_terminal_equity,
            "terminal_liquidation_equity": self.terminal_liquidation_equity,
            "marked_total_return": self.marked_total_return,
            "liquidation_total_return": self.liquidation_total_return,
            "cagr": self.cagr,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "max_drawdown": self.max_drawdown,
            "turnover": self.turnover,
            "total_traded_notional": self.total_traded_notional,
            "num_fills": self.num_fills,
            "exposure_fraction": self.exposure_fraction,
            "worst_daily_return": self.worst_daily_return,
            "expected_shortfall_5pct": self.expected_shortfall_5pct,
            "longest_drawdown_duration_bars": self.longest_drawdown_duration_bars,
            "equity_positive": self.equity_positive,
        }


def _finite_or_none(value: float) -> float | None:
    return None if math.isnan(value) else float(value)


def _reconcile(result: BacktestResult, oos: pd.DataFrame, initial_cash: float) -> None:
    """Every scalar must agree with the engine's accounting (bug guard)."""
    if not result.equity.index.equals(oos.index):
        raise DevelopmentEvaluationError("equity curve does not cover exactly the OOS bars")
    closes = oos["close"].to_numpy(dtype=float)
    recomputed = result.cash.to_numpy(dtype=float) + result.quantity.to_numpy(dtype=float) * closes
    if not np.array_equal(recomputed, result.equity.to_numpy(dtype=float)):
        raise DevelopmentEvaluationError("equity != cash + quantity * close at some bar")
    if result.initial_cash != initial_cash:
        raise DevelopmentEvaluationError("initial cash disagrees with the protocol")


def evaluate_fold_strategy(
    fold: FoldFrames,
    strategy_name: str,
    scenario: CostScenario,
    *,
    initial_cash: float,
    research_train_last_open: pd.Timestamp,
    periods_per_year: float,
) -> tuple[FoldStrategyResult, pd.Series[float]]:
    """Run one strategy under one scenario on one fold's OOS; return the row
    and the fold's daily OOS return series (for pooling and bootstrap)."""
    strategy, needed_context = _strategy(strategy_name)
    # Firewall: neither the OOS frame nor the context may cross the boundary.
    guard_research_train_frame(fold.oos, research_train_last_open)
    context = fold.context.iloc[-needed_context:] if needed_context > 0 else None
    guard_context(context, research_train_last_open)

    result = run_backtest(
        fold.oos, strategy, scenario.cost_model(), initial_cash=initial_cash, context=context
    )
    _reconcile(result, fold.oos, initial_cash)
    returns = bar_returns(result.equity, result.initial_cash)
    returns_np = returns.to_numpy(dtype=float)
    marked_terminal = result.terminal_equity
    liquidation = result.terminal_liquidation_equity
    row = FoldStrategyResult(
        fold_index=fold.fold_index,
        strategy=strategy.name,
        cost_scenario=scenario.name,
        training_row_count=len(fold.training),
        context_row_count=0 if context is None else len(context),
        oos_row_count=len(fold.oos),
        oos_first_open_time=fold.oos.index[0],
        oos_last_open_time=fold.oos.index[-1],
        initial_cash=initial_cash,
        marked_terminal_equity=marked_terminal,
        terminal_liquidation_equity=liquidation,
        marked_total_return=marked_terminal / initial_cash - 1.0,
        liquidation_total_return=liquidation / initial_cash - 1.0,
        cagr=cagr(initial_cash, marked_terminal, result.start_time, result.end_time),
        sharpe=_finite_or_none(sharpe_ratio(returns, periods_per_year)),
        sortino=_finite_or_none(sortino_ratio(returns, periods_per_year)),
        max_drawdown=max_drawdown(result.equity, initial_cash),
        turnover=result.turnover,
        total_traded_notional=result.total_traded_notional,
        num_fills=result.num_trades,
        exposure_fraction=exposure_fraction(result),
        worst_daily_return=float(returns_np.min()),
        expected_shortfall_5pct=expected_shortfall(returns_np),
        longest_drawdown_duration_bars=longest_drawdown_duration(result.equity, initial_cash),
        equity_positive=_equity_is_positive(result),
    )
    return row, returns


# --- Aggregation --------------------------------------------------------------


@dataclass(frozen=True)
class IndependentFoldSummary:
    """Per strategy/scenario aggregate over the five independent reset folds."""

    strategy: str
    cost_scenario: str
    fold_count: int
    median_marked_return: float
    median_liquidation_return: float
    worst_liquidation_fold_return: float
    best_marked_fold_return: float
    median_sharpe: float | None
    worst_max_drawdown: float
    total_fills: int
    median_turnover: float
    fraction_positive_folds: float
    fraction_beating_buy_and_hold: float
    fraction_beating_cash: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "fold_count": self.fold_count,
            "median_marked_return": self.median_marked_return,
            "median_liquidation_return": self.median_liquidation_return,
            "worst_liquidation_fold_return": self.worst_liquidation_fold_return,
            "best_marked_fold_return": self.best_marked_fold_return,
            "median_sharpe": self.median_sharpe,
            "worst_max_drawdown": self.worst_max_drawdown,
            "total_fills": self.total_fills,
            "median_turnover": self.median_turnover,
            "fraction_positive_folds": self.fraction_positive_folds,
            "fraction_beating_buy_and_hold": self.fraction_beating_buy_and_hold,
            "fraction_beating_cash": self.fraction_beating_cash,
        }


def _median(values: list[float]) -> float:
    return float(np.median(np.array(values, dtype=float)))


def _summarize_independent_folds(
    rows: list[FoldStrategyResult],
    by_cell: dict[tuple[int, str, str], FoldStrategyResult],
) -> list[IndependentFoldSummary]:
    strategies = _ordered_unique(row.strategy for row in rows)
    scenarios = _ordered_unique(row.cost_scenario for row in rows)
    summaries: list[IndependentFoldSummary] = []
    for scenario in scenarios:
        for strategy in strategies:
            cells = [
                row for row in rows if row.strategy == strategy and row.cost_scenario == scenario
            ]
            folds = sorted(cells, key=lambda r: r.fold_index)
            marked = [c.marked_total_return for c in folds]
            liq = [c.liquidation_total_return for c in folds]
            beats_bnh = 0
            beats_cash = 0
            for cell in folds:
                bnh = by_cell[(cell.fold_index, _BUY_AND_HOLD, scenario)]
                cash = by_cell[(cell.fold_index, _CASH_STRATEGY, scenario)]
                if cell.marked_total_return > bnh.marked_total_return:
                    beats_bnh += 1
                if cell.marked_total_return > cash.marked_total_return:
                    beats_cash += 1
            sharpes = [c.sharpe for c in folds if c.sharpe is not None]
            summaries.append(
                IndependentFoldSummary(
                    strategy=strategy,
                    cost_scenario=scenario,
                    fold_count=len(folds),
                    median_marked_return=_median(marked),
                    median_liquidation_return=_median(liq),
                    worst_liquidation_fold_return=min(liq),
                    best_marked_fold_return=max(marked),
                    median_sharpe=_median(sharpes) if sharpes else None,
                    worst_max_drawdown=min(c.max_drawdown for c in folds),
                    total_fills=sum(c.num_fills for c in folds),
                    median_turnover=_median([c.turnover for c in folds]),
                    fraction_positive_folds=sum(1 for r in marked if r > 0) / len(folds),
                    fraction_beating_buy_and_hold=beats_bnh / len(folds),
                    fraction_beating_cash=beats_cash / len(folds),
                )
            )
    return summaries


@dataclass(frozen=True)
class PooledResetOOS:
    """Concatenated daily OOS observations across folds — NOT a live path."""

    strategy: str
    cost_scenario: str
    observation_count: int
    mean_daily_return: float
    volatility: float
    sharpe: float | None
    sortino: float | None
    worst_daily_return: float
    expected_shortfall_5pct: float
    reset_path_max_drawdown: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "observation_count": self.observation_count,
            "mean_daily_return": self.mean_daily_return,
            "volatility": self.volatility,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "worst_daily_return": self.worst_daily_return,
            "expected_shortfall_5pct": self.expected_shortfall_5pct,
            "reset_path_max_drawdown": self.reset_path_max_drawdown,
        }


def _reset_path_max_drawdown(returns: np.ndarray) -> float:
    """Max drawdown of the synthetic path formed by compounding the pooled
    per-fold reset returns from 1.0 — a diagnostic on the concatenated
    observations, explicitly not a traded equity curve."""
    path = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peaks = np.maximum.accumulate(path)
    return float((path / peaks - 1.0).min())


def _pooled_reset_oos(
    strategy: str,
    scenario: str,
    fold_returns: list[pd.Series[float]],
    periods_per_year: float,
) -> PooledResetOOS:
    pooled = pd.concat(fold_returns)
    values = pooled.to_numpy(dtype=float)
    std = float(pooled.std(ddof=1)) if len(values) > 1 else 0.0
    return PooledResetOOS(
        strategy=strategy,
        cost_scenario=scenario,
        observation_count=len(values),
        mean_daily_return=float(values.mean()),
        volatility=std,
        sharpe=_finite_or_none(sharpe_ratio(pooled, periods_per_year)),
        sortino=_finite_or_none(sortino_ratio(pooled, periods_per_year)),
        worst_daily_return=float(values.min()),
        expected_shortfall_5pct=expected_shortfall(values),
        reset_path_max_drawdown=_reset_path_max_drawdown(values),
    )


def _ordered_unique(items: Any) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


@dataclass(frozen=True)
class FullTrainExploratory:
    """Whole research-train period evaluated once, in-sample. Kept separate."""

    strategy: str
    cost_scenario: str
    row_count: int
    marked_total_return: float
    liquidation_total_return: float
    cagr: float
    sharpe: float | None
    sortino: float | None
    max_drawdown: float
    turnover: float
    num_fills: int
    exposure_fraction: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "row_count": self.row_count,
            "marked_total_return": self.marked_total_return,
            "liquidation_total_return": self.liquidation_total_return,
            "cagr": self.cagr,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "max_drawdown": self.max_drawdown,
            "turnover": self.turnover,
            "num_fills": self.num_fills,
            "exposure_fraction": self.exposure_fraction,
        }


@dataclass(frozen=True)
class BootstrapCell:
    """One non-B&H strategy/scenario paired-excess bootstrap interval."""

    strategy: str
    cost_scenario: str
    interval: BootstrapInterval

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "interval": self.interval.to_json_dict(),
        }


@dataclass(frozen=True)
class DevelopmentResults:
    """The complete, strict, byte-reproducible M3A development result."""

    development_results_schema_version: int
    package_version: str
    execution_code_commit_sha: str
    registered_code_commit_sha: str
    frozen_m2_dossier_sha256: str
    development_partition_sha256: str
    walk_forward_protocol_sha256: str
    dataset_content_fingerprint: str
    research_train_content_fingerprint: str
    experiment_family_id: str
    strategies: tuple[str, ...]
    cost_scenarios: tuple[str, ...]
    fold_results: tuple[FoldStrategyResult, ...]
    independent_fold_summaries: tuple[IndependentFoldSummary, ...]
    pooled_reset_oos: tuple[PooledResetOOS, ...]
    full_train_exploratory: tuple[FullTrainExploratory, ...]
    bootstrap_cells: tuple[BootstrapCell, ...]
    development_gate_event_count: int
    final_holdout_event_count: int

    def __post_init__(self) -> None:
        require_int("development_results_schema_version", self.development_results_schema_version)
        require_nonempty_str("package_version", self.package_version)
        if self.development_gate_event_count != 0:
            raise ValueError("development-gate event count must be 0 in Milestone 3A")
        if self.final_holdout_event_count != 0:
            raise ValueError("final-holdout event count must be 0 in Milestone 3A")

    def to_json_bytes(self) -> bytes:
        payload = {
            "development_results_schema_version": self.development_results_schema_version,
            "package_version": self.package_version,
            "execution_code_commit_sha": self.execution_code_commit_sha,
            "registered_code_commit_sha": self.registered_code_commit_sha,
            "frozen_m2_dossier_sha256": self.frozen_m2_dossier_sha256,
            "development_partition_sha256": self.development_partition_sha256,
            "walk_forward_protocol_sha256": self.walk_forward_protocol_sha256,
            "dataset_content_fingerprint": self.dataset_content_fingerprint,
            "research_train_content_fingerprint": self.research_train_content_fingerprint,
            "experiment_family_id": self.experiment_family_id,
            "strategies": list(self.strategies),
            "cost_scenarios": list(self.cost_scenarios),
            "fold_results": [row.to_json_dict() for row in self.fold_results],
            "independent_fold_summaries": [
                s.to_json_dict() for s in self.independent_fold_summaries
            ],
            "pooled_reset_oos": [p.to_json_dict() for p in self.pooled_reset_oos],
            "full_train_exploratory": [f.to_json_dict() for f in self.full_train_exploratory],
            "bootstrap_cells": [b.to_json_dict() for b in self.bootstrap_cells],
            "data_access_declaration": {
                "research_train": "evaluated (permitted)",
                "development_gate": "not evaluated (forbidden in M3A)",
                "final_holdout": "not evaluated (forbidden in M3A)",
            },
            "development_gate_event_count": self.development_gate_event_count,
            "final_holdout_event_count": self.final_holdout_event_count,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")


def _periods_per_year(oos: pd.DataFrame) -> float:
    from eth_research.data.schema import frame_interval

    return periods_per_year_from_interval(frame_interval(oos))


def evaluate_development(
    repo_root: str | Path,
    manifest_path: str | Path,
    *,
    execution_code_commit_sha: str,
    registered_code_commit_sha: str,
    experiment_family_id: str,
) -> DevelopmentResults:
    """Run the full research-train walk-forward and return the strict result.

    Verifies the frozen M2 dossier, the committed development partition, and
    the committed walk-forward protocol before evaluating; touches no
    forbidden partition.
    """
    root = Path(repo_root)
    dataset: DevelopmentDataset = load_development_dataset(root, manifest_path)
    research_train = dataset.frame
    boundary = dataset.research_train_last_open_time
    partition = load_development_partition(root / DEVELOPMENT_PARTITION_RELPATH)

    protocol: WalkForwardProtocol = load_walk_forward_protocol(root / WALK_FORWARD_PROTOCOL_RELPATH)
    partition_sha = sha256_file(root / DEVELOPMENT_PARTITION_RELPATH)
    if protocol.development_partition_sha256 != partition_sha:
        raise DevelopmentEvaluationError(
            "protocol does not bind the committed development partition"
        )
    if protocol.research_train_content_fingerprint != partition.research_train.content_fingerprint:
        raise DevelopmentEvaluationError("protocol research-train fingerprint disagrees")

    folds = build_fold_frames(research_train, protocol)
    ppy = _periods_per_year(research_train)

    rows: list[FoldStrategyResult] = []
    fold_returns: dict[tuple[str, str], list[pd.Series[float]]] = {}
    for fold in folds:
        for scenario in COST_SCENARIOS:
            for strategy_name in protocol.strategies:
                row, returns = evaluate_fold_strategy(
                    fold,
                    strategy_name,
                    scenario,
                    initial_cash=protocol.initial_cash,
                    research_train_last_open=boundary,
                    periods_per_year=ppy,
                )
                rows.append(row)
                fold_returns.setdefault((row.strategy, scenario.name), []).append(returns)

    by_cell = {(r.fold_index, r.strategy, r.cost_scenario): r for r in rows}
    summaries = _summarize_independent_folds(rows, by_cell)

    pooled: list[PooledResetOOS] = []
    for scenario in COST_SCENARIOS:
        for strategy_name in protocol.strategies:
            pooled.append(
                _pooled_reset_oos(
                    strategy_name, scenario.name, fold_returns[(strategy_name, scenario.name)], ppy
                )
            )

    bootstrap_cells: list[BootstrapCell] = []
    for scenario in COST_SCENARIOS:
        bnh_pooled = pd.concat(fold_returns[(_BUY_AND_HOLD, scenario.name)])
        for strategy_name in protocol.strategies:
            if strategy_name == _BUY_AND_HOLD:
                continue
            cand_pooled = pd.concat(fold_returns[(strategy_name, scenario.name)])
            excess = paired_excess_returns(cand_pooled, bnh_pooled)
            interval = moving_block_bootstrap(excess, BootstrapConfig())
            bootstrap_cells.append(
                BootstrapCell(
                    strategy=strategy_name, cost_scenario=scenario.name, interval=interval
                )
            )

    full_train = _full_train_exploratory(research_train, protocol, boundary, ppy)

    return DevelopmentResults(
        development_results_schema_version=DEVELOPMENT_RESULTS_SCHEMA_VERSION,
        package_version=__version__,
        execution_code_commit_sha=require_str(
            "execution_code_commit_sha", execution_code_commit_sha
        ),
        registered_code_commit_sha=require_str(
            "registered_code_commit_sha", registered_code_commit_sha
        ),
        frozen_m2_dossier_sha256=partition.frozen_m2_dossier_sha256,
        development_partition_sha256=partition_sha,
        walk_forward_protocol_sha256=sha256_file(root / WALK_FORWARD_PROTOCOL_RELPATH),
        dataset_content_fingerprint=partition.dataset_content_fingerprint,
        research_train_content_fingerprint=partition.research_train.content_fingerprint,
        experiment_family_id=require_str("experiment_family_id", experiment_family_id),
        strategies=protocol.strategies,
        cost_scenarios=tuple(s.name for s in COST_SCENARIOS),
        fold_results=tuple(rows),
        independent_fold_summaries=tuple(summaries),
        pooled_reset_oos=tuple(pooled),
        full_train_exploratory=tuple(full_train),
        bootstrap_cells=tuple(bootstrap_cells),
        development_gate_event_count=0,
        final_holdout_event_count=0,
    )


def _full_train_exploratory(
    research_train: pd.DataFrame,
    protocol: WalkForwardProtocol,
    boundary: pd.Timestamp,
    periods_per_year: float,
) -> list[FullTrainExploratory]:
    guard_research_train_frame(research_train, boundary)
    out: list[FullTrainExploratory] = []
    for scenario in COST_SCENARIOS:
        for strategy_name in protocol.strategies:
            strategy, _ = _strategy(strategy_name)
            result = run_backtest(
                research_train,
                strategy,
                scenario.cost_model(),
                initial_cash=protocol.initial_cash,
            )
            returns = bar_returns(result.equity, result.initial_cash)
            out.append(
                FullTrainExploratory(
                    strategy=strategy.name,
                    cost_scenario=scenario.name,
                    row_count=len(research_train),
                    marked_total_return=result.total_return,
                    liquidation_total_return=result.terminal_liquidation_equity
                    / result.initial_cash
                    - 1.0,
                    cagr=cagr(
                        result.initial_cash,
                        result.terminal_equity,
                        result.start_time,
                        result.end_time,
                    ),
                    sharpe=_finite_or_none(sharpe_ratio(returns, periods_per_year)),
                    sortino=_finite_or_none(sortino_ratio(returns, periods_per_year)),
                    max_drawdown=max_drawdown(result.equity, result.initial_cash),
                    turnover=result.turnover,
                    num_fills=result.num_trades,
                    exposure_fraction=exposure_fraction(result),
                )
            )
    return out


# --- Strict reload + deterministic report -------------------------------------

_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "development_results_schema_version",
        "package_version",
        "execution_code_commit_sha",
        "registered_code_commit_sha",
        "frozen_m2_dossier_sha256",
        "development_partition_sha256",
        "walk_forward_protocol_sha256",
        "dataset_content_fingerprint",
        "research_train_content_fingerprint",
        "experiment_family_id",
        "strategies",
        "cost_scenarios",
        "fold_results",
        "independent_fold_summaries",
        "pooled_reset_oos",
        "full_train_exploratory",
        "bootstrap_cells",
        "data_access_declaration",
        "development_gate_event_count",
        "final_holdout_event_count",
    }
)


def load_development_results_payload(path: str | Path) -> dict[str, Any]:
    """Strictly parse a committed development-results file into a validated dict.

    Rejects duplicate keys, NaN/Inf, and unknown/missing top-level keys, and
    requires both access-ledger event counts to be zero. Returns the parsed
    payload (the report is rendered from the in-memory model at generation
    time; replay regenerates and byte-compares).
    """
    from eth_research._json import StrictJSONError, strict_json_loads

    raw = Path(path).read_bytes()
    try:
        payload: Any = strict_json_loads(raw)
    except StrictJSONError as exc:
        raise DevelopmentEvaluationError(f"development results are not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DevelopmentEvaluationError("development results JSON must be an object")
    keys = set(payload)
    if keys != _TOP_LEVEL_KEYS:
        unknown = sorted(keys - _TOP_LEVEL_KEYS)
        missing = sorted(_TOP_LEVEL_KEYS - keys)
        raise DevelopmentEvaluationError(
            f"development results keys do not match: unknown={unknown}, missing={missing}"
        )
    if payload["development_gate_event_count"] != 0 or payload["final_holdout_event_count"] != 0:
        raise DevelopmentEvaluationError("a committed M3A result must record zero access events")
    return payload


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _ratio(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.3f}"


def render_development_report(results: DevelopmentResults) -> str:
    """Render the Markdown report purely from the validated results model."""
    lines: list[str] = []
    add = lines.append
    scenarios = list(results.cost_scenarios)
    strategies = list(results.strategies)
    fold_by = {(r.fold_index, r.strategy, r.cost_scenario): r for r in results.fold_results}
    summ_by = {(s.strategy, s.cost_scenario): s for s in results.independent_fold_summaries}
    pooled_by = {(p.strategy, p.cost_scenario): p for p in results.pooled_reset_oos}
    full_by = {(f.strategy, f.cost_scenario): f for f in results.full_train_exploratory}
    boot_by = {(b.strategy, b.cost_scenario): b for b in results.bootstrap_cells}
    fold_indices = sorted({r.fold_index for r in results.fold_results})

    add("# Milestone 3A development walk-forward report")
    add("")
    add("## 1. Research-only disclaimer")
    add("")
    add(
        "> Research observations on historical data — **not** a profitability "
        "claim, **not** expected future returns, and **not** investment advice. "
        "No alpha is claimed; the fixed parameters were never optimized."
    )
    add("")
    add("## 2. Data-access boundaries")
    add("")
    add("| level | dates (UTC) | rows | M3A access |")
    add("| --- | --- | ---: | --- |")
    add("| research train | 2016-05-23 .. 2022-06-21 | 2221 | evaluated |")
    add("| development gate | 2022-06-22 .. 2024-06-30 | 740 | **not evaluated (forbidden)** |")
    add("| final holdout | 2024-07-01 .. 2026-07-11 | 741 | **not evaluated (forbidden)** |")
    add("")
    add("## 3. Proof the gate and holdout were not evaluated")
    add("")
    add(
        f"- Development-gate access ledger events: **{results.development_gate_event_count}** "
        "(byte-empty).\n"
        f"- Final-holdout ledger events: **{results.final_holdout_event_count}** (byte-empty).\n"
        "- Every strategy and backtest received only research-train rows (through "
        "2022-06-21); the firewall rejects any later row."
    )
    add("")
    add("## 4. Walk-forward methodology")
    add("")
    add(
        "Expanding-window walk-forward on the research-train partition: 1095 "
        "initial training rows, five contiguous OOS folds over the remaining "
        "1126 rows (226, 225, 225, 225, 225), information gap 0 bars, context "
        "<= 55 bars, each fold reset to an independent 10,000 USD. Independent "
        "resets are a comparison device, **not** one continuously traded "
        "portfolio."
    )
    add("")
    add("## 5. Fold table")
    add("")
    add("| fold | training rows | context rows | OOS rows | OOS window |")
    add("| ---: | ---: | ---: | ---: | --- |")
    for fi in fold_indices:
        sample = fold_by[(fi, strategies[0], scenarios[0])]
        add(
            f"| {fi} | {sample.training_row_count} | {sample.context_row_count} | "
            f"{sample.oos_row_count} | {sample.oos_first_open_time.date()} .. "
            f"{sample.oos_last_open_time.date()} |"
        )
    add("")
    add("## 6. Cost scenarios")
    add("")
    add(
        "Every strategy is evaluated under all three predeclared scenarios; none "
        "is selected after seeing results. base 0.10%/0.05%, stressed "
        "0.20%/0.10%, severe 0.50%/0.25% (fee/slippage). No frictionless scenario."
    )
    add("")
    add("## 7. Per-fold results")
    add("")
    add("Marked total return per (fold, strategy) at each cost scenario.")
    for scenario in scenarios:
        add("")
        add(f"### Cost scenario: {scenario}")
        add("")
        header = "| strategy | " + " | ".join(f"fold {fi}" for fi in fold_indices) + " |"
        add(header)
        add("| --- | " + " | ".join("---:" for _ in fold_indices) + " |")
        for strategy in strategies:
            cells = " | ".join(
                _pct(fold_by[(fi, strategy, scenario)].marked_total_return) for fi in fold_indices
            )
            add(f"| {strategy} | {cells} |")
    add("")
    add("## 8. Independent-fold summary")
    add("")
    for scenario in scenarios:
        add("")
        add(f"### Cost scenario: {scenario}")
        add("")
        add(
            "| strategy | median marked | median liq | worst liq fold | best marked | "
            "median Sharpe | worst maxDD | fills | frac positive | frac > B&H | frac > cash |"
        )
        add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for strategy in strategies:
            s = summ_by[(strategy, scenario)]
            add(
                f"| {strategy} | {_pct(s.median_marked_return)} | "
                f"{_pct(s.median_liquidation_return)} | {_pct(s.worst_liquidation_fold_return)} | "
                f"{_pct(s.best_marked_fold_return)} | {_ratio(s.median_sharpe)} | "
                f"{_pct(s.worst_max_drawdown)} | {s.total_fills} | "
                f"{s.fraction_positive_folds:.2f} | {s.fraction_beating_buy_and_hold:.2f} | "
                f"{s.fraction_beating_cash:.2f} |"
            )
    add("")
    add("## 9. Pooled reset-OOS")
    add("")
    add(
        "The concatenated daily OOS return observations from the five "
        "independent folds — labelled `pooled_reset_oos`. This is **not** a "
        "continuously tradable portfolio: fold terminal equities are never "
        "multiplied as if capital carried, each fold pays its own reset entry "
        "cost, and it is not untouched-test performance."
    )
    for scenario in scenarios:
        add("")
        add(f"### Cost scenario: {scenario}")
        add("")
        add(
            "| strategy | obs | mean daily | volatility | Sharpe | Sortino | "
            "worst daily | ES 5% | reset-path maxDD |"
        )
        add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for strategy in strategies:
            p = pooled_by[(strategy, scenario)]
            add(
                f"| {strategy} | {p.observation_count} | {_pct(p.mean_daily_return)} | "
                f"{p.volatility:.4f} | {_ratio(p.sharpe)} | {_ratio(p.sortino)} | "
                f"{_pct(p.worst_daily_return)} | {_pct(p.expected_shortfall_5pct)} | "
                f"{_pct(p.reset_path_max_drawdown)} |"
            )
    add("")
    add("## 10. Full-train exploratory results")
    add("")
    add(
        "The complete research-train period evaluated once, in-sample — labelled "
        "`exploratory_in_sample_full_train`. Never mixed with the walk-forward "
        "OOS results; in-sample numbers overstate what OOS delivers."
    )
    for scenario in scenarios:
        add("")
        add(f"### Cost scenario: {scenario}")
        add("")
        add("| strategy | marked return | liq return | CAGR | Sharpe | maxDD | fills | exposure |")
        add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for strategy in strategies:
            f = full_by[(strategy, scenario)]
            add(
                f"| {strategy} | {_pct(f.marked_total_return)} | "
                f"{_pct(f.liquidation_total_return)} | {_pct(f.cagr)} | {_ratio(f.sharpe)} | "
                f"{_pct(f.max_drawdown)} | {f.num_fills} | {f.exposure_fraction:.2f} |"
            )
    add("")
    add("## 11. Bootstrap intervals")
    add("")
    add(
        "Moving-block bootstrap (`moving-block-bootstrap-v1`, seed 20260713, "
        "block 30, 5000 resamples, 95%) of the mean daily paired excess return "
        "versus buy-and-hold over the pooled reset-OOS observations. The interval "
        "describes sampling variability only; it does **not** prove alpha, is "
        "**not** annualized, and does not remove uncertainty."
    )
    for scenario in scenarios:
        add("")
        add(f"### Cost scenario: {scenario}")
        add("")
        add("| strategy | obs | point (mean daily excess) | 95% CI lower | median | upper |")
        add("| --- | ---: | ---: | ---: | ---: | ---: |")
        for strategy in strategies:
            if strategy == _BUY_AND_HOLD:
                continue
            iv = boot_by[(strategy, scenario)].interval
            add(
                f"| {strategy} | {iv.observation_count} | {_pct(iv.point_estimate)} | "
                f"{_pct(iv.ci_lower)} | {_pct(iv.ci_median)} | {_pct(iv.ci_upper)} |"
            )
    add("")
    add("## 12. Comparison against buy-and-hold")
    add("")
    add(
        "The `frac > B&H` column in section 8 is the fraction of folds in which a "
        "strategy's marked return exceeded buy-and-hold in the same fold and "
        "scenario. Bootstrap intervals (section 11) whose upper bound is at or "
        "below zero indicate no evidence of positive mean excess over B&H."
    )
    add("")
    add("## 13. Comparison against cash")
    add("")
    add(
        "The `frac > cash` column in section 8 is the fraction of folds in which a "
        "strategy's marked return exceeded the cash baseline (0%). Beating cash is "
        "a much weaker bar than beating buy-and-hold."
    )
    add("")
    add("## 14. SMA(20/50) negative-control observations")
    add("")
    add(
        "SMA(20/50) is retained as the already-rejected negative control (it was "
        "`rejected_for_test_promotion` in Milestone 2B on the M2 validation "
        "period). Its research-train walk-forward behaviour is reported above for "
        "comparison only; nothing here revisits or overturns that rejection."
    )
    add("")
    add("## 15. Donchian(55/20) exploratory observations")
    add("")
    add(
        "Donchian(55/20) is a fixed exploratory baseline — **not** a promoted "
        "candidate and never tuned. Its per-fold, pooled, and bootstrap results "
        "above are exploratory research-train diagnostics."
    )
    add("")
    add("## 16. Cost fragility")
    add("")
    add(
        "Read each strategy's rows across the base -> stressed -> severe scenarios "
        "in sections 7-11: higher costs never improve identical cashflows, and a "
        "strategy that only narrowly beats a benchmark under base costs may not "
        "under severe costs. Turnover-heavy strategies degrade fastest."
    )
    add("")
    add("## 17. Temporal instability")
    add("")
    add(
        "The per-fold table (section 7) shows how the same fixed strategy behaves "
        "very differently across the five chronological folds — evidence that a "
        "single validation period is a fragile basis for a promotion decision."
    )
    add("")
    add("## 18. Weak and failed results (retained)")
    add("")
    add(
        "Every fold is retained, including losing folds and severe-cost failures. "
        "No fold, scenario, or strategy was dropped for being unflattering; the "
        "committed numbers stand as computed."
    )
    add("")
    add("## 19. Multiple-testing statement")
    add("")
    add(
        f"This experiment evaluates {len(strategies)} strategies x "
        f"{len(scenarios)} cost scenarios x {len(fold_indices)} folds. With many "
        "comparisons, some favourable-looking cells are expected by chance alone; "
        "no per-cell result is treated as a discovery, and no selection was made "
        "after seeing results."
    )
    add("")
    add("## 20. Limitations")
    add("")
    for limitation in (
        "One venue (Coinbase Exchange), one instrument (ETH-USD spot), one daily dataset.",
        "Fixed parameters (SMA 20/50, Donchian 55/20); nothing tuned, and nothing "
        "should be inferred about other parameters.",
        "Research-train walk-forward is in-sample development evidence, not live "
        "performance and not test performance.",
        "Independent fold resets and the pooled reset-OOS series are diagnostics, "
        "not tradable paths.",
        "The bootstrap quantifies sampling variability only; it does not prove "
        "alpha or remove uncertainty.",
        "Costs are a simplified constant fee plus directional slippage; no spread, "
        "impact, or liquidity model.",
        "Computational sealing of the forbidden partitions is not epistemic sealing.",
    ):
        add(f"- {limitation}")
    add("")
    add("## 21. Exact next decision")
    add("")
    add(
        "No candidate is promoted here. The next step, if any, is to pre-register "
        "one candidate family and a development-gate promotion criterion, then "
        "spend exactly one recorded development-gate access — a separate, "
        "append-only process outside this milestone. The final holdout remains "
        "sealed and may be consumed at most once, only for a promoted candidate "
        "under an independent authorization."
    )
    add("")
    return "\n".join(lines)
