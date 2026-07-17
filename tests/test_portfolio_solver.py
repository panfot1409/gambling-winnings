"""The execution-cost model and the shared-cash simultaneous solver."""

from __future__ import annotations

import math

import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.costs import CostParameters, trade_cost
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.solver import AssetSolveInput, solve_shared_cash


def _inst(symbol: str, base: str, quote: str = "USD") -> InstrumentId:
    return InstrumentId(
        asset_class="crypto_spot" if quote != base else "fx_spot",
        base_asset=base,
        quote_currency=quote,
        venue="synthetic",
        symbol=symbol,
        instrument_type="spot",
        price_unit=quote,
        quantity_unit=base,
        calendar_id="continuous_24_7",
    )


A = _inst("A-USD", "AAA")
B = _inst("B-USD", "BBB")

_ZERO = CostParameters(scenario="zero")
_COMPAT = CostParameters.compatibility_v1()


def _asset(
    instrument: InstrumentId,
    base_value: float,
    weight: float,
    *,
    price: float = 100.0,
    fx: float = 1.0,
    volume: float = 1e15,
) -> AssetSolveInput:
    return AssetSolveInput(
        instrument=instrument,
        base_value=base_value,
        target_weight=weight,
        fx_rate=fx,
        local_price=price,
        lagged_dollar_volume=volume,
        quote_currency=instrument.quote_currency,
        base_currency="USD",
    )


# --------------------------------------------------------------------------- #
# cost model
# --------------------------------------------------------------------------- #
def test_cost_parameters_reject_non_contractive() -> None:
    with pytest.raises(CanonicalError, match="contractive"):
        CostParameters(scenario="bad", fee_rate=0.6, base_slippage=0.5)
    # the impact cap enters the bound at 1.5x
    with pytest.raises(CanonicalError, match="contractive"):
        CostParameters(scenario="bad", impact_cap=0.7)


def test_compatibility_v1_matches_accepted_rates() -> None:
    assert _COMPAT.fee_rate == 0.001
    assert _COMPAT.base_slippage == 0.0005
    assert _COMPAT.half_spread == 0.0
    assert _COMPAT.impact_cap == 0.0


def test_trade_cost_components_and_zero() -> None:
    zero = trade_cost(_ZERO, 0.0, currency="USD")
    assert zero.total == 0.0
    c = trade_cost(_COMPAT, 1000.0, currency="USD")
    assert c.fee == pytest.approx(1.0)  # 0.001 * 1000
    assert c.slippage == pytest.approx(0.5)  # 0.0005 * 1000
    assert c.total == pytest.approx(1.5)


def test_trade_cost_impact_is_capped_sqrt_of_participation() -> None:
    params = CostParameters(scenario="impact", impact_coefficient=0.1, impact_cap=0.05)
    # participation 0.25 -> 0.1*sqrt(0.25)=0.05 == cap
    at_cap = trade_cost(params, 1000.0, participation=0.25, currency="USD")
    assert at_cap.impact == pytest.approx(0.05 * 1000.0)
    # participation 0.04 -> 0.1*sqrt(0.04)=0.02 < cap
    below = trade_cost(params, 1000.0, participation=0.04, currency="USD")
    assert below.impact == pytest.approx(0.02 * 1000.0)
    # huge participation clamps at cap
    high = trade_cost(params, 1000.0, participation=100.0, currency="USD")
    assert high.impact == pytest.approx(0.05 * 1000.0)


# --------------------------------------------------------------------------- #
# solver — zero cost is an exact closed form
# --------------------------------------------------------------------------- #
def test_zero_cost_solve_is_exact() -> None:
    result = solve_shared_cash(
        (_asset(A, 0.0, 0.3, price=100.0), _asset(B, 0.0, 0.5, price=200.0)),
        base_cash=1000.0,
        params=_ZERO,
    )
    assert result.equity_post == pytest.approx(1000.0, abs=1e-9)
    assert result.total_cost == 0.0
    assert result.residual_cash == pytest.approx(200.0, abs=1e-9)
    by_symbol = {t.instrument.symbol: t for t in result.trades}
    assert by_symbol["A-USD"].base_notional == pytest.approx(300.0, abs=1e-9)
    assert by_symbol["A-USD"].local_quantity == pytest.approx(3.0, abs=1e-9)
    assert by_symbol["B-USD"].base_notional == pytest.approx(500.0, abs=1e-9)
    assert by_symbol["B-USD"].local_quantity == pytest.approx(2.5, abs=1e-9)


def test_single_asset_cost_solve_matches_hand_oracle() -> None:
    # full allocation of 1000 cash to one asset at rate 0.0015: E_post = 1000 / 1.0015
    result = solve_shared_cash((_asset(A, 0.0, 1.0),), base_cash=1000.0, params=_COMPAT)
    expected = 1000.0 / 1.0015
    assert result.equity_post == pytest.approx(expected, rel=1e-12)
    assert result.total_cost == pytest.approx(0.0015 * expected, rel=1e-11)
    assert result.residual_cash == pytest.approx(0.0, abs=1e-6)


def test_solver_is_permutation_invariant() -> None:
    forward = solve_shared_cash(
        (_asset(A, 100.0, 0.3), _asset(B, 50.0, 0.5)), base_cash=500.0, params=_COMPAT
    )
    reverse = solve_shared_cash(
        (_asset(B, 50.0, 0.5), _asset(A, 100.0, 0.3)), base_cash=500.0, params=_COMPAT
    )
    assert forward.equity_post == reverse.equity_post
    assert forward.total_cost == reverse.total_cost
    assert [t.instrument.symbol for t in forward.trades] == [
        t.instrument.symbol for t in reverse.trades
    ]
    for f, r in zip(forward.trades, reverse.trades, strict=True):
        assert f.base_notional == r.base_notional
        assert f.cost.total == r.cost.total


def test_solver_is_permutation_invariant_for_many_assets() -> None:
    # With >=3 assets a naive left-fold sum over the input order is order-sensitive at the ULP level
    # (float addition is not associative), which would perturb the pre-trade equity, gross weight,
    # and total cost and shift the bisection bracket. The solver must canonicalize the order so any
    # reordering is *exactly* identical. The two-asset test above cannot catch this.
    cost = CostParameters(
        scenario="asym",
        fee_rate=0.0007,
        half_spread=0.0003,
        base_slippage=0.0005,
        impact_coefficient=0.2,
        impact_cap=0.05,
    )
    specs = [
        (_inst("S0-USD", "B00"), 91234.5, 0.11, 133.7, 2.3e12),
        (_inst("S1-USD", "B01"), 17654.25, 0.19, 51.9, 8.1e11),
        (_inst("S2-USD", "B02"), 250011.0, 0.07, 940.4, 5.5e13),
        (_inst("S3-USD", "B03"), 3210.75, 0.23, 12.4, 1.9e10),
        (_inst("S4-USD", "B04"), 634221.5, 0.05, 7788.0, 3.3e14),
        (_inst("S5-USD", "B05"), 44120.0, 0.17, 205.5, 7.7e11),
    ]
    assets = [_asset(inst, bv, w, price=p, volume=v) for inst, bv, w, p, v in specs]
    base_cash = 314454.1817052079
    forward = solve_shared_cash(tuple(assets), base_cash=base_cash, params=cost)
    for perm in [(2, 0, 1, 3, 5, 4), (5, 4, 3, 2, 1, 0), (1, 3, 5, 0, 2, 4)]:
        reordered = solve_shared_cash(
            tuple(assets[k] for k in perm), base_cash=base_cash, params=cost
        )
        assert reordered.equity_post == forward.equity_post  # exact, not merely close
        assert reordered.total_cost == forward.total_cost
        assert reordered.residual_cash == forward.residual_cash
        assert {t.instrument.symbol: t.base_notional for t in reordered.trades} == {
            t.instrument.symbol: t.base_notional for t in forward.trades
        }


def test_all_cash_target_sells_everything() -> None:
    result = solve_shared_cash((_asset(A, 500.0, 0.0, price=100.0),), base_cash=0.0, params=_ZERO)
    assert result.equity_post == pytest.approx(500.0, abs=1e-9)
    assert result.residual_cash == pytest.approx(500.0, abs=1e-9)
    trade = result.trades[0]
    assert trade.side == "sell"
    assert trade.base_notional == pytest.approx(-500.0, abs=1e-9)
    assert trade.local_quantity == pytest.approx(-5.0, abs=1e-9)


def test_solver_is_cash_safe_and_long_only() -> None:
    result = solve_shared_cash(
        (_asset(A, 0.0, 0.5), _asset(B, 0.0, 0.5)), base_cash=1000.0, params=_COMPAT
    )
    assert result.residual_cash >= -1e-6
    for trade in result.trades:
        assert trade.post_base_value >= -1e-6
    # equity identity holds
    assert result.equity_post == pytest.approx(result.equity_pre - result.total_cost, rel=1e-12)


def test_solver_rejects_leveraged_weights_and_zero_equity() -> None:
    with pytest.raises(CanonicalError, match="sum"):
        solve_shared_cash((_asset(A, 0.0, 0.6), _asset(B, 0.0, 0.6)), base_cash=100.0, params=_ZERO)
    with pytest.raises(CanonicalError, match="positive"):
        solve_shared_cash((_asset(A, 0.0, 0.5),), base_cash=0.0, params=_ZERO)


def test_solve_converges_within_iteration_budget() -> None:
    result = solve_shared_cash((_asset(A, 0.0, 1.0),), base_cash=1_000_000.0, params=_COMPAT)
    assert result.iterations <= 100
    # the bracket reached a few ULPs: residual within a cent on a million-dollar book
    assert math.isclose(result.equity_post, 1_000_000.0 / 1.0015, rel_tol=1e-11)
