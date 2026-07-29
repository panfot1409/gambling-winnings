"""``adaptive_expert_mixer_v1`` — the single V2F candidate, and the only one.

**This candidate has never been evaluated on any research partition, and under the governance
in force it cannot be.** See ``docs/V2F_RESEARCH_PARTITION_DETERMINATION.md``. It is built
because the directive instructs building it unconditionally; the instruction to *evaluate* it is
conditional on a lawful partition existing, and none does. Nothing in this module reads market
data, computes a metric, or writes a result.

What it is
----------
Weighted Majority (Littlestone & Warmuth) over a fixed expert pool, with anytime Hedge weight
updates (Cesa-Bianchi & Lugosi). Each bar, every expert states a long/flat opinion; the mixture
holds whatever strictly more than half the current weight favours. After the bar resolves, each
expert's weight is multiplied by ``exp(-eta_t * loss)`` where the loss is 0/1 and ``eta_t`` is
the textbook anytime rate.

Why this shape, stated before any result
----------------------------------------
The hypothesis is **not** "one of these experts has edge" — three of the four were already
measured and rejected. It is the strictly different claim that *reallocating between them from
realized performance* beats the benchmark where each fixed allocation did not. That is a real
hypothesis and it is also a **weak** one, for a reason worth stating plainly rather than
discovering afterwards:

    Hedge's guarantee is RELATIVE. Its regret against the best single expert in hindsight is
    bounded; it does not manufacture edge. If every expert in the pool is null or negative, the
    mixture's best realistic outcome is "approximately as good as the least bad expert", which
    qualifies under no honest preregistered criterion.

The cash expert is the one thing that makes the pool strictly richer than any constituent: a
mixture that can shift weight to cash can decline to participate, which none of the three
inherited experts can express on its own. That is where any genuine improvement would have to
come from, and naming it in advance is what stops a later reader from inventing a better story.

No fitted constants
-------------------
§2.14 forbids hidden tuning, grid search, Bayesian search, ML/RL optimization, and parameter
replacement after viewing results. This design has nothing to tune:

* ``eta_t = sqrt(8 * ln(N) / t)`` is the standard anytime Hedge rate — derived from the regret
  bound, not chosen. There is no horizon parameter and no learning rate to pick.
* Initial weights are uniform ``1/N``, the maximum-entropy prior over experts.
* The 0/1 loss is parameter-free: no clip, no scale, no normalization constant.
* The decision rule is "more than half the weight", which is what Weighted Majority *is*, not a
  threshold someone selected. It is the only cut point that treats the two actions symmetrically.
* The three inherited experts keep their V2A parameters **exactly**. Re-tuning them here would
  be ``new_parameter_selection``, a named prohibition in the research-train exhaustion decision.

Long-only and unlevered by construction
---------------------------------------
Weights are non-negative and sum to one, and expert exposures are in ``{0, 1}``, so the mixture
weight is in ``[0, 1]`` — no check enforces it, the arithmetic does. Shorting and leverage are
not rejected here; they are unrepresentable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from eth_research.fractional.strategies import FractionalStrategy, RiskConfig
from eth_research.strategies.base import Strategy
from eth_research.v2.candidates import (
    CandidateError,
    CandidateSpecification,
    assert_distinct_from_rejected_m3c,
    meanrev_signal_at,
    trend_signal_at,
)

MIXER_SCHEMA_VERSION: int = 1

#: Parameters of the three inherited experts, frozen at their V2A pre-registered values.
#: Copied deliberately rather than imported from the spec objects: if a later edit changes a V2A
#: spec, this candidate's identity must NOT silently follow it. A test asserts they still agree,
#: so drift is reported rather than absorbed.
MEANREV_LOOKBACK: int = 20
MEANREV_ENTRY_Z: float = 1.0
TREND_HORIZON: int = 200

#: Longest expert warm-up; the mixture is undefined before this many bars.
WARMUP_BARS: int = TREND_HORIZON

EXPERT_NAMES: tuple[str, ...] = (
    "meanrev_zscore",
    "always_long",
    "single_horizon_sma_gate",
    "cash",
)

#: The requirement, not merely the ordering. Same discipline as the paper-activation gate set:
#: reducing over a rebindable sequence makes the sequence the authority.
REQUIRED_EXPERTS: frozenset[str] = frozenset(EXPERT_NAMES)


class MixerError(CandidateError):
    """The mixer was constructed or driven with an input it must refuse."""


def _expert_exposures_at(closes: np.ndarray) -> np.ndarray:
    """Each expert's long/flat opinion for the LAST close in ``closes``.

    Causal by construction: every expert is a pure function of the trailing window, and none of
    them is passed anything beyond ``closes[-1]``. This is the scalar oracle the causality test
    drives — it exists so "the vectorized path does not peek" is a proven claim, not a comment.
    """
    return np.array(
        [
            meanrev_signal_at(closes, lookback=MEANREV_LOOKBACK, entry_z=MEANREV_ENTRY_Z),
            1.0,  # always_long
            trend_signal_at(closes, horizon=TREND_HORIZON),
            0.0,  # cash
        ],
        dtype=float,
    )


def _eta(step: int) -> float:
    """Anytime Hedge rate ``sqrt(8 ln N / t)``. Derived from the regret bound, not chosen."""
    if step < 1:
        raise MixerError("hedge step must be >= 1")
    return math.sqrt(8.0 * math.log(len(EXPERT_NAMES)) / step)


def _bar_losses(exposures: np.ndarray, realized_return: float) -> np.ndarray:
    """0/1 loss per expert for a resolved bar.

    An expert loses if it was long into a down bar, or flat through an up bar — the second is an
    opportunity cost, and charging it is what stops ``cash`` from winning by default in a rising
    market. A flat bar (``realized_return == 0``) charges nobody; treating zero as "down" would
    hand cash a free win on every unchanged close.
    """
    if realized_return > 0.0:
        return (exposures < 0.5).astype(float)
    if realized_return < 0.0:
        return (exposures >= 0.5).astype(float)
    return np.zeros_like(exposures)


@dataclass(frozen=True, slots=True)
class MixerStep:
    """One bar of the mixture's internal state, for inspection and for the oracle."""

    weights: tuple[float, ...]
    expert_exposures: tuple[float, ...]
    mixture_weight: float
    decision: float


def run_mixer(closes: np.ndarray) -> list[MixerStep]:
    """Drive the mixture bar by bar over ``closes``, returning its full state trajectory.

    The one invariant that matters: the state emitted for bar ``t`` is computed from
    ``closes[: t + 1]`` only. Weights entering bar ``t`` were updated from bars strictly before
    ``t``, because a bar's own return is not known when its position is decided.
    """
    if closes.ndim != 1:
        raise MixerError("closes must be one-dimensional")
    if not np.all(np.isfinite(closes)):
        raise MixerError("closes contain a non-finite value")
    if np.any(closes <= 0.0):
        raise MixerError("closes must be strictly positive")

    n = len(EXPERT_NAMES)
    weights = np.full(n, 1.0 / n, dtype=float)
    steps: list[MixerStep] = []

    for t in range(closes.shape[0]):
        exposures = _expert_exposures_at(closes[: t + 1])
        mixture_weight = float(weights @ exposures)
        decision = 1.0 if mixture_weight > 0.5 else 0.0
        steps.append(
            MixerStep(
                weights=tuple(float(w) for w in weights),
                expert_exposures=tuple(float(e) for e in exposures),
                mixture_weight=mixture_weight,
                decision=decision,
            )
        )

        # Resolve bar t only once bar t+1's close is known, then update for bar t+1.
        if t + 1 < closes.shape[0]:
            realized = float(closes[t + 1] / closes[t] - 1.0)
            losses = _bar_losses(exposures, realized)
            weights = weights * np.exp(-_eta(t + 1) * losses)
            total = float(weights.sum())
            if total <= 0.0 or not math.isfinite(total):
                raise MixerError("hedge weights collapsed to a non-normalizable state")
            weights = weights / total

    return steps


def mixer_signal_at(closes: np.ndarray) -> float:
    """Scalar oracle: the mixture's binary decision for the last close in ``closes``.

    Recomputes the whole trajectory from the start of the supplied window, so the value depends
    on nothing outside it. That is the property the causality test checks — appending future
    bars must not change this value.
    """
    if closes.shape[0] == 0:
        raise MixerError("closes is empty")
    return run_mixer(closes)[-1].decision


def mixer_weight_at(closes: np.ndarray) -> float:
    """Scalar oracle: the continuous mixture weight before the majority cut."""
    if closes.shape[0] == 0:
        raise MixerError("closes is empty")
    return run_mixer(closes)[-1].mixture_weight


class AdaptiveExpertMixer(Strategy):
    """Weighted Majority over the frozen expert pool; long when >1/2 the weight says long."""

    initial_target = 0

    @property
    def name(self) -> str:
        return "adaptive_expert_mixer_v1"

    def target_positions(self, data: pd.DataFrame) -> pd.Series:
        if "close" not in data.columns:
            raise MixerError("strategy input frame is missing the 'close' column")
        close = data["close"].astype(float)
        closes = close.to_numpy(dtype=float)
        if closes.shape[0] == 0:
            return pd.Series(dtype=float, index=close.index)
        decisions = [step.decision for step in run_mixer(closes)]
        # Before every expert has warmed up the mixture is not yet meaningful; hold cash rather
        # than let partially-warm experts vote. WARMUP_BARS is the max over experts, not a choice.
        for i in range(min(WARMUP_BARS, len(decisions))):
            decisions[i] = 0.0
        return pd.Series(decisions, index=close.index, dtype=float)


ADAPTIVE_EXPERT_MIXER_SPEC = CandidateSpecification(
    candidate_id="adaptive_expert_mixer_v1",
    family="online_expert_mixture",
    signal_family="weighted_majority_hedge",
    fixed_parameters={
        "experts": list(EXPERT_NAMES),
        "weight_update": "hedge_multiplicative",
        "learning_rate": "anytime_sqrt_8_ln_N_over_t",
        "initial_weights": "uniform",
        "loss": "zero_one_directional_with_flat_bar_neutral",
        "decision_rule": "weighted_majority_strict_half",
        "meanrev_lookback": MEANREV_LOOKBACK,
        "meanrev_entry_z": MEANREV_ENTRY_Z,
        "trend_horizon": TREND_HORIZON,
        "warmup_bars": WARMUP_BARS,
    },
    long_only=True,
    shorting=False,
    leverage=False,
    execution="next_open_t_plus_1",
)


def assert_mixer_specification_valid() -> None:
    """Re-assert the candidate's own invariants. Cheap, and it runs in CI.

    Deliberately NOT an ``all()`` over a collection — the same vacuous-reduction trap closed in
    ``paper_readiness``. Each condition is named and checked on its own.
    """
    spec = ADAPTIVE_EXPERT_MIXER_SPEC
    if set(EXPERT_NAMES) != REQUIRED_EXPERTS:
        raise MixerError("the expert ordering has drifted from the required expert set")
    if len(EXPERT_NAMES) != len(REQUIRED_EXPERTS):
        raise MixerError("duplicate expert name")
    if not spec.long_only or spec.shorting or spec.leverage:
        raise MixerError("the mixer specification is not long-only and unlevered")
    if spec.execution != "next_open_t_plus_1":
        raise MixerError("the mixer must execute at the next open")
    assert_distinct_from_rejected_m3c(spec)


def build_adaptive_expert_mixer() -> FractionalStrategy:
    """Engine wiring, with a neutral risk overlay so the candidate is the mixture alone."""
    assert_mixer_specification_valid()
    return FractionalStrategy(
        name=ADAPTIVE_EXPERT_MIXER_SPEC.candidate_id,
        signal=AdaptiveExpertMixer(),
        risk=RiskConfig(
            max_exposure=1.0, volatility_target=False, turnover_limit=None, drawdown_breaker=False
        ),
        warmup_bars=WARMUP_BARS,
    )
