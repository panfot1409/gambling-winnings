"""The three pre-registered V2A candidate families, as reused-engine strategies.

Each family is a long-only spot strategy expressed against the reviewed strategy/engine surface: a
binary :class:`~eth_research.strategies.base.Strategy` signal (0 = cash, 1 = ETH) paired with a
reviewed :class:`~eth_research.fractional.strategies.RiskConfig` overlay, so continuous exposure
(volatility scaling, drawdown de-risking) comes only from already-reviewed code. No accepted engine
is modified.

Every family carries a machine-checkable :class:`CandidateSpecification` whose canonical fingerprint
binds its defining parameters; :func:`assert_distinct_from_rejected_m3c` rejects any family that
collides with the permanently-rejected M3C candidate (``M3C_CANDIDATE_ID``) by id, family, signal
structure, or fingerprint.

Each signal also ships a **scalar oracle** — a pure ``signal_at(closes)`` function over a trailing
window — so a causality test can prove the vectorized signal at bar ``t`` depends only on closes up
to and including ``t`` (never the future). Signals are decided after ``close[t]`` and executed at
``open[t+1]`` by the engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from eth_research.fractional.strategies import FractionalStrategy, RiskConfig
from eth_research.m3c.candidate import (
    CANDIDATE_FINGERPRINT as M3C_CANDIDATE_FINGERPRINT,
)
from eth_research.m3c.candidate import (
    M3C_CANDIDATE_FAMILY,
    M3C_CANDIDATE_ID,
)
from eth_research.strategies.base import Strategy
from eth_research.v2.budget import MAX_CANDIDATE_FAMILIES
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
)

CANDIDATES_SCHEMA_VERSION: int = 1

# The M3C signal name whose reuse would constitute a relabel of the rejected candidate.
_REJECTED_SIGNAL_FAMILY: str = "dual_horizon_trend"


class CandidateError(V2ValidationError):
    """A candidate specification was malformed or collided with the rejected M3C candidate."""


# --------------------------------------------------------------------------- #
# signals (binary Strategy subclasses) + their scalar oracles                  #
# --------------------------------------------------------------------------- #
def _closes(data: pd.DataFrame) -> pd.Series:
    if "close" not in data.columns:
        raise CandidateError("strategy input frame is missing the 'close' column")
    return data["close"].astype(float)


class MeanReversionZScore(Strategy):
    """Long when the close is >= ``entry_z`` sample-std below its ``lookback`` mean (else cash)."""

    initial_target = 0

    def __init__(self, *, lookback: int = 20, entry_z: float = 1.0) -> None:
        if lookback < 2:
            raise CandidateError("mean-reversion lookback must be >= 2")
        if not entry_z > 0:
            raise CandidateError("mean-reversion entry_z must be > 0")
        self._lookback = lookback
        self._entry_z = entry_z

    @property
    def name(self) -> str:
        return "meanrev_zscore"

    @property
    def lookback(self) -> int:
        return self._lookback

    @property
    def entry_z(self) -> float:
        return self._entry_z

    def target_positions(self, data: pd.DataFrame) -> pd.Series:
        close = _closes(data)
        mean = close.rolling(self._lookback).mean()
        std = close.rolling(self._lookback).std(ddof=1)
        z = (close - mean) / std
        signal = (z <= -self._entry_z).fillna(False)
        return signal.astype(float)


def meanrev_signal_at(closes: np.ndarray, *, lookback: int, entry_z: float) -> float:
    """Scalar oracle: the mean-reversion signal for the last close in ``closes`` (causal)."""
    if closes.shape[0] < lookback:
        return 0.0
    window = closes[-lookback:]
    mean = float(window.mean())
    std = float(np.std(window, ddof=1))
    if std == 0.0 or not np.isfinite(std):
        return 0.0
    z = (float(closes[-1]) - mean) / std
    return 1.0 if z <= -entry_z else 0.0


class AlwaysLong(Strategy):
    """Constant full participation (a passive long); risk overlays supply any exposure scaling."""

    initial_target = 1

    @property
    def name(self) -> str:
        return "always_long"

    def target_positions(self, data: pd.DataFrame) -> pd.Series:
        close = _closes(data)
        return pd.Series(1.0, index=close.index)


def always_long_signal_at(closes: np.ndarray) -> float:
    """Scalar oracle: always fully long."""
    return 1.0


class SingleHorizonTrend(Strategy):
    """Long when the close is above its single ``horizon`` moving average (else cash)."""

    initial_target = 0

    def __init__(self, *, horizon: int = 200) -> None:
        if horizon < 2:
            raise CandidateError("trend horizon must be >= 2")
        self._horizon = horizon

    @property
    def name(self) -> str:
        return "single_horizon_sma_gate"

    @property
    def horizon(self) -> int:
        return self._horizon

    def target_positions(self, data: pd.DataFrame) -> pd.Series:
        close = _closes(data)
        sma = close.rolling(self._horizon).mean()
        signal = (close > sma).fillna(False)
        return signal.astype(float)


def trend_signal_at(closes: np.ndarray, *, horizon: int) -> float:
    """Scalar oracle: the single-horizon trend signal for the last close in ``closes`` (causal)."""
    if closes.shape[0] < horizon:
        return 0.0
    window = closes[-horizon:]
    sma = float(window.mean())
    return 1.0 if float(closes[-1]) > sma else 0.0


# --------------------------------------------------------------------------- #
# candidate specifications + anti-relabel guard                                #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CandidateSpecification:
    """A pre-registered candidate family: a hashable identity and its defining parameters."""

    candidate_id: str
    family: str
    signal_family: str
    fixed_parameters: dict[str, object]
    long_only: bool
    shorting: bool
    leverage: bool
    execution: str

    def identity(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "family": self.family,
            "signal_family": self.signal_family,
            "fixed_parameters": dict(sorted(self.fixed_parameters.items())),
            "long_only": self.long_only,
            "shorting": self.shorting,
            "leverage": self.leverage,
            "execution": self.execution,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.identity())


MEANREV_SPEC = CandidateSpecification(
    candidate_id="meanrev_zscore_accumulation",
    family="mean_reversion",
    signal_family="zscore_reversion",
    fixed_parameters={"lookback": 20, "entry_z": 1.0, "std_convention": "sample_ddof_1"},
    long_only=True,
    shorting=False,
    leverage=False,
    execution="next_open_t_plus_1",
)

VOL_SCALED_SPEC = CandidateSpecification(
    candidate_id="vol_scaled_hold_drawdown_guard",
    family="risk_overlay",
    signal_family="always_long",
    fixed_parameters={
        "volatility_target": True,
        "volatility_lookback": 30,
        "annual_volatility_target": 0.5,
        "drawdown_breaker": True,
        "max_exposure": 1.0,
    },
    long_only=True,
    shorting=False,
    leverage=False,
    execution="next_open_t_plus_1",
)

TREND_SPEC = CandidateSpecification(
    candidate_id="trend_regime_single_horizon",
    family="trend",
    signal_family="single_horizon_sma_gate",
    fixed_parameters={"horizon": 200},
    long_only=True,
    shorting=False,
    leverage=False,
    execution="next_open_t_plus_1",
)

# The pre-registered candidate set (order fixed). Within the one-shot budget of three families.
V2A_CANDIDATES: tuple[CandidateSpecification, ...] = (MEANREV_SPEC, VOL_SCALED_SPEC, TREND_SPEC)


def assert_distinct_from_rejected_m3c(spec: CandidateSpecification) -> None:
    """Reject ``spec`` if it relabels or reparameterizes the permanently-rejected M3C candidate."""
    if spec.candidate_id == M3C_CANDIDATE_ID:
        raise CandidateError(f"candidate id {spec.candidate_id!r} is the rejected M3C candidate")
    if spec.family == M3C_CANDIDATE_FAMILY:
        raise CandidateError(f"candidate family {spec.family!r} is the rejected M3C family")
    if spec.signal_family == _REJECTED_SIGNAL_FAMILY:
        raise CandidateError(
            f"candidate signal_family {spec.signal_family!r} reuses the rejected M3C signal"
        )
    if spec.fingerprint() == M3C_CANDIDATE_FINGERPRINT:
        raise CandidateError("candidate fingerprint collides with the rejected M3C candidate")


def assert_candidate_set_valid(specs: tuple[CandidateSpecification, ...]) -> None:
    """Re-assert the whole pre-registered set: within budget, unique, long-only, M3C-distinct."""
    if not specs:
        raise CandidateError("the candidate set is empty")
    if len(specs) > MAX_CANDIDATE_FAMILIES:
        raise CandidateError(
            f"{len(specs)} candidate families exceed the budget of {MAX_CANDIDATE_FAMILIES}"
        )
    ids = [s.candidate_id for s in specs]
    if len(set(ids)) != len(ids):
        raise CandidateError("duplicate candidate ids in the set")
    fingerprints = [s.fingerprint() for s in specs]
    if len(set(fingerprints)) != len(fingerprints):
        raise CandidateError("duplicate candidate fingerprints in the set")
    for spec in specs:
        if not spec.long_only or spec.shorting or spec.leverage:
            raise CandidateError(f"candidate {spec.candidate_id!r} is not long-only/unlevered")
        assert_distinct_from_rejected_m3c(spec)


# --------------------------------------------------------------------------- #
# FractionalStrategy builders (reused-engine wiring)                           #
# --------------------------------------------------------------------------- #
def _build_meanrev() -> FractionalStrategy:
    return FractionalStrategy(
        name=MEANREV_SPEC.candidate_id,
        signal=MeanReversionZScore(lookback=20, entry_z=1.0),
        risk=RiskConfig(
            max_exposure=1.0, volatility_target=False, turnover_limit=None, drawdown_breaker=False
        ),
        warmup_bars=20,
    )


def _build_vol_scaled() -> FractionalStrategy:
    return FractionalStrategy(
        name=VOL_SCALED_SPEC.candidate_id,
        signal=AlwaysLong(),
        risk=RiskConfig(
            max_exposure=1.0, volatility_target=True, turnover_limit=None, drawdown_breaker=True
        ),
        warmup_bars=30,
    )


def _build_trend() -> FractionalStrategy:
    return FractionalStrategy(
        name=TREND_SPEC.candidate_id,
        signal=SingleHorizonTrend(horizon=200),
        risk=RiskConfig(
            max_exposure=1.0, volatility_target=False, turnover_limit=None, drawdown_breaker=False
        ),
        warmup_bars=200,
    )


_BUILDERS: dict[str, Callable[[], FractionalStrategy]] = {
    MEANREV_SPEC.candidate_id: _build_meanrev,
    VOL_SCALED_SPEC.candidate_id: _build_vol_scaled,
    TREND_SPEC.candidate_id: _build_trend,
}


def build_fractional_strategy(spec: CandidateSpecification) -> FractionalStrategy:
    """Build the reused-engine :class:`FractionalStrategy` for a pre-registered candidate."""
    builder = _BUILDERS.get(spec.candidate_id)
    if builder is None:
        raise CandidateError(f"no builder registered for candidate {spec.candidate_id!r}")
    return builder()


def build_all_fractional_strategies() -> tuple[FractionalStrategy, ...]:
    """Build every pre-registered candidate's reused-engine strategy (validates the set first)."""
    assert_candidate_set_valid(V2A_CANDIDATES)
    return tuple(build_fractional_strategy(spec) for spec in V2A_CANDIDATES)


BENCHMARK_NAME: str = "buy_and_hold"


def build_buy_and_hold_benchmark() -> FractionalStrategy:
    """The passive long benchmark every candidate is compared against (no risk overlays)."""
    return FractionalStrategy(
        name=BENCHMARK_NAME,
        signal=AlwaysLong(),
        risk=RiskConfig(
            max_exposure=1.0, volatility_target=False, turnover_limit=None, drawdown_breaker=False
        ),
        warmup_bars=0,
    )
