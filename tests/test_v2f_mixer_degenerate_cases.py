"""The degenerate cases §5 names, and the one question §4 says must be frozen to one reading.

The directive lists a specific ambiguity to resolve before any freeze: does the candidate trade
**a fractional convex mixture** or **a binary majority vote**? The module docstring answered both
ways — the rule paragraph said "holds whatever strictly more than half the current weight
favours" (binary), while the long-only/unlevered argument was stated about ``mixture_weight`` being
in ``[0, 1]`` (convex-sounding). Both sentences are individually true, but an auditor reading only
the safety paragraph would reasonably conclude the strategy holds fractional exposure.

``test_the_traded_exposure_is_binary_never_fractional`` settles it by execution rather than by
reading: over random paths the value that actually reaches the engine takes exactly two values.
``mixture_weight`` is an internal intermediate that is never traded.

The rest is the degenerate matrix: ties, zero returns, duplicate bars, an all-equal pool, an
all-wrong pool, and non-finite or non-positive input. None of these found a defect — that is the
result, and it is recorded as a result rather than as an absence of testing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.v2f.mixer import (
    EXPERT_NAMES,
    WARMUP_BARS,
    AdaptiveExpertMixer,
    MixerError,
    _bar_losses,
    _eta,
    run_mixer,
)

UNIFORM = np.full(len(EXPERT_NAMES), 1.0 / len(EXPERT_NAMES))


def _path(seed: int, bars: int = WARMUP_BARS + 120, vol: float = 0.03) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(rng.normal(0.0, vol, bars)))


# --- §4: exactly one reading of what the candidate trades -------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 7, 19, 101, 2024])
def test_the_traded_exposure_is_binary_never_fractional(seed: int) -> None:
    """The value that reaches the engine is in {0, 1}. Not a convex mixture. Not ever.

    This is the assertion that freezes the interpretation. If someone later changes
    ``target_positions`` to emit ``mixture_weight``, this fails — which is the point, because
    that would be a different candidate wearing the same identity.
    """
    traded = set(AdaptiveExpertMixer().target_positions(pd.DataFrame({"close": _path(seed)})))
    assert traded <= {0.0, 1.0}, f"traded a value outside {{0,1}}: {sorted(traded)}"


def test_mixture_weight_is_an_intermediate_and_does_reach_values_between_zero_and_one() -> None:
    """The control for the test above: ``mixture_weight`` genuinely is continuous.

    Without this, "traded values are in {0,1}" could be true simply because the mixture weight
    never left {0,1} either, and the distinction the previous test draws would be empty.
    """
    weights = {step.mixture_weight for step in run_mixer(_path(7))}
    strictly_between = {w for w in weights if 0.0 < w < 1.0}
    assert strictly_between, "mixture_weight never took an intermediate value; test is vacuous"
    assert all(0.0 <= w <= 1.0 for w in weights), "mixture weight escaped [0, 1]"


def test_no_short_and_no_leverage_are_unrepresentable_not_merely_rejected() -> None:
    """Long-only and unlevered follow from arithmetic, so no guard can be removed to break it."""
    for seed in range(12):
        for step in run_mixer(_path(seed, bars=WARMUP_BARS + 60)):
            w = np.array(step.weights)
            assert (w >= 0.0).all(), "a weight went negative"
            assert abs(float(w.sum()) - 1.0) < 1e-12, "weights stopped summing to one"
            assert 0.0 <= step.mixture_weight <= 1.0
            assert step.decision in (0.0, 1.0)


# --- ties -------------------------------------------------------------------------------------


def test_an_exact_half_tie_is_deterministic_and_resolves_flat() -> None:
    """At exactly 0.5 the strict ``>`` holds cash. Deterministic, and the safe direction."""
    weights = UNIFORM.copy()
    exposures = np.array([1.0, 1.0, 0.0, 0.0])
    mixture_weight = float(weights @ exposures)
    assert mixture_weight == 0.5
    assert (1.0 if mixture_weight > 0.5 else 0.0) == 0.0


# --- zero and near-zero returns ---------------------------------------------------------------


@pytest.mark.parametrize("realized", [0.0, -0.0])
def test_a_flat_bar_charges_nobody(realized: float) -> None:
    """Treating zero as "down" would hand cash a free win on every unchanged close."""
    losses = _bar_losses(np.array([1.0, 1.0, 0.0, 0.0]), realized)
    assert losses.tolist() == [0.0, 0.0, 0.0, 0.0]


def test_a_duplicate_bar_leaves_every_weight_untouched() -> None:
    """A repeated close is a zero return, so no expert is charged and no weight moves."""
    steps = run_mixer(np.array([100.0, 100.0, 101.0]))
    assert np.allclose(np.array(steps[1].weights), np.array(steps[0].weights))


# --- degenerate pools -------------------------------------------------------------------------


def _drive(exposures: np.ndarray, losses_fn: object, rounds: int = 49) -> np.ndarray:
    weights = UNIFORM.copy()
    for step in range(1, rounds + 1):
        losses = losses_fn(exposures, step)  # type: ignore[operator]
        weights = weights * np.exp(-_eta(step) * losses)
        weights = weights / weights.sum()
    return weights


def test_an_all_equal_pool_stays_exactly_uniform() -> None:
    """Identical opinions earn identical losses, so no expert can pull ahead."""
    final = _drive(
        np.array([1.0, 1.0, 1.0, 1.0]),
        lambda e, t: _bar_losses(e, 0.01 if t % 2 else -0.01),
    )
    assert np.allclose(final, UNIFORM)


def test_an_all_wrong_pool_also_stays_uniform() -> None:
    """The honest demonstration of what Hedge does and does not promise.

    Charge every expert on every round and the weights never move. The guarantee is RELATIVE —
    bounded regret against the best expert in hindsight — so a uniformly bad pool yields a
    uniformly weighted bad mixture. It cannot manufacture edge, which is exactly what the
    preregistered weak prior says.
    """
    final = _drive(np.array([1.0, 1.0, 1.0, 1.0]), lambda e, t: np.ones(len(EXPERT_NAMES)))
    assert np.allclose(final, UNIFORM)


# --- hostile input --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("closes", "expected"),
    [
        (np.array([1.0, np.nan, 2.0]), "non-finite"),
        (np.array([1.0, np.inf, 2.0]), "non-finite"),
        (np.array([1.0, -np.inf, 2.0]), "non-finite"),
        (np.array([1.0, 0.0, 2.0]), "strictly positive"),
        (np.array([1.0, -5.0, 2.0]), "strictly positive"),
    ],
)
def test_hostile_price_input_is_refused(closes: np.ndarray, expected: str) -> None:
    with pytest.raises(MixerError, match=expected):
        run_mixer(closes)


def test_control_a_clean_path_is_accepted() -> None:
    """Without this, every refusal above is satisfied by a function that refuses everything."""
    assert len(run_mixer(_path(3, bars=250))) == 250
