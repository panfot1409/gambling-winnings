"""V2B §16 execution binding: the M4B universe, the vectorized basis, and the compatibility oracle.

The core claim these tests defend is that the fast per-event basis reproduces the accepted M4B
engine's accounting *exactly* (to machine epsilon) under zero cost — so the time-varying candidate
curves it produces in the one-shot run are as trustworthy as if the accepted engine had run them,
which it structurally cannot (its protocol is static).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import eth_research
from eth_research.v2.strict import V2ValidationError
from eth_research.v2b import execution as ex
from eth_research.v2b.acquisition import WINDOW_END_EXCLUSIVE
from eth_research.v2b.candidates import WEIGHT_BTC, WEIGHT_ETH

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def universe() -> ex.V2BUniverse:
    # Built once per module: build_v2b_universe re-derives the whole firewalled partition.
    return ex.build_v2b_universe(REPO_ROOT)


def test_universe_binds_the_firewalled_partition(universe: ex.V2BUniverse) -> None:
    assert len(universe.index) == 2221
    for inst in (universe.eth, universe.btc):
        assert inst.asset_class == "crypto_spot"
        assert inst.quote_currency == "USD"
        assert inst.calendar_id == ex.CALENDAR_ID
    assert universe.eth.symbol == "ETH-USD"
    assert universe.btc.symbol == "BTC-USD"
    # No FX (both USD-quoted), one continuous 24/7 calendar, both listed for the whole window.
    assert universe.fx.observations == ()
    assert set(universe.calendars) == {ex.CALENDAR_ID}
    assert universe.calendars[ex.CALENDAR_ID].kind == "continuous_24_7"
    assert len(universe.membership.intervals) == 2
    assert all(iv.effective_end is None for iv in universe.membership.intervals)


def test_firewall_last_engine_timestamp_strictly_before_the_seal(universe: ex.V2BUniverse) -> None:
    # The mark of the last bar (its close_time) is the greatest timestamp the engine ever sees.
    assert universe.last_engine_timestamp == pd.Timestamp("2022-06-21T23:00:00Z")
    assert universe.last_engine_timestamp < pd.Timestamp(WINDOW_END_EXCLUSIVE)
    # Every rebalance event (a bar open) is a partition open, hence <= the research cutoff.
    assert universe.schedule.timestamps[-1] < pd.Timestamp(WINDOW_END_EXCLUSIVE)


def test_zero_cost_reconciliation_is_bit_exact(universe: ex.V2BUniverse) -> None:
    rows = ex.build_zero_cost_reconciliation(universe, event_count=150)
    names = {r.name for r in rows}
    assert names == set(ex.BENCHMARK_WEIGHTS)
    for row in rows:
        # The accounting is the same arithmetic in both paths, so agreement is at machine epsilon,
        # far inside the 1e-9 contract tolerance.
        assert row.max_relative_error < 1e-12, (row.name, row.max_relative_error)


def test_benchmarks_are_the_four_pre_registered_long_only_paths(universe: ex.V2BUniverse) -> None:
    paths = ex.benchmark_weight_paths(universe.index)
    assert set(paths) == {"cash", "eth_buy_and_hold", "btc_buy_and_hold", "static_50_50"}
    for frame in paths.values():
        w_eth = frame[WEIGHT_ETH].to_numpy()
        w_btc = frame[WEIGHT_BTC].to_numpy()
        assert np.all(w_eth >= 0.0)  # long-only
        assert np.all(w_btc >= 0.0)
        assert np.all(w_eth + w_btc <= 1.0 + 1e-12)  # gross <= 1
        assert np.ptp(w_eth) == 0.0  # a benchmark is a constant path
        assert np.ptp(w_btc) == 0.0
    assert ex.PRIMARY_BENCHMARK == "eth_buy_and_hold"


def test_buy_and_hold_open_trade_close_mark(universe: ex.V2BUniverse) -> None:
    panel = universe.partition.panel
    paths = ex.benchmark_weight_paths(universe.index)
    res = ex.simulate_target_path(panel, paths["eth_buy_and_hold"], ex.zero_cost_scenario())
    close_last = float(panel["eth_close"].iloc[-1])
    open_first = float(panel["eth_open"].iloc[0])
    expected = ex.INITIAL_CASH * close_last / open_first
    assert res.terminal_equity == pytest.approx(expected, rel=1e-12)
    # The net-return series reconstructs the equity curve exactly.
    reconstructed = ex.INITIAL_CASH * np.cumprod(1.0 + res.net_returns)
    assert np.allclose(reconstructed, res.equity_curve, rtol=1e-12, atol=0.0)


def test_cash_benchmark_never_moves(universe: ex.V2BUniverse) -> None:
    cash_path = ex.benchmark_weight_paths(universe.index)["cash"]
    res = ex.simulate_target_path(universe.partition.panel, cash_path, ex.zero_cost_scenario())
    assert res.terminal_equity == pytest.approx(ex.INITIAL_CASH, rel=1e-12)
    assert float(np.max(np.abs(res.net_returns))) == 0.0
    assert float(np.max(res.turnover)) == 0.0
    assert res.total_cost == 0.0


def test_rotation_charges_turnover_only_at_switches(universe: ex.V2BUniverse) -> None:
    index = universe.index
    path = ex.representative_rotation_path(index)
    from eth_research.portfolio.costs import CostParameters

    res = ex.simulate_target_path(universe.partition.panel, path, CostParameters.compatibility_v1())
    # Cost is charged: the rotation pays real turnover (enter ETH, switch to BTC, exit to cash).
    assert res.total_cost > 0.0
    # Cost strictly lowers terminal equity vs the zero-cost run of the same path.
    zero = ex.simulate_target_path(universe.partition.panel, path, ex.zero_cost_scenario())
    assert res.terminal_equity < zero.terminal_equity


def test_cost_reduces_a_rebalanced_benchmark_but_not_buy_and_hold(universe: ex.V2BUniverse) -> None:
    from eth_research.portfolio.costs import CostParameters

    panel = universe.partition.panel
    paths = ex.benchmark_weight_paths(universe.index)
    cost = CostParameters.compatibility_v1()
    # 50/50 rebalances daily -> daily turnover -> costed terminal strictly below zero-cost terminal.
    fifty_cost = ex.simulate_target_path(panel, paths["static_50_50"], cost).terminal_equity
    zero = ex.simulate_target_path(panel, paths["static_50_50"], ex.zero_cost_scenario())
    assert fifty_cost < zero.terminal_equity
    # ETH buy-and-hold only trades once (the initial entry): total cost is a single small charge.
    bh = ex.simulate_target_path(panel, paths["eth_buy_and_hold"], cost)
    assert bh.total_cost > 0.0
    assert float(np.sum(bh.turnover > 1e-12)) == 1.0  # exactly one trading event


def test_simulate_rejects_shorting(universe: ex.V2BUniverse) -> None:
    bad = pd.DataFrame({WEIGHT_ETH: -0.5, WEIGHT_BTC: 0.0}, index=universe.index)
    with pytest.raises(ex.V2BExecutionError, match="negative weight"):
        ex.simulate_target_path(universe.partition.panel, bad, ex.zero_cost_scenario())


def test_simulate_rejects_leverage(universe: ex.V2BUniverse) -> None:
    bad = pd.DataFrame({WEIGHT_ETH: 0.7, WEIGHT_BTC: 0.7}, index=universe.index)
    with pytest.raises(ex.V2BExecutionError, match="gross <= 1"):
        ex.simulate_target_path(universe.partition.panel, bad, ex.zero_cost_scenario())


def test_builder_takes_only_repo_root() -> None:
    # Substitution resistance: the universe is derived only from repo_root, never a caller frame.
    assert list(inspect.signature(ex.build_v2b_universe).parameters) == ["repo_root"]
    # V2BExecutionError is a V2ValidationError, so callers can catch the family uniformly.
    assert issubclass(ex.V2BExecutionError, V2ValidationError)
