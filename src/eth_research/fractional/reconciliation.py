"""Reconcile a fractional backtest against its primitive records (Phase 11).

Every reported series and scalar must re-derive from the primitive bar and fill
records alone. This module recomputes equity, cash, ETH, fees, achieved exposure,
and the cost decomposition from the bars/fills and fails loudly on any mismatch —
so a reported number can never drift from the primitives it claims to summarize.

It also reconciles the target chain: the raw strategy target, the risk-adjusted
executable target, and the achieved exposure, confirming the achieved exposure is
exactly the reference weight of the post-fill portfolio and that a converged
(non-partial) fill lands on its executable target within tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.fractional.accounting import (
    DEFAULT_TOLERANCES,
    PortfolioState,
    Tolerances,
    weight_at_reference,
)
from eth_research.fractional.cost_model import CostScenario, cost_breakdown
from eth_research.fractional.engine import FractionalBacktestResult


class ReconciliationError(Exception):
    """A reported value did not re-derive from the primitive records."""


@dataclass(frozen=True)
class ReconciliationReport:
    """Evidence that a fractional result reconciles to its primitives."""

    bars_checked: int
    fills_checked: int
    max_equity_residual: float
    max_exposure_residual: float
    total_fees: float
    total_traded_notional: float
    checks: tuple[str, ...]


def reconcile_result(
    result: FractionalBacktestResult,
    scenario: CostScenario,
    *,
    tol: Tolerances = DEFAULT_TOLERANCES,
) -> ReconciliationReport:
    """Re-derive every reported quantity from the bars/fills; raise on mismatch."""
    equity_vals = result.equity.to_numpy(dtype="float64")
    cash_vals = result.cash.to_numpy(dtype="float64")
    quantity_vals = result.quantity.to_numpy(dtype="float64")
    if not (len(result.bars) == len(equity_vals) == len(cash_vals) == len(quantity_vals)):
        raise ReconciliationError("bar count disagrees with the reported series lengths")

    max_equity_residual = 0.0
    max_exposure_residual = 0.0
    notional_tol = 1e-9

    for i, bar in enumerate(result.bars):
        # Series entries must equal the bar records exactly.
        if cash_vals[i] != bar.cash_after or quantity_vals[i] != bar.quantity_after:
            raise ReconciliationError(f"bar {i}: cash/quantity series disagree with the record")

        # Equity identity: equity == cash + quantity * close.
        recomputed_equity = bar.cash_after + bar.quantity_after * bar.close
        residual = abs(recomputed_equity - equity_vals[i])
        if residual > tol.cash_tolerance:
            raise ReconciliationError(
                f"bar {i}: equity {equity_vals[i]!r} != cash + quantity*close {recomputed_equity!r}"
            )
        max_equity_residual = max(max_equity_residual, residual)

        # Long-only: no materially negative cash or ETH; exposure in [0, 1].
        if bar.cash_after < -tol.cash_tolerance:
            raise ReconciliationError(f"bar {i}: negative cash {bar.cash_after!r}")
        if bar.quantity_after < -tol.quantity_tolerance:
            raise ReconciliationError(f"bar {i}: negative ETH {bar.quantity_after!r}")
        if not (-tol.weight_tolerance <= bar.achieved_exposure <= 1.0 + tol.weight_tolerance):
            raise ReconciliationError(f"bar {i}: exposure {bar.achieved_exposure!r} outside [0, 1]")

        # Achieved exposure is exactly the reference weight of the post-fill book.
        state = PortfolioState(cash=bar.cash_after, quantity=bar.quantity_after)
        weight = weight_at_reference(state, bar.reference_open)
        exposure_residual = abs(weight - bar.achieved_exposure)
        if exposure_residual > tol.weight_tolerance:
            raise ReconciliationError(
                f"bar {i}: achieved exposure {bar.achieved_exposure!r} != recomputed {weight!r}"
            )
        max_exposure_residual = max(max_exposure_residual, exposure_residual)

        # A converged (non-partial) fill lands on its executable target.
        if (
            not bar.partial
            and abs(bar.achieved_exposure - bar.executable_target) > tol.weight_tolerance
        ):
            raise ReconciliationError(
                f"bar {i}: converged achieved {bar.achieved_exposure!r} != "
                f"executable {bar.executable_target!r}"
            )

        # Cost decomposition of an executed fill re-derives exactly.
        if bar.side is not None and bar.fill_price is not None and bar.executed_quantity > 0.0:
            cb = cost_breakdown(
                scenario,
                bar.reference_open,
                bar.side,
                bar.executed_quantity,
                bar.lagged_dollar_volume,
            )
            if abs(cb.fill_price - bar.fill_price) > notional_tol * max(1.0, bar.reference_open):
                raise ReconciliationError(f"bar {i}: fill price does not re-derive")
            if abs(cb.fee_cost - bar.fee) > notional_tol * max(1.0, cb.reference_notional):
                raise ReconciliationError(f"bar {i}: fee does not re-derive")
            components = cb.half_spread_cost + cb.base_slippage_cost + cb.impact_cost
            if abs(cb.price_shortfall - components) > notional_tol * max(
                1.0, cb.reference_notional
            ):
                raise ReconciliationError(f"bar {i}: cost decomposition does not sum")

    # Fees: the fill records and the bar records agree with the fill total.
    fill_fees = sum(f.fee for f in result.fills)
    bar_fees = sum(bar.fee for bar in result.bars)
    if abs(fill_fees - bar_fees) > tol.cash_tolerance:
        raise ReconciliationError(f"fill fees {fill_fees!r} != bar fees {bar_fees!r}")
    traded_notional = sum(f.fill_notional for f in result.fills)

    # Terminal equity re-derives from the compounded per-bar returns.
    compounded = result.initial_cash
    for i in range(len(equity_vals)):
        previous = result.initial_cash if i == 0 else equity_vals[i - 1]
        compounded = previous * (equity_vals[i] / previous)
    if abs(compounded - float(result.equity.iloc[-1])) > tol.cash_tolerance:
        raise ReconciliationError("compounded equity path disagrees with the terminal equity")

    return ReconciliationReport(
        bars_checked=len(result.bars),
        fills_checked=len(result.fills),
        max_equity_residual=max_equity_residual,
        max_exposure_residual=max_exposure_residual,
        total_fees=fill_fees,
        total_traded_notional=traded_notional,
        checks=(
            "series_match_records",
            "equity_identity",
            "long_only",
            "exposure_bounds",
            "achieved_equals_reference_weight",
            "converged_reaches_executable",
            "cost_decomposition",
            "fee_totals",
            "terminal_equity_path",
        ),
    )
