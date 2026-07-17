"""The deterministic scenario-batch runner (§33) and the synthetic performance guards (§34)."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.corporate_actions import CorporateActionSet
from eth_research.portfolio.costs import CostParameters
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.panel import build_market_panel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.scenarios import (
    Scenario,
    run_scenario,
    run_scenario_batch,
)
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.trace import DEFAULT_MAX_SAMPLES
from eth_research.portfolio.universe import UniverseSpec
from eth_research.portfolio.valuation import StalenessPolicy

_CAL_ID = "continuous_24_7"
_CALS = {_CAL_ID: TradingCalendar(_CAL_ID, _CAL_ID, (), "test")}
_FX = FxEvidence(observations=())
_NO_CA = CorporateActionSet(actions=())
_EPOCH = pd.Timestamp("2026-07-14T00:00:00", tz="UTC")


def _inst(index: int) -> InstrumentId:
    base = f"A{index:03d}"
    return InstrumentId(
        "crypto_spot", base, "USD", "synthetic", f"{base}-USD", "spot", "USD", base, _CAL_ID
    )


def _frame(n_bars: int, seed: int) -> pd.DataFrame:
    opens = pd.date_range(_EPOCH, periods=n_bars, freq="h", tz="UTC")
    # A deterministic, bounded, strictly-positive price path (no randomness): a gentle saw wave.
    prices = [100.0 + ((seed + i) % 7) for i in range(n_bars)]
    return pd.DataFrame(
        {
            "open_time": opens,
            "close_time": opens + pd.Timedelta(hours=1),
            "open": prices,
            "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "volume": [1_000.0] * n_bars,
        }
    )


def _scenario(name: str, n_assets: int, n_bars: int, n_events: int) -> Scenario:
    """A self-consistent synthetic equal-weight scenario of ``n_assets`` over ``n_bars`` bars."""
    instruments = tuple(_inst(i) for i in range(n_assets))
    panel = build_market_panel({inst: _frame(n_bars, seed=i) for i, inst in enumerate(instruments)})
    membership = MembershipSchedule(
        intervals=tuple(
            MembershipInterval(inst, _EPOCH, None, _EPOCH, "listing", "test")
            for inst in instruments
        )
    )
    opens = pd.date_range(_EPOCH, periods=n_bars, freq="h", tz="UTC")
    # Evenly spaced rebalance events across the available bar opens (bounded, deterministic).
    step = max(1, n_bars // n_events)
    stamps = tuple(opens[min(i * step, n_bars - 1)] for i in range(n_events))
    schedule = RebalanceSchedule(timestamps=stamps)
    universe = UniverseSpec(
        base_currency="USD",
        instruments=instruments,
        calendars=_CALS,
        bar_interval_seconds=3600,
        max_staleness_seconds=90_000.0,
        membership_fingerprint=membership.fingerprint,
        fx_fingerprint=_FX.fingerprint,
        corporate_action_fingerprint=_NO_CA.fingerprint,
        rebalance_schedule_fingerprint=schedule.fingerprint,
    )
    protocol = PortfolioProtocol(
        base_currency="USD",
        initial_cash=1_000.0,
        policy="equal_weight",
        cost_scenario=CostParameters(scenario="zero"),
        staleness=StalenessPolicy(max_staleness_seconds=1_000_000.0),
    )
    return Scenario(
        name=name,
        universe=universe,
        protocol=protocol,
        panel=panel,
        membership=membership,
        fx=_FX,
        schedule=schedule,
        calendars=_CALS,
    )


# --------------------------------------------------------------------------- #
# §33 — the deterministic sequential batch API
# --------------------------------------------------------------------------- #
def test_single_scenario_runs_and_builds_a_result() -> None:
    outcome = run_scenario(_scenario("solo", n_assets=2, n_bars=5, n_events=2))
    assert outcome.name == "solo"
    assert len(outcome.result.result_id) == 64
    assert outcome.result.base_currency == "USD"


def test_batch_is_deterministic_and_order_sensitive() -> None:
    a = _scenario("alpha", 2, 6, 3)
    b = _scenario("bravo", 3, 6, 2)
    forward = run_scenario_batch([a, b])
    again = run_scenario_batch([a, b])
    assert forward.batch_fingerprint == again.batch_fingerprint  # deterministic
    assert [o.name for o in forward.outcomes] == ["alpha", "bravo"]  # order preserved

    reversed_batch = run_scenario_batch([b, a])
    assert reversed_batch.batch_fingerprint != forward.batch_fingerprint  # order-sensitive
    # ...but each scenario's own result identity is independent of batch position.
    forward_ids = {o.name: o.result.result_id for o in forward.outcomes}
    reversed_ids = {o.name: o.result.result_id for o in reversed_batch.outcomes}
    assert forward_ids == reversed_ids


def test_batch_rejects_duplicate_and_empty_names() -> None:
    a = _scenario("dup", 2, 5, 2)
    b = _scenario("dup", 2, 5, 2)
    with pytest.raises(CanonicalError, match="duplicate name"):
        run_scenario_batch([a, b])
    with pytest.raises(CanonicalError, match="name must be non-empty"):
        run_scenario_batch([_scenario("", 2, 5, 2)])


def test_empty_batch_is_an_empty_deterministic_result() -> None:
    batch = run_scenario_batch([])
    assert batch.outcomes == ()
    assert len(batch.batch_fingerprint) == 64  # a stable identity even for the empty batch


# --------------------------------------------------------------------------- #
# §34 — performance guards: large synthetic loads complete and produce bounded artifacts
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("n_assets", "n_bars"),
    [
        (2, 1_000),
        (10, 10_000),
        (50, 5_000),
    ],
)
def test_performance_load_completes_with_bounded_artifacts(n_assets: int, n_bars: int) -> None:
    # A handful of rebalance events keeps the event loop cheap; the load exercises the panel /
    # valuation / solver width. The point of the guard is that a large load completes without
    # hanging and that the committed artifacts stay O(1) in size regardless of the input dimensions.
    scenario = _scenario(f"perf_{n_assets}x{n_bars}", n_assets=n_assets, n_bars=n_bars, n_events=3)
    outcome = run_scenario(scenario)
    assert len(outcome.run_result.events) == 3  # bounded by the schedule, not the bar count
    trace = outcome.result.trace_commitment
    assert trace.event_count == 3
    assert len(trace.samples) <= DEFAULT_MAX_SAMPLES  # the trace never grows with the load
    assert outcome.result.metrics.average_held_assets == pytest.approx(float(n_assets), abs=1e-9)
