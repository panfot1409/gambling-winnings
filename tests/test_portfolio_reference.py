"""The synthetic reference universe: determinism, composition, and a runnable reference run.

synthetic test fixture — not real market data.
"""

from __future__ import annotations

import pandas as pd

from eth_research.portfolio.corporate_actions import CorporateAction
from eth_research.portfolio.costs import CostParameters, trade_cost
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.reference import (
    build_reference_universe,
    reference_protocol,
)

_LAST_RUN_EVENT = pd.Timestamp("2026-07-14T22:00:00", tz="UTC")


def _application_time(action: CorporateAction) -> pd.Timestamp:
    """The time an action would apply: a ratio event's effective_time, else its payment_time."""
    if action.action_type in ("split", "reverse_split"):
        return action.effective_time
    payment = action.payment_time
    assert payment is not None  # cash actions always carry a payment_time
    return payment


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #
def test_build_reference_universe_is_deterministic() -> None:
    first = build_reference_universe()
    second = build_reference_universe()
    assert first.universe_spec.fingerprint == second.universe_spec.fingerprint
    assert first.panel.fingerprint == second.panel.fingerprint
    assert first.membership.fingerprint == second.membership.fingerprint
    assert first.fx.fingerprint == second.fx.fingerprint
    assert first.corporate_actions.fingerprint == second.corporate_actions.fingerprint
    # the whole universe identity is a stable 64-hex domain hash
    assert len(first.universe_spec.fingerprint) == 64


# --------------------------------------------------------------------------- #
# composition: instruments, currencies, calendars, membership, corporate actions
# --------------------------------------------------------------------------- #
def test_universe_spans_three_instruments_two_currencies_two_calendars() -> None:
    universe = build_reference_universe()
    instruments = universe.universe_spec.instruments
    assert len(instruments) == 3
    assert {inst.asset_class for inst in instruments} == {"crypto_spot", "cash_equity"}
    assert len({inst.quote_currency for inst in instruments}) >= 2  # USD and EUR
    assert len({inst.calendar_id for inst in instruments}) >= 2  # continuous + weekday
    assert len(universe.calendars) >= 2
    # base currency is USD and the only conversion the universe needs is EUR -> USD
    assert universe.universe_spec.base_currency == "USD"
    assert universe.universe_spec.required_fx_pairs == (("EUR", "USD"),)


def test_early_close_session_is_present() -> None:
    universe = build_reference_universe()
    equity_calendar = universe.calendars["xsyn_equity"]
    assert equity_calendar.kind == "session_list"
    early = [session for session in equity_calendar.sessions if session.early_close]
    assert len(early) == 1  # exactly one shorter, early-close day
    early_session = early[0]
    # the early close closes strictly before its date's normal 21:00 UTC close
    normal_close = pd.Timestamp(f"{early_session.date}T21:00:00", tz="UTC")
    assert early_session.close < normal_close


def test_membership_carries_a_late_listing_and_a_removal() -> None:
    universe = build_reference_universe()
    schedule = universe.run_schedule.events()
    instruments = universe.universe_spec.instruments
    eur_equity = next(inst for inst in instruments if inst.quote_currency == "EUR")
    usd_equity = next(inst for inst in instruments if inst.symbol == "ACME-USD")

    # late listing: the EUR equity is inactive at the first rebalance and active at the second
    assert universe.membership.active_at(eur_equity, schedule[0]) is False
    assert universe.membership.active_at(eur_equity, schedule[1]) is True

    # constituent removal: the USD equity's single membership window carries an effective_end
    usd_intervals = [
        interval
        for interval in universe.membership.intervals
        if interval.instrument.instrument_id == usd_equity.instrument_id
    ]
    assert len(usd_intervals) == 1
    assert usd_intervals[0].effective_end is not None


def test_three_corporate_actions_all_apply_after_the_run_window() -> None:
    universe = build_reference_universe()
    actions = universe.corporate_actions.actions
    assert len(actions) == 3
    assert {action.action_type for action in actions} == {
        "split",
        "cash_dividend",
        "delisting_cash_out",
    }
    last_event = universe.run_schedule.events()[-1]
    assert last_event == _LAST_RUN_EVENT
    # every application time is strictly after the last runnable rebalance event
    for action in actions:
        assert _application_time(action) > last_event


# --------------------------------------------------------------------------- #
# the runnable reference run
# --------------------------------------------------------------------------- #
def test_reference_run_executes_deterministically_with_corporate_actions() -> None:
    universe = build_reference_universe()
    protocol = reference_protocol()
    result = run_portfolio_simulation(
        protocol,
        universe.panel,
        universe.membership,
        universe.fx,
        universe.run_schedule,
        calendars=universe.calendars,
        corporate_actions=universe.corporate_actions,
    )
    again = run_portfolio_simulation(
        protocol,
        universe.panel,
        universe.membership,
        universe.fx,
        universe.run_schedule,
        calendars=universe.calendars,
        corporate_actions=universe.corporate_actions,
    )
    # a run passing the corporate-action set is accepted (no in-window action) and reproducible
    assert result.result_fingerprint == again.result_fingerprint
    assert result.canonical() == again.canonical()
    assert len(result.events) == 3
    assert result.terminal_equity > 0.0
    # the non-zero cost scenario means the cost path is exercised at the trading events
    assert any(event.total_cost > 0.0 for event in result.events)


def test_reference_run_marks_a_held_equity_while_its_market_is_closed() -> None:
    universe = build_reference_universe()
    result = run_portfolio_simulation(
        reference_protocol(),
        universe.panel,
        universe.membership,
        universe.fx,
        universe.run_schedule,
        calendars=universe.calendars,
        corporate_actions=universe.corporate_actions,
    )
    equities = [
        inst for inst in universe.universe_spec.instruments if inst.asset_class == "cash_equity"
    ]
    equity_ids = {inst.instrument_id for inst in equities}
    equity_calendar = universe.calendars[equities[0].calendar_id]

    # find a rebalance where a held equity is carried and marked at a stale (past) close
    closed_market_events = [
        event
        for event in result.events
        if event.stale_mark_count >= 1
        and equity_ids & {holding.instrument_id for holding in event.holdings}
    ]
    assert closed_market_events, "expected a closed-market valuation event"
    event = closed_market_events[0]
    # the equity venue really is shut at that timestamp, yet the equity is still held and valued
    assert equity_calendar.is_open(event.tau) is False
    assert event.max_staleness_seconds > 0.0
    held_equities = [holding for holding in event.holdings if holding.instrument_id in equity_ids]
    assert held_equities
    assert all(holding.base_value > 0.0 for holding in held_equities)


# --------------------------------------------------------------------------- #
# lagged-liquidity impact term
# --------------------------------------------------------------------------- #
def test_realistic_volume_exercises_the_lagged_liquidity_impact_term() -> None:
    universe = build_reference_universe()
    crypto = next(
        inst for inst in universe.universe_spec.instruments if inst.asset_class == "crypto_spot"
    )
    frame = universe.panel.frame(crypto)
    # realistic, finite per-bar volume (never the engine's no-prior-bar default)
    assert bool((frame["volume"] > 0.0).all())
    lagged_dollar_volume = float(frame["volume"].iloc[0]) * float(frame["close"].iloc[0])
    assert lagged_dollar_volume > 0.0

    # under a non-zero liquidity-impact cost scenario, a trade against that lagged volume incurs a
    # strictly positive impact charge; the compatibility scenario used by the run has none.
    impact_scenario = CostParameters(
        scenario="reference_impact",
        fee_rate=0.001,
        base_slippage=0.0005,
        impact_coefficient=0.1,
        impact_cap=0.02,
    )
    notional = 0.25 * lagged_dollar_volume
    participation = notional / lagged_dollar_volume
    impacted = trade_cost(impact_scenario, notional, participation=participation, currency="USD")
    assert impacted.impact > 0.0
    compat = trade_cost(
        CostParameters.compatibility_v1(), notional, participation=participation, currency="USD"
    )
    assert compat.impact == 0.0
