"""Tests for the V2A candidate families and the partition firewall (§7-9).

Covers: the pre-registered candidate specifications (fingerprints, budget, long-only, and the
anti-relabel guard bound to the rejected M3C candidate); scalar-oracle causality — the vectorized
signal at bar t must equal a pure trailing-window oracle, proving no look-ahead; and the partition
firewall, which exposes only the research-train partition and rejects the sealed ones by name.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eth_research.fractional.strategies import FractionalStrategy
from eth_research.m3c.candidate import (
    CANDIDATE_FINGERPRINT as M3C_CANDIDATE_FINGERPRINT,
)
from eth_research.m3c.candidate import (
    M3C_CANDIDATE_ID,
)
from eth_research.v2 import candidates as cand
from eth_research.v2 import partitions as firewall
from eth_research.v2.candidates import (
    AlwaysLong,
    CandidateError,
    CandidateSpecification,
    MeanReversionZScore,
    SingleHorizonTrend,
    always_long_signal_at,
    meanrev_signal_at,
    trend_signal_at,
)

REPO = Path(__file__).resolve().parents[1]


def _price_frame(seed: int = 7, n: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 0.03, size=n)
    close = 100.0 * np.exp(np.cumsum(steps))
    index = pd.date_range("2016-05-23", periods=n, freq="D", tz="UTC", name="timestamp")
    return pd.DataFrame({"close": close}, index=index)


# --------------------------------------------------------------------------- #
# candidate specifications                                                     #
# --------------------------------------------------------------------------- #
def test_three_distinct_candidates_within_budget() -> None:
    specs = cand.V2A_CANDIDATES
    assert len(specs) == 3
    cand.assert_candidate_set_valid(specs)  # within budget, unique, long-only, M3C-distinct
    fps = {s.fingerprint() for s in specs}
    assert len(fps) == 3


def test_anti_relabel_guard_rejects_m3c_collisions() -> None:
    # A candidate carrying the rejected id, family, signal, or fingerprint is rejected.
    base = cand.MEANREV_SPEC
    with pytest.raises(CandidateError):
        cand.assert_distinct_from_rejected_m3c(
            CandidateSpecification(
                candidate_id=M3C_CANDIDATE_ID,
                family="mean_reversion",
                signal_family="zscore_reversion",
                fixed_parameters={"x": 1},
                long_only=True,
                shorting=False,
                leverage=False,
                execution="next_open_t_plus_1",
            )
        )
    with pytest.raises(CandidateError):
        cand.assert_distinct_from_rejected_m3c(
            CandidateSpecification(
                candidate_id="sneaky",
                family="trend",
                signal_family="dual_horizon_trend",  # the rejected signal structure
                fixed_parameters={"medium_horizon": 63, "long_horizon": 252},
                long_only=True,
                shorting=False,
                leverage=False,
                execution="next_open_t_plus_1",
            )
        )
    # The real families pass.
    cand.assert_distinct_from_rejected_m3c(base)
    assert base.fingerprint() != M3C_CANDIDATE_FINGERPRINT


def test_specs_are_long_only_unlevered() -> None:
    for spec in cand.V2A_CANDIDATES:
        assert spec.long_only is True
        assert spec.shorting is False
        assert spec.leverage is False
        assert spec.execution == "next_open_t_plus_1"


# --------------------------------------------------------------------------- #
# scalar-oracle causality (no look-ahead)                                      #
# --------------------------------------------------------------------------- #
def test_meanrev_signal_matches_scalar_oracle_causally() -> None:
    frame = _price_frame()
    closes = frame["close"].to_numpy()
    strat = MeanReversionZScore(lookback=20, entry_z=1.0)
    vec = strat.target_positions(frame).to_numpy()
    for t in range(len(closes)):
        oracle = meanrev_signal_at(closes[: t + 1], lookback=20, entry_z=1.0)
        assert vec[t] == oracle, t


def test_trend_signal_matches_scalar_oracle_causally() -> None:
    frame = _price_frame()
    closes = frame["close"].to_numpy()
    strat = SingleHorizonTrend(horizon=50)
    vec = strat.target_positions(frame).to_numpy()
    for t in range(len(closes)):
        oracle = trend_signal_at(closes[: t + 1], horizon=50)
        assert vec[t] == oracle, t


def test_always_long_is_constant_one() -> None:
    frame = _price_frame()
    vec = AlwaysLong().target_positions(frame).to_numpy()
    assert (vec == 1.0).all()
    assert always_long_signal_at(frame["close"].to_numpy()) == 1.0


def test_signals_are_binary_and_long_only() -> None:
    frame = _price_frame()
    for strat in (MeanReversionZScore(), AlwaysLong(), SingleHorizonTrend(horizon=30)):
        vec = strat.target_positions(frame).to_numpy()
        assert set(np.unique(vec)).issubset({0.0, 1.0})


def test_meanrev_goes_long_on_a_sharp_dip() -> None:
    # A flat series then a sharp drop should trigger the oversold long.
    index = pd.date_range("2016-05-23", periods=40, freq="D", tz="UTC", name="timestamp")
    close = np.full(40, 100.0)
    close[-1] = 80.0  # sharp dip on the last bar
    frame = pd.DataFrame({"close": close}, index=index)
    vec = MeanReversionZScore(lookback=20, entry_z=1.0).target_positions(frame).to_numpy()
    assert vec[-1] == 1.0  # oversold => long
    assert vec[-2] == 0.0  # flat before the dip => cash


# --------------------------------------------------------------------------- #
# builders                                                                     #
# --------------------------------------------------------------------------- #
def test_builders_produce_reused_engine_strategies() -> None:
    strategies = cand.build_all_fractional_strategies()
    assert len(strategies) == 3
    names = {s.name for s in strategies}
    assert names == {
        "meanrev_zscore_accumulation",
        "vol_scaled_hold_drawdown_guard",
        "trend_regime_single_horizon",
    }
    for s in strategies:
        assert isinstance(s, FractionalStrategy)
        assert s.risk.max_exposure == 1.0
        assert s.warmup_bars >= 1
    # The risk-overlay family uses vol targeting + the drawdown breaker; trend/reversion do not.
    by_name = {s.name: s for s in strategies}
    assert by_name["vol_scaled_hold_drawdown_guard"].risk.volatility_target is True
    assert by_name["vol_scaled_hold_drawdown_guard"].risk.drawdown_breaker is True
    assert by_name["trend_regime_single_horizon"].risk.volatility_target is False


# --------------------------------------------------------------------------- #
# partition firewall                                                           #
# --------------------------------------------------------------------------- #
def test_partition_name_guard_rejects_sealed_partitions() -> None:
    assert firewall.require_research_train_partition("x", "research_train") == "research_train"
    for sealed in ("development_gate", "final_holdout"):
        with pytest.raises(firewall.PartitionFirewallError):
            firewall.require_research_train_partition("x", sealed)
    with pytest.raises(firewall.PartitionFirewallError):
        firewall.require_research_train_partition("x", "some_other_partition")


def test_load_research_train_only_returns_firewalled_frame() -> None:
    view = firewall.load_research_train_only(REPO)
    assert view.row_count == firewall.RESEARCH_TRAIN_ROW_COUNT == 2221
    assert str(view.first_open_time) == "2016-05-23 00:00:00+00:00"
    assert str(view.last_open_time) == "2022-06-21 00:00:00+00:00"
    # No sealed-partition row leaks past the research-train cutoff.
    assert view.frame.index.max() == pd.Timestamp(firewall.RESEARCH_TRAIN_LAST_OPEN)
    assert list(view.frame.columns) == ["open", "high", "low", "close", "volume"]
