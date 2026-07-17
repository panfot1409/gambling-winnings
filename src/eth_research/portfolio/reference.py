"""Milestone 4B §30 — a deterministic, seeded, code-generated synthetic reference universe.

synthetic test fixture — not real market data.

This module assembles ONE small, fully offline research universe from the accepted M4B evidence
models and returns it as a frozen :class:`ReferenceUniverse` bundle. Nothing here reads a wall
clock, a network, or a random source: every timestamp is a fixed UTC literal and every price,
volume, and FX rate is a fixed seeded constant, so :func:`build_reference_universe` is byte-for-byte
reproducible and its component fingerprints are stable across calls and runtimes. The bar prices are
raw / unadjusted (the convention :mod:`eth_research.portfolio.corporate_actions` documents), so the
corporate actions are carried as evidence only and never applied.

The universe deliberately exercises the full M4B surface in miniature:

1. a 24/7 USD-quoted crypto spot instrument on a continuous calendar;
2. a USD-quoted cash equity on an explicit weekday session calendar;
3. a EUR-quoted cash equity on the same weekday session calendar;
4. EUR/USD FX evidence covering the whole run window causally;
5. explicit weekday sessions including one early-close day;
6. a late listing (an interval effective after the universe start) and a constituent removal
   (an interval that ends with an ``effective_end``);
7. corporate actions as evidence only — a 2:1 split, a cash dividend, and a delisting cash-out —
   whose application times all fall strictly after the last runnable rebalance event, so the run
   stays runnable while the universe fingerprint still binds them;
8. a closed-market valuation: at the last rebalance the equities' venue is shut while the crypto
   still trades, so the held equities are carried and marked at their last completed close (the
   staleness path, within the staleness bound); and
9. realistic per-bar volume so the cost model's lagged-liquidity impact term can be exercised.

:func:`reference_protocol` pairs the universe with an equal-weight, long-only, USD protocol under a
non-zero cost scenario, so a reference RUN through ``run_portfolio_simulation`` exercises the cost
path and reproduces byte-identical results.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from eth_research.portfolio.calendar import Session, TradingCalendar
from eth_research.portfolio.corporate_actions import CorporateAction, CorporateActionSet
from eth_research.portfolio.costs import CostParameters
from eth_research.portfolio.fx import FxEvidence, FxObservation
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.panel import MarketPanel, build_market_panel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.universe import UniverseSpec
from eth_research.portfolio.valuation import StalenessPolicy

__all__ = ["ReferenceUniverse", "build_reference_universe", "reference_protocol"]

_BASE_CURRENCY = "USD"
_INITIAL_CASH = 120_000.0
_BAR_INTERVAL_SECONDS = 3600
# 72 hours: generous enough to carry a held equity across its closed market at the last rebalance
# (a one-hour carry) without the staleness policy refusing the mark.
_MAX_STALENESS_SECONDS = 259_200.0

_CRYPTO_CALENDAR_ID = "continuous_24_7"
_EQUITY_CALENDAR_ID = "xsyn_equity"
_SOURCE = "synthetic"

# The universe opens on Monday 2026-07-13; the runnable rebalance events all fall on Tuesday
# 2026-07-14, strictly before every corporate-action application time (2026-07-15 onward).
_UNIVERSE_START = "2026-07-13T00:00:00"
_LAST_RUN_EVENT = "2026-07-14T22:00:00"


def _ts(text: str) -> pd.Timestamp:
    """A fixed tz-aware UTC timestamp literal (no wall-clock read)."""
    return pd.Timestamp(text, tz="UTC")


# --------------------------------------------------------------------------- #
# instruments
# --------------------------------------------------------------------------- #
def _crypto() -> InstrumentId:
    """The 24/7 USD-quoted crypto spot instrument (feature 1)."""
    return InstrumentId(
        asset_class="crypto_spot",
        base_asset="ETH",
        quote_currency="USD",
        venue=_SOURCE,
        symbol="ETH-USD",
        instrument_type="spot",
        price_unit="USD",
        quantity_unit="ETH",
        calendar_id=_CRYPTO_CALENDAR_ID,
    )


def _equity_usd() -> InstrumentId:
    """The USD-quoted cash equity on the weekday session calendar (feature 2)."""
    return InstrumentId(
        asset_class="cash_equity",
        base_asset="ACME",
        quote_currency="USD",
        venue=_SOURCE,
        symbol="ACME-USD",
        instrument_type="spot",
        price_unit="USD",
        quantity_unit="ACME",
        calendar_id=_EQUITY_CALENDAR_ID,
    )


def _equity_eur() -> InstrumentId:
    """The EUR-quoted cash equity on the weekday session calendar (feature 3)."""
    return InstrumentId(
        asset_class="cash_equity",
        base_asset="BLEU",
        quote_currency="EUR",
        venue=_SOURCE,
        symbol="BLEU-EUR",
        instrument_type="spot",
        price_unit="EUR",
        quantity_unit="BLEU",
        calendar_id=_EQUITY_CALENDAR_ID,
    )


# --------------------------------------------------------------------------- #
# calendars
# --------------------------------------------------------------------------- #
def _crypto_calendar() -> TradingCalendar:
    """The always-open continuous 24/7 calendar the crypto instrument follows."""
    return TradingCalendar(
        calendar_id=_CRYPTO_CALENDAR_ID,
        kind="continuous_24_7",
        sessions=(),
        source=_SOURCE,
    )


def _equity_calendar() -> TradingCalendar:
    """An explicit ``session_list`` weekday calendar with one early-close day (feature 5).

    synthetic test fixture — not real market data. Sessions run 13:00-21:00 UTC Monday through
    Friday of the universe's opening week; Thursday 2026-07-16 closes two hours early at 19:00 UTC.
    """
    normal_close_hour = 21
    early_close_hour = 19
    day_close: tuple[tuple[str, int], ...] = (
        ("2026-07-13", normal_close_hour),  # Monday
        ("2026-07-14", normal_close_hour),  # Tuesday — the runnable rebalance day
        ("2026-07-15", normal_close_hour),  # Wednesday
        ("2026-07-16", early_close_hour),  # Thursday — EARLY CLOSE (shorter session)
        ("2026-07-17", normal_close_hour),  # Friday
    )
    sessions: list[Session] = []
    for date_str, close_hour in day_close:
        midnight = _ts(f"{date_str}T00:00:00")
        sessions.append(
            Session(
                session_id=f"{_EQUITY_CALENDAR_ID}:{date_str}",
                date=date_str,
                open=midnight + pd.Timedelta(hours=13),
                close=midnight + pd.Timedelta(hours=close_hour),
                early_close=close_hour < normal_close_hour,
                source=_SOURCE,
            )
        )
    return TradingCalendar(
        calendar_id=_EQUITY_CALENDAR_ID,
        kind="session_list",
        sessions=tuple(sessions),
        source=_SOURCE,
    )


def _calendars() -> dict[str, TradingCalendar]:
    """The calendars the universe carries, keyed by ``calendar_id`` (>= 2 distinct calendars)."""
    return {
        _CRYPTO_CALENDAR_ID: _crypto_calendar(),
        _EQUITY_CALENDAR_ID: _equity_calendar(),
    }


# --------------------------------------------------------------------------- #
# bar frames (raw / unadjusted OHLCV)
# --------------------------------------------------------------------------- #
def _bar_frame(
    start: str, opens: Sequence[float], closes: Sequence[float], *, volume: float
) -> pd.DataFrame:
    """A canonical hourly OHLCV bar frame from fixed prices (raw / unadjusted).

    synthetic test fixture — not real market data. ``high``/``low`` bracket each bar's open/close by
    one price unit and every ``volume`` is the same fixed, finite figure, so the frame passes
    :func:`~eth_research.portfolio.bars.validate_bar_frame` and its fingerprint is deterministic.
    """
    open_times = pd.date_range(start=start, periods=len(opens), freq="h", tz="UTC")
    highs = [max(o, c) + 1.0 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) - 1.0 for o, c in zip(opens, closes, strict=True)]
    return pd.DataFrame(
        {
            "open_time": open_times,
            "close_time": open_times + pd.Timedelta(hours=1),
            "open": [float(o) for o in opens],
            "high": highs,
            "low": lows,
            "close": [float(c) for c in closes],
            "volume": [float(volume)] * len(opens),
        }
    )


def _crypto_bars() -> pd.DataFrame:
    """Hourly 24/7 crypto bars from 12:00 to 22:00 UTC on 2026-07-14 (11 bars)."""
    # synthetic test fixture — not real market data. A modest, realistic 40 ETH/bar volume feeds the
    # lagged-liquidity participation term (feature 9); prices drift gently around 2000 USD.
    opens = [2000.0 + 10.0 * index for index in range(11)]
    closes = [price + 5.0 for price in opens]
    return _bar_frame("2026-07-14T12:00:00", opens, closes, volume=40.0)


def _equity_usd_bars() -> pd.DataFrame:
    """Hourly USD-equity session bars from 13:00 to 20:00 UTC on 2026-07-14 (8 bars)."""
    # synthetic test fixture — not real market data.
    opens = [150.0 + 1.0 * index for index in range(8)]
    closes = [price + 0.5 for price in opens]
    return _bar_frame("2026-07-14T13:00:00", opens, closes, volume=2000.0)


def _equity_eur_bars() -> pd.DataFrame:
    """Hourly EUR-equity session bars from 13:00 to 20:00 UTC on 2026-07-14 (8 bars)."""
    # synthetic test fixture — not real market data.
    opens = [90.0 + 0.5 * index for index in range(8)]
    closes = [price + 0.3 for price in opens]
    return _bar_frame("2026-07-14T13:00:00", opens, closes, volume=2000.0)


def _panel() -> MarketPanel:
    """The validated, canonical bar panel over the three reference instruments."""
    return build_market_panel(
        {
            _crypto(): _crypto_bars(),
            _equity_usd(): _equity_usd_bars(),
            _equity_eur(): _equity_eur_bars(),
        }
    )


# --------------------------------------------------------------------------- #
# membership, FX, corporate actions, schedule
# --------------------------------------------------------------------------- #
def _membership() -> MembershipSchedule:
    """Membership with a late listing and a constituent removal (feature 6).

    The crypto is listed open-ended from the universe start. The USD equity's window ends with an
    ``effective_end`` after the run (a constituent removal). The EUR equity lists late — its
    ``effective_start`` (2026-07-14T13:30) is strictly after the universe start, so it is inactive
    at the first rebalance and joins at the second.
    """
    universe_start = _ts(_UNIVERSE_START)
    return MembershipSchedule(
        intervals=(
            MembershipInterval(
                instrument=_crypto(),
                effective_start=universe_start,
                effective_end=None,
                knowledge_time=universe_start,
                reason="listing",
                source=_SOURCE,
            ),
            MembershipInterval(
                instrument=_equity_usd(),
                effective_start=universe_start,
                effective_end=_ts("2026-07-17T21:00:00"),
                knowledge_time=universe_start,
                reason="constituent_removal",
                source=_SOURCE,
            ),
            MembershipInterval(
                instrument=_equity_eur(),
                effective_start=_ts("2026-07-14T13:30:00"),
                effective_end=None,
                knowledge_time=_ts("2026-07-14T12:00:00"),
                reason="listing",
                source=_SOURCE,
            ),
        )
    )


def _fx() -> FxEvidence:
    """EUR/USD FX evidence covering the run window causally (feature 4).

    Both observations precede every rebalance event, so a causal EUR->USD rate is always available
    for the EUR-quoted equity's marks and trades.
    """
    return FxEvidence(
        observations=(
            FxObservation("EUR", "USD", _ts("2026-07-13T00:00:00"), 1.08, _SOURCE),
            FxObservation("EUR", "USD", _ts("2026-07-14T12:00:00"), 1.09, _SOURCE),
        )
    )


def _corporate_actions() -> CorporateActionSet:
    """Split, cash dividend, and delisting cash-out — evidence only (feature 7).

    Every application time (the split's ``effective_time`` and the cash actions' ``payment_time``)
    falls strictly after the last runnable rebalance event (2026-07-14T22:00), so the engine's
    fail-closed check accepts the set and the run proceeds while the universe fingerprint binds it.
    """
    knowledge = _ts("2026-07-14T00:00:00")
    return CorporateActionSet(
        actions=(
            CorporateAction(
                instrument=_equity_usd(),
                action_id="acme-split-2for1",
                action_type="split",
                knowledge_time=knowledge,
                effective_time=_ts("2026-07-15T13:00:00"),
                payment_time=None,
                ratio=2.0,
                cash_amount=None,
                currency=None,
                source=_SOURCE,
            ),
            CorporateAction(
                instrument=_equity_usd(),
                action_id="acme-cash-dividend",
                action_type="cash_dividend",
                knowledge_time=knowledge,
                effective_time=_ts("2026-07-16T13:00:00"),
                payment_time=_ts("2026-07-16T13:00:00"),
                ratio=None,
                cash_amount=0.75,
                currency="USD",
                source=_SOURCE,
            ),
            CorporateAction(
                instrument=_equity_eur(),
                action_id="bleu-delist-cashout",
                action_type="delisting_cash_out",
                knowledge_time=knowledge,
                effective_time=_ts("2026-07-17T13:00:00"),
                payment_time=_ts("2026-07-17T13:00:00"),
                ratio=None,
                cash_amount=88.5,
                currency="EUR",
                source=_SOURCE,
            ),
        )
    )


def _run_schedule() -> RebalanceSchedule:
    """The runnable rebalance events, all strictly before every corporate-action application time.

    13:00 opens the equity session (crypto + USD equity trade; the EUR equity is not yet listed);
    14:00 sees the EUR equity's late listing take effect; 22:00 is after the equity venue has
    closed, so the held equities are carried while the crypto still trades (feature 8).
    """
    return RebalanceSchedule(
        timestamps=(
            _ts("2026-07-14T13:00:00"),
            _ts("2026-07-14T14:00:00"),
            _ts(_LAST_RUN_EVENT),
        )
    )


# --------------------------------------------------------------------------- #
# public bundle + builders
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReferenceUniverse:
    """The frozen bundle of every piece of the synthetic reference universe.

    synthetic test fixture — not real market data. ``run_schedule``'s window lies strictly before
    every corporate-action application time, so a run passing ``corporate_actions`` is not refused.
    """

    universe_spec: UniverseSpec
    panel: MarketPanel
    membership: MembershipSchedule
    fx: FxEvidence
    corporate_actions: CorporateActionSet
    calendars: dict[str, TradingCalendar]
    run_schedule: RebalanceSchedule


def build_reference_universe() -> ReferenceUniverse:
    """Assemble the deterministic synthetic reference universe (feature 1-9).

    Calling this twice yields equal component fingerprints (``universe_spec``, ``panel``,
    ``membership``, ``fx``, ``corporate_actions``): every input is a fixed seeded literal, with no
    wall-clock, randomness, or environment read.
    """
    calendars = _calendars()
    panel = _panel()
    membership = _membership()
    fx = _fx()
    corporate_actions = _corporate_actions()
    run_schedule = _run_schedule()
    universe_spec = UniverseSpec(
        base_currency=_BASE_CURRENCY,
        instruments=(_crypto(), _equity_usd(), _equity_eur()),
        calendars=calendars,
        bar_interval_seconds=_BAR_INTERVAL_SECONDS,
        max_staleness_seconds=_MAX_STALENESS_SECONDS,
        membership_fingerprint=membership.fingerprint,
        fx_fingerprint=fx.fingerprint,
        corporate_action_fingerprint=corporate_actions.fingerprint,
        rebalance_schedule_fingerprint=run_schedule.fingerprint,
    )
    return ReferenceUniverse(
        universe_spec=universe_spec,
        panel=panel,
        membership=membership,
        fx=fx,
        corporate_actions=corporate_actions,
        calendars=calendars,
        run_schedule=run_schedule,
    )


def reference_protocol() -> PortfolioProtocol:
    """An equal-weight, long-only, USD protocol under a non-zero cost scenario.

    The cost scenario is :meth:`CostParameters.compatibility_v1` (fee 0.1% + 0.05% base slippage),
    so a reference RUN exercises the cost path. The staleness bound matches the universe's, so the
    closed-market carry at the last rebalance is admitted rather than refused.
    """
    return PortfolioProtocol(
        base_currency=_BASE_CURRENCY,
        initial_cash=_INITIAL_CASH,
        policy="equal_weight",
        cost_scenario=CostParameters.compatibility_v1(),
        staleness=StalenessPolicy(max_staleness_seconds=_MAX_STALENESS_SECONDS),
    )
