"""Public backtest entry points that delegate to the accepted engines.

Two engines are exposed unchanged behind a thin, strictly-typed boundary:

* :func:`run_binary_backtest` — the all-in / all-out engine (``backtest.run_backtest``);
* :func:`run_fractional_backtest` — the continuous-exposure engine
  (:func:`eth_research.fractional.engine.run_fractional_backtest`).

Each resolves a strategy spec and a cost scenario, runs the accepted engine, and delegates
the performance numbers to the accepted metrics (:func:`eth_research.metrics.summarize` /
:func:`eth_research.fractional.metrics.compute_fractional_metrics`) — no formula is
reimplemented here — then records them in an immutable :class:`ResearchResult`.
"""

from __future__ import annotations

import math

import pandas as pd

from eth_research.api.errors import (
    AccountingError,
    BacktestError,
    ConfigurationError,
    StrategyError,
)
from eth_research.api.models import (
    BINARY_COST_SCENARIOS,
    FRACTIONAL_COST_SCENARIOS,
    ChronologicalSplitSpec,
    CostSpec,
    DatasetHandle,
    DatasetSpec,
    ResearchRunSpec,
    StrategySpec,
    _iso_utc,
)
from eth_research.api.results import MetricValue, ResearchResult, build_research_result
from eth_research.api.strategies import (
    FractionalStrategy,
    Strategy,
    build_binary_strategy,
    build_fractional_strategy,
)
from eth_research.backtest import AccountingError as _InternalAccountingError
from eth_research.backtest import BacktestResult, run_backtest
from eth_research.costs import cost_scenario as _binary_cost_scenario
from eth_research.fractional.cost_model import SCENARIOS_BY_NAME
from eth_research.fractional.cost_model import CostScenario as _FractionalCostScenario
from eth_research.fractional.engine import EngineError as _FractionalEngineError
from eth_research.fractional.engine import FractionalBacktestResult
from eth_research.fractional.engine import run_fractional_backtest as _engine
from eth_research.fractional.metrics import FractionalMetrics, compute_fractional_metrics
from eth_research.metrics import PerformanceSummary, periods_per_year_from_interval, summarize

__all__ = [
    "calculate_metrics",
    "run_binary_backtest",
    "run_fractional_backtest",
]


# --------------------------------------------------------------------------- #
# resolution helpers                                                          #
# --------------------------------------------------------------------------- #
def _resolve_binary_strategy(strategy: StrategySpec | Strategy) -> tuple[Strategy, StrategySpec]:
    if isinstance(strategy, StrategySpec):
        return build_binary_strategy(strategy), strategy
    if isinstance(strategy, Strategy):
        return strategy, StrategySpec(kind=f"custom:{strategy.name}")
    raise StrategyError("strategy must be a StrategySpec or a Strategy instance")


def _resolve_fractional_strategy(
    strategy: StrategySpec | FractionalStrategy,
) -> tuple[FractionalStrategy, StrategySpec]:
    if isinstance(strategy, StrategySpec):
        return build_fractional_strategy(strategy), strategy
    if isinstance(strategy, FractionalStrategy):
        return strategy, StrategySpec(kind=f"custom:{strategy.name}")
    raise StrategyError("strategy must be a StrategySpec or a FractionalStrategy instance")


def _binary_cost_model(cost: CostSpec) -> object:
    if cost.scenario not in BINARY_COST_SCENARIOS:
        raise ConfigurationError(
            f"unknown binary cost scenario {cost.scenario!r}; "
            f"expected one of {BINARY_COST_SCENARIOS}"
        )
    return _binary_cost_scenario(cost.scenario).cost_model()


def _fractional_scenario(cost: CostSpec) -> _FractionalCostScenario:
    if cost.scenario not in FRACTIONAL_COST_SCENARIOS:
        raise ConfigurationError(
            f"unknown fractional cost scenario {cost.scenario!r}; "
            f"expected one of {FRACTIONAL_COST_SCENARIOS}"
        )
    return SCENARIOS_BY_NAME[cost.scenario]


def _context_frame(context: DatasetHandle | None) -> pd.DataFrame | None:
    return context.frame if context is not None else None


def _context_bars(context: DatasetHandle | None) -> int:
    return context.row_count if context is not None else 0


def _context_fingerprint(context: DatasetHandle | None) -> str | None:
    return context.fingerprint if context is not None else None


# --------------------------------------------------------------------------- #
# metric extraction (pure delegation + type coercion to plain scalars)        #
# --------------------------------------------------------------------------- #
def _scalar(value: float | None) -> float | None:
    """Coerce a delegated metric to a plain finite float, or ``None``.

    An undefined metric — e.g. the Sharpe ratio of a zero-volatility cash strategy is the
    accepted engine's ``NaN`` — is represented as JSON ``null`` rather than a non-finite
    number, so the canonical result stays serializable and deterministic. The value is
    never altered otherwise; this is type coercion, not recomputation.
    """
    if value is None:
        return None
    coerced = float(value)
    return coerced if math.isfinite(coerced) else None


def _binary_metrics(summary: PerformanceSummary) -> dict[str, MetricValue]:
    return {
        "n_periods": int(summary.n_periods),
        "periods_per_year": _scalar(summary.periods_per_year),
        "initial_equity": _scalar(summary.initial_equity),
        "terminal_equity": _scalar(summary.terminal_equity),
        "total_return": _scalar(summary.total_return),
        "cagr": _scalar(summary.cagr),
        "sharpe": _scalar(summary.sharpe),
        "sortino": _scalar(summary.sortino),
        "max_drawdown": _scalar(summary.max_drawdown),
        "total_traded_notional": _scalar(summary.total_traded_notional),
        "turnover": _scalar(summary.turnover),
        "num_trades": int(summary.num_trades),
    }


def _fractional_metrics(metrics: FractionalMetrics) -> dict[str, MetricValue]:
    return {
        "total_return": _scalar(metrics.total_return),
        "annualized_return": _scalar(metrics.annualized_return),
        "annualized_volatility": _scalar(metrics.annualized_volatility),
        "sharpe_ratio": _scalar(metrics.sharpe_ratio),
        "sortino_ratio": _scalar(metrics.sortino_ratio),
        "max_drawdown": _scalar(metrics.max_drawdown),
        "num_fills": int(metrics.num_fills),
        "num_partial_fills": int(metrics.num_partial_fills),
        "total_traded_notional": _scalar(metrics.total_traded_notional),
        "turnover": _scalar(metrics.turnover),
        "total_fees": _scalar(metrics.total_fees),
        "average_achieved_exposure": _scalar(metrics.average_achieved_exposure),
        "time_in_market": _scalar(metrics.time_in_market),
        "terminal_equity": _scalar(metrics.terminal_equity),
        "terminal_liquidation_equity": _scalar(metrics.terminal_liquidation_equity),
    }


# --------------------------------------------------------------------------- #
# engine runs                                                                 #
# --------------------------------------------------------------------------- #
def _run_binary(
    dataset: DatasetHandle,
    strategy: StrategySpec | Strategy,
    cost: CostSpec,
    *,
    initial_cash: float,
    context: DatasetHandle | None,
    risk_free_rate: float,
) -> tuple[BacktestResult, PerformanceSummary, StrategySpec]:
    strat, spec = _resolve_binary_strategy(strategy)
    cost_model = _binary_cost_model(cost)
    try:
        result = run_backtest(
            dataset.frame,
            strat,
            costs=cost_model,  # type: ignore[arg-type]
            initial_cash=initial_cash,
            context=_context_frame(context),
        )
        summary = summarize(result, risk_free_rate=risk_free_rate)
    except _InternalAccountingError as exc:
        raise AccountingError(f"backtest accounting invariant failed: {exc}") from exc
    except (ValueError, TypeError) as exc:
        raise BacktestError(f"binary backtest failed: {exc}") from exc
    return result, summary, spec


def _run_fractional(
    dataset: DatasetHandle,
    strategy: StrategySpec | FractionalStrategy,
    cost: CostSpec,
    *,
    initial_cash: float,
    context: DatasetHandle | None,
    risk_free_rate: float,
) -> tuple[FractionalBacktestResult, FractionalMetrics, StrategySpec]:
    strat, spec = _resolve_fractional_strategy(strategy)
    scenario = _fractional_scenario(cost)
    try:
        result = _engine(
            dataset.frame,
            strat,
            scenario,
            initial_cash=initial_cash,
            context=_context_frame(context),
        )
        ppy = periods_per_year_from_interval(pd.Timedelta(seconds=dataset.interval_seconds))
        metrics = compute_fractional_metrics(
            result, periods_per_year=ppy, risk_free_rate=risk_free_rate
        )
    except _FractionalEngineError as exc:
        raise BacktestError(f"fractional backtest failed: {exc}") from exc
    except (ValueError, TypeError) as exc:
        raise BacktestError(f"fractional backtest failed: {exc}") from exc
    return result, metrics, spec


def _assemble(
    *,
    engine: str,
    dataset: DatasetHandle,
    spec: StrategySpec,
    cost: CostSpec,
    initial_cash: float,
    context: DatasetHandle | None,
    risk_free_rate: float,
    split: ChronologicalSplitSpec | None,
    equity: pd.Series,
    metrics: dict[str, MetricValue],
) -> ResearchResult:
    run_spec = ResearchRunSpec(
        engine=engine,
        dataset=DatasetSpec(interval_seconds=dataset.interval_seconds),
        strategy=spec,
        cost=cost,
        initial_cash=float(initial_cash),
        context_bars=_context_bars(context),
        risk_free_rate=float(risk_free_rate),
        split=split,
        context_fingerprint=_context_fingerprint(context),
    )
    return build_research_result(
        run_spec=run_spec,
        dataset_fingerprint=dataset.fingerprint,
        dataset_row_count=dataset.row_count,
        evaluated_row_count=len(equity),
        start_time=_iso_utc(pd.Timestamp(equity.index[0])),
        end_time=_iso_utc(pd.Timestamp(equity.index[-1])),
        metrics=metrics,
    )


# --------------------------------------------------------------------------- #
# public entry points                                                         #
# --------------------------------------------------------------------------- #
def run_binary_backtest(
    dataset: DatasetHandle,
    strategy: StrategySpec | Strategy,
    cost: CostSpec,
    *,
    initial_cash: float = 10_000.0,
    context: DatasetHandle | None = None,
    risk_free_rate: float = 0.0,
    split: ChronologicalSplitSpec | None = None,
) -> ResearchResult:
    """Run a binary (all-in / all-out) backtest and return an immutable result.

    ``strategy`` is either a :class:`StrategySpec` naming a built-in, or a custom
    :class:`Strategy` instance (trusted caller code). ``cost`` names a binary cost scenario
    (``base`` / ``stressed`` / ``severe``). ``context`` supplies an optional warm-up window
    that must be contiguous with and strictly precede the dataset.
    """
    result, summary, spec = _run_binary(
        dataset,
        strategy,
        cost,
        initial_cash=initial_cash,
        context=context,
        risk_free_rate=risk_free_rate,
    )
    return _assemble(
        engine="binary",
        dataset=dataset,
        spec=spec,
        cost=cost,
        initial_cash=initial_cash,
        context=context,
        risk_free_rate=risk_free_rate,
        split=split,
        equity=result.equity,
        metrics=_binary_metrics(summary),
    )


def run_fractional_backtest(
    dataset: DatasetHandle,
    strategy: StrategySpec | FractionalStrategy,
    cost: CostSpec,
    *,
    initial_cash: float = 10_000.0,
    context: DatasetHandle | None = None,
    risk_free_rate: float = 0.0,
    split: ChronologicalSplitSpec | None = None,
) -> ResearchResult:
    """Run a fractional (continuous-exposure, long-only [0, 1]) backtest.

    ``strategy`` is either a :class:`StrategySpec` naming a built-in fractional strategy or
    a custom :class:`FractionalStrategy`. ``cost`` names a fractional cost scenario
    (``compatibility_v1`` / ``causal_proxy_base`` / ``causal_proxy_stressed``).
    """
    result, metrics, spec = _run_fractional(
        dataset,
        strategy,
        cost,
        initial_cash=initial_cash,
        context=context,
        risk_free_rate=risk_free_rate,
    )
    return _assemble(
        engine="fractional",
        dataset=dataset,
        spec=spec,
        cost=cost,
        initial_cash=initial_cash,
        context=context,
        risk_free_rate=risk_free_rate,
        split=split,
        equity=result.equity,
        metrics=_fractional_metrics(metrics),
    )


def calculate_metrics(
    dataset: DatasetHandle,
    strategy: StrategySpec | Strategy,
    cost: CostSpec,
    *,
    initial_cash: float = 10_000.0,
    context: DatasetHandle | None = None,
    risk_free_rate: float = 0.0,
) -> dict[str, MetricValue]:
    """Run a binary backtest and return only its delegated performance metrics.

    A thin convenience over :func:`run_binary_backtest` for callers that want the numbers
    (from :func:`eth_research.metrics.summarize`) without the full recorded result.
    """
    _, summary, _ = _run_binary(
        dataset,
        strategy,
        cost,
        initial_cash=initial_cash,
        context=context,
        risk_free_rate=risk_free_rate,
    )
    return _binary_metrics(summary)
