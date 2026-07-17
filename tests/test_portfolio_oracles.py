"""Independent hand-calculated oracles for the portfolio simulator (Milestone 4B, §31).

Every expected number in this file is a literal I computed BY HAND (the arithmetic is shown in a
comment next to it) and then compared against what the production code returns. Nothing here feeds a
solver/engine result back in as its own expected value: the production objects are the *system under
test*, the literals are the independent check. Each scenario is deliberately tiny so the arithmetic
is fully auditable and each test runs in well under a second.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.metrics import max_drawdown, total_return
from eth_research.portfolio.accounting import Fill, PortfolioState
from eth_research.portfolio.attribution import attribute_step
from eth_research.portfolio.bars import validate_bar_frame
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.costs import CostBreakdown, CostParameters, trade_cost
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.fx import FxEvidence, FxObservation
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.panel import build_market_panel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.solver import AssetSolveInput, solve_shared_cash
from eth_research.portfolio.targets import (
    cash_target,
    declared_weights_target,
    equal_weight_target,
)
from eth_research.portfolio.valuation import StalenessPolicy, mark_instrument

# --------------------------------------------------------------------------- #
# shared construction helpers (mirroring the idioms in the sibling test files)
# --------------------------------------------------------------------------- #


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _inst(symbol: str, base: str, quote: str = "USD") -> InstrumentId:
    return InstrumentId(
        asset_class="crypto_spot",
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
C = _inst("C-USD", "CCC")
D = _inst("D-USD", "DDD")
S = _inst("S-USD", "SSS")
EUR_INST = _inst("SHR-EUR", "SHR", quote="EUR")

_ZERO = CostParameters(scenario="zero")
_COMPAT = CostParameters.compatibility_v1()
_STALE = StalenessPolicy(max_staleness_seconds=1_000_000.0)
_FX = FxEvidence(observations=())
_CAL = {"continuous_24_7": TradingCalendar("continuous_24_7", "continuous_24_7", (), "test")}
_PPY = 8766.0  # hourly bars per 365.25-day year (only the annualization basis; unused by oracles)


def _flat_bars(price: float, periods: int = 5) -> pd.DataFrame:
    opens = pd.date_range(start="2026-07-14T00:00:00", periods=periods, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": opens,
            "close_time": opens + pd.Timedelta(hours=1),
            "open": [price] * periods,
            "high": [price] * periods,
            "low": [price] * periods,
            "close": [price] * periods,
            "volume": [1000.0] * periods,
        }
    )


def _moving_bars(opens: Sequence[float], closes: Sequence[float]) -> pd.DataFrame:
    times = pd.date_range(start="2026-07-14T00:00:00", periods=len(opens), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": times,
            "close_time": times + pd.Timedelta(hours=1),
            "open": [float(o) for o in opens],
            "high": [float(max(o, c)) for o, c in zip(opens, closes, strict=True)],
            "low": [float(min(o, c)) for o, c in zip(opens, closes, strict=True)],
            "close": [float(c) for c in closes],
            "volume": [1000.0] * len(opens),
        }
    )


def _membership(instruments: Sequence[InstrumentId]) -> MembershipSchedule:
    return MembershipSchedule(
        intervals=tuple(
            MembershipInterval(
                instrument,
                _ts("2026-07-14T00:00:00"),
                None,
                _ts("2026-07-14T00:00:00"),
                "listing",
                "test",
            )
            for instrument in instruments
        )
    )


def _protocol(policy: str, cost: CostParameters = _ZERO) -> PortfolioProtocol:
    return PortfolioProtocol(
        base_currency="USD",
        initial_cash=1000.0,
        policy=policy,  # type: ignore[arg-type]
        cost_scenario=cost,
        staleness=_STALE,
    )


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


_ONE_EVENT = RebalanceSchedule(timestamps=(_ts("2026-07-14T01:00:00"),))
_THREE_EVENTS = RebalanceSchedule(
    timestamps=(
        _ts("2026-07-14T01:00:00"),
        _ts("2026-07-14T02:00:00"),
        _ts("2026-07-14T03:00:00"),
    )
)
_THREE_FROM_ZERO = RebalanceSchedule(
    timestamps=(
        _ts("2026-07-14T00:00:00"),
        _ts("2026-07-14T01:00:00"),
        _ts("2026-07-14T02:00:00"),
    )
)


# --------------------------------------------------------------------------- #
# 1. Zero cost conserves equity exactly (engine, flat prices).
# --------------------------------------------------------------------------- #
def test_zero_cost_full_allocation_conserves_equity() -> None:
    # 1000 cash, one asset at weight 1.0, flat price 100, zero cost. Zero cost is the exact identity
    # E_post == E_pre, so terminal equity == initial == 1000 to the last cent.
    panel = build_market_panel({S: _flat_bars(100.0, periods=3)})
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, _membership([S]), _FX, _ONE_EVENT, calendars=_CAL
    )
    assert result.initial_equity == pytest.approx(1000.0, abs=1e-9)
    assert result.terminal_equity == pytest.approx(1000.0, abs=1e-9)  # conserved, no drag
    assert result.events[0].total_cost == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# 2. Single-asset full allocation under compatibility_v1 (solver closed form).
# --------------------------------------------------------------------------- #
def test_single_asset_compat_solver_post_equity_oracle() -> None:
    # One asset, flat->fully invested, cost rate r = fee 0.001 + slippage 0.0005 = 0.0015.
    # E_post = E_pre / (1 + r) = 1000 / 1.0015 = 998.5022466300549...
    # total_cost = E_pre - E_post = 1000 - 998.5022466300549 = 1.4977533699451...
    result = solve_shared_cash((_asset(A, 0.0, 1.0),), base_cash=1000.0, params=_COMPAT)
    assert result.equity_post == pytest.approx(998.5022466300549, abs=1e-9)
    assert result.total_cost == pytest.approx(1.4977533699451, abs=1e-9)
    assert result.residual_cash == pytest.approx(0.0, abs=1e-6)  # fully invested


# --------------------------------------------------------------------------- #
# 3. Moving price single asset: buy at open, mark at the bar's own close[t].
# --------------------------------------------------------------------------- #
def test_single_asset_moving_price_marks_at_close() -> None:
    # 1000 buys at open[0]=50 -> 1000/50 = 20 units (zero cost). The engine marks each step at the
    # close of the bar it traded into: event0 -> 20*55 = 1100, event1 (a pure hold) -> 20*60 = 1200.
    panel = build_market_panel({S: _moving_bars([50.0, 55.0], [55.0, 60.0])})
    schedule = RebalanceSchedule(
        timestamps=(_ts("2026-07-14T00:00:00"), _ts("2026-07-14T01:00:00"))
    )
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, _membership([S]), _FX, schedule, calendars=_CAL
    )
    assert result.events[0].equity == pytest.approx(1100.0, abs=1e-9)  # 20 * 55
    assert result.terminal_equity == pytest.approx(1200.0, abs=1e-9)  # 20 * 60
    assert result.all_fills == 1  # bought once, then held


# --------------------------------------------------------------------------- #
# 4. Two-asset equal weight, flat: 50% each, gross 1.0, cash 0.
# --------------------------------------------------------------------------- #
def test_two_asset_equal_weight_flat_holds_half_each() -> None:
    # 1000 split 0.5/0.5 over two flat-100 assets: each base value 0.5*1000 = 500, cash 0.
    panel = build_market_panel({A: _flat_bars(100.0), B: _flat_bars(100.0)})
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, _membership([A, B]), _FX, _ONE_EVENT, calendars=_CAL
    )
    event = result.events[0]
    assert event.equity == pytest.approx(1000.0, abs=1e-6)
    assert event.cash == pytest.approx(0.0, abs=1e-6)  # gross exposure 1.0 leaves no cash
    assert event.positions_count == 2
    for holding in event.holdings:
        assert holding.base_value == pytest.approx(500.0, abs=1e-6)  # 0.5 * 1000


# --------------------------------------------------------------------------- #
# 5. Cash policy: no fills, terminal == initial, everything in cash.
# --------------------------------------------------------------------------- #
def test_cash_policy_holds_everything_in_cash() -> None:
    panel = build_market_panel({A: _flat_bars(100.0), B: _flat_bars(100.0)})
    result = run_portfolio_simulation(
        _protocol("cash"), panel, _membership([A, B]), _FX, _THREE_EVENTS, calendars=_CAL
    )
    assert result.all_fills == 0
    assert result.terminal_equity == pytest.approx(1000.0, abs=1e-9)
    for event in result.events:
        assert event.positions_count == 0
        assert event.cash == pytest.approx(1000.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# 6. equal_weight over N assets -> weight 1/N each (N = 2, 3, 4).
# --------------------------------------------------------------------------- #
def test_equal_weight_target_is_one_over_n() -> None:
    universe = (A, B, C, D)
    # N=2 -> 1/2 = 0.5 ; N=3 -> 1/3 = 0.3333333333333333 ; N=4 -> 1/4 = 0.25
    expected = {2: 0.5, 3: 0.3333333333333333, 4: 0.25}
    for n in (2, 3, 4):
        active = universe[:n]
        target = equal_weight_target(active)
        assert len(target.weights) == n
        for instrument in active:
            assert target.weight_for(instrument) == pytest.approx(expected[n])
        assert target.gross_weight == pytest.approx(1.0, abs=1e-9)  # fully allocated


# --------------------------------------------------------------------------- #
# 7. declared_weights with gross < 1 leaves a hand-computed residual cash weight.
# --------------------------------------------------------------------------- #
def test_declared_weights_residual_cash_weight() -> None:
    # 0.3 + 0.2 = 0.5 gross; the unallocated 1 - 0.5 = 0.5 is held as base cash.
    target = declared_weights_target((A, B), {A: 0.3, B: 0.2})
    assert target.gross_weight == pytest.approx(0.5, abs=1e-12)
    assert target.residual_cash_weight == pytest.approx(0.5, abs=1e-12)
    assert target.weight_for(A) == pytest.approx(0.3)
    assert target.weight_for(B) == pytest.approx(0.2)


# --------------------------------------------------------------------------- #
# 8. Solver is permutation invariant; pre-trade equity is a clean hand literal.
# --------------------------------------------------------------------------- #
def test_solver_permutation_invariance() -> None:
    # E_pre = base_cash 500 + base_value(A) 100 + base_value(B) 50 = 650 regardless of input order.
    forward = solve_shared_cash(
        (_asset(A, 100.0, 0.3), _asset(B, 50.0, 0.5)), base_cash=500.0, params=_COMPAT
    )
    reverse = solve_shared_cash(
        (_asset(B, 50.0, 0.5), _asset(A, 100.0, 0.3)), base_cash=500.0, params=_COMPAT
    )
    assert forward.equity_pre == pytest.approx(650.0, abs=1e-12)
    assert forward.equity_post == reverse.equity_post  # exact: solve is order independent
    assert forward.total_cost == reverse.total_cost
    for left, right in zip(forward.trades, reverse.trades, strict=True):
        assert left.instrument.symbol == right.instrument.symbol
        assert left.base_notional == right.base_notional


# --------------------------------------------------------------------------- #
# 9. No-trade tolerance: an asset already at its target weight produces a hold.
# --------------------------------------------------------------------------- #
def test_asset_already_on_target_is_a_hold() -> None:
    # base_value 1000 == weight 1.0 * E_pre(1000); the desired delta is 0, so the solver holds.
    result = solve_shared_cash((_asset(A, 1000.0, 1.0),), base_cash=0.0, params=_ZERO)
    assert result.equity_post == pytest.approx(1000.0, abs=1e-9)
    trade = result.trades[0]
    assert trade.side == "hold"
    assert trade.base_notional == pytest.approx(0.0, abs=1e-9)
    assert result.total_cost == pytest.approx(0.0, abs=1e-12)


# --------------------------------------------------------------------------- #
# 10. apply_fill: overspend fails closed; a legal buy moves cash by notional + cost.
# --------------------------------------------------------------------------- #
def test_apply_fill_cash_move_and_overspend() -> None:
    buy = Fill(
        event_id="e-buy",
        event_time=_ts("2026-07-14T00:00:00"),
        instrument=A,
        side="buy",
        local_quantity=5.0,
        fill_price=100.0,
        fx_rate=1.0,
        base_notional=500.0,  # 5 * 100 * fx 1.0
        cost=CostBreakdown("USD", 1.0, 0.0, 0.0, 0.0, 0.0),  # fee 1.0
    )
    after = PortfolioState.opening("USD", 1000.0).apply_fill(buy)
    assert after.base_cash == pytest.approx(499.0, abs=1e-12)  # 1000 - 500 - 1
    assert after.quantity_of(A) == pytest.approx(5.0, abs=1e-12)
    # The same buy needs 501 but only 100 is on hand: cash-safety refuses it.
    with pytest.raises(CanonicalError, match="cash would go negative"):
        PortfolioState.opening("USD", 100.0).apply_fill(buy)


# --------------------------------------------------------------------------- #
# 11. attribute_step: a pure local-price move.
# --------------------------------------------------------------------------- #
def test_attribute_step_pure_local_price_move() -> None:
    # 4 units, local close 50 -> 57.5 at entry FX 2.0: local P&L = 4 * (57.5 - 50) * 2.0 = 60.0.
    step = attribute_step(
        equity_before=1000.0,
        equity_after=1060.0,
        held_quantities={"a": 4.0},
        marks_before={"a": 100.0},  # 50 * 2.0
        marks_after={"a": 115.0},  # 57.5 * 2.0
        local_close_before={"a": 50.0},
        local_close_after={"a": 57.5},
        fx_before={"a": 2.0},
        fx_after={"a": 2.0},
        total_cost=0.0,
    )
    assert step.local_price_pnl == pytest.approx(60.0, abs=1e-9)
    assert step.fx_translation_pnl == pytest.approx(0.0, abs=1e-9)
    assert abs(step.residual) < 1e-9


# --------------------------------------------------------------------------- #
# 12. attribute_step: a pure FX-translation move.
# --------------------------------------------------------------------------- #
def test_attribute_step_pure_fx_move() -> None:
    # 10 units, flat local close 100, FX 1.0 -> 1.25: FX P&L = 10 * 100 * (1.25 - 1.0) = 250.0.
    step = attribute_step(
        equity_before=1000.0,
        equity_after=1250.0,
        held_quantities={"a": 10.0},
        marks_before={"a": 100.0},  # 100 * 1.0
        marks_after={"a": 125.0},  # 100 * 1.25
        local_close_before={"a": 100.0},
        local_close_after={"a": 100.0},
        fx_before={"a": 1.0},
        fx_after={"a": 1.25},
        total_cost=0.0,
    )
    assert step.fx_translation_pnl == pytest.approx(250.0, abs=1e-9)
    assert step.local_price_pnl == pytest.approx(0.0, abs=1e-9)
    assert abs(step.residual) < 1e-9


# --------------------------------------------------------------------------- #
# 13. attribute_step: additive identity with a cost and an action-cash term.
# --------------------------------------------------------------------------- #
def test_attribute_step_additive_identity_with_cost_and_action_cash() -> None:
    # local = 10*(105-100)*1.0 = 50 ; action_cash = 2 ; cost = 3 ; so equity_after must be
    # 1000 + 50 + 0 + 2 - 3 = 1049 with residual 0. Identity: change == local + fx + action - cost.
    step = attribute_step(
        equity_before=1000.0,
        equity_after=1049.0,
        held_quantities={"a": 10.0},
        marks_before={"a": 100.0},
        marks_after={"a": 105.0},
        local_close_before={"a": 100.0},
        local_close_after={"a": 105.0},
        fx_before={"a": 1.0},
        fx_after={"a": 1.0},
        total_cost=3.0,
        action_cash=2.0,
    )
    assert step.local_price_pnl == pytest.approx(50.0, abs=1e-9)
    assert step.action_cash == pytest.approx(2.0, abs=1e-12)
    assert step.cost == pytest.approx(3.0, abs=1e-12)
    reconstructed = (
        step.local_price_pnl
        + step.fx_translation_pnl
        + step.action_cash
        - step.cost
        + step.residual
    )
    assert reconstructed == pytest.approx(step.equity_change, abs=1e-9)
    assert step.equity_change == pytest.approx(49.0, abs=1e-9)  # 1049 - 1000
    assert abs(step.residual) < 1e-9


# --------------------------------------------------------------------------- #
# 14. FX translation in valuation: a EUR-quoted mark converted to USD.
# --------------------------------------------------------------------------- #
def test_mark_instrument_fx_translation_to_usd() -> None:
    # Local close 200 EUR at rate 1.25 USD/EUR -> base value per unit = 200 * 1.25 = 250.0 USD.
    frame = validate_bar_frame(
        pd.DataFrame(
            {
                "open_time": pd.date_range("2026-07-14T00:00:00", periods=1, freq="h", tz="UTC"),
                "close_time": pd.date_range("2026-07-14T01:00:00", periods=1, freq="h", tz="UTC"),
                "open": [199.0],
                "high": [201.0],
                "low": [198.0],
                "close": [200.0],
                "volume": [1000.0],
            }
        ),
        EUR_INST,
    )
    fx = FxEvidence(
        observations=(FxObservation("EUR", "USD", _ts("2026-07-14T00:00:00"), 1.25, "x"),)
    )
    mark = mark_instrument(frame, fx, EUR_INST, "USD", _ts("2026-07-14T01:30:00"), staleness=_STALE)
    assert mark.fx_rate == pytest.approx(1.25, abs=1e-12)
    assert mark.base_value_per_unit == pytest.approx(250.0, abs=1e-9)  # 200 * 1.25


# --------------------------------------------------------------------------- #
# 15. total_return metric == terminal/initial - 1 on a known engine run.
# --------------------------------------------------------------------------- #
def test_total_return_metric_on_known_run() -> None:
    # 10 units held through closes 110->121->133: terminal 1330 on initial 1000.
    # total_return = 1330 / 1000 - 1 = 0.33.
    panel = build_market_panel({S: _moving_bars([100.0, 110.0, 121.0], [110.0, 121.0, 133.0])})
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, _membership([S]), _FX, _THREE_FROM_ZERO, calendars=_CAL
    )
    metrics = compute_portfolio_metrics(result, periods_per_year=_PPY)
    assert metrics.terminal_equity == pytest.approx(1330.0, abs=1e-9)
    assert metrics.total_return == pytest.approx(0.33, abs=1e-9)


# --------------------------------------------------------------------------- #
# 16. max_drawdown / total_return primitives on a hand-built equity path.
# --------------------------------------------------------------------------- #
def test_max_drawdown_on_hand_built_path() -> None:
    # Path with the initial peak prepended: [100, 120, 90, 100]. Running peak 120 at the trough 90
    # gives the deepest loss 90/120 - 1 = -0.25. End value 100 == start -> total_return 0.0.
    equity = pd.Series([120.0, 90.0, 100.0], dtype=float)
    assert max_drawdown(equity, 100.0) == pytest.approx(-0.25, abs=1e-12)
    assert total_return(equity, 100.0) == pytest.approx(0.0, abs=1e-12)  # 100/100 - 1


# --------------------------------------------------------------------------- #
# 17. Membership gating: a late listing is inactive early and active later.
# --------------------------------------------------------------------------- #
def test_membership_gates_a_late_listing() -> None:
    # A is effective from 02:00 (known since 00:00): inactive at 01:00, active from 02:00 on.
    schedule = MembershipSchedule(
        intervals=(
            MembershipInterval(
                A,
                _ts("2026-07-14T02:00:00"),
                None,
                _ts("2026-07-14T00:00:00"),
                "listing",
                "test",
            ),
        )
    )
    assert schedule.active_at(A, _ts("2026-07-14T01:00:00")) is False
    assert schedule.active_at(A, _ts("2026-07-14T02:00:00")) is True
    assert schedule.active_universe(_ts("2026-07-14T01:00:00")) == ()
    assert schedule.active_universe(_ts("2026-07-14T02:00:00")) == (A,)


# --------------------------------------------------------------------------- #
# 18. Staleness carry: exact staleness seconds, then refusal over the bound.
# --------------------------------------------------------------------------- #
def test_staleness_seconds_and_over_bound_refusal() -> None:
    # Last completed close is at 02:00; valuing at 03:00 is (03:00 - 02:00) = 3600 s stale.
    frame = validate_bar_frame(
        pd.DataFrame(
            {
                "open_time": pd.date_range("2026-07-14T00:00:00", periods=2, freq="h", tz="UTC"),
                "close_time": pd.date_range("2026-07-14T01:00:00", periods=2, freq="h", tz="UTC"),
                "open": [100.0, 102.0],
                "high": [101.0, 106.0],
                "low": [99.0, 101.0],
                "close": [100.0, 105.0],
                "volume": [1000.0, 1000.0],
            }
        ),
        A,
    )
    tau = _ts("2026-07-14T03:00:00")
    lenient = mark_instrument(frame, _FX, A, "USD", tau, staleness=StalenessPolicy(7200.0))
    assert lenient.staleness_seconds == pytest.approx(3600.0, abs=1e-9)  # one bar (1h) of carry
    assert lenient.base_value_per_unit == pytest.approx(105.0, abs=1e-9)  # last close
    with pytest.raises(CanonicalError, match="stale"):
        mark_instrument(frame, _FX, A, "USD", tau, staleness=StalenessPolicy(1800.0))


# --------------------------------------------------------------------------- #
# 19. trade_cost under compatibility_v1 == (fee + slippage) * notional, impact 0.
# --------------------------------------------------------------------------- #
def test_trade_cost_compat_fee_plus_slippage() -> None:
    # notional 2000: fee = 0.001*2000 = 2.0 ; slippage = 0.0005*2000 = 1.0 ; total = 3.0 ; impact 0.
    cost = trade_cost(_COMPAT, 2000.0, currency="USD")
    assert cost.fee == pytest.approx(2.0, abs=1e-12)
    assert cost.slippage == pytest.approx(1.0, abs=1e-12)
    assert cost.spread == pytest.approx(0.0, abs=1e-12)
    assert cost.impact == pytest.approx(0.0, abs=1e-12)
    assert cost.total == pytest.approx(3.0, abs=1e-12)


# --------------------------------------------------------------------------- #
# 20. trade_cost impact: sqrt below the cap, then clamped at the cap.
# --------------------------------------------------------------------------- #
def test_trade_cost_impact_below_and_at_cap() -> None:
    params = CostParameters(scenario="impact", impact_coefficient=0.2, impact_cap=0.05)
    # participation 0.04: rate = 0.2*sqrt(0.04) = 0.2*0.2 = 0.04 < cap -> impact = 0.04*1000 = 40.
    below = trade_cost(params, 1000.0, participation=0.04, currency="USD")
    assert below.impact == pytest.approx(40.0, abs=1e-9)
    assert 0.0 < below.impact <= 0.05 * 1000.0  # positive but bounded by cap*notional
    # participation 1.0: rate = 0.2 * sqrt(1) = 0.2 > cap -> clamped to 0.05 -> impact = 50.0.
    capped = trade_cost(params, 1000.0, participation=1.0, currency="USD")
    assert capped.impact == pytest.approx(50.0, abs=1e-9)  # 0.05 * 1000


# --------------------------------------------------------------------------- #
# 21. Two-asset equal weight, moving prices: hand-computed terminal equity.
# --------------------------------------------------------------------------- #
def test_two_asset_equal_weight_moving_terminal_equity() -> None:
    # 1000 split 500/500 at open 100 -> 5 units each. Marked at close[0]=100 both -> equity 1000.
    # Held to close[1]: A 5*120 = 600, B 5*90 = 450 -> terminal equity 600 + 450 = 1050.
    panel = build_market_panel(
        {
            A: _moving_bars([100.0, 100.0], [100.0, 120.0]),
            B: _moving_bars([100.0, 100.0], [100.0, 90.0]),
        }
    )
    schedule = RebalanceSchedule(
        timestamps=(_ts("2026-07-14T00:00:00"), _ts("2026-07-14T01:00:00"))
    )
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, _membership([A, B]), _FX, schedule, calendars=_CAL
    )
    assert result.events[0].equity == pytest.approx(1000.0, abs=1e-6)
    assert result.terminal_equity == pytest.approx(1050.0, abs=1e-6)  # 600 + 450
    assert result.all_fills == 2  # one buy per asset at the first event


# --------------------------------------------------------------------------- #
# 22. cash_target: residual cash weight is the whole book (1.0).
# --------------------------------------------------------------------------- #
def test_cash_target_residual_weight_is_one() -> None:
    target = cash_target((A, B))
    assert target.weights == ()
    assert target.gross_weight == pytest.approx(0.0, abs=1e-12)
    assert target.residual_cash_weight == pytest.approx(1.0, abs=1e-12)  # 1 - 0


# --------------------------------------------------------------------------- #
# 23. Zero-cost solver: exact residual cash and per-asset notionals.
# --------------------------------------------------------------------------- #
def test_zero_cost_solver_residual_and_notionals() -> None:
    # 1000 cash, weights 0.3 and 0.5 (gross 0.8), zero cost -> E_post = 1000 exactly.
    # residual cash = 1000 * (1 - 0.8) = 200. Notionals: 0.3*1000 = 300 (qty 3 @ 100),
    # 0.5*1000 = 500 (qty 2.5 @ 200).
    result = solve_shared_cash(
        (_asset(A, 0.0, 0.3, price=100.0), _asset(B, 0.0, 0.5, price=200.0)),
        base_cash=1000.0,
        params=_ZERO,
    )
    assert result.equity_post == pytest.approx(1000.0, abs=1e-9)
    assert result.residual_cash == pytest.approx(200.0, abs=1e-9)
    assert result.residual_cash >= -1e-6  # cash-safe
    by_symbol = {trade.instrument.symbol: trade for trade in result.trades}
    assert by_symbol["A-USD"].base_notional == pytest.approx(300.0, abs=1e-9)
    assert by_symbol["A-USD"].local_quantity == pytest.approx(3.0, abs=1e-9)
    assert by_symbol["B-USD"].base_notional == pytest.approx(500.0, abs=1e-9)
    assert by_symbol["B-USD"].local_quantity == pytest.approx(2.5, abs=1e-9)


# --------------------------------------------------------------------------- #
# 24. num_fills counts one buy per asset opened, then holds.
# --------------------------------------------------------------------------- #
def test_metrics_num_fills_counts_opening_buys() -> None:
    panel = build_market_panel({A: _flat_bars(100.0), B: _flat_bars(100.0)})
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, _membership([A, B]), _FX, _THREE_EVENTS, calendars=_CAL
    )
    metrics = compute_portfolio_metrics(result, periods_per_year=_PPY)
    assert metrics.num_fills == 2  # two opening buys; every later event is a pure hold
    assert metrics.average_held_assets == pytest.approx(2.0, abs=1e-12)


# --------------------------------------------------------------------------- #
# 25. Single-asset compatibility_v1 through the engine: terminal 1000/1.0015.
# --------------------------------------------------------------------------- #
def test_single_asset_compat_engine_terminal_equity() -> None:
    # Full allocation of 1000 under compatibility_v1 (rate 0.0015) on a flat-100 asset marks back
    # to its post-cost equity: terminal = 1000 / 1.0015 = 998.5022466300549, cost = 1.4977533699451.
    panel = build_market_panel({S: _flat_bars(100.0, periods=3)})
    result = run_portfolio_simulation(
        _protocol("equal_weight", cost=_COMPAT),
        panel,
        _membership([S]),
        _FX,
        _ONE_EVENT,
        calendars=_CAL,
    )
    assert result.terminal_equity == pytest.approx(998.5022466300549, abs=1e-9)
    assert result.events[0].total_cost == pytest.approx(1.4977533699451, abs=1e-9)


# --------------------------------------------------------------------------- #
# 26. trade_cost FX-conversion charge applies only when flagged.
# --------------------------------------------------------------------------- #
def test_trade_cost_fx_conversion_applies_when_flagged() -> None:
    # fee 0.001 + fx_conversion 0.002. On notional 1000: fee = 1.0 always; fx_conversion = 2.0 only
    # when apply_fx_conversion is set. So total is 3.0 with conversion and 1.0 without.
    params = CostParameters(scenario="fxconv", fee_rate=0.001, fx_conversion_rate=0.002)
    converted = trade_cost(params, 1000.0, apply_fx_conversion=True, currency="USD")
    assert converted.fx_conversion == pytest.approx(2.0, abs=1e-12)  # 0.002 * 1000
    assert converted.total == pytest.approx(3.0, abs=1e-12)  # 1.0 + 2.0
    domestic = trade_cost(params, 1000.0, apply_fx_conversion=False, currency="USD")
    assert domestic.fx_conversion == pytest.approx(0.0, abs=1e-12)
    assert domestic.total == pytest.approx(1.0, abs=1e-12)  # fee only
