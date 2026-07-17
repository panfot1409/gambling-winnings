"""The additive step attribution: local-price, FX-translation, cost, and residual."""

from __future__ import annotations

import pytest

from eth_research.portfolio.attribution import attribute_step


def test_single_asset_local_move_has_zero_residual() -> None:
    attribution = attribute_step(
        equity_before=1000.0,
        equity_after=1100.0,
        held_quantities={"a": 10.0},
        marks_before={"a": 100.0},
        marks_after={"a": 110.0},
        local_close_before={"a": 100.0},
        local_close_after={"a": 110.0},
        fx_before={"a": 1.0},
        fx_after={"a": 1.0},
        total_cost=0.0,
    )
    assert attribution.local_price_pnl == pytest.approx(100.0)
    assert attribution.fx_translation_pnl == pytest.approx(0.0)
    assert abs(attribution.residual) < 1e-6


def test_fx_translation_is_isolated() -> None:
    # Local close flat, FX moves 1.0 -> 1.1: the whole change is FX translation, residual ~0.
    attribution = attribute_step(
        equity_before=1000.0,
        equity_after=1100.0,
        held_quantities={"a": 10.0},
        marks_before={"a": 100.0},
        marks_after={"a": 110.0},
        local_close_before={"a": 100.0},
        local_close_after={"a": 100.0},
        fx_before={"a": 1.0},
        fx_after={"a": 1.1},
        total_cost=0.0,
    )
    assert attribution.local_price_pnl == pytest.approx(0.0)
    assert attribution.fx_translation_pnl == pytest.approx(100.0)
    assert abs(attribution.residual) < 1e-6


def test_cost_only_step_is_additive() -> None:
    attribution = attribute_step(
        equity_before=1000.0,
        equity_after=995.0,
        held_quantities={"a": 10.0},
        marks_before={"a": 100.0},
        marks_after={"a": 100.0},
        local_close_before={"a": 100.0},
        local_close_after={"a": 100.0},
        fx_before={"a": 1.0},
        fx_after={"a": 1.0},
        total_cost=5.0,
    )
    reconstructed = (
        attribution.local_price_pnl
        + attribution.fx_translation_pnl
        - attribution.cost
        + attribution.residual
    )
    assert reconstructed == pytest.approx(attribution.equity_change)
    assert attribution.equity_change == pytest.approx(-5.0)
    assert abs(attribution.residual) < 1e-6


def test_instrument_unmarked_before_folds_into_residual() -> None:
    # A freshly opened holding (no mark before the step) contributes nothing to the P&L terms.
    attribution = attribute_step(
        equity_before=1000.0,
        equity_after=1000.0,
        held_quantities={"a": 10.0},
        marks_before={},
        marks_after={"a": 100.0},
        local_close_before={},
        local_close_after={"a": 100.0},
        fx_before={},
        fx_after={"a": 1.0},
        total_cost=0.0,
    )
    assert attribution.local_price_pnl == 0.0
    assert attribution.fx_translation_pnl == 0.0
    assert attribution.residual == pytest.approx(0.0)


def test_attribution_canonical_shape() -> None:
    attribution = attribute_step(
        equity_before=1000.0,
        equity_after=1000.0,
        held_quantities={},
        marks_before={},
        marks_after={},
        local_close_before={},
        local_close_after={},
        fx_before={},
        fx_after={},
        total_cost=0.0,
    )
    canonical = attribution.canonical()
    assert set(canonical) == {
        "local_price_pnl",
        "fx_translation_pnl",
        "cost",
        "residual",
        "equity_change",
    }
    for value in canonical.values():
        assert isinstance(value, float)
