"""Exact finite-binary64 ULP contract for the M3C fresh-clone replay.

The one completed M3C run must reproduce on an independent machine. Every financial,
structural, provenance, cost, registry, and identity value must reproduce
**exactly**. A small, *structurally enumerated* set of secondary statistical scalars
may differ, but only by a **bounded number of representable binary64 steps (ULPs)**,
because each is derived from a non-correctly-rounded transcendental library function
(``numpy.log1p`` and/or ``math.erf``): IEEE-754 mandates correct rounding for
``+ - * /`` and ``sqrt`` only, so those transcendentals may return last-ULP-different
values across libm builds and CPU microarchitectures (the "table-maker's dilemma").
Integer-power moments (``x**3``, ``x**4``) and percentile interpolation are *not*
themselves transcendental; where they appear they only **propagate** the upstream
``log1p`` variation, they do not add new transcendental error.

This module governs only the *statistical* allowlist (Contract B). Some engine
**financial** fields flow through a *fractional* ``pow`` (e.g. ``annualized_return =
(terminal/initial)**(365.25/n) - 1``), which is also a non-correctly-rounded
transcendental; those fields are held to exact Contract A and reproduce byte-for-byte
on the supported Linux/x86_64 glibc CPython 3.12.3/3.12/3.13 envelope (the CI matrix) —
the scope of the exact claim; see ``docs/M3C_STATISTICAL_METHOD_NOTE.md`` §8.

This module replaces the earlier ``math.isclose(rel_tol=1e-9, abs_tol=1e-12)`` gate,
which — around the real committed values — admitted tens of millions of ULPs (see
``docs/M3C_BUG_LOG.md`` N2). Here acceptance is an exact integer ULP distance with a
fixed cap, plus explicit type/finite/sign/zero guards, and the allowlist is the exact
set of leaves (no wildcard fold index).
"""

from __future__ import annotations

import math
import struct
from typing import Any

from eth_research.walkforward import OOS_FOLD_COUNT

# Evidence-based cap. The observed cross-machine drift on the supported
# Linux/x86_64 CPython 3.12.3 + 3.13 runners was 1-2 ULPs (docs/M3C_BUG_LOG.md).
# Eight ULPs gives explicit, bounded headroom for those supported environments
# without admitting any numerically meaningful change. Raising it requires committed
# workflow evidence and cap / cap+1 adversarial tests, and must never exceed 32.
MAX_REPLAY_ULPS: int = 8

# The seven fixed statistical leaves, each derived (directly or via a standardized
# moment / percentile) from the np.log1p paired-excess series and/or math.erf.
_FIXED_STATISTICAL_LEAVES: frozenset[tuple[Any, ...]] = frozenset(
    {
        ("bootstrap", "point_estimate"),  # mean of np.log1p paired excess
        ("bootstrap", "ci_lower"),  # 2.5th percentile of log1p-derived resample means
        ("bootstrap", "ci_upper"),  # 97.5th percentile of the same
        ("psr_diagnostic", "observed_sharpe"),  # mean/std of the log1p series
        ("psr_diagnostic", "skewness"),  # standardized 3rd moment of the log1p series
        ("psr_diagnostic", "kurtosis"),  # standardized 4th moment of the log1p series
        ("psr_diagnostic", "psr"),  # 0.5*(1 + math.erf(z)) of the above
    }
)

# The exact, structurally-enumerated allowlist: the seven fixed leaves plus exactly
# ``paired_comparisons[0..OOS_FOLD_COUNT-1].mean_daily_paired_log_excess``. No wildcard
# fold index, no similarly-named field at another nesting location, no other key.
# Everything else (counts, seed, resamples, confidence, algorithm, block_lengths, the
# constant benchmark_sharpe=0.0, and every financial/structural/provenance field) must
# reproduce exactly.
ALLOWED_STATISTICAL_LEAVES: frozenset[tuple[Any, ...]] = _FIXED_STATISTICAL_LEAVES | frozenset(
    ("paired_comparisons", i, "mean_daily_paired_log_excess") for i in range(OOS_FOLD_COUNT)
)

# Which allowed leaves feed a mechanical promotion criterion (for the CI annotation).
# Only the primary interval's lower bound (P1: "CI lower bound > 0") is a decision
# input; the point estimate, upper bound, per-fold means, and the whole PSR block are
# descriptive. The decision is re-derived and required identical regardless.
_CRITERION_FOR_LEAF: dict[tuple[Any, ...], str] = {
    ("bootstrap", "ci_lower"): "P1",
}


class ULPContractError(ValueError):
    """A value violated the finite-binary64 ULP-contract input requirements."""


def _monotonic_key(x: float) -> int:
    """Order-preserving integer key: adjacent binary64 values map to adjacent ints.

    The raw 64-bit pattern read as a signed integer is already monotonic within each
    sign; remapping the negative half places ``-0.0`` (key 0) immediately below the
    smallest positive subnormal (key 1) and above the smallest-magnitude negative
    (key -1). ``+0.0`` and ``-0.0`` therefore share key 0 — they are numerically
    equal; a sign flip at zero is caught by the caller's explicit sign guard, never by
    a small ULP distance.
    """
    signed = int(struct.unpack("<q", struct.pack("<d", x))[0])
    return signed if signed >= 0 else (-0x8000000000000000 - signed)


def ulp_distance(a: float, b: float) -> int:
    """Exact number of representable binary64 steps between two finite floats.

    Strict inputs: both must be exactly ``float`` (``bool``/``int``/``Decimal``/``str``/
    ``None`` are rejected) and finite (NaN and ±Inf are rejected). There is no
    relative- or absolute-tolerance fallback.
    """
    for value in (a, b):
        if type(value) is not float:
            raise ULPContractError(
                f"ulp_distance requires float, got {type(value).__name__}: {value!r}"
            )
        if not math.isfinite(value):
            raise ULPContractError(f"ulp_distance requires finite values, got {value!r}")
    return abs(_monotonic_key(a) - _monotonic_key(b))


def feeds_promotion_criterion(path: tuple[Any, ...]) -> str | None:
    """The promotion criterion id a statistical leaf feeds, or None if descriptive."""
    return _CRITERION_FOR_LEAF.get(path)


def _leaf_equal(a: Any, b: Any) -> bool:
    """Strict leaf equality: same JSON type, and for floats bit-for-bit identical.

    Bit comparison distinguishes ``+0.0`` from ``-0.0`` and an ``int`` from a ``float``
    of equal value, so a signed-zero or type change is always surfaced as a diff.
    """
    if type(a) is not type(b):
        return False
    if type(a) is float:
        return struct.pack("<d", a) == struct.pack("<d", b)
    return bool(a == b)


def walk_leaf_diffs(
    committed: Any, reproduced: Any, path: tuple[Any, ...] = ()
) -> list[tuple[tuple[Any, ...], Any, Any]]:
    """Every leaf path at which two parsed-JSON structures differ (bit-exact floats)."""
    if isinstance(committed, dict) and isinstance(reproduced, dict):
        diffs: list[tuple[tuple[Any, ...], Any, Any]] = []
        for key in sorted(set(committed) | set(reproduced), key=str):
            here = (*path, key)
            if key not in committed or key not in reproduced:
                diffs.append(
                    (here, committed.get(key, "<absent>"), reproduced.get(key, "<absent>"))
                )
            else:
                diffs.extend(walk_leaf_diffs(committed[key], reproduced[key], here))
        return diffs
    if isinstance(committed, list) and isinstance(reproduced, list):
        if len(committed) != len(reproduced):
            return [(path, f"<len {len(committed)}>", f"<len {len(reproduced)}>")]
        diffs = []
        for i, (a, b) in enumerate(zip(committed, reproduced, strict=True)):
            diffs.extend(walk_leaf_diffs(a, b, (*path, i)))
        return diffs
    return [] if _leaf_equal(committed, reproduced) else [(path, committed, reproduced)]


def statistical_leaf_reason(path: tuple[Any, ...], committed: Any, reproduced: Any) -> str | None:
    """None iff this difference is a legitimate bounded-ULP statistical variation.

    Requires, in order: an exactly-allowed path; both values exactly ``float``; both
    finite; neither exactly zero (no bounded tolerance across an exact zero); identical
    sign; and an exact ULP distance within :data:`MAX_REPLAY_ULPS`. Any failure returns
    a human reason string (the difference is *hard* and fails the replay closed).
    """
    if path not in ALLOWED_STATISTICAL_LEAVES:
        return "not an allowlisted statistical leaf"
    if type(committed) is not float or type(reproduced) is not float:
        return "not a float on both sides"
    if not (math.isfinite(committed) and math.isfinite(reproduced)):
        return "non-finite value"
    if committed == 0.0 or reproduced == 0.0:
        return "exact zero on one side (no bounded-ULP tolerance across zero)"
    if math.copysign(1.0, committed) != math.copysign(1.0, reproduced):
        return "sign flip / zero crossing"
    distance = ulp_distance(committed, reproduced)
    if distance > MAX_REPLAY_ULPS:
        return f"ULP distance {distance} exceeds the cap {MAX_REPLAY_ULPS}"
    return None


def classify_reproduction_json(
    committed_json: Any, reproduced_json: Any
) -> tuple[
    list[tuple[tuple[Any, ...], float, float, int]],
    list[tuple[tuple[Any, ...], Any, Any, str]],
]:
    """Partition committed-vs-reproduced leaf differences into ``(tolerated, hard)``.

    ``tolerated`` entries are ``(path, committed, reproduced, ulp_distance)`` for an
    allowed statistical leaf within the bounded-ULP contract. ``hard`` entries are
    ``(path, committed, reproduced, reason)`` for everything else — any financial,
    structural, provenance, non-float, sign-flipping, or over-cap difference. If
    ``hard`` is non-empty the replay must fail closed.
    """
    tolerated: list[tuple[tuple[Any, ...], float, float, int]] = []
    hard: list[tuple[tuple[Any, ...], Any, Any, str]] = []
    for path, committed_value, reproduced_value in walk_leaf_diffs(committed_json, reproduced_json):
        reason = statistical_leaf_reason(path, committed_value, reproduced_value)
        if reason is None:
            tolerated.append(
                (
                    path,
                    committed_value,
                    reproduced_value,
                    ulp_distance(committed_value, reproduced_value),
                )
            )
        else:
            hard.append((path, committed_value, reproduced_value, reason))
    return tolerated, hard


def format_path(path: tuple[Any, ...]) -> str:
    """Dotted JSON path, e.g. ``paired_comparisons.0.mean_daily_paired_log_excess``."""
    return ".".join(str(part) for part in path)
