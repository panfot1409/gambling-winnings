"""The additive attribution of an equity change across one rebalance step.

Between two consecutive execution events the portfolio's base-currency equity changes for five
reasons: the local prices of held-through instruments moved, the FX rates translating those local
values to the base currency moved, corporate-action cash was received, costs were paid, and a
residual absorbs everything the first four terms do not explain (a held-through step leaves it at
zero within tolerance).

:func:`attribute_step` computes that decomposition from the pre-rebalance held quantities and the
per-instrument local closes and FX legs at the two events. For each held-through instrument it
splits the value change into a local-price term (priced at the *entry* FX, so it is a pure local
move) and an FX-translation term (the *exit* local close times the FX change), which is the standard
first-order local/FX split, and it retains those per-asset contributions so the result can report
attribution by asset and by currency. The residual is reported, never forced to zero, so an
unexpected leak is visible rather than hidden.

Corporate-action cash (``action_cash``) is a first-class additive term for forward compatibility; it
is ``0.0`` today because the engine does not yet apply corporate actions (it fails closed on any
in-window action instead — see :mod:`eth_research.portfolio.engine`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_research.api.serialization import require_finite_float

__all__ = ["AssetContribution", "StepAttribution", "attribute_step"]


@dataclass(frozen=True)
class AssetContribution:
    """One held-through instrument's local-price and FX-translation P&L over a step."""

    instrument_id: str
    quote_currency: str
    local_price_pnl: float
    fx_translation_pnl: float

    def canonical(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "quote_currency": self.quote_currency,
            "local_price_pnl": self.local_price_pnl,
            "fx_translation_pnl": self.fx_translation_pnl,
        }


@dataclass(frozen=True)
class StepAttribution:
    """The additive, base-currency decomposition of one step's equity change.

    ``equity_change == local_price_pnl + fx_translation_pnl + action_cash - cost + residual`` holds
    by construction (``residual`` is the honest remainder). ``per_asset`` carries the per-instrument
    split, canonically ordered by ``instrument_id``.
    """

    local_price_pnl: float
    fx_translation_pnl: float
    action_cash: float
    cost: float
    residual: float
    equity_change: float
    per_asset: tuple[AssetContribution, ...]

    @property
    def per_currency(self) -> tuple[tuple[str, float], ...]:
        """FX-translation P&L aggregated by quote currency, sorted by currency."""
        totals: dict[str, float] = {}
        for contribution in self.per_asset:
            totals[contribution.quote_currency] = (
                totals.get(contribution.quote_currency, 0.0) + contribution.fx_translation_pnl
            )
        return tuple(sorted(totals.items()))

    def canonical(self) -> dict[str, Any]:
        """The canonical field mapping (aggregates as base-currency floats; per-asset inlined)."""
        return {
            "local_price_pnl": self.local_price_pnl,
            "fx_translation_pnl": self.fx_translation_pnl,
            "action_cash": self.action_cash,
            "cost": self.cost,
            "residual": self.residual,
            "equity_change": self.equity_change,
            "per_asset": [contribution.canonical() for contribution in self.per_asset],
            "per_currency": [
                {"currency": currency, "fx_translation_pnl": value}
                for currency, value in self.per_currency
            ],
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
    currency_of: dict[str, str] | None = None,
    action_cash: float = 0.0,
) -> StepAttribution:
    """Decompose ``equity_after - equity_before`` into local-price, FX, action-cash, cost, residual.

    ``held_quantities`` are the quantities held *before* the rebalance (the instruments carried
    through the interval). For each such instrument that is marked at both events, the local-price
    P&L is ``qty * (close_after - close_before) * fx_before`` and the FX-translation P&L is
    ``qty * close_after * (fx_after - fx_before)``. ``marks_before``/``marks_after`` (base value
    per unit) scope the held-through set to instruments valued at both events; anything they do not
    cover folds into the residual rather than silently vanishing. ``currency_of`` maps each held
    instrument id to its quote currency for the per-currency split (unknown ids report ``""``).
    ``action_cash`` is the corporate-action cash received over the step (``0.0`` today). The
    residual is reported as computed.
    """
    require_finite_float(equity_before, "attribute_step.equity_before")
    require_finite_float(equity_after, "attribute_step.equity_after")
    require_finite_float(total_cost, "attribute_step.total_cost")
    require_finite_float(action_cash, "attribute_step.action_cash")
    currencies = currency_of or {}

    local_price_pnl = 0.0
    fx_translation_pnl = 0.0
    per_asset: list[AssetContribution] = []
    for instrument_id in sorted(held_quantities):
        quantity = held_quantities[instrument_id]
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
        asset_local = quantity * (close_after - close_before) * rate_before
        asset_fx = quantity * close_after * (rate_after - rate_before)
        local_price_pnl += asset_local
        fx_translation_pnl += asset_fx
        per_asset.append(
            AssetContribution(
                instrument_id=instrument_id,
                quote_currency=currencies.get(instrument_id, ""),
                local_price_pnl=asset_local,
                fx_translation_pnl=asset_fx,
            )
        )

    equity_change = equity_after - equity_before
    residual = equity_change - (local_price_pnl + fx_translation_pnl + action_cash - total_cost)
    return StepAttribution(
        local_price_pnl=local_price_pnl,
        fx_translation_pnl=fx_translation_pnl,
        action_cash=action_cash,
        cost=total_cost,
        residual=residual,
        equity_change=equity_change,
        per_asset=tuple(per_asset),
    )
