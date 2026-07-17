"""The additive attribution of an equity change across one rebalance step.

Between two consecutive execution events the portfolio's base-currency equity changes for four
reasons: the local prices of held-through instruments moved, the FX rates translating those local
values to the base currency moved, costs were paid, and a residual absorbs everything the first
three terms do not explain (a correct single-asset step leaves it at zero within tolerance).

:func:`attribute_step` computes that decomposition from the pre-rebalance held quantities and the
per-instrument local closes and FX legs at the two events. For each held-through instrument it
splits the value change into a local-price term (priced at the *entry* FX, so it is a pure local
move) and an FX-translation term (the *exit* local close times the FX change), which is the standard
first-order local/FX split. The residual is reported, never forced to zero, so an unexpected leak is
visible rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_research.api.serialization import require_finite_float

__all__ = ["StepAttribution", "attribute_step"]


@dataclass(frozen=True)
class StepAttribution:
    """The additive, base-currency decomposition of one step's equity change."""

    local_price_pnl: float
    fx_translation_pnl: float
    cost: float
    residual: float
    equity_change: float

    def canonical(self) -> dict[str, Any]:
        """The canonical field mapping (all base-currency floats)."""
        return {
            "local_price_pnl": self.local_price_pnl,
            "fx_translation_pnl": self.fx_translation_pnl,
            "cost": self.cost,
            "residual": self.residual,
            "equity_change": self.equity_change,
        }


def attribute_step(
    *,
    equity_before: float,
    equity_after: float,
    held_quantities: dict[str, float],
    marks_before: dict[str, float],
    marks_after: dict[str, float],
    local_close_before: dict[str, float],
    local_close_after: dict[str, float],
    fx_before: dict[str, float],
    fx_after: dict[str, float],
    total_cost: float,
) -> StepAttribution:
    """Decompose ``equity_after - equity_before`` into local-price, FX, cost, and residual terms.

    ``held_quantities`` are the quantities held *before* the rebalance (the instruments carried
    through the interval). For each such instrument that is marked at both events, the local-price
    P&L is ``qty * (close_after - close_before) * fx_before`` and the FX-translation P&L is
    ``qty * close_after * (fx_after - fx_before)``. ``marks_before``/``marks_after`` (base value
    per unit) scope the held-through set to instruments valued at both events; anything they do not
    cover (for example a holding whose mark could not be taken after the step) folds into the
    residual rather than silently vanishing. The residual is reported as computed.
    """
    require_finite_float(equity_before, "attribute_step.equity_before")
    require_finite_float(equity_after, "attribute_step.equity_after")
    require_finite_float(total_cost, "attribute_step.total_cost")

    local_price_pnl = 0.0
    fx_translation_pnl = 0.0
    for instrument_id, quantity in held_quantities.items():
        if instrument_id not in marks_before or instrument_id not in marks_after:
            continue
        if instrument_id not in local_close_before or instrument_id not in local_close_after:
            continue
        if instrument_id not in fx_before or instrument_id not in fx_after:
            continue
        close_before = local_close_before[instrument_id]
        close_after = local_close_after[instrument_id]
        rate_before = fx_before[instrument_id]
        rate_after = fx_after[instrument_id]
        local_price_pnl += quantity * (close_after - close_before) * rate_before
        fx_translation_pnl += quantity * close_after * (rate_after - rate_before)

    equity_change = equity_after - equity_before
    residual = equity_change - (local_price_pnl + fx_translation_pnl - total_cost)
    return StepAttribution(
        local_price_pnl=local_price_pnl,
        fx_translation_pnl=fx_translation_pnl,
        cost=total_cost,
        residual=residual,
        equity_change=equity_change,
    )
