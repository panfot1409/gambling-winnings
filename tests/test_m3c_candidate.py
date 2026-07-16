"""Causality + strictness for the one fixed M3C candidate and the research budget.

The directional signal is checked against an **independent scalar-loop oracle**
(not the vectorized implementation compared with itself), and the causality
properties from Section 7 of the milestone are exercised directly.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from eth_research.m3c.candidate import (
    CANDIDATE_FINGERPRINT,
    M3C_CANDIDATE_ID,
    M3C_MAX_CONTEXT_BARS,
    ResearchBudget,
    build_candidate_strategy,
    build_m3c_strategies,
    build_research_budget,
)
from eth_research.m3c.strategy import DualHorizonTrend

_REJECT = (ValueError, TypeError)


def _rising(n: int, *, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.001, 0.02, size=n)
    close = 100.0 * np.exp(np.cumsum(steps))
    return pd.DataFrame(
        {"close": close}, index=pd.date_range("2016-01-01", periods=n, freq="D", tz="UTC")
    )


def _scalar_oracle(close: np.ndarray, medium: int = 63, long: int = 252) -> np.ndarray:
    """A deliberately naive per-bar reference, independent of the vectorized code."""
    out = np.zeros(close.size, dtype="float64")
    for t in range(close.size):
        if t < long:
            continue  # insufficient warm-up -> flat
        med = close[t] / close[t - medium] - 1.0
        lng = close[t] / close[t - long] - 1.0
        out[t] = 1.0 if (med > 0.0 and lng > 0.0) else 0.0
    return out


def test_matches_independent_scalar_oracle() -> None:
    frame = _rising(600, seed=7)
    got = DualHorizonTrend().target_positions(frame).to_numpy()
    want = _scalar_oracle(frame["close"].to_numpy())
    assert np.array_equal(got, want)


def test_prefix_invariance_at_many_cuts() -> None:
    frame = _rising(700, seed=3)
    full = DualHorizonTrend().target_positions(frame).to_numpy()
    for cut in (300, 400, 512, 640, 699):
        prefix = DualHorizonTrend().target_positions(frame.iloc[:cut]).to_numpy()
        assert np.array_equal(prefix, full[:cut]), cut


def _close_frame(close: np.ndarray) -> pd.DataFrame:
    idx = pd.date_range("2016-01-01", periods=close.size, freq="D", tz="UTC")
    return pd.DataFrame({"close": close}, index=idx)


def test_future_price_mutation_cannot_change_past_targets() -> None:
    frame = _rising(500, seed=11)
    base = DualHorizonTrend().target_positions(frame).to_numpy()
    close = np.asarray(frame["close"].to_numpy(), dtype="float64").copy()
    close[400:] *= 3.0  # blow up the future
    after = DualHorizonTrend().target_positions(_close_frame(close)).to_numpy()
    assert np.array_equal(base[:400], after[:400])


def test_exact_horizons_63_and_252() -> None:
    # A flat series has exactly-zero momentum everywhere, so the strict ``>`` keeps
    # it flat; lifting only close[300] makes both the 63- and 252-day momenta at
    # bar 300 (and only there) positive. Off-by-one on either horizon is caught.
    close = np.full(400, 100.0)
    flat = DualHorizonTrend().target_positions(_close_frame(close)).to_numpy()
    assert (flat == 0.0).all()  # exactly-zero momentum is flat (strict >)
    up = close.copy()
    up[300] = 101.0
    got = DualHorizonTrend().target_positions(_close_frame(up)).to_numpy()
    assert got[300] == 1.0  # both momenta positive at t=300 (uses t-63 and t-252)
    assert got[299] == 0.0  # neighbour before unaffected
    assert got[301] == 0.0  # neighbour after unaffected


def test_warmup_and_zero_momentum_are_flat() -> None:
    frame = _rising(400, seed=1)
    sig = DualHorizonTrend().target_positions(frame).to_numpy()
    assert (sig[:252] == 0.0).all()  # warm-up flat (needs 252 prior closes)
    flat = pd.DataFrame(
        {"close": np.full(400, 50.0)},
        index=pd.date_range("2016-01-01", periods=400, freq="D", tz="UTC"),
    )
    assert (DualHorizonTrend().target_positions(flat).to_numpy() == 0.0).all()


def test_index_equality_and_finite_unit_range() -> None:
    frame = _rising(500, seed=5)
    sig = DualHorizonTrend().target_positions(frame)
    assert sig.index.equals(frame.index)
    values = sig.to_numpy()
    assert np.isfinite(values).all()
    assert ((values == 0.0) | (values == 1.0)).all()


def test_nonfinite_or_nonpositive_close_rejected() -> None:
    for bad in (np.inf, np.nan, 0.0, -1.0):
        close = np.full(300, 100.0)
        close[280] = bad
        frame = pd.DataFrame(
            {"close": close}, index=pd.date_range("2016-01-01", periods=300, freq="D", tz="UTC")
        )
        with pytest.raises(_REJECT):
            DualHorizonTrend().target_positions(frame)


def test_horizon_construction_is_validated() -> None:
    with pytest.raises(_REJECT):
        DualHorizonTrend(medium_horizon=252, long_horizon=63)  # medium must be < long
    with pytest.raises(_REJECT):
        DualHorizonTrend(medium_horizon=0, long_horizon=252)
    with pytest.raises(_REJECT):
        DualHorizonTrend(medium_horizon=True, long_horizon=252)  # bool is not an int


def test_candidate_strategy_shape() -> None:
    strat = build_candidate_strategy()
    assert strat.name == M3C_CANDIDATE_ID
    assert strat.risk.volatility_target is True
    assert strat.risk.turnover_limit is None  # no turnover limiter
    assert strat.risk.drawdown_breaker is False
    assert strat.warmup_bars == M3C_MAX_CONTEXT_BARS == 252
    assert strat.signal.initial_target == 0


def test_grid_is_four_benchmarks_plus_one_candidate() -> None:
    names = tuple(s.name for s in build_m3c_strategies())
    assert names[-1] == M3C_CANDIDATE_ID
    assert names[:-1] == (
        "cash",
        "buy_and_hold",
        "donchian_55_20",
        "vol_target_donchian_55_20_30d_50pct",
    )
    assert len(set(names)) == 5  # no duplicate; exactly one new candidate


def test_candidate_fingerprint_is_stable_and_hex64() -> None:
    assert len(CANDIDATE_FINGERPRINT) == 64
    assert all(c in "0123456789abcdef" for c in CANDIDATE_FINGERPRINT)


def test_budget_round_trips_and_rejects_tampering() -> None:
    budget = build_research_budget()
    assert ResearchBudget.from_dict(budget.to_dict()) == budget
    # A second candidate family must be refused.
    with pytest.raises(_REJECT):
        dataclasses.replace(budget, max_new_candidate_families=2)
    # A nonzero gate-access budget must be refused.
    with pytest.raises(_REJECT):
        dataclasses.replace(budget, development_gate_accesses_permitted=1)
    # Enabling post-result parameter changes must be refused.
    with pytest.raises(_REJECT):
        dataclasses.replace(budget, post_result_parameter_changes_permitted=True)
    # A wrong candidate fingerprint must be refused.
    with pytest.raises(_REJECT):
        dataclasses.replace(budget, permitted_candidate_fingerprint="0" * 64)


def test_budget_from_dict_rejects_bool_as_int_and_missing_keys() -> None:
    good = build_research_budget().to_dict()
    bad = dict(good)
    bad["max_new_candidate_families"] = True  # bool is not an int
    with pytest.raises(_REJECT):
        ResearchBudget.from_dict(bad)
    missing = {k: v for k, v in good.items() if k != "milestone"}
    with pytest.raises(_REJECT):
        ResearchBudget.from_dict(missing)
