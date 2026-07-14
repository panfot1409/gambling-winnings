"""Causal risk overlays: hand-calculated scaling + stateful breaker sequence."""

from __future__ import annotations

import math

import numpy as np
import pytest

from eth_research.fractional.risk import (
    DrawdownBreakerConfig,
    RiskError,
    apply_max_exposure,
    apply_turnover_limit,
    apply_volatility_target,
    initial_drawdown_state,
    step_drawdown_breaker,
)


class TestMaxExposure:
    def test_caps_and_flags_activation(self) -> None:
        t = apply_max_exposure(0.8, 0.5)
        assert t.adjusted_target == 0.5
        assert t.activated
        t2 = apply_max_exposure(0.3, 1.0)
        assert t2.adjusted_target == 0.3
        assert not t2.activated

    def test_out_of_range_is_rejected(self) -> None:
        with pytest.raises(RiskError, match="raw_target"):
            apply_max_exposure(1.5, 1.0)


class TestVolatilityTarget:
    def test_zero_volatility_leaves_target_unscaled(self) -> None:
        returns = np.zeros(30)
        t = apply_volatility_target(1.0, returns)
        assert t.sufficient
        assert t.estimated_annual_volatility == 0.0
        assert t.volatility_scale == 1.0  # min(1, 0.5/0.10 floor)
        assert t.adjusted_target == 1.0

    def test_high_volatility_scales_down_hand_calculated(self) -> None:
        # Alternating +/-0.05 over 30 bars: sample std = 0.05*sqrt(30/29).
        returns = np.array([0.05, -0.05] * 15)
        expected_vol = 0.05 * math.sqrt(30 / 29) * math.sqrt(365.25)
        expected_scale = 0.5 / expected_vol
        t = apply_volatility_target(1.0, returns)
        assert t.estimated_annual_volatility is not None
        assert t.volatility_scale is not None
        assert t.estimated_annual_volatility == pytest.approx(expected_vol, rel=1e-12)
        assert t.volatility_scale == pytest.approx(expected_scale, rel=1e-12)
        assert t.volatility_scale < 1.0
        assert t.adjusted_target == pytest.approx(expected_scale, rel=1e-12)  # raw = 1.0

    def test_insufficient_history_forces_zero(self) -> None:
        t = apply_volatility_target(1.0, np.zeros(29))
        assert not t.sufficient
        assert t.reason == "insufficient_volatility_history"
        assert t.adjusted_target == 0.0
        assert t.volatility_scale is None

    def test_uses_only_the_last_lookback_returns(self) -> None:
        # Prepend wild history; only the last 30 (all zero) should count.
        returns = np.concatenate([np.full(50, 0.9), np.zeros(30)])
        t = apply_volatility_target(1.0, returns)
        assert t.observation_count == 30
        assert t.estimated_annual_volatility == 0.0

    def test_non_finite_is_rejected(self) -> None:
        bad = np.zeros(30)
        bad[5] = np.inf
        with pytest.raises(RiskError, match="non-finite"):
            apply_volatility_target(1.0, bad)


class TestTurnoverLimit:
    def test_clips_increase_to_cap(self) -> None:
        t = apply_turnover_limit(1.0, 0.0)  # wants +1.0, cap 0.25
        assert t.adjusted_target == 0.25
        assert t.activated

    def test_clips_decrease_to_cap(self) -> None:
        t = apply_turnover_limit(0.0, 1.0)  # wants -1.0
        assert t.adjusted_target == 0.75
        assert t.activated

    def test_within_band_is_untouched(self) -> None:
        t = apply_turnover_limit(0.6, 0.5)  # delta 0.1 < 0.25
        assert t.adjusted_target == pytest.approx(0.6)
        assert not t.activated

    def test_reference_is_prior_achieved_not_requested(self) -> None:
        # Prior achieved 0.4 (a partial fill), new target 1.0 -> capped to 0.65.
        t = apply_turnover_limit(1.0, 0.4)
        assert t.adjusted_target == pytest.approx(0.65)


class TestDrawdownBreaker:
    def test_no_drawdown_passes_target_through(self) -> None:
        state = initial_drawdown_state(100.0)
        adjusted, state, trace = step_drawdown_breaker(state, 105.0, 1.0)
        assert adjusted == 1.0
        assert not trace.tripped
        assert trace.peak_equity == 105.0

    def test_threshold_crossing_trips_and_forces_zero(self) -> None:
        cfg = DrawdownBreakerConfig(
            drawdown_threshold=0.30, cooldown_bars=3, recovery_threshold=0.10
        )
        state = initial_drawdown_state(100.0)
        # Equity peaks at 100, then draws down to 69 (31% DD) -> trips.
        adjusted, state, trace = step_drawdown_breaker(state, 69.0, 1.0, cfg)
        assert trace.drawdown == pytest.approx(0.31)
        assert trace.tripped
        assert adjusted == 0.0

    def test_cooldown_then_recovery_resumes(self) -> None:
        cfg = DrawdownBreakerConfig(
            drawdown_threshold=0.30, cooldown_bars=3, recovery_threshold=0.10
        )
        state = initial_drawdown_state(100.0)
        # Trip at 60 (40% DD): forced to 0, cooldown counts down from the trip bar.
        adj, state, _ = step_drawdown_breaker(state, 60.0, 1.0, cfg)
        assert adj == 0.0
        assert state.tripped
        # Held at 0 through the cooldown even as equity recovers to 95 (5% DD).
        adj, state, _ = step_drawdown_breaker(state, 95.0, 1.0, cfg)
        assert adj == 0.0
        assert state.tripped
        # Cooldown reaches zero with drawdown recovered: still 0 this bar, but the
        # breaker clears for the next decision.
        adj, state, _ = step_drawdown_breaker(state, 96.0, 1.0, cfg)
        assert adj == 0.0
        assert not state.tripped
        # Next decision resumes the requested target.
        adj, state, _ = step_drawdown_breaker(state, 97.0, 1.0, cfg)
        assert adj == 1.0
        assert not state.tripped

    def test_stays_tripped_while_still_deep_after_cooldown(self) -> None:
        cfg = DrawdownBreakerConfig(
            drawdown_threshold=0.30, cooldown_bars=1, recovery_threshold=0.10
        )
        state = initial_drawdown_state(100.0)
        _, state, _ = step_drawdown_breaker(state, 50.0, 1.0, cfg)  # trip, 50% DD
        # Cooldown elapses but still 40% down -> remains tripped, target 0.
        adjusted, state, _ = step_drawdown_breaker(state, 60.0, 1.0, cfg)
        assert adjusted == 0.0
        assert state.tripped

    def test_fold_reset_is_fresh_state(self) -> None:
        state = initial_drawdown_state(1000.0)
        assert state.peak_equity == 1000.0
        assert not state.tripped
        assert state.cooldown_remaining == 0

    def test_determinism_same_inputs_same_outputs(self) -> None:
        cfg = DrawdownBreakerConfig()
        a = step_drawdown_breaker(initial_drawdown_state(100.0), 80.0, 0.7, cfg)
        b = step_drawdown_breaker(initial_drawdown_state(100.0), 80.0, 0.7, cfg)
        assert a == b
