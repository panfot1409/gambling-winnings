"""Exact fractional long-only accounting: hand-calculated identities.

Every number below is worked by hand from
``docs/M3B_FRACTIONAL_ACCOUNTING_SPEC.md`` so the accounting cannot drift.
"""

from __future__ import annotations

import pytest

from eth_research.fractional.accounting import (
    DEFAULT_TOLERANCES,
    AccountingError,
    Fill,
    PortfolioState,
    achieved_weight_after,
    apply_fill,
    equity_at,
    validate_state,
    weight_at_reference,
)


class TestBuy:
    def test_hand_calculated_buy(self) -> None:
        # C0=1000, Q0=0; buy 5 ETH @ 100, fee 0.1% -> fee 0.5.
        state = PortfolioState(cash=1000.0, quantity=0.0)
        new_state, fill = apply_fill(state, "buy", 5.0, 100.0, 0.001)
        assert new_state.quantity == 5.0
        assert new_state.cash == pytest.approx(499.5, abs=1e-12)
        assert fill.fill_notional == pytest.approx(500.0, abs=1e-12)
        assert fill.fee == pytest.approx(0.5, abs=1e-12)
        # weight marks ETH at the reference open (100), costs sit only in cash.
        assert weight_at_reference(new_state, 100.0) == pytest.approx(500.0 / 999.5, abs=1e-15)

    def test_full_investment_reaches_weight_one(self) -> None:
        # C0=1000, Q0=0; buy 10 ETH @ 100, zero fee -> all cash deployed.
        state = PortfolioState(cash=1000.0, quantity=0.0)
        new_state, _ = apply_fill(state, "buy", 10.0, 100.0, 0.0)
        assert new_state.cash == pytest.approx(0.0, abs=1e-12)
        assert new_state.quantity == 10.0
        assert weight_at_reference(new_state, 100.0) == pytest.approx(1.0, abs=1e-12)

    def test_buy_never_creates_cash(self) -> None:
        state = PortfolioState(cash=1000.0, quantity=1.0)
        new_state, fill = apply_fill(state, "buy", 3.0, 120.0, 0.002)
        assert new_state.cash < state.cash
        assert new_state.quantity > state.quantity
        assert fill.cash_after < fill.cash_before

    def test_buy_beyond_cash_is_rejected(self) -> None:
        state = PortfolioState(cash=100.0, quantity=0.0)
        with pytest.raises(AccountingError, match="cash"):
            apply_fill(state, "buy", 2.0, 100.0, 0.0)  # needs 200

    def test_tiny_cash_shortfall_is_kept_within_tolerance(self) -> None:
        # C1 = 100 - 100.0000000001 = -1e-10: within cash_tolerance it is kept
        # as-is (not overwritten to 0), so a full-investment buy stays
        # bit-identical to the binary engine, which does not clamp either.
        state = PortfolioState(cash=100.0, quantity=0.0)
        new_state, _ = apply_fill(state, "buy", 1.0, 100.0000000001, 0.0)
        assert -DEFAULT_TOLERANCES.cash_tolerance <= new_state.cash < 0.0
        validate_state(new_state)  # accepted within tolerance


class TestSell:
    def test_hand_calculated_sell(self) -> None:
        # C0=0, Q0=10; sell 4 ETH @ 100, fee 0.1% -> fee 0.4.
        state = PortfolioState(cash=0.0, quantity=10.0)
        new_state, fill = apply_fill(state, "sell", 4.0, 100.0, 0.001)
        assert new_state.quantity == 6.0
        assert new_state.cash == pytest.approx(399.6, abs=1e-12)
        assert fill.fee == pytest.approx(0.4, abs=1e-12)
        assert weight_at_reference(new_state, 100.0) == pytest.approx(600.0 / 999.6, abs=1e-15)

    def test_sell_never_creates_eth(self) -> None:
        state = PortfolioState(cash=0.0, quantity=10.0)
        new_state, _ = apply_fill(state, "sell", 4.0, 100.0, 0.001)
        assert new_state.quantity < state.quantity
        assert new_state.cash > state.cash

    def test_sell_beyond_inventory_is_rejected(self) -> None:
        state = PortfolioState(cash=0.0, quantity=1.0)
        with pytest.raises(AccountingError, match="quantity"):
            apply_fill(state, "sell", 2.0, 100.0, 0.0)

    def test_sell_all_reaches_weight_zero(self) -> None:
        state = PortfolioState(cash=0.0, quantity=10.0)
        new_state, _ = apply_fill(state, "sell", 10.0, 100.0, 0.001)
        assert new_state.quantity == 0.0
        assert weight_at_reference(new_state, 100.0) == pytest.approx(0.0, abs=1e-12)


class TestWeightsAndEquity:
    def test_weight_at_reference_is_the_eth_fraction(self) -> None:
        assert weight_at_reference(PortfolioState(500.0, 5.0), 100.0) == pytest.approx(0.5)
        assert weight_at_reference(PortfolioState(1000.0, 0.0), 100.0) == 0.0

    def test_equity_marks_at_the_given_price(self) -> None:
        assert equity_at(PortfolioState(100.0, 2.0), 50.0) == pytest.approx(200.0)

    def test_non_positive_reference_price_is_rejected(self) -> None:
        with pytest.raises(AccountingError, match="reference price"):
            weight_at_reference(PortfolioState(100.0, 1.0), 0.0)

    def test_achieved_weight_after_matches_apply_then_weight(self) -> None:
        state = PortfolioState(cash=1000.0, quantity=2.0)
        direct = achieved_weight_after(state, "buy", 3.0, 110.0, 0.001, 100.0)
        new_state, _ = apply_fill(state, "buy", 3.0, 110.0, 0.001)
        assert direct == pytest.approx(weight_at_reference(new_state, 100.0), abs=1e-15)


class TestValidation:
    def test_negative_cash_beyond_tolerance_is_rejected(self) -> None:
        with pytest.raises(AccountingError, match="cash"):
            validate_state(PortfolioState(cash=-1.0, quantity=1.0))

    def test_negative_quantity_beyond_tolerance_is_rejected(self) -> None:
        with pytest.raises(AccountingError, match="quantity"):
            validate_state(PortfolioState(cash=1.0, quantity=-1.0))

    def test_within_tolerance_state_is_accepted(self) -> None:
        validate_state(PortfolioState(cash=-1e-9, quantity=-1e-13))  # must not raise

    def test_pinned_tolerances(self) -> None:
        t = DEFAULT_TOLERANCES
        assert (t.cash_tolerance, t.quantity_tolerance, t.weight_tolerance) == (1e-6, 1e-12, 1e-9)
        assert (t.solver_tolerance, t.no_trade_epsilon, t.notional_epsilon) == (1e-12, 1e-9, 1e-6)
        assert t.max_iterations == 100


def test_no_trade_leaves_state_unchanged() -> None:
    state = PortfolioState(cash=500.0, quantity=5.0)
    new_state, fill = apply_fill(state, "buy", 0.0, 100.0, 0.001)
    assert new_state == state
    assert isinstance(fill, Fill)
    assert fill.quantity == 0.0
    assert fill.fee == 0.0
