"""Section 32 compatibility oracle: single-asset M4B reduces to the accepted fractional engine.

A one-instrument, one-currency, continuous-calendar M4B universe under a fully-allocated reference
policy and zero cost must reproduce the accepted ``run_fractional_backtest`` equity curve to within
the accepted binary64 replay tolerance (``MAX_REPLAY_ULPS``). Both engines buy at ``open[0]`` and
mark each bar at its own ``close[t]``; M4B's end-of-step marking convention was chosen precisely so
this reduction holds exactly rather than via a widened tolerance. The accepted M3B result artifacts
are not touched — this test only *reads* the accepted engine.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

import pandas as pd

from eth_research.fractional.cost_model import CostScenario
from eth_research.fractional.engine import run_fractional_backtest
from eth_research.fractional.strategies import FractionalStrategy, RiskConfig
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.costs import CostParameters
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.panel import build_market_panel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.valuation import StalenessPolicy
from eth_research.strategies.buy_and_hold import BuyAndHold

MAX_REPLAY_ULPS = 8  # the accepted M3C binary64 replay contract
_INITIAL = 1000.0
_CAL_ID = "continuous_24_7"


def _ulps(a: float, b: float) -> int:
    """Distance in representable float64 steps (monotone two's-complement ordering)."""
    ia = int(struct.unpack("<q", struct.pack("<d", a))[0])
    ib = int(struct.unpack("<q", struct.pack("<d", b))[0])
    if ia < 0:
        ia = (1 << 63) - ia
    if ib < 0:
        ib = (1 << 63) - ib
    return abs(ia - ib)


def _zero_scenario() -> CostScenario:
    return CostScenario(
        name="zero",
        fee_rate=0.0,
        half_spread_rate=0.0,
        base_slippage_rate=0.0,
        impact_coefficient=0.0,
        impact_cap=0.0,
        liquidity_lookback=2,
        liquidity_min_observations=1,
        max_participation=None,
    )


def _frame(opens: Sequence[float], closes: Sequence[float]) -> pd.DataFrame:
    times = pd.date_range("2026-07-14T00:00:00", periods=len(opens), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [float(o) for o in opens],
            "high": [float(max(o, c)) for o, c in zip(opens, closes, strict=True)],
            "low": [float(min(o, c)) for o, c in zip(opens, closes, strict=True)],
            "close": [float(c) for c in closes],
            "volume": [1000.0] * len(opens),
        },
        index=times,
    )


def _accepted_equity(frame: pd.DataFrame) -> list[float]:
    strategy = FractionalStrategy(
        "buy_and_hold", BuyAndHold(), RiskConfig(max_exposure=1.0), warmup_bars=0
    )
    result = run_fractional_backtest(frame, strategy, _zero_scenario(), initial_cash=_INITIAL)
    return [float(value) for value in result.equity.to_numpy()]


def _m4b_equity(frame: pd.DataFrame) -> list[float]:
    instrument = InstrumentId(
        "crypto_spot", "ETH", "USD", "synthetic", "ETH-USD", "spot", "USD", "ETH", _CAL_ID
    )
    bars = frame.reset_index().rename(columns={"index": "open_time"})
    bars["close_time"] = bars["open_time"] + pd.Timedelta(hours=1)
    panel = build_market_panel(
        {instrument: bars[["open_time", "close_time", "open", "high", "low", "close", "volume"]]}
    )
    start = frame.index[0]
    membership = MembershipSchedule(
        intervals=(MembershipInterval(instrument, start, None, start, "listing", "compat"),)
    )
    schedule = RebalanceSchedule(timestamps=tuple(frame.index))
    protocol = PortfolioProtocol(
        base_currency="USD",
        initial_cash=_INITIAL,
        policy="equal_weight",  # a single active asset -> 100% allocation
        cost_scenario=CostParameters(scenario="zero"),
        staleness=StalenessPolicy(max_staleness_seconds=1_000_000.0),
    )
    calendars = {_CAL_ID: TradingCalendar(_CAL_ID, _CAL_ID, (), "compat")}
    result = run_portfolio_simulation(
        protocol, panel, membership, FxEvidence(observations=()), schedule, calendars=calendars
    )
    return [event.equity for event in result.events]


def _assert_matches(opens: Sequence[float], closes: Sequence[float]) -> int:
    frame = _frame(opens, closes)
    accepted = _accepted_equity(frame)
    m4b = _m4b_equity(frame)
    assert len(accepted) == len(m4b)
    worst = max(_ulps(a, b) for a, b in zip(accepted, m4b, strict=True))
    assert worst <= MAX_REPLAY_ULPS, f"equity differs by {worst} ULPs (> {MAX_REPLAY_ULPS})"
    return worst


def test_single_asset_reduces_to_accepted_engine_on_a_moving_price() -> None:
    worst = _assert_matches(
        [100.0, 103.5, 101.2, 108.9, 107.0, 111.3],
        [103.5, 101.2, 108.9, 107.0, 111.3, 115.6],
    )
    assert worst <= 1  # in practice this is exact to <= 1 ULP


def test_single_asset_reduces_on_a_flat_price() -> None:
    _assert_matches([100.0, 100.0, 100.0, 100.0], [100.0, 100.0, 100.0, 100.0])


def test_single_asset_reduces_on_a_declining_price() -> None:
    _assert_matches([200.0, 190.0, 180.5, 170.25], [190.0, 180.5, 170.25, 165.0])


def test_terminal_equity_matches_accepted() -> None:
    frame = _frame([100.0, 110.0, 121.0], [110.0, 121.0, 133.0])
    assert _accepted_equity(frame)[-1] == _m4b_equity(frame)[-1]
