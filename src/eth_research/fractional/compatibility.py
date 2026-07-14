"""Compatibility oracle: bit-equality with the binary engine (Phase 12).

Under the ``compatibility_v1`` scenario a binary-equivalent fractional strategy
(maximum exposure 1.0, no volatility target, no turnover limiter, no breaker)
must reproduce the binary :func:`eth_research.backtest.run_backtest` engine
exactly. This oracle runs both on the same data — reusing the *same* underlying
binary ``Strategy`` for signals — and checks the cash, ETH, and equity series for
**bit-for-bit** equality.

The only permitted disagreement is the terminal *hypothetical* liquidation value,
which differs by at most floating-point noise from a benign multiplication-order
convention (`(q*c)*(1-s)` vs `q*(c*(1-s))`); the realized equity curve, the P&L
that matters, is exact.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from eth_research.backtest import CostModel, run_backtest
from eth_research.fractional.cost_model import COMPATIBILITY_V1
from eth_research.fractional.engine import run_fractional_backtest
from eth_research.fractional.strategies import FractionalStrategy

# The binary cost model that compatibility_v1 mirrors: fee 0.1%, slippage 0.05%.
BINARY_COMPATIBILITY_COST = CostModel(fee_rate=0.001, slippage_rate=0.0005)
TERMINAL_LIQUIDATION_TOLERANCE = 1e-9


class CompatibilityError(Exception):
    """A binary-equivalent fractional run disagreed with the binary engine."""


@dataclass(frozen=True)
class ParityReport:
    """The outcome of one compatibility comparison."""

    strategy_name: str
    bars: int
    equity_matches: bool
    quantity_matches: bool
    cash_matches: bool
    terminal_liquidation_close: bool
    max_terminal_liquidation_diff: float


def _is_binary_equivalent(strategy: FractionalStrategy) -> bool:
    risk = strategy.risk
    return (
        risk.max_exposure == 1.0
        and not risk.volatility_target
        and risk.turnover_limit is None
        and not risk.drawdown_breaker
    )


def binary_parity(
    frame: pd.DataFrame,
    strategy: FractionalStrategy,
    *,
    initial_cash: float = 10_000.0,
    context: pd.DataFrame | None = None,
) -> ParityReport:
    """Compare a binary-equivalent fractional run to the binary engine.

    The binary engine is driven by ``strategy.signal`` (the same ``Strategy``
    instance the fractional adapter uses), so any mismatch is an execution/cost
    difference, never a signal difference.
    """
    if not _is_binary_equivalent(strategy):
        raise CompatibilityError(
            f"strategy {strategy.name!r} applies risk overlays and has no binary equivalent"
        )
    binary = run_backtest(
        frame,
        strategy.signal,
        BINARY_COMPATIBILITY_COST,
        initial_cash=initial_cash,
        context=context,
    )
    fractional = run_fractional_backtest(
        frame, strategy, COMPATIBILITY_V1, initial_cash=initial_cash, context=context
    )
    terminal_diff = abs(fractional.terminal_liquidation_equity - binary.terminal_liquidation_equity)
    return ParityReport(
        strategy_name=strategy.name,
        bars=len(frame),
        equity_matches=np.array_equal(fractional.equity.to_numpy(), binary.equity.to_numpy()),
        quantity_matches=np.array_equal(fractional.quantity.to_numpy(), binary.quantity.to_numpy()),
        cash_matches=np.array_equal(fractional.cash.to_numpy(), binary.cash.to_numpy()),
        terminal_liquidation_close=terminal_diff <= TERMINAL_LIQUIDATION_TOLERANCE,
        max_terminal_liquidation_diff=terminal_diff,
    )


def assert_binary_parity(
    frame: pd.DataFrame,
    strategy: FractionalStrategy,
    *,
    initial_cash: float = 10_000.0,
    context: pd.DataFrame | None = None,
) -> ParityReport:
    """Run :func:`binary_parity` and raise :class:`CompatibilityError` on any gap."""
    report = binary_parity(frame, strategy, initial_cash=initial_cash, context=context)
    if not (report.equity_matches and report.quantity_matches and report.cash_matches):
        raise CompatibilityError(
            f"{strategy.name!r}: fractional compatibility run diverged from the binary engine "
            f"(equity={report.equity_matches}, quantity={report.quantity_matches}, "
            f"cash={report.cash_matches})"
        )
    if not report.terminal_liquidation_close:
        raise CompatibilityError(
            f"{strategy.name!r}: terminal liquidation differs by "
            f"{report.max_terminal_liquidation_diff!r} (> {TERMINAL_LIQUIDATION_TOLERANCE})"
        )
    return report
