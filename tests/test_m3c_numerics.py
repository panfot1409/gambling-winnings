"""Exact finite-binary64 ULP contract: comparator + structural allowlist + mutations.

Covers the corrected numerical replay contract (docs/M3C_BUG_LOG.md N1-N6): an exact
integer ULP distance with a fixed cap, a structurally-exact allowlist (no wildcard
fold index), and hard-fail on every financial/structural/sign/zero/over-cap change.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

import pytest

from eth_research.m3c.numerics import (
    ALLOWED_STATISTICAL_LEAVES,
    MAX_REPLAY_ULPS,
    ULPContractError,
    classify_reproduction_json,
    feeds_promotion_criterion,
    statistical_leaf_reason,
    ulp_distance,
)
from eth_research.walkforward import OOS_FOLD_COUNT


def _nudge(x: float, ulps: int) -> float:
    """Move ``x`` by exactly ``ulps`` representable steps (sign = direction)."""
    target = math.inf if ulps > 0 else -math.inf
    for _ in range(abs(ulps)):
        x = math.nextafter(x, target)
    return x


# --------------------------------------------------------------------------- comparator


def test_ulp_distance_adjacent_is_one_everywhere() -> None:
    for base in (1.0, -1.0, 0.002, -0.00012686998, 1e-300, 1e300, 2.0, 0.5, -1024.0):
        assert ulp_distance(base, math.nextafter(base, math.inf)) == 1
        assert ulp_distance(base, math.nextafter(base, -math.inf)) == 1


def test_ulp_distance_is_symmetric_and_zero_on_equal() -> None:
    a, b = 0.002, _nudge(0.002, 5)
    assert ulp_distance(a, b) == ulp_distance(b, a) == 5
    assert ulp_distance(1.25, 1.25) == 0


def test_ulp_distance_crosses_zero_and_exponent_boundaries() -> None:
    # +0.0 and -0.0 are numerically equal -> distance 0 (sign handled separately).
    assert ulp_distance(0.0, -0.0) == 0
    # smallest subnormal each side of zero is 2 steps apart (through the shared 0).
    tiny = 5e-324
    assert ulp_distance(-tiny, tiny) == 2
    assert ulp_distance(0.0, tiny) == 1
    # exponent boundary 1.0 -> just below 1.0 is one step.
    assert ulp_distance(1.0, math.nextafter(1.0, 0.0)) == 1
    # normal/subnormal boundary.
    smallest_normal = 2.2250738585072014e-308
    assert ulp_distance(smallest_normal, math.nextafter(smallest_normal, 0.0)) == 1


def test_ulp_distance_max_finite() -> None:
    max_finite = 1.7976931348623157e308
    assert ulp_distance(max_finite, math.nextafter(max_finite, 0.0)) == 1


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_ulp_distance_rejects_non_finite(bad: float) -> None:
    with pytest.raises(ULPContractError):
        ulp_distance(bad, 1.0)
    with pytest.raises(ULPContractError):
        ulp_distance(1.0, bad)


@pytest.mark.parametrize("bad", [True, False, 1, 0, Decimal("1.0"), "1.0", None])
def test_ulp_distance_rejects_non_float_types(bad: Any) -> None:
    with pytest.raises(ULPContractError):
        ulp_distance(bad, 1.0)
    with pytest.raises(ULPContractError):
        ulp_distance(1.0, bad)


def test_monotonic_key_orders_like_the_reals() -> None:
    # A ladder of values from -inf-ish to +inf-ish must have strictly increasing keys.
    from eth_research.m3c.numerics import _monotonic_key

    ladder = [-1e308, -1.0, -5e-324, 0.0, 5e-324, 1.0, 1e308]
    keys = [_monotonic_key(v) for v in ladder]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)  # all seven distinct (no +0.0/-0.0 pair here)


# --------------------------------------------------------------------------- allowlist


def test_allowlist_is_structurally_exact() -> None:
    # Exactly 7 fixed + OOS_FOLD_COUNT per-fold means; nothing else.
    assert len(ALLOWED_STATISTICAL_LEAVES) == 7 + OOS_FOLD_COUNT
    for i in range(OOS_FOLD_COUNT):
        assert (
            "paired_comparisons",
            i,
            "mean_daily_paired_log_excess",
        ) in ALLOWED_STATISTICAL_LEAVES
    # No wildcard: an out-of-range fold index is NOT allowed (N3).
    assert (
        "paired_comparisons",
        OOS_FOLD_COUNT,
        "mean_daily_paired_log_excess",
    ) not in ALLOWED_STATISTICAL_LEAVES
    assert (
        "paired_comparisons",
        99,
        "mean_daily_paired_log_excess",
    ) not in ALLOWED_STATISTICAL_LEAVES
    # A similarly-named field elsewhere is not allowed.
    assert ("paired_comparisons", 0, "candidate_marked_return") not in ALLOWED_STATISTICAL_LEAVES
    assert ("aggregates", 0, "median_marked_return") not in ALLOWED_STATISTICAL_LEAVES
    # The constant benchmark_sharpe is exact, not allowlisted.
    assert ("psr_diagnostic", "benchmark_sharpe") not in ALLOWED_STATISTICAL_LEAVES


def test_only_ci_lower_feeds_a_promotion_criterion() -> None:
    assert feeds_promotion_criterion(("bootstrap", "ci_lower")) == "P1"
    assert feeds_promotion_criterion(("bootstrap", "point_estimate")) is None
    assert feeds_promotion_criterion(("psr_diagnostic", "psr")) is None
    assert (
        feeds_promotion_criterion(("paired_comparisons", 0, "mean_daily_paired_log_excess")) is None
    )


# ------------------------------------------------------------------ leaf reason matrix

_LEAF = ("bootstrap", "point_estimate")  # an allowed statistical leaf
_BASE = -0.00012686998005055427


@pytest.mark.parametrize("ulps", [1, 2, 4, MAX_REPLAY_ULPS])
def test_within_cap_ulp_drift_on_allowed_leaf_is_tolerated(ulps: int) -> None:
    reason = statistical_leaf_reason(_LEAF, _BASE, _nudge(_BASE, ulps))
    assert reason is None


def test_exactly_cap_plus_one_is_hard() -> None:
    reason = statistical_leaf_reason(_LEAF, _BASE, _nudge(_BASE, MAX_REPLAY_ULPS + 1))
    assert reason is not None
    assert "exceeds the cap" in reason


def test_same_relative_delta_but_millions_of_ulps_is_hard() -> None:
    # The N2 regression: rel 1e-9 near 0.002 is ~8.9M ULPs and MUST now fail.
    base = 0.0019397907812665118
    reproduced = base * (1 + 1e-9)
    assert ulp_distance(base, reproduced) > 1_000_000
    reason = statistical_leaf_reason(
        ("paired_comparisons", 0, "mean_daily_paired_log_excess"), base, reproduced
    )
    assert reason is not None
    assert "exceeds the cap" in reason


def test_tiny_absolute_delta_but_enormous_ulps_is_hard() -> None:
    # Near a subnormal, a ~1e-318 absolute change is still millions of ULPs.
    base = 5e-324
    reproduced = _nudge(base, 1_000_000)
    assert abs(reproduced - base) < 1e-317  # tiny absolute
    assert statistical_leaf_reason(_LEAF, base, reproduced) is not None


def test_sign_flip_and_zero_crossing_are_hard() -> None:
    assert statistical_leaf_reason(_LEAF, _BASE, -_BASE) is not None  # sign flip
    assert "sign" in (statistical_leaf_reason(_LEAF, 1e-9, -1e-9) or "")


def test_signed_zero_on_allowed_leaf_is_hard() -> None:
    # +0.0 vs -0.0: exact equality is preferred; a signed-zero flip must not pass.
    assert statistical_leaf_reason(_LEAF, 0.0, -0.0) is not None
    assert statistical_leaf_reason(_LEAF, _BASE, 0.0) is not None  # collapse to zero


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_on_allowed_leaf_is_hard(bad: float) -> None:
    assert statistical_leaf_reason(_LEAF, _BASE, bad) is not None


@pytest.mark.parametrize("bad", [True, 1, "x", None])
def test_non_float_on_allowed_leaf_is_hard(bad: Any) -> None:
    assert statistical_leaf_reason(_LEAF, _BASE, bad) is not None
    assert statistical_leaf_reason(_LEAF, bad, _BASE) is not None


def test_within_cap_drift_on_a_NON_allowed_leaf_is_hard() -> None:
    # Even a 1-ULP change to a financial/aggregate field must fail closed.
    fin = ("aggregates", 0, "median_marked_return")
    assert statistical_leaf_reason(fin, 1.848, _nudge(1.848, 1)) is not None
    assert (
        statistical_leaf_reason(fin, 1.848, _nudge(1.848, 1))
        == "not an allowlisted statistical leaf"
    )


# ------------------------------------------------------------ classifier over structures


def _results_like() -> dict[str, Any]:
    return {
        "bootstrap": {"point_estimate": _BASE, "ci_lower": -0.0023056, "resamples": 20000},
        "psr_diagnostic": {"psr": 0.4579391619967602, "benchmark_sharpe": 0.0, "sample_size": 1126},
        "paired_comparisons": [
            {
                "fold_index": i,
                "mean_daily_paired_log_excess": 0.001 * (i + 1),
                "candidate_beats_bnh": i in (0, 4),
            }
            for i in range(OOS_FOLD_COUNT)
        ],
        "aggregates": [{"median_marked_return": 1.8482029745405835}],
        "experiment_id": "m3c-dual-horizon-trend-v1-run-001",
    }


def test_classifier_tolerates_only_bounded_allowed_leaves() -> None:
    committed = _results_like()
    reproduced = _results_like()
    reproduced["bootstrap"]["point_estimate"] = _nudge(_BASE, 2)
    reproduced["paired_comparisons"][0]["mean_daily_paired_log_excess"] = _nudge(0.001, 1)
    tolerated, hard = classify_reproduction_json(committed, reproduced)
    assert not hard
    assert {p for p, *_ in tolerated} == {
        ("bootstrap", "point_estimate"),
        ("paired_comparisons", 0, "mean_daily_paired_log_excess"),
    }
    assert all(ulp <= MAX_REPLAY_ULPS for *_, ulp in tolerated)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda r: r["aggregates"][0].__setitem__(
                "median_marked_return", _nudge(1.8482029745405835, 1)
            ),
            id="financial-1ulp",
        ),
        pytest.param(lambda r: r["bootstrap"].__setitem__("resamples", 20001), id="count-int"),
        pytest.param(
            lambda r: r["psr_diagnostic"].__setitem__("benchmark_sharpe", 1e-320),
            id="benchmark_sharpe-nudge",
        ),
        pytest.param(lambda r: r.__setitem__("experiment_id", "tampered"), id="identity-string"),
        pytest.param(
            lambda r: r["bootstrap"].__setitem__(
                "point_estimate", _nudge(_BASE, MAX_REPLAY_ULPS + 1)
            ),
            id="allowed-over-cap",
        ),
        pytest.param(
            lambda r: r["bootstrap"].__setitem__("point_estimate", -_BASE), id="allowed-sign-flip"
        ),
        pytest.param(
            lambda r: r["paired_comparisons"][0].__setitem__("candidate_beats_bnh", False),
            id="bool-flip",
        ),
        pytest.param(lambda r: r["paired_comparisons"].pop(), id="wrong-list-length"),
        pytest.param(
            lambda r: r["paired_comparisons"].append(
                {
                    "fold_index": 5,
                    "mean_daily_paired_log_excess": 0.006,
                    "candidate_beats_bnh": False,
                }
            ),
            id="fold-index-5",
        ),
        pytest.param(lambda r: r["paired_comparisons"].reverse(), id="reordered-folds"),
        pytest.param(
            lambda r: r["bootstrap"].__setitem__("point_estimate", float("nan")), id="allowed-nan"
        ),
        pytest.param(lambda r: r["bootstrap"].__setitem__("extra_field", 1.0), id="extra-field"),
        pytest.param(lambda r: r["bootstrap"].pop("ci_lower"), id="deleted-field"),
        pytest.param(
            lambda r: r["bootstrap"].__setitem__("point_estimate", 3), id="int-replaces-float"
        ),
    ],
)
def test_classifier_hard_fails_every_non_approved_mutation(mutate: Any) -> None:
    committed = _results_like()
    reproduced = _results_like()
    mutate(reproduced)
    _tolerated, hard = classify_reproduction_json(committed, reproduced)
    assert hard, "mutation must be classified hard (fail closed)"


def test_reordered_folds_surface_as_hard_via_fold_index() -> None:
    committed = _results_like()
    reproduced = _results_like()
    reproduced["paired_comparisons"].reverse()
    _tolerated, hard = classify_reproduction_json(committed, reproduced)
    hard_paths = {p for p, *_ in hard}
    assert any(p[:1] == ("paired_comparisons",) and p[-1] == "fold_index" for p in hard_paths)
