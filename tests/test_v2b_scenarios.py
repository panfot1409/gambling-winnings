"""V2B §17-18 cost / latency / capacity scenario declarations and helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import eth_research
from eth_research.v2b import scenarios as sc
from eth_research.v2b.candidates import WEIGHT_BTC, WEIGHT_ETH

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def test_committed_scenario_declaration_reproduces() -> None:
    sc.verify_scenario_declaration(REPO_ROOT)
    committed = (REPO_ROOT / sc.EXECUTION_SCENARIOS_RELPATH).read_bytes()
    assert committed == sc.render_scenario_declaration_bytes()


def test_at_least_four_cost_scenarios_all_contractive() -> None:
    assert len(sc.COST_SCENARIOS) >= 4
    for name, params in sc.COST_SCENARIOS.items():
        # CostParameters.__post_init__ already enforces contractivity; re-assert the invariant.
        assert params.marginal_rate_bound() < 1.0, name
    assert sc.PRIMARY_COST in sc.COST_SCENARIOS
    assert sc.STRESSED_COST in sc.COST_SCENARIOS
    # The primary regime is the accepted single-asset compatibility_v1 (0.1% fee + 0.05% slippage).
    primary = sc.COST_SCENARIOS[sc.PRIMARY_COST]
    assert primary.fee_rate == pytest.approx(0.001)
    assert primary.base_slippage == pytest.approx(0.0005)
    # The stressed regime is strictly costlier than primary on the linear terms.
    stressed = sc.COST_SCENARIOS[sc.STRESSED_COST]
    assert stressed.marginal_rate_bound() > primary.marginal_rate_bound()


def test_apply_latency_zero_is_identity() -> None:
    index = pd.date_range("2016-01-01", periods=5, freq="D", tz="UTC")
    path = pd.DataFrame({WEIGHT_ETH: [1.0, 0.0, 1.0, 0.0, 1.0], WEIGHT_BTC: 0.0}, index=index)
    out = sc.apply_latency(path, 0)
    pd.testing.assert_frame_equal(out, path)


def test_apply_latency_shifts_forward_and_flattens_warmup() -> None:
    index = pd.date_range("2016-01-01", periods=5, freq="D", tz="UTC")
    path = pd.DataFrame({WEIGHT_ETH: [1.0, 1.0, 0.0, 0.0, 1.0], WEIGHT_BTC: 0.0}, index=index)
    out = sc.apply_latency(path, 1)
    # The leading bar is flat (all cash), and every later target is yesterday's target.
    assert out[WEIGHT_ETH].tolist() == [0.0, 1.0, 1.0, 0.0, 0.0]
    assert out[WEIGHT_BTC].tolist() == [0.0, 0.0, 0.0, 0.0, 0.0]


def test_apply_latency_rejects_negative() -> None:
    index = pd.date_range("2016-01-01", periods=2, freq="D", tz="UTC")
    path = pd.DataFrame({WEIGHT_ETH: 0.0, WEIGHT_BTC: 0.0}, index=index)
    with pytest.raises(sc.V2BScenarioError, match="non-negative"):
        sc.apply_latency(path, -1)


def _small_panel() -> pd.DataFrame:
    index = pd.date_range("2016-01-01", periods=4, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "eth_open": [100.0, 100.0, 100.0, 100.0],
            "eth_close": [100.0, 100.0, 100.0, 100.0],
            "eth_volume": [10.0, 10.0, 10.0, 10.0],  # dollar vol = 1000/bar
            "btc_open": [100.0, 100.0, 100.0, 100.0],
            "btc_close": [100.0, 100.0, 100.0, 100.0],
            "btc_volume": [
                20.0,
                20.0,
                20.0,
                20.0,
            ],  # dollar vol = 2000/bar (ETH is the binding leg)
        },
        index=index,
    )


def test_capacity_participation_uses_lagged_binding_leg() -> None:
    panel = _small_panel()
    index = pd.DatetimeIndex(panel.index)
    # Turnover 0 at t0 (no lag anyway), then full 1.0 turnover on later bars.
    turnover = np.array([0.0, 1.0, 0.5, 1.0])
    report = sc.capacity_report(panel, turnover, index, capital_base=100.0)
    # Lagged binding dollar volume is 1000 (ETH); traded = turnover * 100; participation = traded /
    # 1000. t0 has no lag (skipped); t1 -> 0.1, t2 -> 0.05, t3 -> 0.1. Worst-case max = 0.1.
    assert report.max_participation == pytest.approx(0.1)
    # Mean is over the finite events only (t0 has no lagged volume): (0.1 + 0.05 + 0.1) / 3.
    assert report.mean_participation == pytest.approx((0.1 + 0.05 + 0.1) / 3)
    assert report.capital_base == 100.0


def test_capacity_rejects_nonpositive_capital() -> None:
    panel = _small_panel()
    index = pd.DatetimeIndex(panel.index)
    with pytest.raises(sc.V2BScenarioError, match="positive"):
        sc.capacity_report(panel, np.zeros(4), index, capital_base=0.0)


def test_latency_scenarios_are_declared() -> None:
    assert sc.LATENCY_SCENARIOS["causal_t_plus_1_open"] == 0
    assert sc.LATENCY_SCENARIOS["delayed_one_bar"] == 1
