"""Independent result-reconstruction oracle for the V2B cross-asset nomination decision.

This module is read-only, result-neutral acceptance tooling. It never re-runs a backtest, evaluates
a candidate, or reads a sealed partition; it reconstructs the committed V2B nomination *decision*
from the already-committed primitive evidence in ``research/v2b/v2b_results.json`` (and the frozen
multiplicity state) and proves that decision is a faithful mechanical function of that evidence.

The reconstruction is independent: it does NOT import or call the audited nomination engine
(``eth_research.v2b.nomination``), the multiplicity engine, the orchestrator, or any results
renderer. It re-implements, from scratch, the seven pre-registered gates, the family-wise corrected
alpha (``cumulative_alpha_budget / total_family_count``), the interval-lower-bound-above-zero test,
the strict fold-majority test, the Monte-Carlo threshold comparison, the gate conjunction
(eligibility), the at-most-one nomination rule with its tie behavior, and the lenient uncorrected
one-sided test, then asserts the recomputed decision equals the committed one.

The seven gates, all required for eligibility: (1) primary 95% lower bound > 0; (2) stressed-cost
lower bound > 0; (3) latency-stressed lower bound > 0; (4) family-wise-corrected one-sided lower
bound > 0; (5) Monte-Carlo sign-flip p-value at or below the corrected per-family alpha; (6) every
parameter-neighborhood keeps a lower bound > 0; (7) a strict majority of folds beat the benchmark.
The committed accepted outcome is a null: both candidates ineligible (each clears exactly one gate,
the strict fold majority), no nomination. This oracle proves that null follows from the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eth_research.v2.strict import (
    V2ValidationError,
    require_exact_keys,
    require_hex64,
    require_int,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_positive_real,
    require_real,
    require_slug,
    strict_json_loads,
)
from eth_research.v2.strict import (
    require_bool as _require_bool,
)

V2B_RESULTS_RELPATH: str = "research/v2b/v2b_results.json"
V2B_MULTIPLICITY_RELPATH: str = "research/v2b/research_multiplicity_state.json"

# The pinned pre-registered V2B protocol identity (also recorded in the v2ab package header).
EXPECTED_PROTOCOL_FINGERPRINT: str = (
    "2bdf606e24b6715442c5e3f0b14c16c11acac66d30f9d7774a16a82b20cf61f7"
)

# The (at most) two genuinely-new cross-asset candidate families, in committed order.
EXPECTED_CANDIDATE_IDS: tuple[str, ...] = (
    "cross_asset_btc_confirmed_eth_trend",
    "cross_asset_eth_btc_relative_strength_rotation",
)

# The single passive benchmark the whole program is scored against.
EXPECTED_BENCHMARK: str = "eth_buy_and_hold"

# The lenient, uncorrected nominal one-sided level (the diagnostic, not the corrected verdict rule).
UNCORRECTED_NOMINAL_ALPHA: float = 0.05

TIE_BEHAVIOR: str = "highest_primary_point_estimate_else_none"
NO_ELIGIBLE_REASON: str = "no candidate cleared every gate"

# The seven pre-registered gate names, exactly as the committed gate record spells them.
GATE_NAMES: frozenset[str] = frozenset(
    {
        "primary_lower_above_zero",
        "stressed_lower_above_zero",
        "latency_lower_above_zero",
        "corrected_lower_above_zero",
        "mc_supports",
        "sensitivity_all_above_zero",
        "strict_fold_majority",
    }
)

_RESULTS_KEYS: frozenset[str] = frozenset(
    {"schema_version", "run_id", "package_version", "protocol_fingerprint", "result"}
)
_RESULT_KEYS: frozenset[str] = frozenset(
    {"schema_version", "corrected_alpha", "candidates", "decision", "verdict"}
)
_CANDIDATE_KEYS: frozenset[str] = frozenset(
    {"evaluation", "corrected_bootstrap", "mc_sign_flip_p_value", "sensitivity", "gates"}
)
_EVAL_KEYS: frozenset[str] = frozenset(
    {
        "aggregate_sharpe",
        "benchmark",
        "candidate_id",
        "fold_count",
        "folds_beating_benchmark",
        "latency_lower_above_zero",
        "primary_ci_lower",
        "primary_ci_upper",
        "primary_lower_above_zero",
        "primary_point_estimate",
        "stressed_lower_above_zero",
    }
)
_CORRECTED_KEYS: frozenset[str] = frozenset(
    {
        "ci95_lower",
        "ci95_upper",
        "corrected_alpha",
        "corrected_lower_above_zero",
        "corrected_one_sided_lower",
        "observation_count",
        "one_sided_p_value",
        "point_estimate",
        "resamples",
    }
)
_SENSITIVITY_KEYS: frozenset[str] = frozenset(
    {
        "all_above_zero",
        "candidate_id",
        "fraction_lower_above_zero",
        "min_primary_ci_lower",
        "neighbor_count",
        "neighbors_lower_above_zero",
    }
)
_GATE_RECORD_KEYS: frozenset[str] = frozenset(
    {"candidate_id", "eligible", "gates", "primary_point_estimate"}
)
_DECISION_KEYS: frozenset[str] = frozenset(
    {
        "eligible_candidate_ids",
        "gates",
        "nominated_candidate_id",
        "reason",
        "schema_version",
        "tie_behavior",
    }
)
_MULTIPLICITY_KEYS: frozenset[str] = frozenset(
    {
        "corrected_one_sided_confidence",
        "corrected_per_family_alpha",
        "correction_method",
        "cumulative_alpha_budget",
        "historical_family_count",
        "historical_nominal_alpha",
        "historical_primary_test_count",
        "limitations",
        "no_reset",
        "research_family_catalog_sha256",
        "schema_version",
        "tie_behavior",
        "total_family_count",
        "v2a_family_count",
        "v2b_max_family_count",
    }
)


class V2BOracleError(V2ValidationError):
    """The reconstructed V2B decision does not faithfully follow the committed evidence."""


# --------------------------------------------------------------------------- #
# independent decision primitives (our own logic, not the audited engine)      #
# --------------------------------------------------------------------------- #
def _interval_lower_above_zero(lower: float) -> bool:
    """Independent one-sided read: an interval lower bound clears zero iff it is > 0."""
    return lower > 0.0


def _strict_fold_majority(folds_beating: int, fold_count: int) -> bool:
    """Independent strict-majority test: more than half the folds beat the benchmark."""
    if fold_count <= 0:
        raise V2BOracleError("fold_count must be positive")
    return folds_beating > fold_count / 2.0


def _mc_supports(mc_p_value: float, corrected_alpha: float) -> bool:
    """Independent threshold test: the sign-flip p-value must be at or below the corrected alpha."""
    return mc_p_value <= corrected_alpha


def _corrected_alpha_for(cumulative_budget: float, total_family_count: int) -> float:
    """Independent Bonferroni rank-1 per-family level: the budget divided by the family count."""
    if total_family_count <= 0:
        raise V2BOracleError("total_family_count must be positive")
    return cumulative_budget / total_family_count


def _nominate(eligible: list[tuple[str, float]]) -> str | None:
    """At-most-one rule: the single eligible candidate with the strictly-highest point estimate."""
    if not eligible:
        return None
    ranked = sorted(eligible, key=lambda item: item[1], reverse=True)
    if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


# --------------------------------------------------------------------------- #
# parsed-evidence + reconstruction dataclasses                                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _Eval:
    candidate_id: str
    benchmark: str
    fold_count: int
    folds_beating_benchmark: int
    primary_point_estimate: float
    primary_ci_lower: float
    primary_ci_upper: float
    primary_lower_above_zero: bool
    stressed_lower_above_zero: bool
    latency_lower_above_zero: bool
    aggregate_sharpe: float


@dataclass(frozen=True, slots=True)
class _Corrected:
    corrected_one_sided_lower: float
    corrected_lower_above_zero: bool
    corrected_alpha: float
    one_sided_p_value: float
    point_estimate: float


@dataclass(frozen=True, slots=True)
class _Sensitivity:
    candidate_id: str
    all_above_zero: bool
    fraction_lower_above_zero: float
    neighbor_count: int
    neighbors_lower_above_zero: int


@dataclass(frozen=True, slots=True)
class _GateRecord:
    candidate_id: str
    eligible: bool
    gates: dict[str, bool]
    primary_point_estimate: float


@dataclass(frozen=True, slots=True)
class _Candidate:
    evaluation: _Eval
    corrected: _Corrected
    mc_p_value: float
    sensitivity: _Sensitivity
    gates: _GateRecord


@dataclass(frozen=True, slots=True)
class V2BCandidateReconstruction:
    """One candidate's independently-recomputed seven-gate vector and derived eligibility."""

    candidate_id: str
    gates: dict[str, bool]
    eligible: bool
    committed_eligible: bool
    passed_gate_count: int
    primary_point_estimate: float
    uncorrected_one_sided_p_value: float
    passes_uncorrected: bool


@dataclass(frozen=True, slots=True)
class V2BReconstruction:
    """The independently-reconstructed V2B decision, ready for cross-checking the committed one."""

    run_id: str
    corrected_alpha: float
    expected_alpha: float
    total_family_count: int
    candidate_ids: tuple[str, ...]
    candidates: tuple[V2BCandidateReconstruction, ...]
    eligible_candidate_ids: tuple[str, ...]
    nominated_candidate_id: str | None
    committed_nominated_candidate_id: str | None


# --------------------------------------------------------------------------- #
# strict parsing of the committed evidence                                     #
# --------------------------------------------------------------------------- #
def _parse_eval(label: str, value: object) -> _Eval:
    obj = require_mapping(label, value)
    require_exact_keys(label, obj, _EVAL_KEYS)
    return _Eval(
        candidate_id=require_slug(f"{label}.candidate_id", obj["candidate_id"]),
        benchmark=require_nonempty_str(f"{label}.benchmark", obj["benchmark"]),
        fold_count=require_int(f"{label}.fold_count", obj["fold_count"]),
        folds_beating_benchmark=require_int(
            f"{label}.folds_beating_benchmark", obj["folds_beating_benchmark"]
        ),
        primary_point_estimate=require_real(
            f"{label}.primary_point_estimate", obj["primary_point_estimate"]
        ),
        primary_ci_lower=require_real(f"{label}.primary_ci_lower", obj["primary_ci_lower"]),
        primary_ci_upper=require_real(f"{label}.primary_ci_upper", obj["primary_ci_upper"]),
        primary_lower_above_zero=_require_bool(
            f"{label}.primary_lower_above_zero", obj["primary_lower_above_zero"]
        ),
        stressed_lower_above_zero=_require_bool(
            f"{label}.stressed_lower_above_zero", obj["stressed_lower_above_zero"]
        ),
        latency_lower_above_zero=_require_bool(
            f"{label}.latency_lower_above_zero", obj["latency_lower_above_zero"]
        ),
        aggregate_sharpe=require_real(f"{label}.aggregate_sharpe", obj["aggregate_sharpe"]),
    )


def _parse_corrected(label: str, value: object) -> _Corrected:
    obj = require_mapping(label, value)
    require_exact_keys(label, obj, _CORRECTED_KEYS)
    require_real(f"{label}.ci95_lower", obj["ci95_lower"])
    require_real(f"{label}.ci95_upper", obj["ci95_upper"])
    require_int(f"{label}.observation_count", obj["observation_count"])
    require_int(f"{label}.resamples", obj["resamples"])
    return _Corrected(
        corrected_one_sided_lower=require_real(
            f"{label}.corrected_one_sided_lower", obj["corrected_one_sided_lower"]
        ),
        corrected_lower_above_zero=_require_bool(
            f"{label}.corrected_lower_above_zero", obj["corrected_lower_above_zero"]
        ),
        corrected_alpha=require_real(f"{label}.corrected_alpha", obj["corrected_alpha"]),
        one_sided_p_value=require_real(f"{label}.one_sided_p_value", obj["one_sided_p_value"]),
        point_estimate=require_real(f"{label}.point_estimate", obj["point_estimate"]),
    )


def _parse_sensitivity(label: str, value: object) -> _Sensitivity:
    obj = require_mapping(label, value)
    require_exact_keys(label, obj, _SENSITIVITY_KEYS)
    require_real(f"{label}.min_primary_ci_lower", obj["min_primary_ci_lower"])
    return _Sensitivity(
        candidate_id=require_slug(f"{label}.candidate_id", obj["candidate_id"]),
        all_above_zero=_require_bool(f"{label}.all_above_zero", obj["all_above_zero"]),
        fraction_lower_above_zero=require_real(
            f"{label}.fraction_lower_above_zero", obj["fraction_lower_above_zero"]
        ),
        neighbor_count=require_int(f"{label}.neighbor_count", obj["neighbor_count"]),
        neighbors_lower_above_zero=require_int(
            f"{label}.neighbors_lower_above_zero", obj["neighbors_lower_above_zero"]
        ),
    )


def _parse_gate_record(label: str, value: object) -> _GateRecord:
    obj = require_mapping(label, value)
    require_exact_keys(label, obj, _GATE_RECORD_KEYS)
    gates_obj = require_mapping(f"{label}.gates", obj["gates"])
    require_exact_keys(f"{label}.gates", gates_obj, GATE_NAMES)
    gates = {name: _require_bool(f"{label}.gates.{name}", gates_obj[name]) for name in GATE_NAMES}
    return _GateRecord(
        candidate_id=require_slug(f"{label}.candidate_id", obj["candidate_id"]),
        eligible=_require_bool(f"{label}.eligible", obj["eligible"]),
        gates=gates,
        primary_point_estimate=require_real(
            f"{label}.primary_point_estimate", obj["primary_point_estimate"]
        ),
    )


def _parse_candidate(label: str, value: object) -> _Candidate:
    obj = require_mapping(label, value)
    require_exact_keys(label, obj, _CANDIDATE_KEYS)
    return _Candidate(
        evaluation=_parse_eval(f"{label}.evaluation", obj["evaluation"]),
        corrected=_parse_corrected(f"{label}.corrected_bootstrap", obj["corrected_bootstrap"]),
        mc_p_value=require_real(f"{label}.mc_sign_flip_p_value", obj["mc_sign_flip_p_value"]),
        sensitivity=_parse_sensitivity(f"{label}.sensitivity", obj["sensitivity"]),
        gates=_parse_gate_record(f"{label}.gates", obj["gates"]),
    )


def _parse_nominated(label: str, value: object) -> str | None:
    """Decode the nomination id: a JSON null is no nomination; an empty string is rejected."""
    if value is None:
        return None
    return require_slug(label, value)


# --------------------------------------------------------------------------- #
# the reconstruction                                                           #
# --------------------------------------------------------------------------- #
def _reconstruct_v2b_from_obj(results_obj: object, multiplicity_obj: object) -> V2BReconstruction:
    """Reconstruct and self-verify the V2B decision from already-decoded evidence objects."""
    obj = require_mapping("v2b_results", results_obj)
    require_exact_keys("v2b_results", obj, _RESULTS_KEYS)
    run_id = require_slug("v2b_results.run_id", obj["run_id"])
    require_int("v2b_results.schema_version", obj["schema_version"])
    require_nonempty_str("v2b_results.package_version", obj["package_version"])
    protocol_fp = require_hex64("v2b_results.protocol_fingerprint", obj["protocol_fingerprint"])
    if protocol_fp != EXPECTED_PROTOCOL_FINGERPRINT:
        raise V2BOracleError("protocol fingerprint drifted from the pre-registered V2B protocol")

    result = require_mapping("v2b_results.result", obj["result"])
    require_exact_keys("v2b_results.result", result, _RESULT_KEYS)
    require_int("v2b_results.result.schema_version", result["schema_version"])
    require_nonempty_str("v2b_results.result.verdict", result["verdict"])
    corrected_alpha = require_positive_real(
        "v2b_results.result.corrected_alpha", result["corrected_alpha"]
    )

    total_family_count, expected_alpha = _reconcile_alpha(multiplicity_obj, corrected_alpha)

    candidates = require_list(
        "v2b_results.result.candidates", result["candidates"], _parse_candidate
    )
    reconstructions, eligible = _reconcile_candidates(candidates, corrected_alpha)

    nominated = _nominate(eligible)
    eligible_ids = tuple(cid for cid, _ in eligible)
    committed_nominated = _reconcile_decision(
        require_mapping("v2b_results.result.decision", result["decision"]),
        candidates,
        eligible_ids,
        nominated,
    )

    if eligible_ids or nominated is not None:
        raise V2BOracleError("evidence yields an eligible candidate; the accepted null is violated")

    return V2BReconstruction(
        run_id=run_id,
        corrected_alpha=corrected_alpha,
        expected_alpha=expected_alpha,
        total_family_count=total_family_count,
        candidate_ids=tuple(c.evaluation.candidate_id for c in candidates),
        candidates=tuple(reconstructions),
        eligible_candidate_ids=eligible_ids,
        nominated_candidate_id=nominated,
        committed_nominated_candidate_id=committed_nominated,
    )


def _reconcile_alpha(multiplicity_obj: object, corrected_alpha: float) -> tuple[int, float]:
    """Independently derive the corrected alpha from the family count and bind it to the result."""
    state = require_mapping("multiplicity_state", multiplicity_obj)
    require_exact_keys("multiplicity_state", state, _MULTIPLICITY_KEYS)
    total = require_int("multiplicity_state.total_family_count", state["total_family_count"])
    historical = require_int(
        "multiplicity_state.historical_family_count", state["historical_family_count"]
    )
    v2b_max = require_int("multiplicity_state.v2b_max_family_count", state["v2b_max_family_count"])
    cumulative = require_positive_real(
        "multiplicity_state.cumulative_alpha_budget", state["cumulative_alpha_budget"]
    )
    per_family = require_real(
        "multiplicity_state.corrected_per_family_alpha", state["corrected_per_family_alpha"]
    )
    if total != historical + v2b_max:
        raise V2BOracleError(
            "total_family_count is not the historical plus V2B family basis; a family was dropped"
        )
    expected_alpha = _corrected_alpha_for(cumulative, total)
    if per_family != expected_alpha:
        raise V2BOracleError("committed per-family alpha does not equal budget / family count")
    if corrected_alpha != expected_alpha:
        raise V2BOracleError(
            "result corrected_alpha does not equal the family-wise corrected level"
        )
    tie = require_nonempty_str("multiplicity_state.tie_behavior", state["tie_behavior"])
    if tie != TIE_BEHAVIOR:
        raise V2BOracleError("multiplicity tie_behavior drifted from the frozen policy")
    return total, expected_alpha


def _reconcile_candidates(
    candidates: list[_Candidate], corrected_alpha: float
) -> tuple[list[V2BCandidateReconstruction], list[tuple[str, float]]]:
    """Recompute each candidate's seven gates from evidence and assert they match the committed."""
    ids = [c.evaluation.candidate_id for c in candidates]
    if tuple(ids) != EXPECTED_CANDIDATE_IDS:
        raise V2BOracleError("candidate set / order is not the registered two cross-asset families")

    reconstructions: list[V2BCandidateReconstruction] = []
    eligible: list[tuple[str, float]] = []
    for cand in candidates:
        _assert_candidate_invariants(cand, corrected_alpha)
        gates = {
            "primary_lower_above_zero": _interval_lower_above_zero(
                cand.evaluation.primary_ci_lower
            ),
            "stressed_lower_above_zero": cand.evaluation.stressed_lower_above_zero,
            "latency_lower_above_zero": cand.evaluation.latency_lower_above_zero,
            "corrected_lower_above_zero": _interval_lower_above_zero(
                cand.corrected.corrected_one_sided_lower
            ),
            "mc_supports": _mc_supports(cand.mc_p_value, corrected_alpha),
            "sensitivity_all_above_zero": cand.sensitivity.fraction_lower_above_zero == 1.0,
            "strict_fold_majority": _strict_fold_majority(
                cand.evaluation.folds_beating_benchmark, cand.evaluation.fold_count
            ),
        }
        if gates != cand.gates.gates:
            raise V2BOracleError(
                f"{cand.evaluation.candidate_id}: recomputed gates disagree with committed gates"
            )
        is_eligible = all(gates.values())
        if is_eligible != cand.gates.eligible:
            raise V2BOracleError(
                f"{cand.evaluation.candidate_id}: committed eligibility flag is inconsistent"
            )
        passed = sum(1 for flag in gates.values() if flag)
        # The accepted result: each candidate clears exactly one gate (the strict fold majority),
        # which already implies it is ineligible (one of seven gates cannot be all seven).
        if passed != 1 or not gates["strict_fold_majority"]:
            raise V2BOracleError(
                f"{cand.evaluation.candidate_id}: gate profile is not the accepted single-gate pass"
            )
        passes_uncorrected = cand.corrected.one_sided_p_value <= UNCORRECTED_NOMINAL_ALPHA
        if is_eligible:
            eligible.append((cand.evaluation.candidate_id, cand.evaluation.primary_point_estimate))
        reconstructions.append(
            V2BCandidateReconstruction(
                candidate_id=cand.evaluation.candidate_id,
                gates=gates,
                eligible=is_eligible,
                committed_eligible=cand.gates.eligible,
                passed_gate_count=passed,
                primary_point_estimate=cand.evaluation.primary_point_estimate,
                uncorrected_one_sided_p_value=cand.corrected.one_sided_p_value,
                passes_uncorrected=passes_uncorrected,
            )
        )

    # The lenient uncorrected one-sided test at 0.05 must not admit either candidate.
    if any(r.passes_uncorrected for r in reconstructions):
        raise V2BOracleError("a candidate passes the lenient uncorrected one-sided test at 0.05")
    return reconstructions, eligible


def _assert_candidate_invariants(cand: _Candidate, corrected_alpha: float) -> None:
    """Structural checks binding a candidate's evidence primitives to their reported flags."""
    ev = cand.evaluation
    if ev.benchmark != EXPECTED_BENCHMARK:
        raise V2BOracleError(f"{ev.candidate_id}: benchmark {ev.benchmark!r} was substituted")
    if ev.fold_count <= 0 or not 0 <= ev.folds_beating_benchmark <= ev.fold_count:
        raise V2BOracleError(f"{ev.candidate_id}: fold counts are out of range")
    if ev.primary_ci_lower > ev.primary_ci_upper:
        raise V2BOracleError(f"{ev.candidate_id}: primary interval is inverted")
    if not ev.primary_ci_lower <= ev.primary_point_estimate <= ev.primary_ci_upper:
        raise V2BOracleError(f"{ev.candidate_id}: point estimate lies outside its interval")
    if ev.primary_lower_above_zero != _interval_lower_above_zero(ev.primary_ci_lower):
        raise V2BOracleError(f"{ev.candidate_id}: primary flag disagrees with the interval bound")
    if cand.corrected.corrected_lower_above_zero != _interval_lower_above_zero(
        cand.corrected.corrected_one_sided_lower
    ):
        raise V2BOracleError(f"{ev.candidate_id}: corrected flag disagrees with its lower bound")
    if not 0.0 <= cand.mc_p_value <= 1.0 or not 0.0 <= cand.corrected.one_sided_p_value <= 1.0:
        raise V2BOracleError(f"{ev.candidate_id}: a p-value is outside [0, 1]")
    if cand.corrected.corrected_alpha != corrected_alpha:
        raise V2BOracleError(f"{ev.candidate_id}: corrected_bootstrap alpha inconsistent")
    _assert_sensitivity_invariants(cand)
    if cand.gates.candidate_id != ev.candidate_id:
        raise V2BOracleError(f"{ev.candidate_id}: gate record candidate id is mislabelled")
    if cand.gates.primary_point_estimate != ev.primary_point_estimate:
        raise V2BOracleError(f"{ev.candidate_id}: gate record point estimate is mislabelled")


def _assert_sensitivity_invariants(cand: _Candidate) -> None:
    sens = cand.sensitivity
    if sens.candidate_id != cand.evaluation.candidate_id:
        raise V2BOracleError(f"{cand.evaluation.candidate_id}: sensitivity record is mislabelled")
    if sens.neighbor_count <= 0 or not 0 <= sens.neighbors_lower_above_zero <= sens.neighbor_count:
        raise V2BOracleError(f"{cand.evaluation.candidate_id}: sensitivity neighbor counts invalid")
    if sens.fraction_lower_above_zero != sens.neighbors_lower_above_zero / sens.neighbor_count:
        raise V2BOracleError(
            f"{cand.evaluation.candidate_id}: sensitivity fraction disagrees with its neighbors"
        )
    if sens.all_above_zero != (sens.fraction_lower_above_zero == 1.0):
        raise V2BOracleError(
            f"{cand.evaluation.candidate_id}: sensitivity all_above_zero flag is inconsistent"
        )


def _reconcile_decision(
    decision: dict[str, object],
    candidates: list[_Candidate],
    eligible_ids: tuple[str, ...],
    nominated: str | None,
) -> str | None:
    """Assert the committed decision block equals the independently-derived nomination."""
    require_exact_keys("v2b_results.result.decision", decision, _DECISION_KEYS)
    require_int("v2b_results.result.decision.schema_version", decision["schema_version"])
    committed_eligible = tuple(
        require_list(
            "v2b_results.result.decision.eligible_candidate_ids",
            decision["eligible_candidate_ids"],
            require_slug,
        )
    )
    if committed_eligible != eligible_ids:
        raise V2BOracleError("committed eligible set disagrees with the recomputed eligible set")
    committed_nominated = _parse_nominated(
        "v2b_results.result.decision.nominated_candidate_id", decision["nominated_candidate_id"]
    )
    if committed_nominated != nominated:
        raise V2BOracleError("committed nomination disagrees with the recomputed nomination")
    tie = require_nonempty_str("v2b_results.result.decision.tie_behavior", decision["tie_behavior"])
    if tie != TIE_BEHAVIOR:
        raise V2BOracleError("decision tie_behavior drifted from the frozen policy")
    reason = require_nonempty_str("v2b_results.result.decision.reason", decision["reason"])
    if not eligible_ids and reason != NO_ELIGIBLE_REASON:
        raise V2BOracleError("no-eligible decision reason was altered")
    decision_gates = require_list(
        "v2b_results.result.decision.gates", decision["gates"], _parse_gate_record
    )
    committed_by_id = {c.evaluation.candidate_id: c.gates for c in candidates}
    if tuple(g.candidate_id for g in decision_gates) != EXPECTED_CANDIDATE_IDS:
        raise V2BOracleError("decision gate list does not cover the registered two candidates")
    for record in decision_gates:
        mirror = committed_by_id.get(record.candidate_id)
        if mirror is None or record.gates != mirror.gates or record.eligible != mirror.eligible:
            raise V2BOracleError(
                f"{record.candidate_id}: decision gate record disagrees with the candidate record"
            )
        if record.eligible:
            raise V2BOracleError(f"{record.candidate_id}: decision marks an ineligible candidate")
    return committed_nominated


def _load_json_bytes(raw: bytes, label: str) -> object:
    """Strictly decode committed bytes; surface a NaN / Infinity / dup-key as an oracle error."""
    try:
        return strict_json_loads(raw)
    except ValueError as exc:
        raise V2BOracleError(f"{label} failed strict JSON decode: {exc}") from exc


def _reconstruct_v2b_from_bytes(
    results_bytes: bytes, multiplicity_bytes: bytes
) -> V2BReconstruction:
    return _reconstruct_v2b_from_obj(
        _load_json_bytes(results_bytes, V2B_RESULTS_RELPATH),
        _load_json_bytes(multiplicity_bytes, V2B_MULTIPLICITY_RELPATH),
    )


def reconstruct_v2b(repo_root: str | Path) -> V2BReconstruction:
    """Reconstruct the committed V2B decision from the results and the frozen multiplicity state.

    Reads only committed bytes (``research/v2b/v2b_results.json`` and the multiplicity state) and
    raises :class:`V2BOracleError` on any inconsistency between the decision and its evidence.
    """
    root = Path(repo_root)
    return _reconstruct_v2b_from_bytes(
        (root / V2B_RESULTS_RELPATH).read_bytes(),
        (root / V2B_MULTIPLICITY_RELPATH).read_bytes(),
    )


def verify_v2b_reconstruction(repo_root: str | Path) -> list[str]:
    """Reconstruct the V2B decision and cross-check it against the committed one (empty == OK)."""
    problems: list[str] = []
    try:
        reconstruction = reconstruct_v2b(repo_root)
    except V2ValidationError as exc:
        return [f"v2b reconstruction failed: {exc}"]
    except OSError as exc:  # pragma: no cover - filesystem edge
        return [f"v2b evidence could not be read: {exc}"]

    if reconstruction.nominated_candidate_id is not None:
        problems.append("reconstructed nomination is not null")
    if reconstruction.committed_nominated_candidate_id is not None:
        problems.append("committed nomination is not null")
    if reconstruction.nominated_candidate_id != reconstruction.committed_nominated_candidate_id:
        problems.append("reconstructed nomination disagrees with committed nomination")
    if reconstruction.eligible_candidate_ids:
        problems.append("reconstruction found an eligible candidate")
    if reconstruction.corrected_alpha != reconstruction.expected_alpha:
        problems.append("corrected alpha does not match the family-wise level")
    for candidate in reconstruction.candidates:
        if candidate.eligible != candidate.committed_eligible:
            problems.append(f"{candidate.candidate_id}: eligibility mismatch")
        if candidate.passes_uncorrected:
            problems.append(f"{candidate.candidate_id}: passes the uncorrected diagnostic")
    return problems


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Verify the independent V2B decision reconstruction."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--check", action="store_true", help="Verify the committed evidence (default)."
    )
    args = parser.parse_args(argv)
    problems = verify_v2b_reconstruction(args.repo_root)
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "EXPECTED_BENCHMARK",
    "EXPECTED_CANDIDATE_IDS",
    "GATE_NAMES",
    "UNCORRECTED_NOMINAL_ALPHA",
    "V2B_MULTIPLICITY_RELPATH",
    "V2B_RESULTS_RELPATH",
    "V2BCandidateReconstruction",
    "V2BOracleError",
    "V2BReconstruction",
    "reconstruct_v2b",
    "verify_v2b_reconstruction",
]
