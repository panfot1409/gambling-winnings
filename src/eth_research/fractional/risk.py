"""Causal risk overlays in the frozen policy order (Milestone 3B, Phase 10).

The fixed pipeline is: raw strategy target → maximum exposure → volatility target
→ drawdown breaker → turnover limiter → (execution solver). Every overlay is a
pure, deterministic, **causal** function of state through ``close[t-1]`` and
records a full trace (pre/post values, activation flag, typed reason). No overlay
reads bar ``t``'s close or anything later; an undefined ratio is reported, never
silently substituted.

For the real experiment, maximum exposure is ``1.0`` for all strategies; the
volatility target (30-day, 50% annual) and the 0.25 turnover limiter are enabled
only for the two ``vol_target_*`` strategies; the drawdown breaker is built and
tested here but **disabled** in run-001.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

VOLATILITY_LOOKBACK: int = 30
VOLATILITY_MIN_OBSERVATIONS: int = 30
ANNUALIZATION_FACTOR: float = math.sqrt(365.25)
ANNUAL_VOLATILITY_TARGET: float = 0.50
VOLATILITY_DENOMINATOR_FLOOR: float = 0.10
MAX_TARGET_WEIGHT: float = 1.0
MIN_TARGET_WEIGHT: float = 0.0
DEFAULT_MAX_ABS_WEIGHT_CHANGE: float = 0.25


class RiskError(Exception):
    """A risk overlay received an out-of-domain input (e.g. a target outside [0, 1])."""


def _require_unit_interval(name: str, value: float) -> None:
    if not (MIN_TARGET_WEIGHT <= value <= MAX_TARGET_WEIGHT):
        raise RiskError(f"{name} must be in [0, 1], got {value!r}")


@dataclass(frozen=True)
class MaxExposureTrace:
    raw_target: float
    max_weight: float
    adjusted_target: float
    activated: bool


def apply_max_exposure(raw_target: float, max_weight: float) -> MaxExposureTrace:
    """Cap the raw target at ``max_weight``: ``post = min(pre, m)``."""
    _require_unit_interval("raw_target", raw_target)
    _require_unit_interval("max_weight", max_weight)
    adjusted = min(raw_target, max_weight)
    return MaxExposureTrace(
        raw_target=raw_target,
        max_weight=max_weight,
        adjusted_target=adjusted,
        activated=adjusted < raw_target,
    )


@dataclass(frozen=True)
class VolatilityTargetTrace:
    raw_target: float
    observation_count: int
    estimated_annual_volatility: float | None
    volatility_scale: float | None
    adjusted_target: float
    sufficient: bool
    reason: str | None


def apply_volatility_target(
    raw_target: float,
    recent_simple_returns: np.ndarray,
    *,
    lookback: int = VOLATILITY_LOOKBACK,
    min_observations: int = VOLATILITY_MIN_OBSERVATIONS,
) -> VolatilityTargetTrace:
    """Scale the target to a 50% annual volatility budget from lagged returns.

    ``recent_simple_returns`` are simple close-to-close returns ending no later
    than ``close[t-1]``. Before ``min_observations`` exist the adjusted target is
    ``0`` (no backfill from future data). Requesting a volatility target never
    implies it was achieved (realized volatility is reported separately).
    """
    _require_unit_interval("raw_target", raw_target)
    returns = np.asarray(recent_simple_returns, dtype="float64")
    if returns.ndim != 1:
        raise RiskError("recent_simple_returns must be one-dimensional")
    window = returns[-lookback:]
    count = int(window.size)
    if count < min_observations:
        return VolatilityTargetTrace(
            raw_target=raw_target,
            observation_count=count,
            estimated_annual_volatility=None,
            volatility_scale=None,
            adjusted_target=0.0,
            sufficient=False,
            reason="insufficient_volatility_history",
        )
    if not np.isfinite(window).all():
        raise RiskError("non-finite value in the volatility window")
    estimated = float(np.std(window, ddof=1)) * ANNUALIZATION_FACTOR
    scale = min(1.0, ANNUAL_VOLATILITY_TARGET / max(estimated, VOLATILITY_DENOMINATOR_FLOOR))
    adjusted = min(max(raw_target * scale, MIN_TARGET_WEIGHT), MAX_TARGET_WEIGHT)
    return VolatilityTargetTrace(
        raw_target=raw_target,
        observation_count=count,
        estimated_annual_volatility=estimated,
        volatility_scale=scale,
        adjusted_target=adjusted,
        sufficient=True,
        reason=None,
    )


@dataclass(frozen=True)
class TurnoverLimitTrace:
    target_in: float
    prior_achieved_exposure: float
    max_abs_weight_change: float
    adjusted_target: float
    activated: bool


def apply_turnover_limit(
    target_in: float,
    prior_achieved_exposure: float,
    *,
    max_abs_weight_change: float = DEFAULT_MAX_ABS_WEIGHT_CHANGE,
) -> TurnoverLimitTrace:
    """Bound the change from the prior **achieved** exposure to +/- the cap.

    The reference is the exposure actually achieved last bar (partial fills
    matter), not the last requested target: ``out = prior + clip(in - prior,
    -cap, +cap)``.
    """
    _require_unit_interval("target_in", target_in)
    _require_unit_interval("prior_achieved_exposure", prior_achieved_exposure)
    if max_abs_weight_change < 0.0:
        raise RiskError(
            f"max_abs_weight_change must be non-negative, got {max_abs_weight_change!r}"
        )
    delta = target_in - prior_achieved_exposure
    clipped = max(-max_abs_weight_change, min(max_abs_weight_change, delta))
    adjusted = prior_achieved_exposure + clipped
    return TurnoverLimitTrace(
        target_in=target_in,
        prior_achieved_exposure=prior_achieved_exposure,
        max_abs_weight_change=max_abs_weight_change,
        adjusted_target=adjusted,
        activated=clipped != delta,
    )


# --- Drawdown circuit breaker (built + tested; DISABLED in run-001) ----------

DEFAULT_DRAWDOWN_THRESHOLD: float = 0.30
DEFAULT_DRAWDOWN_COOLDOWN_BARS: int = 5
DEFAULT_DRAWDOWN_RECOVERY_THRESHOLD: float = 0.10


@dataclass(frozen=True)
class DrawdownBreakerConfig:
    """Hysteresis breaker: trip past ``threshold`` drawdown, resume after the
    cooldown elapses **and** drawdown recovers below ``recovery_threshold``."""

    drawdown_threshold: float = DEFAULT_DRAWDOWN_THRESHOLD
    cooldown_bars: int = DEFAULT_DRAWDOWN_COOLDOWN_BARS
    recovery_threshold: float = DEFAULT_DRAWDOWN_RECOVERY_THRESHOLD


DEFAULT_DRAWDOWN_CONFIG = DrawdownBreakerConfig()


@dataclass(frozen=True)
class DrawdownBreakerState:
    """Immutable breaker state carried between causal decisions within a fold."""

    peak_equity: float
    tripped: bool
    cooldown_remaining: int


@dataclass(frozen=True)
class DrawdownBreakerTrace:
    raw_target: float
    prior_equity: float
    peak_equity: float
    drawdown: float
    tripped: bool
    cooldown_remaining: int
    adjusted_target: float
    activated: bool


def initial_drawdown_state(initial_equity: float) -> DrawdownBreakerState:
    """Fresh breaker state at the start of a fold (reset per fold)."""
    return DrawdownBreakerState(peak_equity=initial_equity, tripped=False, cooldown_remaining=0)


def step_drawdown_breaker(
    state: DrawdownBreakerState,
    prior_equity: float,
    raw_target: float,
    config: DrawdownBreakerConfig = DEFAULT_DRAWDOWN_CONFIG,
) -> tuple[float, DrawdownBreakerState, DrawdownBreakerTrace]:
    """Advance the breaker one causal decision using equity through ``close[t-1]``.

    ``prior_equity`` is the equity marked at ``close[t-1]`` (never bar ``t``).
    Returns ``(adjusted_target, new_state, trace)``. While tripped the target is
    forced to ``0`` until the cooldown elapses and drawdown recovers.
    """
    _require_unit_interval("raw_target", raw_target)
    peak = max(state.peak_equity, prior_equity)
    drawdown = 0.0 if peak <= 0.0 else (peak - prior_equity) / peak

    tripped = state.tripped
    cooldown = state.cooldown_remaining
    if not tripped and drawdown >= config.drawdown_threshold:
        tripped = True
        cooldown = config.cooldown_bars

    if tripped:
        adjusted = 0.0
        cooldown = max(0, cooldown - 1)
        if cooldown <= 0 and drawdown <= config.recovery_threshold:
            tripped = False
    else:
        adjusted = raw_target

    new_state = DrawdownBreakerState(peak_equity=peak, tripped=tripped, cooldown_remaining=cooldown)
    trace = DrawdownBreakerTrace(
        raw_target=raw_target,
        prior_equity=prior_equity,
        peak_equity=peak,
        drawdown=drawdown,
        tripped=tripped,
        cooldown_remaining=cooldown,
        adjusted_target=adjusted,
        activated=adjusted != raw_target,
    )
    return adjusted, new_state, trace
