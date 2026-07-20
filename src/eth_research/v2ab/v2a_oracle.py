"""Independent result-reconstruction oracle for the V2A one-shot research decision.

This module is read-only, result-neutral acceptance tooling. It never re-runs a backtest, evaluates
a candidate, or reads a sealed partition; it only reconstructs the committed V2A *decision* from the
already-committed primitive evidence in ``research/v2a/results.json`` and proves that decision is a
faithful mechanical function of that evidence.

The reconstruction is deliberately independent: it does NOT import or call the audited decision
engine (``eth_research.v2.decision``), the evaluator, or any results renderer. It re-implements,
from scratch, the four pre-registered nomination criteria, the interval-lower-bound-above-zero
test, the fold-win count test, the all-criteria conjunction (eligibility), the at-most-one
nomination rule, and the tie behavior, then asserts the recomputed decision equals the committed
one.

The pre-registered V2A rule (fixed before any candidate ran) nominates a candidate only if it clears
FOUR criteria: (1) it beats the passive benchmark in at least 3 of the 5 out-of-sample folds;
(2) the primary paired-log-excess bootstrap 95% lower bound is above zero; (3) the same holds under
the stressed cost scenario; (4) the aggregate Sharpe is positive. Among the candidates clearing all
four, the single one with the strictly-highest primary point estimate is nominated; a tie, or none
clearing, nominates nobody. The committed accepted outcome is a null: zero candidates eligible, no
nomination. This oracle proves that null is exactly what the evidence yields.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_exact_keys,
    require_hex64,
    require_int,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_real,
    require_slug,
    strict_json_loads,
)
from eth_research.v2.strict import (
    require_bool as _require_bool,
)

V2A_RESULTS_RELPATH: str = "research/v2a/results.json"
V2A_PREREGISTRATION_RELPATH: str = "research/v2a/pre_registration.json"
V2A_MANIFEST_RELPATH: str = "research/v2a/results_manifest.json"

# The pre-registered nomination bar (fixed before any candidate ran; see the V2A protocol).
MIN_FOLDS_BEATING_BENCHMARK: int = 3
EXPECTED_FOLD_COUNT: int = 5

# V2A-emittable statuses and the fixed standing posture (never a live / forward claim).
STATUS_SUPPORTED: str = "research_stage_supported"
STATUS_REJECTED: str = "research_stage_rejected"
STATUS_NOMINATED: str = "eligible_for_development_gate_review"
STANDING_POSTURE: str = "not_sell_ready"

# The four pre-registered criteria keys, exactly as the committed decision records them.
CRITERIA_KEYS: frozenset[str] = frozenset(
    {
        "folds_beating_benchmark",
        "positive_sharpe",
        "primary_lower_above_zero",
        "stressed_robustness",
    }
)

# The three registered V2A candidate families and their frozen spec fingerprints. A relabelled or
# re-specified candidate is caught against these pinned pre-registered identities.
EXPECTED_CANDIDATE_FINGERPRINTS: dict[str, str] = {
    "meanrev_zscore_accumulation": (
        "55e21c3341f1989c321a3223d86628cb4b1da2d439807c9d207721dc9b6a8c6f"
    ),
    "trend_regime_single_horizon": (
        "c5d54b7c18e971bba38bd00eb7dcf36bf16bb284f4780c66e41dd7b9c6642e26"
    ),
    "vol_scaled_hold_drawdown_guard": (
        "54eb7fa8b0e3ecfedde4190e043cff9a436f4c87d4afa2d4268f7d4140e35796"
    ),
}
EXPECTED_CANDIDATE_IDS: frozenset[str] = frozenset(EXPECTED_CANDIDATE_FINGERPRINTS)

# The pinned pre-registered protocol / constitution / budget identities. The benchmark and the
# primary endpoint live inside the protocol, so a changed benchmark or endpoint reruns the protocol
# and changes this fingerprint; that drift is caught here.
EXPECTED_PROTOCOL_FINGERPRINT: str = (
    "2854a8065845b7a7eff344044dbfdcaf3456d002c0e32f91c039a5431b56054f"
)
EXPECTED_CONSTITUTION_FINGERPRINT: str = (
    "ebdd6dd4496f1fd79c352cba5c4f447cedeb1c22fd6568b2dc62450c74d3e2c4"
)
EXPECTED_BUDGET_FINGERPRINT: str = (
    "b9cb17cc534405c1967364e770713838e4e8c5fa64d8a5563d234e865e8df145"
)

_RESULTS_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "run_id",
        "package_version",
        "research_train_fingerprint",
        "protocol_fingerprint",
        "constitution_fingerprint",
        "budget_fingerprint",
        "candidate_fingerprints",
        "evaluation",
        "decision",
    }
)
_EVALUATION_KEYS: frozenset[str] = frozenset(
    {"protocol_fingerprint", "periods_per_year", "evaluations"}
)
_EVAL_ENTRY_KEYS: frozenset[str] = frozenset(
    {
        "candidate_id",
        "fold_count",
        "folds_beating_benchmark",
        "primary_point_estimate",
        "primary_ci_lower",
        "primary_ci_upper",
        "primary_lower_above_zero",
        "stressed_lower_above_zero",
        "aggregate_sharpe",
    }
)
_DECISION_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "protocol_fingerprint",
        "constitution_fingerprint",
        "standing_posture",
        "outcomes",
        "nominated_candidate_id",
    }
)
_OUTCOME_KEYS: frozenset[str] = frozenset({"candidate_id", "status", "criteria", "nominated"})
_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "nominated_candidate_id",
        "results_file",
        "results_fingerprint",
        "results_sha256",
        "run_id",
        "schema_version",
    }
)


class V2AOracleError(V2ValidationError):
    """The reconstructed V2A decision does not faithfully follow the committed evidence."""


# --------------------------------------------------------------------------- #
# independent decision primitives (our own logic, not the audited engine)      #
# --------------------------------------------------------------------------- #
def _interval_lower_above_zero(lower: float) -> bool:
    """Independent one-sided read: a 95% interval lower bound clears zero iff it is > 0."""
    return lower > 0.0


def _meets_fold_minimum(folds_beating: int, minimum: int) -> bool:
    """Independent count test: at least ``minimum`` out-of-sample folds must beat the benchmark."""
    return folds_beating >= minimum


def _v2a_criteria(entry: _EvalEntry) -> dict[str, bool]:
    """Recompute the four pre-registered criteria for one candidate from its raw evidence."""
    return {
        "folds_beating_benchmark": _meets_fold_minimum(
            entry.folds_beating_benchmark, MIN_FOLDS_BEATING_BENCHMARK
        ),
        "positive_sharpe": entry.aggregate_sharpe > 0.0,
        "primary_lower_above_zero": _interval_lower_above_zero(entry.primary_ci_lower),
        "stressed_robustness": entry.stressed_lower_above_zero,
    }


def _nominate(eligible: list[tuple[str, float]]) -> str | None:
    """At-most-one rule: the single eligible candidate with the strictly-highest point estimate."""
    if not eligible:
        return None
    top = max(estimate for _, estimate in eligible)
    leaders = [cid for cid, estimate in eligible if estimate == top]
    return leaders[0] if len(leaders) == 1 else None


# --------------------------------------------------------------------------- #
# parsed-evidence + reconstruction dataclasses                                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _EvalEntry:
    candidate_id: str
    fold_count: int
    folds_beating_benchmark: int
    primary_point_estimate: float
    primary_ci_lower: float
    primary_ci_upper: float
    primary_lower_above_zero: bool
    stressed_lower_above_zero: bool
    aggregate_sharpe: float


@dataclass(frozen=True, slots=True)
class _Outcome:
    candidate_id: str
    status: str
    criteria: dict[str, bool]
    nominated: bool


@dataclass(frozen=True, slots=True)
class V2ACandidateReconstruction:
    """One candidate's independently-recomputed criteria vector and derived status."""

    candidate_id: str
    fold_count: int
    folds_beating_benchmark: int
    primary_ci_lower: float
    primary_point_estimate: float
    aggregate_sharpe: float
    criteria: dict[str, bool]
    eligible: bool
    reconstructed_status: str
    committed_status: str
    lenient_point_above_zero: bool
    lenient_eligible: bool


@dataclass(frozen=True, slots=True)
class V2AReconstruction:
    """The independently-reconstructed V2A decision, ready for cross-checking the committed one."""

    run_id: str
    candidate_ids: tuple[str, ...]
    candidate_fingerprints: dict[str, str]
    candidates: tuple[V2ACandidateReconstruction, ...]
    eligible_candidate_ids: tuple[str, ...]
    nominated_candidate_id: str | None
    committed_nominated_candidate_id: str | None
    lenient_eligible_candidate_ids: tuple[str, ...]
    standing_posture: str


# --------------------------------------------------------------------------- #
# strict parsing of the committed evidence                                     #
# --------------------------------------------------------------------------- #
def _parse_eval_entry(label: str, value: object) -> _EvalEntry:
    obj = require_mapping(label, value)
    require_exact_keys(label, obj, _EVAL_ENTRY_KEYS)
    return _EvalEntry(
        candidate_id=require_slug(f"{label}.candidate_id", obj["candidate_id"]),
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
        aggregate_sharpe=require_real(f"{label}.aggregate_sharpe", obj["aggregate_sharpe"]),
    )


def _parse_outcome(label: str, value: object) -> _Outcome:
    obj = require_mapping(label, value)
    require_exact_keys(label, obj, _OUTCOME_KEYS)
    criteria_obj = require_mapping(f"{label}.criteria", obj["criteria"])
    require_exact_keys(f"{label}.criteria", criteria_obj, CRITERIA_KEYS)
    criteria = {
        key: _require_bool(f"{label}.criteria.{key}", criteria_obj[key]) for key in CRITERIA_KEYS
    }
    return _Outcome(
        candidate_id=require_slug(f"{label}.candidate_id", obj["candidate_id"]),
        status=require_nonempty_str(f"{label}.status", obj["status"]),
        criteria=criteria,
        nominated=_require_bool(f"{label}.nominated", obj["nominated"]),
    )


def _parse_nominated(label: str, value: object) -> str | None:
    """Decode the nomination id: a JSON null is no nomination; an empty string is rejected."""
    if value is None:
        return None
    return require_slug(label, value)


# --------------------------------------------------------------------------- #
# the reconstruction                                                           #
# --------------------------------------------------------------------------- #
def _reconstruct_v2a_from_obj(results_obj: object) -> V2AReconstruction:
    """Reconstruct and self-verify the V2A decision from an already-decoded results object."""
    obj = require_mapping("v2a_results", results_obj)
    require_exact_keys("v2a_results", obj, _RESULTS_KEYS)

    run_id = require_slug("v2a_results.run_id", obj["run_id"])
    require_int("v2a_results.schema_version", obj["schema_version"])
    require_nonempty_str("v2a_results.package_version", obj["package_version"])
    require_nonempty_str(
        "v2a_results.research_train_fingerprint", obj["research_train_fingerprint"]
    )
    protocol_fp = require_hex64("v2a_results.protocol_fingerprint", obj["protocol_fingerprint"])
    constitution_fp = require_hex64(
        "v2a_results.constitution_fingerprint", obj["constitution_fingerprint"]
    )
    budget_fp = require_hex64("v2a_results.budget_fingerprint", obj["budget_fingerprint"])
    if protocol_fp != EXPECTED_PROTOCOL_FINGERPRINT:
        raise V2AOracleError("protocol fingerprint drifted from the pre-registered V2A protocol")
    if constitution_fp != EXPECTED_CONSTITUTION_FINGERPRINT:
        raise V2AOracleError("constitution fingerprint drifted from the pre-registered value")
    if budget_fp != EXPECTED_BUDGET_FINGERPRINT:
        raise V2AOracleError("budget fingerprint drifted from the pre-registered value")

    fp_obj = require_mapping("v2a_results.candidate_fingerprints", obj["candidate_fingerprints"])
    candidate_fingerprints = {
        require_slug("v2a_results.candidate_fingerprints.key", key): require_hex64(
            f"v2a_results.candidate_fingerprints.{key}", val
        )
        for key, val in fp_obj.items()
    }
    if candidate_fingerprints != EXPECTED_CANDIDATE_FINGERPRINTS:
        raise V2AOracleError("candidate ids / fingerprints differ from the registered three")

    evaluation = require_mapping("v2a_results.evaluation", obj["evaluation"])
    require_exact_keys("v2a_results.evaluation", evaluation, _EVALUATION_KEYS)
    eval_protocol_fp = require_hex64(
        "v2a_results.evaluation.protocol_fingerprint", evaluation["protocol_fingerprint"]
    )
    require_real("v2a_results.evaluation.periods_per_year", evaluation["periods_per_year"])
    if eval_protocol_fp != protocol_fp:
        raise V2AOracleError("evaluation protocol fingerprint disagrees with the results header")
    entries = require_list(
        "v2a_results.evaluation.evaluations", evaluation["evaluations"], _parse_eval_entry
    )

    decision = require_mapping("v2a_results.decision", obj["decision"])
    require_exact_keys("v2a_results.decision", decision, _DECISION_KEYS)
    require_int("v2a_results.decision.schema_version", decision["schema_version"])
    dec_protocol_fp = require_hex64(
        "v2a_results.decision.protocol_fingerprint", decision["protocol_fingerprint"]
    )
    dec_constitution_fp = require_hex64(
        "v2a_results.decision.constitution_fingerprint", decision["constitution_fingerprint"]
    )
    if dec_protocol_fp != protocol_fp or dec_constitution_fp != constitution_fp:
        raise V2AOracleError("decision fingerprints disagree with the results header")
    standing_posture = require_nonempty_str(
        "v2a_results.decision.standing_posture", decision["standing_posture"]
    )
    if standing_posture != STANDING_POSTURE:
        raise V2AOracleError(f"standing posture must be {STANDING_POSTURE!r}")
    outcomes = require_list("v2a_results.decision.outcomes", decision["outcomes"], _parse_outcome)
    committed_nominated = _parse_nominated(
        "v2a_results.decision.nominated_candidate_id", decision["nominated_candidate_id"]
    )

    return _reconcile_v2a(
        run_id, candidate_fingerprints, entries, outcomes, committed_nominated, standing_posture
    )


def _reconcile_v2a(
    run_id: str,
    candidate_fingerprints: dict[str, str],
    entries: list[_EvalEntry],
    outcomes: list[_Outcome],
    committed_nominated: str | None,
    standing_posture: str,
) -> V2AReconstruction:
    """Recompute the decision from evidence and assert it matches the committed decision."""
    eval_ids = [entry.candidate_id for entry in entries]
    outcome_ids = [outcome.candidate_id for outcome in outcomes]
    if len(eval_ids) != len(EXPECTED_CANDIDATE_IDS) or set(eval_ids) != EXPECTED_CANDIDATE_IDS:
        raise V2AOracleError("evaluation candidate set is not the registered three")
    if len(set(eval_ids)) != len(eval_ids):
        raise V2AOracleError("duplicate candidate id in the evaluation set")
    if set(outcome_ids) != EXPECTED_CANDIDATE_IDS or len(set(outcome_ids)) != len(outcome_ids):
        raise V2AOracleError("decision outcome set does not match the evaluation set")

    outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}

    # First pass: per-candidate criteria + structural invariants; collect the eligible set.
    criteria_by_id: dict[str, dict[str, bool]] = {}
    eligible: list[tuple[str, float]] = []
    for entry in entries:
        _assert_entry_invariants(entry)
        criteria = _v2a_criteria(entry)
        criteria_by_id[entry.candidate_id] = criteria
        committed = outcome_by_id[entry.candidate_id]
        if criteria != committed.criteria:
            raise V2AOracleError(
                f"{entry.candidate_id}: recomputed criteria disagree with the committed decision"
            )
        if all(criteria.values()):
            eligible.append((entry.candidate_id, entry.primary_point_estimate))

    nominated = _nominate(eligible)
    if nominated != committed_nominated:
        raise V2AOracleError(
            "recomputed nomination disagrees with the committed nominated_candidate_id"
        )

    # Second pass: derive each status independently and assert it matches the committed status.
    candidates: list[V2ACandidateReconstruction] = []
    lenient_eligible: list[str] = []
    for entry in entries:
        criteria = criteria_by_id[entry.candidate_id]
        is_eligible = all(criteria.values())
        committed = outcome_by_id[entry.candidate_id]
        expected_nominated = entry.candidate_id == nominated
        if committed.nominated != expected_nominated:
            raise V2AOracleError(f"{entry.candidate_id}: committed nominated flag is inconsistent")
        if expected_nominated:
            status = STATUS_NOMINATED
        elif is_eligible:
            status = STATUS_SUPPORTED
        else:
            status = STATUS_REJECTED
        if committed.status != status:
            raise V2AOracleError(
                f"{entry.candidate_id}: committed status {committed.status!r} != reconstructed "
                f"{status!r}"
            )
        # Most-lenient uncorrected diagnostic: grant the primary criterion on the point estimate
        # alone (no interval, no correction). It must still not flip any candidate to eligible.
        lenient_point = entry.primary_point_estimate > 0.0
        lenient_ok = (
            criteria["folds_beating_benchmark"]
            and lenient_point
            and criteria["stressed_robustness"]
            and criteria["positive_sharpe"]
        )
        if lenient_ok:
            lenient_eligible.append(entry.candidate_id)
        candidates.append(
            V2ACandidateReconstruction(
                candidate_id=entry.candidate_id,
                fold_count=entry.fold_count,
                folds_beating_benchmark=entry.folds_beating_benchmark,
                primary_ci_lower=entry.primary_ci_lower,
                primary_point_estimate=entry.primary_point_estimate,
                aggregate_sharpe=entry.aggregate_sharpe,
                criteria=criteria,
                eligible=is_eligible,
                reconstructed_status=status,
                committed_status=committed.status,
                lenient_point_above_zero=lenient_point,
                lenient_eligible=lenient_ok,
            )
        )

    eligible_ids = tuple(cid for cid, _ in eligible)
    # The accepted V2A outcome is a null: the evidence must yield zero eligible and no nomination.
    if eligible_ids or nominated is not None:
        raise V2AOracleError("evidence yields an eligible candidate; the accepted null is violated")
    if lenient_eligible:
        raise V2AOracleError("the lenient uncorrected diagnostic flipped a candidate to eligible")

    return V2AReconstruction(
        run_id=run_id,
        candidate_ids=tuple(eval_ids),
        candidate_fingerprints=candidate_fingerprints,
        candidates=tuple(candidates),
        eligible_candidate_ids=eligible_ids,
        nominated_candidate_id=nominated,
        committed_nominated_candidate_id=committed_nominated,
        lenient_eligible_candidate_ids=tuple(lenient_eligible),
        standing_posture=standing_posture,
    )


def _assert_entry_invariants(entry: _EvalEntry) -> None:
    """Structural checks binding an entry's interval, point, bool flag, and fold counts."""
    if entry.fold_count != EXPECTED_FOLD_COUNT:
        raise V2AOracleError(f"{entry.candidate_id}: fold_count {entry.fold_count} != 5")
    if not 0 <= entry.folds_beating_benchmark <= entry.fold_count:
        raise V2AOracleError(f"{entry.candidate_id}: folds_beating_benchmark out of range")
    if entry.primary_ci_lower > entry.primary_ci_upper:
        raise V2AOracleError(f"{entry.candidate_id}: primary interval is inverted")
    if not entry.primary_ci_lower <= entry.primary_point_estimate <= entry.primary_ci_upper:
        raise V2AOracleError(f"{entry.candidate_id}: point estimate lies outside its interval")
    if entry.primary_lower_above_zero != _interval_lower_above_zero(entry.primary_ci_lower):
        raise V2AOracleError(
            f"{entry.candidate_id}: primary_lower_above_zero disagrees with the interval bound"
        )


def _load_json_bytes(raw: bytes, label: str) -> object:
    """Strictly decode committed bytes; surface a NaN / Infinity / dup-key as an oracle error."""
    try:
        return strict_json_loads(raw)
    except ValueError as exc:
        raise V2AOracleError(f"{label} failed strict JSON decode: {exc}") from exc


def _reconstruct_v2a_from_bytes(raw: bytes) -> V2AReconstruction:
    return _reconstruct_v2a_from_obj(_load_json_bytes(raw, V2A_RESULTS_RELPATH))


def reconstruct_v2a(repo_root: str | Path) -> V2AReconstruction:
    """Reconstruct the committed V2A decision from ``research/v2a/results.json`` and its provenance.

    Reads only committed bytes. Beyond the results-internal reconstruction it binds the results to
    the pre-registration and to the results manifest (shared identities + the manifest's own
    SHA-256 of the canonical results). Raises :class:`V2AOracleError` on any inconsistency.
    """
    root = Path(repo_root)
    results_bytes = (root / V2A_RESULTS_RELPATH).read_bytes()
    results_obj = _load_json_bytes(results_bytes, V2A_RESULTS_RELPATH)
    reconstruction = _reconstruct_v2a_from_obj(results_obj)
    _bind_v2a_provenance(root, results_obj)
    return reconstruction


def _bind_v2a_provenance(root: Path, results_obj: object) -> None:
    """Cross-bind the results to the committed pre-registration and results manifest."""
    header = require_mapping("v2a_results", results_obj)
    prereg = require_mapping(
        "v2a_pre_registration",
        _load_json_bytes(
            (root / V2A_PREREGISTRATION_RELPATH).read_bytes(), V2A_PREREGISTRATION_RELPATH
        ),
    )
    for field in (
        "protocol_fingerprint",
        "constitution_fingerprint",
        "budget_fingerprint",
        "run_id",
        "package_version",
    ):
        if prereg.get(field) != header.get(field):
            raise V2AOracleError(f"pre-registration {field} disagrees with the results header")

    manifest = require_mapping(
        "v2a_results_manifest",
        _load_json_bytes((root / V2A_MANIFEST_RELPATH).read_bytes(), V2A_MANIFEST_RELPATH),
    )
    require_exact_keys("v2a_results_manifest", manifest, _MANIFEST_KEYS)
    manifest_sha = require_hex64("v2a_results_manifest.results_sha256", manifest["results_sha256"])
    if manifest_sha != canonical_sha256(results_obj):
        raise V2AOracleError("results manifest SHA-256 does not bind the committed results bytes")
    decision = require_mapping("v2a_results.decision", header["decision"])
    if manifest["nominated_candidate_id"] != decision["nominated_candidate_id"]:
        raise V2AOracleError("results manifest nomination disagrees with the decision")


def verify_v2a_reconstruction(repo_root: str | Path) -> list[str]:
    """Reconstruct the V2A decision and cross-check it against the committed one (empty == OK)."""
    problems: list[str] = []
    try:
        reconstruction = reconstruct_v2a(repo_root)
    except V2ValidationError as exc:
        return [f"v2a reconstruction failed: {exc}"]
    except OSError as exc:  # pragma: no cover - filesystem edge
        return [f"v2a evidence could not be read: {exc}"]

    if reconstruction.nominated_candidate_id is not None:
        problems.append("reconstructed nomination is not null")
    if reconstruction.committed_nominated_candidate_id is not None:
        problems.append("committed nomination is not null")
    if reconstruction.nominated_candidate_id != reconstruction.committed_nominated_candidate_id:
        problems.append("reconstructed nomination disagrees with committed nomination")
    if reconstruction.eligible_candidate_ids:
        problems.append("reconstruction found an eligible candidate")
    if reconstruction.lenient_eligible_candidate_ids:
        problems.append("lenient uncorrected diagnostic flips a candidate")
    for candidate in reconstruction.candidates:
        if candidate.reconstructed_status != candidate.committed_status:
            problems.append(f"{candidate.candidate_id}: status mismatch")
    return problems


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Verify the independent V2A decision reconstruction."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--check", action="store_true", help="Verify the committed evidence (default)."
    )
    args = parser.parse_args(argv)
    problems = verify_v2a_reconstruction(args.repo_root)
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "EXPECTED_CANDIDATE_FINGERPRINTS",
    "EXPECTED_CANDIDATE_IDS",
    "MIN_FOLDS_BEATING_BENCHMARK",
    "V2A_RESULTS_RELPATH",
    "V2ACandidateReconstruction",
    "V2AOracleError",
    "V2AReconstruction",
    "reconstruct_v2a",
    "verify_v2a_reconstruction",
]
