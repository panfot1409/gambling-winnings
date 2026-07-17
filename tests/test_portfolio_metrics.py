"""Descriptive portfolio metrics: reconciliation, cross-section, undefined ratios, JSON-safety."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pandas as pd
import pytest

from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.costs import CostParameters
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.panel import build_market_panel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.valuation import StalenessPolicy

_PPY = 8766.0  # hourly bars per 365.25-day year
_FX = FxEvidence(observations=())
_CAL = {"continuous_24_7": TradingCalendar("continuous_24_7", "continuous_24_7", (), "test")}
_STALE = StalenessPolicy(max_staleness_seconds=1_000_000.0)
_ZERO = CostParameters(scenario="zero")


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _inst(symbol: str, base: str) -> InstrumentId:
    return InstrumentId(
        "crypto_spot", base, "USD", "synthetic", symbol, "spot", "USD", base, "continuous_24_7"
    )


A = _inst("A-USD", "AAA")
B = _inst("B-USD", "BBB")
S = _inst("S-USD", "SSS")


def _flat(price: float, periods: int = 5) -> pd.DataFrame:
    opens = pd.date_range("2026-07-14T00:00:00", periods=periods, freq="h", tz="UTC")
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


def _moving(opens: Sequence[float], closes: Sequence[float]) -> pd.DataFrame:
    t = pd.date_range("2026-07-14T00:00:00", periods=len(opens), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": t,
            "close_time": t + pd.Timedelta(hours=1),
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
                i, _ts("2026-07-14T00:00:00"), None, _ts("2026-07-14T00:00:00"), "listing", "test"
            )
            for i in instruments
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


_SCHEDULE = RebalanceSchedule(
    timestamps=(_ts("2026-07-14T01:00:00"), _ts("2026-07-14T02:00:00"), _ts("2026-07-14T03:00:00"))
)


def test_cash_only_metrics_are_flat() -> None:
    panel = build_market_panel({A: _flat(100.0), B: _flat(100.0)})
    result = run_portfolio_simulation(
        _protocol("cash"), panel, _membership([A, B]), _FX, _SCHEDULE, calendars=_CAL
    )
    m = compute_portfolio_metrics(result, periods_per_year=_PPY)
    assert m.total_return == pytest.approx(0.0)
    assert m.average_gross_exposure == pytest.approx(0.0)
    assert m.average_cash_weight == pytest.approx(1.0)
    assert m.total_cost == pytest.approx(0.0)
    assert m.max_drawdown == pytest.approx(0.0)
    assert m.num_fills == 0
    assert m.average_held_assets == pytest.approx(0.0)


def test_equal_weight_flat_is_fully_invested_and_concentration_is_half() -> None:
    panel = build_market_panel({A: _flat(100.0), B: _flat(100.0)})
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, _membership([A, B]), _FX, _SCHEDULE, calendars=_CAL
    )
    m = compute_portfolio_metrics(result, periods_per_year=_PPY)
    assert m.total_return == pytest.approx(0.0)
    assert m.average_gross_exposure == pytest.approx(1.0)
    assert m.average_cash_weight == pytest.approx(0.0)
    assert m.average_max_weight == pytest.approx(0.5)
    assert m.average_hhi == pytest.approx(0.5)  # 2 * 0.5**2
    assert m.average_held_assets == pytest.approx(2.0)


def test_metrics_reconcile_with_attribution_rollup() -> None:
    panel = build_market_panel({S: _moving([100.0, 110.0, 121.0], [110.0, 121.0, 133.0])})
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
    m = compute_portfolio_metrics(result, periods_per_year=_PPY)
    identity = (
        m.cumulative_local_price_pnl
        + m.cumulative_fx_translation_pnl
        + m.cumulative_action_cash
        - m.cumulative_cost
        + m.cumulative_residual
    )
    assert identity == pytest.approx(m.terminal_equity - m.initial_equity)
    assert m.terminal_equity == pytest.approx(1330.0)


def test_cost_run_has_positive_cost_drag_and_turnover() -> None:
    panel = build_market_panel({S: _flat(100.0, periods=3)})
    schedule = RebalanceSchedule(timestamps=(_ts("2026-07-14T01:00:00"),))
    result = run_portfolio_simulation(
        _protocol("equal_weight", cost=CostParameters.compatibility_v1()),
        panel,
        _membership([S]),
        _FX,
        schedule,
        calendars=_CAL,
    )
    m = compute_portfolio_metrics(result, periods_per_year=_PPY)
    assert m.cost_drag > 0.0
    # Bought the post-cost equity once: notional/initial = 1 - cost_drag, just under 1.
    assert 0.99 < m.turnover < 1.0
    assert m.turnover == pytest.approx(1.0 - m.cost_drag, abs=1e-6)


def test_single_event_ratios_are_none_not_nan() -> None:
    panel = build_market_panel({S: _flat(100.0, periods=3)})
    schedule = RebalanceSchedule(timestamps=(_ts("2026-07-14T01:00:00"),))
    result = run_portfolio_simulation(
        _protocol("equal_weight"), panel, _membership([S]), _FX, schedule, calendars=_CAL
    )
    m = compute_portfolio_metrics(result, periods_per_year=_PPY)
    assert m.sharpe_ratio is None
    assert m.sortino_ratio is None
    assert m.annualized_volatility is None
    # canonical form must be strict-JSON-safe (no NaN/Infinity).
    json.dumps(m.canonical(), allow_nan=False)


def test_metrics_reject_bad_periods_per_year() -> None:
    panel = build_market_panel({A: _flat(100.0), B: _flat(100.0)})
    result = run_portfolio_simulation(
        _protocol("cash"), panel, _membership([A, B]), _FX, _SCHEDULE, calendars=_CAL
    )
    with pytest.raises(Exception, match="periods_per_year"):
        compute_portfolio_metrics(result, periods_per_year=0.0)
