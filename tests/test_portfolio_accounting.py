"""The immutable accounting ledger: cash-safe, long-only fill application."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.accounting import Fill, PortfolioState, Position
from eth_research.portfolio.costs import CostBreakdown
from eth_research.portfolio.identity import InstrumentId

INST = InstrumentId(
    asset_class="crypto_spot",
    base_asset="ETH",
    quote_currency="USD",
    venue="synthetic",
    symbol="ETH-USD",
    instrument_type="spot",
    price_unit="USD",
    quantity_unit="ETH",
    calendar_id="continuous_24_7",
)
_TS = pd.Timestamp("2026-07-14T00:00:00", tz="UTC")


def _fill(side: str, qty: float, price: float, *, fee: float = 0.0) -> Fill:
    base_notional = qty * price  # fx 1.0
    return Fill(
        event_id=f"e-{side}",
        event_time=_TS,
        instrument=INST,
        side=side,
        local_quantity=qty,
        fill_price=price,
        fx_rate=1.0,
        base_notional=base_notional,
        cost=CostBreakdown("USD", fee, 0.0, 0.0, 0.0, 0.0),
    )


def test_opening_state_is_all_cash() -> None:
    state = PortfolioState.opening("USD", 1000.0)
    assert state.base_cash == 1000.0
    assert state.positions == ()
    assert state.equity({}) == 1000.0


def test_buy_moves_cash_and_holding() -> None:
    state = PortfolioState.opening("USD", 1000.0)
    after = state.apply_fill(_fill("buy", 5.0, 100.0, fee=1.0))
    assert after.base_cash == pytest.approx(1000.0 - 500.0 - 1.0)
    assert after.quantity_of(INST) == pytest.approx(5.0)
    # equity marked at 100/unit base: cash 499 + 5*100 = 999 (the fee is the drag)
    assert after.equity({INST.instrument_id: 100.0}) == pytest.approx(999.0)


def test_sell_moves_cash_and_holding_back() -> None:
    state = PortfolioState.opening("USD", 1000.0).apply_fill(_fill("buy", 5.0, 100.0))
    after = state.apply_fill(_fill("sell", -2.0, 100.0))
    assert after.quantity_of(INST) == pytest.approx(3.0)
    assert after.base_cash == pytest.approx(500.0 + 200.0)


def test_hold_is_a_noop() -> None:
    state = PortfolioState.opening("USD", 1000.0)
    assert state.apply_fill(_fill("hold", 0.0, 100.0)) is state


def test_cash_safety_is_enforced() -> None:
    state = PortfolioState.opening("USD", 100.0)
    with pytest.raises(CanonicalError, match="cash would go negative"):
        state.apply_fill(_fill("buy", 5.0, 100.0))  # needs 500, has 100


def test_long_only_is_enforced() -> None:
    state = PortfolioState.opening("USD", 1000.0).apply_fill(_fill("buy", 2.0, 100.0))
    with pytest.raises(CanonicalError, match="long-only"):
        state.apply_fill(_fill("sell", -5.0, 100.0))  # would go to -3
    with pytest.raises(CanonicalError, match="short"):
        PortfolioState.opening("USD", 1000.0).apply_fill(_fill("sell", -1.0, 100.0))


def test_state_rejects_negative_cash_and_duplicate_positions() -> None:
    with pytest.raises(CanonicalError, match="cash-safe"):
        PortfolioState("USD", -1.0, ())
    with pytest.raises(CanonicalError, match="duplicate"):
        PortfolioState("USD", 0.0, (Position(INST, 1.0), Position(INST, 2.0)))


def test_equity_requires_a_mark_for_every_holding() -> None:
    state = PortfolioState.opening("USD", 500.0).apply_fill(_fill("buy", 5.0, 100.0))
    with pytest.raises(CanonicalError, match="no mark"):
        state.equity({})


def test_fill_and_state_fingerprints_are_stable() -> None:
    a = _fill("buy", 5.0, 100.0)
    assert a.fingerprint == _fill("buy", 5.0, 100.0).fingerprint
    state = PortfolioState.opening("USD", 1000.0).apply_fill(a)
    assert len(state.fingerprint) == 64


def test_fill_rejects_bad_side_and_naive_time() -> None:
    with pytest.raises(CanonicalError, match="side"):
        Fill(
            "e",
            _TS,
            INST,
            "leverage",
            1.0,
            100.0,
            1.0,
            100.0,
            CostBreakdown("USD", 0.0, 0.0, 0.0, 0.0, 0.0),
        )
    with pytest.raises(CanonicalError, match="timezone-aware"):
        Fill(
            "e",
            pd.Timestamp("2026-07-14T00:00:00"),
            INST,
            "buy",
            1.0,
            100.0,
            1.0,
            100.0,
            CostBreakdown("USD", 0.0, 0.0, 0.0, 0.0, 0.0),
        )
