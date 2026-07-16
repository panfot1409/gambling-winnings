"""The M3C 75-cell grid on the research train, with a common 252-bar context.

Reuses the reviewed Milestone 3B engine/accounting/solver/cost/metrics/reconciliation
unchanged. The only structural difference from M3B is the **common warm-up context**:
the candidate's 252-day momentum needs up to 252 preceding closes, so every strategy
in a fold receives the *same* context frame of up to 252 strictly-earlier research-train
rows (M3B used 55). Context creates no P&L, no metric period, and identical available
timestamps for all five strategies — equal information availability, not tuning. The
OOS fold boundaries are the exact accepted M3A boundaries, taken from the committed
walk-forward protocol; only the context length differs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from eth_research.data.schema import frame_interval
from eth_research.fractional.accounting import DEFAULT_TOLERANCES, Tolerances
from eth_research.fractional.cost_model import SCENARIOS, CostScenario
from eth_research.fractional.engine import FractionalBacktestResult, run_fractional_backtest
from eth_research.fractional.metrics import FractionalMetrics, compute_fractional_metrics
from eth_research.fractional.reconciliation import reconcile_result
from eth_research.fractional.strategies import FractionalStrategy
from eth_research.m3c.candidate import M3C_MAX_CONTEXT_BARS, build_m3c_strategies
from eth_research.metrics import periods_per_year_from_interval
from eth_research.walkforward import FoldFrames, WalkForwardProtocol


class M3CExperimentError(RuntimeError):
    """The M3C grid disagreed with the frozen partition, folds, or reconciliation."""


def build_m3c_fold_frames(
    research_train: pd.DataFrame, wf_protocol: WalkForwardProtocol
) -> tuple[FoldFrames, ...]:
    """Materialize each fold's (training, common-context, OOS) frames.

    The OOS block matches the accepted protocol boundary exactly; the context is the
    ``min(252, training_row_count)`` rows immediately before the OOS start — strictly
    inside the expanding training window, so it never touches an OOS row and never
    reaches a sealed partition (the frame is research-train-only). The same context is
    later handed to every strategy for the fold.
    """
    if len(research_train) != wf_protocol.research_train_row_count:
        raise M3CExperimentError("research-train frame does not match the protocol row count")
    frames: list[FoldFrames] = []
    for fold in wf_protocol.folds:
        train_end = fold.training_row_count
        oos_end = train_end + fold.oos_row_count
        context_rows = min(M3C_MAX_CONTEXT_BARS, train_end)
        training = research_train.iloc[:train_end]
        context = research_train.iloc[train_end - context_rows : train_end]
        oos = research_train.iloc[train_end:oos_end]
        if oos.index[0] != fold.oos_first_open_time or oos.index[-1] != fold.oos_last_open_time:
            raise M3CExperimentError(
                f"fold {fold.fold_index}: OOS frame disagrees with the protocol"
            )
        if len(context) > 0 and context.index[-1] >= oos.index[0]:
            raise M3CExperimentError(f"fold {fold.fold_index}: context overlaps the OOS block")
        frames.append(
            FoldFrames(fold_index=fold.fold_index, training=training, context=context, oos=oos)
        )
    return tuple(frames)


@dataclass(frozen=True)
class M3CCellRun:
    """One reconciled (fold, cost, strategy) backtest and its derived metrics.

    Not a serialized artifact; the runtime carrier the results/statistics/trace
    layers reduce into strict published models.
    """

    fold_index: int
    strategy: str
    cost_scenario: str
    context_row_count: int
    result: FractionalBacktestResult
    metrics: FractionalMetrics

    @property
    def marked_daily_returns(self) -> pd.Series:
        """Per-OOS-day marked net return (equity[t]/equity[t-1]-1; day 0 vs cash)."""
        equity = self.result.equity.to_numpy(dtype="float64")
        prior = np.empty(equity.size, dtype="float64")
        prior[0] = self.result.initial_cash
        prior[1:] = equity[:-1]
        returns = equity / prior - 1.0
        return pd.Series(returns, index=self.result.equity.index, name="marked_return")


def compute_m3c_cell_runs(
    research_train: pd.DataFrame,
    wf_protocol: WalkForwardProtocol,
    *,
    initial_cash: float,
    strategies: tuple[FractionalStrategy, ...] | None = None,
    scenarios: tuple[CostScenario, ...] = SCENARIOS,
    tol: Tolerances = DEFAULT_TOLERANCES,
) -> tuple[M3CCellRun, ...]:
    """Run the full 5x3x5 grid, fold-major then scenario then strategy (byte-stable).

    Every cell is reconciled against its primitives before it is kept, so a silent
    accounting drift fails the run instead of being published.
    """
    fold_frames = build_m3c_fold_frames(research_train, wf_protocol)
    resolved = build_m3c_strategies() if strategies is None else strategies
    periods_per_year = periods_per_year_from_interval(frame_interval(research_train))
    runs: list[M3CCellRun] = []
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
                reconcile_result(result, scenario, tol=tol)
                metrics = compute_fractional_metrics(result, periods_per_year=periods_per_year)
                runs.append(
                    M3CCellRun(
                        fold_index=fold.fold_index,
                        strategy=strategy.name,
                        cost_scenario=scenario.name,
                        context_row_count=len(fold.context),
                        result=result,
                        metrics=metrics,
                    )
                )
    return tuple(runs)
