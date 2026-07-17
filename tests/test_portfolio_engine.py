"""The causal multi-asset engine: conservation, cash-safety, determinism, and modeled cost."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.corporate_actions import CorporateAction, CorporateActionSet
from eth_research.portfolio.costs import CostParameters
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.panel import MarketPanel, build_market_panel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.valuation import StalenessPolicy


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _inst(symbol: str, base: str) -> InstrumentId:
    return InstrumentId(
        asset_class="crypto_spot",
        base_asset=base,
        quote_currency="USD",
        venue="synthetic",
        symbol=symbol,
        instrument_type="spot",
        price_unit="USD",
        quantity_unit=base,
        calendar_id="continuous_24_7",
    )


A = _inst("A-USD", "AAA")
B = _inst("B-USD", "BBB")
S = _inst("S-USD", "SSS")

_ZERO = CostParameters(scenario="zero")
_COMPAT = CostParameters.compatibility_v1()
_STALE = StalenessPolicy(max_staleness_seconds=1_000_000.0)
_FX = FxEvidence(observations=())
_CAL = {"continuous_24_7": TradingCalendar("continuous_24_7", "continuous_24_7", (), "test")}
_SCHEDULE = RebalanceSchedule(
    timestamps=(_ts("2026-07-14T01:00:00"), _ts("2026-07-14T02:00:00"), _ts("2026-07-14T03:00:00"))
)


def _flat_bars(price: float, periods: int = 5) -> pd.DataFrame:
    open_times = pd.date_range(start="2026-07-14T00:00:00", periods=periods, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": open_times,
            "close_time": open_times + pd.Timedelta(hours=1),
            "open": [price] * periods,
            "high": [price] * periods,
            "low": [price] * periods,
            "close": [price] * periods,
            "volume": [1000.0] * periods,
        }
    )


def _moving_bars(opens: Sequence[float], closes: Sequence[float]) -> pd.DataFrame:
    open_times = pd.date_range(start="2026-07-14T00:00:00", periods=len(opens), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": open_times,
            "close_time": open_times + pd.Timedelta(hours=1),
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


def _two_asset_panel() -> MarketPanel:
    return build_market_panel({A: _flat_bars(100.0), B: _flat_bars(100.0)})


def _protocol(policy: str, cost: CostParameters = _ZERO) -> PortfolioProtocol:
    return PortfolioProtocol(
        base_currency="USD",
        initial_cash=1000.0,
        policy=policy,  # type: ignore[arg-type]
        cost_scenario=cost,
        staleness=_STALE,
    )


def test_equal_weight_conserves_equity_under_zero_cost() -> None:
    result = run_portfolio_simulation(
        _protocol("equal_weight"),
        _two_asset_panel(),
        _membership([A, B]),
        _FX,
        _SCHEDULE,
        calendars=_CAL,
    )
    assert result.initial_equity == pytest.approx(1000.0)
    assert result.terminal_equity == pytest.approx(1000.0)
    for event in result.events:
        assert event.equity == pytest.approx(1000.0)
    # first event opens two positions; later events are pure holds
    assert result.all_fills == 2
    assert result.events[-1].positions_count == 2


def test_engine_is_cash_safe() -> None:
    result = run_portfolio_simulation(
        _protocol("equal_weight"),
        _two_asset_panel(),
        _membership([A, B]),
        _FX,
        _SCHEDULE,
        calendars=_CAL,
    )
    for event in result.events:
        assert event.cash >= -1e-6


def test_engine_is_deterministic() -> None:
    args = (
        _protocol("equal_weight"),
        _two_asset_panel(),
        _membership([A, B]),
        _FX,
        _SCHEDULE,
    )
    first = run_portfolio_simulation(*args, calendars=_CAL)
    second = run_portfolio_simulation(*args, calendars=_CAL)
    assert first.result_fingerprint == second.result_fingerprint
    assert first.canonical() == second.canonical()


def test_all_cash_policy_holds_everything_in_cash() -> None:
    result = run_portfolio_simulation(
        _protocol("cash"),
        _two_asset_panel(),
        _membership([A, B]),
        _FX,
        _SCHEDULE,
        calendars=_CAL,
    )
    assert result.all_fills == 0
    assert result.terminal_equity == pytest.approx(1000.0)
    for event in result.events:
        assert event.positions_count == 0
        assert event.cash == pytest.approx(1000.0)


def test_single_asset_full_allocation_loses_exactly_the_modeled_cost() -> None:
    panel = build_market_panel({S: _flat_bars(100.0, periods=3)})
    schedule = RebalanceSchedule(timestamps=(_ts("2026-07-14T01:00:00"),))
    result = run_portfolio_simulation(
        _protocol("equal_weight", cost=_COMPAT),
        panel,
        _membership([S]),
        _FX,
        schedule,
        calendars=_CAL,
    )
    expected_equity = 1000.0 / 1.0015  # E_post = E_pre / (1 + total cost rate)
    assert result.terminal_equity == pytest.approx(expected_equity, rel=1e-9)
    assert result.events[0].total_cost == pytest.approx(1000.0 - expected_equity, rel=1e-6)
    # the whole equity change is the paid cost
    assert result.events[0].attribution.equity_change == pytest.approx(expected_equity - 1000.0)


def test_marks_at_the_bar_it_trades_into_reproduces_accepted_convention() -> None:
    # A single fully-allocated asset on a *moving* price pins the marking convention (flat bars
    # cannot). 1000 buys 10 units at open[0]=100 under zero cost; the engine must then mark each
    # step at the close of the bar it trades into (close[t]), exactly as the accepted single-asset
    # engine marks bar t at close[t] — giving 10*110, 10*121, 10*133.
    panel = build_market_panel({S: _moving_bars([100.0, 110.0, 121.0], [110.0, 121.0, 133.0])})
    schedule = RebalanceSchedule(
        timestamps=(
            _ts("2026-07-14T00:00:00"),
            _ts("2026-07-14T01:00:00"),
            _ts("2026-07-14T02:00:00"),
        )
    )
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, _membership([S]), _FX, schedule, calendars=_CAL
    )
    assert [event.equity for event in result.events] == pytest.approx([1100.0, 1210.0, 1330.0])
    assert result.terminal_equity == pytest.approx(1330.0)
    assert result.all_fills == 1  # bought once at the first event, then a pure hold


def test_held_through_step_has_zero_attribution_residual() -> None:
    # From the second event on, the single asset is a pure hold: its base-currency equity change
    # must be fully explained by the local-price term (FX is identity), leaving ~0 residual.
    panel = build_market_panel({S: _moving_bars([100.0, 110.0, 121.0], [110.0, 121.0, 133.0])})
    schedule = RebalanceSchedule(
        timestamps=(
            _ts("2026-07-14T00:00:00"),
            _ts("2026-07-14T01:00:00"),
            _ts("2026-07-14T02:00:00"),
        )
    )
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, _membership([S]), _FX, schedule, calendars=_CAL
    )
    hold = result.events[1].attribution  # 10 units, close 110 -> 121
    assert hold.local_price_pnl == pytest.approx(110.0)  # 10 * (121 - 110)
    assert hold.fx_translation_pnl == pytest.approx(0.0)
    assert abs(hold.residual) < 1e-9


def _split(instrument: InstrumentId, effective: str) -> CorporateAction:
    return CorporateAction(
        instrument=instrument,
        action_id="split-1",
        action_type="split",
        knowledge_time=_ts("2026-07-14T00:00:00"),
        effective_time=_ts(effective),
        payment_time=None,
        ratio=2.0,
        cash_amount=None,
        currency=None,
        source="test",
    )


def _dividend(instrument: InstrumentId, payment: str) -> CorporateAction:
    return CorporateAction(
        instrument=instrument,
        action_id="div-1",
        action_type="cash_dividend",
        knowledge_time=_ts("2026-07-14T00:00:00"),
        effective_time=_ts(payment),
        payment_time=_ts(payment),
        ratio=None,
        cash_amount=0.5,
        currency="USD",
        source="test",
    )


def test_engine_refuses_a_split_inside_the_run_window() -> None:
    # A 2:1 split effective at 02:00 falls inside the schedule window [01:00, 03:00]: the engine
    # does not apply corporate actions and must refuse rather than silently misstate quantities.
    actions = CorporateActionSet(actions=(_split(A, "2026-07-14T02:00:00"),))
    with pytest.raises(CanonicalError, match="does not apply corporate actions"):
        run_portfolio_simulation(
            _protocol("equal_weight"),
            _two_asset_panel(),
            _membership([A, B]),
            _FX,
            _SCHEDULE,
            calendars=_CAL,
            corporate_actions=actions,
        )


def test_engine_refuses_a_cash_payment_inside_the_run_window() -> None:
    actions = CorporateActionSet(actions=(_dividend(A, "2026-07-14T02:00:00"),))
    with pytest.raises(CanonicalError, match="does not apply corporate actions"):
        run_portfolio_simulation(
            _protocol("equal_weight"),
            _two_asset_panel(),
            _membership([A, B]),
            _FX,
            _SCHEDULE,
            calendars=_CAL,
            corporate_actions=actions,
        )


def test_engine_runs_when_actions_fall_outside_the_run_window() -> None:
    # A split effective at 09:00 is after the last event (03:00): outside the window, so accepted.
    actions = CorporateActionSet(actions=(_split(A, "2026-07-14T09:00:00"),))
    result = run_portfolio_simulation(
        _protocol("equal_weight"),
        _two_asset_panel(),
        _membership([A, B]),
        _FX,
        _SCHEDULE,
        calendars=_CAL,
        corporate_actions=actions,
    )
    assert result.terminal_equity == pytest.approx(1000.0)


def test_result_carries_evidence_fingerprints() -> None:
    panel = _two_asset_panel()
    membership = _membership([A, B])
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, membership, _FX, _SCHEDULE, calendars=_CAL
    )
    assert result.panel_fingerprint == panel.fingerprint
    assert result.membership_fingerprint == membership.fingerprint
    assert result.schedule_fingerprint == _SCHEDULE.fingerprint
    assert len(result.result_fingerprint) == 64
