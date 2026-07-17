"""Descriptive, reconstructible portfolio metrics (Milestone 4B, §23).

Every scalar here is a *description* of the run's own equity curve and event evidence — never an
alpha, beta, information ratio, factor loading, significance test, optimization objective, or a
value-at-risk sold as a guarantee. The performance ratios reuse the shared metric primitives
(:mod:`eth_research.metrics`) on the portfolio's base-currency equity series, so a single-asset run
reconciles with the accepted fractional engine's numbers. The cross-sectional additions (gross
exposure, cash weight, max weight, Herfindahl concentration, average held assets, stale-mark counts)
and the attribution roll-ups are computed directly from the per-event event records, and the
cumulative attribution terms telescope to ``terminal - initial`` equity, so the summary is always
internally consistent.

Ratios that are undefined for a run (fewer than two events, or zero realized volatility) are
reported as ``None``, never as ``NaN`` — the canonical form must stay JSON-safe (no NaN/Infinity).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pandas as pd

from eth_research.api.serialization import CanonicalError
from eth_research.metrics import (
    bar_returns,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    total_return,
)

if TYPE_CHECKING:
    from eth_research.portfolio.engine import PortfolioRunResult

__all__ = ["PortfolioMetrics", "compute_portfolio_metrics"]


def _finite_or_none(value: float) -> float | None:
    """The value if finite, else ``None`` (so an undefined ratio never leaks NaN/Infinity)."""
    return value if math.isfinite(value) else None


@dataclass(frozen=True)
class PortfolioMetrics:
    """A reconciled, canonical-JSON-safe descriptive summary of one portfolio run."""

    initial_equity: float
    terminal_equity: float
    total_return: float
    annualized_return: float | None
    annualized_volatility: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown: float
    num_events: int
    num_fills: int
    total_cost: float
    cost_drag: float
    total_traded_notional: float
    turnover: float
    average_gross_exposure: float
    average_cash_weight: float
    average_max_weight: float
    average_hhi: float
    average_held_assets: float
    stale_mark_events: int
    max_staleness_seconds: float
    cumulative_local_price_pnl: float
    cumulative_fx_translation_pnl: float
    cumulative_action_cash: float
    cumulative_cost: float
    cumulative_residual: float
    per_currency_contribution: tuple[tuple[str, float], ...]

    def canonical(self) -> dict[str, Any]:
        """The canonical, JSON-safe metric mapping (undefined ratios as ``null``)."""
        return {
            "initial_equity": self.initial_equity,
            "terminal_equity": self.terminal_equity,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "annualized_volatility": self.annualized_volatility,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "num_events": self.num_events,
            "num_fills": self.num_fills,
            "total_cost": self.total_cost,
            "cost_drag": self.cost_drag,
            "total_traded_notional": self.total_traded_notional,
            "turnover": self.turnover,
            "average_gross_exposure": self.average_gross_exposure,
            "average_cash_weight": self.average_cash_weight,
            "average_max_weight": self.average_max_weight,
            "average_hhi": self.average_hhi,
            "average_held_assets": self.average_held_assets,
            "stale_mark_events": self.stale_mark_events,
            "max_staleness_seconds": self.max_staleness_seconds,
            "cumulative_local_price_pnl": self.cumulative_local_price_pnl,
            "cumulative_fx_translation_pnl": self.cumulative_fx_translation_pnl,
            "cumulative_action_cash": self.cumulative_action_cash,
            "cumulative_cost": self.cumulative_cost,
            "cumulative_residual": self.cumulative_residual,
            "per_currency_contribution": [
                {"currency": currency, "fx_translation_pnl": value}
                for currency, value in self.per_currency_contribution
            ],
        }


def compute_portfolio_metrics(
    result: PortfolioRunResult,
    *,
    periods_per_year: float,
    risk_free_rate: float = 0.0,
) -> PortfolioMetrics:
    """Compute the descriptive metric summary for a completed portfolio run.

    ``periods_per_year`` sets the annualization basis for the volatility and the Sharpe / Sortino
    ratios (there is no hidden timing assumption — the caller supplies it from the rebalance
    cadence). ``annualized_return`` compounds the total return over the event count. Raises
    :class:`CanonicalError` on a run with no events or a non-positive ``periods_per_year``.
    """
    if periods_per_year <= 0.0:
        raise CanonicalError(
            f"metrics.periods_per_year: must be positive, got {periods_per_year!r}"
        )
    events = result.events
    n = len(events)
    if n == 0:
        raise CanonicalError("metrics: cannot summarize a run with no events")

    initial = result.initial_equity
    terminal = result.terminal_equity
    equity = pd.Series(
        [event.equity for event in events],
        index=[event.tau for event in events],
        name="equity",
    )
    returns = bar_returns(equity, initial)

    if n >= 2:
        annualized_volatility = _finite_or_none(
            float(returns.std(ddof=1)) * math.sqrt(periods_per_year)
        )
    else:
        annualized_volatility = None
    try:
        # Undefined for a short run with a large per-period move (the compounding overflows);
        # reported as None rather than an absurd or non-finite number.
        annualized_return = _finite_or_none((terminal / initial) ** (periods_per_year / n) - 1.0)
    except OverflowError:
        annualized_return = None

    gross_exposures: list[float] = []
    cash_weights: list[float] = []
    max_weights: list[float] = []
    hhis: list[float] = []
    held_assets: list[int] = []
    stale_events = 0
    max_staleness = 0.0
    total_cost = 0.0
    cumulative_local = 0.0
    cumulative_fx = 0.0
    cumulative_action = 0.0
    cumulative_residual = 0.0
    currency_totals: dict[str, float] = {}

    for event in events:
        equity_e = event.equity
        weights = [holding.base_value / equity_e for holding in event.holdings]
        gross_exposures.append(sum(weights))
        cash_weights.append(event.cash / equity_e)
        max_weights.append(max(weights) if weights else 0.0)
        hhis.append(sum(weight * weight for weight in weights))
        held_assets.append(event.positions_count)
        if event.stale_mark_count > 0:
            stale_events += 1
        max_staleness = max(max_staleness, event.max_staleness_seconds)
        total_cost += event.total_cost
        cumulative_local += event.attribution.local_price_pnl
        cumulative_fx += event.attribution.fx_translation_pnl
        cumulative_action += event.attribution.action_cash
        cumulative_residual += event.attribution.residual
        for currency, value in event.attribution.per_currency:
            currency_totals[currency] = currency_totals.get(currency, 0.0) + value

    traded_notional = sum(abs(fill.base_notional) for event in events for fill in event.fills)

    return PortfolioMetrics(
        initial_equity=initial,
        terminal_equity=terminal,
        total_return=total_return(equity, initial),
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sharpe_ratio=_finite_or_none(sharpe_ratio(returns, periods_per_year, risk_free_rate)),
        sortino_ratio=_finite_or_none(sortino_ratio(returns, periods_per_year, risk_free_rate)),
        max_drawdown=max_drawdown(equity, initial),
        num_events=n,
        num_fills=result.all_fills,
        total_cost=total_cost,
        cost_drag=total_cost / initial,
        total_traded_notional=traded_notional,
        turnover=traded_notional / initial,
        average_gross_exposure=sum(gross_exposures) / n,
        average_cash_weight=sum(cash_weights) / n,
        average_max_weight=sum(max_weights) / n,
        average_hhi=sum(hhis) / n,
        average_held_assets=sum(held_assets) / n,
        stale_mark_events=stale_events,
        max_staleness_seconds=max_staleness,
        cumulative_local_price_pnl=cumulative_local,
        cumulative_fx_translation_pnl=cumulative_fx,
        cumulative_action_cash=cumulative_action,
        cumulative_cost=total_cost,
        cumulative_residual=cumulative_residual,
        per_currency_contribution=tuple(sorted(currency_totals.items())),
    )
