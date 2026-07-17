"""The causal, deterministic multi-asset rebalance engine.

:func:`run_portfolio_simulation` executes the canonical event timeline (see
``docs/M4B_EVENT_TIMELINE.md``) once per rebalance event ``tau``: it resolves the membership-active
universe known by ``tau``, establishes the tradable set (active instruments with a bar opening
exactly at ``tau`` and a causal FX rate to base), derives the reference target over that set, solves
one shared-cash post-cost equity for every asset simultaneously, turns the resolved trades into
cash-safe fills, marks every holding at the close of the bar it trades into, and records an additive
attribution of the equity change. Every *decision* read is causal — only facts knowable at or before
``tau`` enter the target, the solve, or the fills — and every artifact is canonical-JSON-safe with a
stable fingerprint, so a re-run over identical inputs reproduces byte-identical results.

**Marking convention.** A rebalance step at ``tau`` executes at the bar opening at ``tau`` and then
marks that holding at *its own bar's close* (``close_time`` = the end of the step's bar), exactly as
the accepted single-asset engine marks bar ``t`` at ``close[t]``. This end-of-step mark is a
*report*, computed after all fills and consumed only at the next event (by which time that close is
strictly in the past), so it is never a decision input and introduces no look-ahead. A held-through
instrument with no bar opening at ``tau`` (a closed market, or one that has left the universe) is
instead marked at its latest completed close at or before ``tau`` — carried, not force-liquidated.

**Stated limitation — corporate actions are refused, not mis-stated.** Timeline steps 3 and 4
(split / reverse-split quantity adjustments, and dividend / delisting cash payments) are
deliberately deferred: applying them causally — in particular attributing a split's value change
exactly, when raw prices halve while quantity doubles — is a later milestone. Rather than
*silently* misstate quantities and cash, this engine **fails closed**: pass the run's
:class:`CorporateActionSet` and, if any action's application time (a split/reverse's
``effective_time``, or a cash action's ``payment_time``) falls within the schedule's event window
for a panel instrument, the run is refused with a clear error. A run whose window carries no such
action proceeds normally. Relatedly, an instrument held but gone from the active membership
universe (no bar opening at ``tau``) is *carried and marked*, not force-liquidated, at that event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio._time import iso_utc
from eth_research.portfolio.accounting import Fill, PortfolioState
from eth_research.portfolio.attribution import StepAttribution, attribute_step
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.corporate_actions import CorporateActionSet
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.information import AsOfView
from eth_research.portfolio.membership import MembershipSchedule
from eth_research.portfolio.panel import MarketPanel
from eth_research.portfolio.protocol import PortfolioProtocol, build_target
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.solver import AssetSolveInput, solve_shared_cash
from eth_research.portfolio.targets import PortfolioTarget
from eth_research.portfolio.validation import domain_hash
from eth_research.portfolio.valuation import mark_instrument

__all__ = ["EventRecord", "HoldingValue", "PortfolioRunResult", "run_portfolio_simulation"]

# When an instrument has no completed prior bar at ``tau``, its lagged (participation) dollar volume
# is unknown. A large finite proxy makes the participation rate ~0, so the liquidity-impact cost
# term is ~0 for that first trade rather than undefined — a deliberately conservative default.
_DEFAULT_LAGGED_DOLLAR_VOLUME = 1e15


@dataclass(frozen=True)
class _ExecRef:
    """The execution references (open price and FX) an asset's fill is priced at."""

    open_price: float
    fx_rate: float


@dataclass(frozen=True)
class HoldingValue:
    """One instrument's post-event holding: local quantity and end-of-step base value."""

    instrument_id: str
    quote_currency: str
    quantity: float
    base_value: float

    def canonical(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "quote_currency": self.quote_currency,
            "quantity": self.quantity,
            "base_value": self.base_value,
        }


@dataclass(frozen=True)
class EventRecord:
    """The recorded outcome of one rebalance event: equity, cash, holdings, and attribution."""

    tau: pd.Timestamp
    equity: float
    cash: float
    positions_count: int
    total_cost: float
    fills: tuple[Fill, ...]
    attribution: StepAttribution
    holdings: tuple[HoldingValue, ...]
    max_staleness_seconds: float
    stale_mark_count: int
    state_fingerprint: str

    def canonical(self) -> dict[str, Any]:
        """The canonical, JSON-safe event mapping (fills reduced to a count; holdings inlined)."""
        return {
            "tau": iso_utc(self.tau),
            "equity": self.equity,
            "cash": self.cash,
            "positions_count": self.positions_count,
            "total_cost": self.total_cost,
            "fills_count": len(self.fills),
            "attribution": self.attribution.canonical(),
            "holdings": [holding.canonical() for holding in self.holdings],
            "max_staleness_seconds": self.max_staleness_seconds,
            "stale_mark_count": self.stale_mark_count,
            "state_fingerprint": self.state_fingerprint,
        }


@dataclass(frozen=True)
class PortfolioRunResult:
    """The immutable, fingerprinted outcome of a whole simulation run."""

    protocol_fingerprint: str
    panel_fingerprint: str
    membership_fingerprint: str
    schedule_fingerprint: str
    base_currency: str
    initial_equity: float
    terminal_equity: float
    events: tuple[EventRecord, ...]
    all_fills: int
    final_state_fingerprint: str

    def canonical(self) -> dict[str, Any]:
        """The canonical, JSON-safe result mapping (events inlined in schedule order)."""
        return {
            "protocol_fingerprint": self.protocol_fingerprint,
            "panel_fingerprint": self.panel_fingerprint,
            "membership_fingerprint": self.membership_fingerprint,
            "schedule_fingerprint": self.schedule_fingerprint,
            "base_currency": self.base_currency,
            "initial_equity": self.initial_equity,
            "terminal_equity": self.terminal_equity,
            "all_fills": self.all_fills,
            "final_state_fingerprint": self.final_state_fingerprint,
            "events": [event.canonical() for event in self.events],
        }

    @property
    def result_fingerprint(self) -> str:
        """The domain-separated content hash over the canonical result (stable across runtimes)."""
        return domain_hash("portfolio_run_result", self.canonical())


def _has_causal_fx(view: AsOfView, quote: str, base: str) -> bool:
    """Whether a causal ``quote -> base`` rate exists at the view's ``tau``."""
    try:
        view.fx_rate(quote, base)
    except CanonicalError:
        return False
    return True


def _tradable_set(
    view: AsOfView,
    calendars: dict[str, TradingCalendar],
    base_currency: str,
) -> tuple[InstrumentId, ...]:
    """The active instruments tradable at ``tau``: open market, a bar at ``tau``, and causal FX."""
    tradable: list[InstrumentId] = []
    for instrument in view.active_universe:
        calendar = calendars.get(instrument.calendar_id)
        if calendar is None:
            raise CanonicalError(
                f"engine: no calendar provided for {instrument.calendar_id!r} "
                f"(instrument {instrument.symbol!r})"
            )
        if not calendar.is_open(view.tau):
            continue
        if view.current_open(instrument) is None:
            continue
        if not _has_causal_fx(view, instrument.quote_currency, base_currency):
            continue
        tradable.append(instrument)
    return tuple(tradable)


def _lagged_dollar_volume(view: AsOfView, instrument: InstrumentId) -> float:
    """The prior bar's ``volume * close`` (quote), or a large default when there is no prior bar."""
    prior = view.prior_bars(instrument)
    if len(prior) == 0:
        return _DEFAULT_LAGGED_DOLLAR_VOLUME
    last = prior.iloc[-1]
    dollar_volume = float(last["volume"]) * float(last["close"])
    if dollar_volume <= 0.0:
        return _DEFAULT_LAGGED_DOLLAR_VOLUME
    return dollar_volume


def _build_solve_inputs(
    view: AsOfView,
    state: PortfolioState,
    tradable: tuple[InstrumentId, ...],
    target: PortfolioTarget,
    base_currency: str,
) -> tuple[list[AssetSolveInput], dict[str, _ExecRef]]:
    """Build one :class:`AssetSolveInput` per tradable asset, valuing holdings at the open."""
    inputs: list[AssetSolveInput] = []
    refs: dict[str, _ExecRef] = {}
    for instrument in tradable:
        open_price = view.current_open(instrument)
        if open_price is None:  # defensive: tradable already guarantees a bar opens at tau
            continue
        fx_rate = view.fx_rate(instrument.quote_currency, base_currency)
        quantity = state.quantity_of(instrument)
        inputs.append(
            AssetSolveInput(
                instrument=instrument,
                base_value=quantity * open_price * fx_rate,
                target_weight=target.weight_for(instrument),
                fx_rate=fx_rate,
                local_price=open_price,
                lagged_dollar_volume=_lagged_dollar_volume(view, instrument),
                quote_currency=instrument.quote_currency,
                base_currency=base_currency,
            )
        )
        refs[instrument.instrument_id] = _ExecRef(open_price=open_price, fx_rate=fx_rate)
    return inputs, refs


def _apply_event_trades(
    state: PortfolioState,
    inputs: list[AssetSolveInput],
    refs: dict[str, _ExecRef],
    tau: pd.Timestamp,
    protocol: PortfolioProtocol,
) -> tuple[PortfolioState, list[Fill], float]:
    """Solve the shared-cash target and apply the resulting fills, returning the new state."""
    if not inputs:
        return state, [], 0.0
    # Absorb sub-tolerance float noise: the accounting state permits cash a hair below zero, but
    # the solver requires non-negative base cash. This shifts equity_pre by at most the cash tol.
    base_cash = state.base_cash if state.base_cash > 0.0 else 0.0
    equity_pre = base_cash + sum(item.base_value for item in inputs)
    if not equity_pre > 0.0:
        return state, [], 0.0
    result = solve_shared_cash(
        tuple(inputs),
        base_cash=base_cash,
        params=protocol.cost_scenario,
        tolerances=protocol.tolerances,
    )
    fills: list[Fill] = []
    for trade in result.trades:
        if trade.side == "hold":
            continue
        ref = refs[trade.instrument.instrument_id]
        fill = Fill(
            event_id=f"{tau.isoformat()}:{trade.instrument.instrument_id[:8]}",
            event_time=tau,
            instrument=trade.instrument,
            side=trade.side,
            local_quantity=trade.local_quantity,
            fill_price=ref.open_price,
            fx_rate=ref.fx_rate,
            base_notional=trade.base_notional,
            cost=trade.cost,
        )
        state = state.apply_fill(fill)
        fills.append(fill)
    return state, fills, result.total_cost


def _bar_close_time_at(frame: pd.DataFrame, tau: pd.Timestamp) -> pd.Timestamp | None:
    """The ``close_time`` of the bar whose ``open_time == tau``, or ``None`` if none opens then."""
    at_tau = frame[frame["open_time"] == tau]
    if len(at_tau) == 0:
        return None
    return pd.Timestamp(at_tau["close_time"].iloc[0])


def _mark_holdings(
    panel: MarketPanel,
    fx: FxEvidence,
    protocol: PortfolioProtocol,
    instruments: dict[str, InstrumentId],
    tau: pd.Timestamp,
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    """Mark every instrument in ``instruments``: base value per unit, local close, FX, staleness.

    An instrument trading this step (a bar opens at ``tau``) is marked at *that bar's close* — the
    end-of-step valuation the accepted engine uses for bar ``t`` — so a single-asset run reproduces
    it exactly. A held-through instrument with no bar opening at ``tau`` is marked at its latest
    completed close at or before ``tau`` (carried, never force-liquidated). The mark is a report
    taken after all fills; it is never read by any decision at this event.
    """
    marks: dict[str, float] = {}
    local_close: dict[str, float] = {}
    fx_rates: dict[str, float] = {}
    staleness: dict[str, float] = {}
    for instrument_id, instrument in instruments.items():
        frame = panel.frame(instrument)
        bar_close_time = _bar_close_time_at(frame, tau)
        mark_time = bar_close_time if bar_close_time is not None else tau
        mark = mark_instrument(
            frame,
            fx,
            instrument,
            protocol.base_currency,
            mark_time,
            staleness=protocol.staleness,
        )
        marks[instrument_id] = mark.base_value_per_unit
        local_close[instrument_id] = mark.local_close
        fx_rates[instrument_id] = mark.fx_rate
        staleness[instrument_id] = mark.staleness_seconds
    return marks, local_close, fx_rates, staleness


def _refuse_in_window_corporate_actions(
    corporate_actions: CorporateActionSet | None,
    panel: MarketPanel,
    schedule: RebalanceSchedule,
) -> None:
    """Fail closed on any corporate action that would apply within the run window.

    This engine does not yet *apply* corporate actions (see the module docstring). Instead of
    silently misstating quantities and cash, it refuses to run when ``corporate_actions`` holds an
    action whose application time — a split/reverse's ``effective_time`` or a cash action's
    ``payment_time`` — falls within ``[first_event, last_event]`` for an instrument in the panel. A
    set whose actions all fall outside the run window (or concern instruments not in the panel) is
    accepted, and ``None`` is a no-op.
    """
    if corporate_actions is None or not corporate_actions.actions:
        return
    panel_ids = {instrument.instrument_id for instrument in panel.instruments}
    events = schedule.events()
    first, last = events[0], events[-1]
    for action in corporate_actions.actions:
        if action.instrument.instrument_id not in panel_ids:
            continue
        application: pd.Timestamp | None
        if action.action_type in ("split", "reverse_split"):
            application = action.effective_time
        else:
            application = action.payment_time
        if application is None:
            continue
        if first <= application <= last:
            raise CanonicalError(
                f"engine: corporate action {action.action_id!r} "
                f"({action.action_type}) applies at {iso_utc(application)}, within the "
                f"run window [{iso_utc(first)}, {iso_utc(last)}]. This engine does not "
                f"apply corporate actions; restrict the schedule to a window without "
                f"pending actions on panel instruments"
            )


def run_portfolio_simulation(
    protocol: PortfolioProtocol,
    panel: MarketPanel,
    membership: MembershipSchedule,
    fx: FxEvidence,
    schedule: RebalanceSchedule,
    *,
    calendars: dict[str, TradingCalendar],
    corporate_actions: CorporateActionSet | None = None,
) -> PortfolioRunResult:
    """Run the causal multi-asset rebalance over ``schedule`` and return a fingerprinted result.

    Corporate-action *application* (splits, dividends, delisting cash) is out of scope; when a
    ``corporate_actions`` set is supplied the engine fails closed on any action applying within the
    run window rather than silently misstating (see the module docstring). Raises
    :class:`CanonicalError` if a required calendar is missing, an in-window corporate action is
    present, or a holding cannot be causally marked (for example an over-stale mark) at some event.
    """
    if not isinstance(calendars, dict):
        raise CanonicalError(
            "engine: calendars must be a mapping of calendar_id to TradingCalendar"
        )
    for calendar_id, calendar in calendars.items():
        if not isinstance(calendar, TradingCalendar):
            raise CanonicalError(f"engine: calendars[{calendar_id!r}] must be a TradingCalendar")
    _refuse_in_window_corporate_actions(corporate_actions, panel, schedule)

    tolerances = protocol.tolerances
    state = PortfolioState.opening(
        protocol.base_currency, protocol.initial_cash, tolerances=tolerances
    )
    initial_equity = protocol.initial_cash

    prev_marks: dict[str, float] = {}
    prev_local_close: dict[str, float] = {}
    prev_fx: dict[str, float] = {}
    prev_equity = initial_equity

    events: list[EventRecord] = []
    all_fills = 0

    for tau in schedule.events():
        view = AsOfView.at(panel, membership, fx, tau)
        held_pre = {
            position.instrument.instrument_id: position.quantity for position in state.positions
        }
        held_pre_instruments = {
            position.instrument.instrument_id: position.instrument for position in state.positions
        }

        tradable = _tradable_set(view, calendars, protocol.base_currency)
        target = build_target(protocol, tradable)
        target.require_subset_of(tradable)

        inputs, refs = _build_solve_inputs(view, state, tradable, target, protocol.base_currency)
        state, event_fills, total_cost = _apply_event_trades(state, inputs, refs, tau, protocol)
        all_fills += len(event_fills)

        to_mark = dict(held_pre_instruments)
        for position in state.positions:
            to_mark[position.instrument.instrument_id] = position.instrument
        marks, local_close, fx_rates, staleness = _mark_holdings(panel, fx, protocol, to_mark, tau)
        equity = state.equity(marks)
        currency_of = {
            instrument_id: instrument.quote_currency
            for instrument_id, instrument in to_mark.items()
        }

        attribution = attribute_step(
            equity_before=prev_equity,
            equity_after=equity,
            held_quantities=held_pre,
            marks_before=prev_marks,
            marks_after=marks,
            local_close_before=prev_local_close,
            local_close_after=local_close,
            fx_before=prev_fx,
            fx_after=fx_rates,
            total_cost=total_cost,
            currency_of=currency_of,
        )

        holdings = tuple(
            HoldingValue(
                instrument_id=position.instrument.instrument_id,
                quote_currency=position.instrument.quote_currency,
                quantity=position.quantity,
                base_value=position.quantity * marks[position.instrument.instrument_id],
            )
            for position in state.positions
        )
        held_staleness = [staleness[p.instrument.instrument_id] for p in state.positions]
        max_staleness = max(held_staleness) if held_staleness else 0.0
        stale_count = sum(1 for value in held_staleness if value > 0.0)

        events.append(
            EventRecord(
                tau=tau,
                equity=equity,
                cash=state.base_cash,
                positions_count=len(state.positions),
                total_cost=total_cost,
                fills=tuple(event_fills),
                attribution=attribution,
                holdings=holdings,
                max_staleness_seconds=max_staleness,
                stale_mark_count=stale_count,
                state_fingerprint=state.fingerprint,
            )
        )
        prev_marks, prev_local_close, prev_fx = marks, local_close, fx_rates
        prev_equity = equity

    terminal_equity = events[-1].equity if events else initial_equity
    return PortfolioRunResult(
        protocol_fingerprint=protocol.fingerprint,
        panel_fingerprint=panel.fingerprint,
        membership_fingerprint=membership.fingerprint,
        schedule_fingerprint=schedule.fingerprint,
        base_currency=protocol.base_currency,
        initial_equity=initial_equity,
        terminal_equity=terminal_equity,
        events=tuple(events),
        all_fills=all_fills,
        final_state_fingerprint=state.fingerprint,
    )
