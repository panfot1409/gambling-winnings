"""The V2 commercial-truth pack: an evidence-derived, tamper-evident statement of readiness.

This module derives ONE honest commercial truth for the stacked V2A->V2B state from the
already-committed accepted evidence only. It reads two governed null result sets, the buyer-evidence
boundary, the multiplicity state, the offline shadow policy, and the three byte-empty sealed access
ledgers, and it computes a strict readiness derivation, a fixed set of evidence-backed claims, and
the exact list of ``sell_ready`` blockers. It never evaluates a candidate, reads a sealed partition,
or mutates any accepted artifact; it only reads bytes.

The central invariant is that ``sell_ready`` is a PURE DERIVATION, never a stored settable field
trusted on its own. It is the conjunction of "at least one candidate is nominated" with every
readiness gate that must hold, recomputed from the committed evidence. As long as zero candidates
are nominated and the development-gate and final-holdout ledgers are byte-empty, the derivation
returns false -- and no forged result, removed limitation, or manually toggled artifact field can
change that. The verifier recomputes every readiness boolean from the evidence and rejects any
artifact whose stored values (or stored ``sell_ready``) disagree with the derivation.

Sales-material scanner marker convention
----------------------------------------
``scan_sales_material`` fails on unsupported marketing superlatives (proven alpha, validated alpha,
production ready, sell-ready, guaranteed, low risk, and the rest of ``FORBIDDEN_PHRASES``). It
PERMITS such a phrase only when it is clearly identified as a negated honest statement or as a
false-claim example, via three documented mechanisms (all case-insensitive; hyphens and colons are
normalized to spaces):

* Negation -- a negator ("no", "not", "never", "without", "cannot", ...) within the preceding words
  (the window can span the previous physical line, so a wrapped "V2 NOT / SELL-READY" is permitted).
  This is what lets the repository's honest "not sell-ready" posture pass.
* Paragraph example marker -- the surrounding paragraph (a run of non-blank lines) contains one of
  the marker tokens in ``EXAMPLE_MARKERS`` ("FALSE CLAIM EXAMPLE", "forbidden phrase", "unsupported
  superlative", ...). Paragraph scope is deliberate: a specification that names the forbidden
  phrases still passes when the marker and the enumerated phrases wrap across adjacent lines.
* Fenced example block -- lines strictly between a ``FALSE-CLAIM-EXAMPLES: BEGIN`` sentinel and a
  ``FALSE-CLAIM-EXAMPLES: END`` sentinel are treated as forbidden-phrase examples and permitted.

Everything else is reported as a violation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.v2.constitution import (
    STANDING_POSTURE,
    assert_no_reserved_status,
    require_v2a_emittable_status,
)
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    require_bool,
    require_exact_keys,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_nonnegative_int,
    require_real,
    require_sha256_fingerprint,
    sha256_bytes,
    strict_json_loads,
)

COMMERCIAL_TRUTH_SCHEMA_VERSION: int = 1
COMMERCIAL_TRUTH_RELPATH: str = "research/v2/commercial_truth.json"

#: Domain separation tag for the pack's self-binding digest (never reused by another artifact).
_DIGEST_DOMAIN: bytes = b"eth_research.v2ab.commercial_truth.v1\n"

# --- committed evidence the derivation reads (accepted artifacts; read-only) ---------------------
_V2A_RESULTS: str = "research/v2a/results.json"
_V2B_RESULTS: str = "research/v2b/v2b_results.json"
_BUYER_EVIDENCE: str = "research/v2b/buyer_evidence.json"
_MULTIPLICITY: str = "research/v2b/research_multiplicity_state.json"
_MULTI_ASSET_SHADOW: str = "research/v2b/multi_asset_shadow.json"
_DEV_GATE_LEDGER: str = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER: str = "research/m2b/test_evaluations.jsonl"
_PROSPECTIVE_LEDGER: str = "research/m3d/prospective_evaluations.jsonl"

#: The immutable evidence artifacts whose exact bytes the pack binds (tamper-evidence). A changed
#: result or a removed limitation changes one of these SHAs and is detected by the verifier.
_BOUND_EVIDENCE: tuple[str, ...] = (
    _V2A_RESULTS,
    _V2B_RESULTS,
    _BUYER_EVIDENCE,
    _MULTIPLICITY,
    _MULTI_ASSET_SHADOW,
    _DEV_GATE_LEDGER,
    _HOLDOUT_LEDGER,
    _PROSPECTIVE_LEDGER,
)

#: Completion-record paths that WOULD evidence a forward/live/commercial capability. They are absent
#: today; their absence is the honest evidence that the corresponding gate is not completed. If one
#: is ever legitimately produced and committed, the matching readiness boolean flips on its own.
_COMPLETION_RECORDS: dict[str, str] = {
    "capacity_estimate_completed": "research/v2/capacity_estimate.json",
    "unattended_operation_demonstrated": "research/v2/unattended_operation_record.json",
    "deployment_failure_controls_tested": "research/v2/deployment_failure_drill_record.json",
    "uncontrolled_exposure_prevented": "research/v2/live_exposure_control_proof.json",
    "buyer_can_evaluate_without_repository": "research/v2/standalone_evaluation_bundle.json",
    "buyer_can_deploy_without_source": "research/v2/source_free_deployment_package.json",
    "legal_terms_reviewed": "research/v2/legal_terms_review.json",
    "contributor_ip_clearance_complete": "research/v2/contributor_ip_clearance.json",
}

#: The LICENSE whose presence would evidence ``project_license_chosen`` (absent today).
_LICENSE_CANDIDATES: tuple[str, ...] = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING")

#: The readiness gate keys, in canonical order. ``sell_ready`` is NOT a gate: it is the pure
#: conjunction derived from these plus the presence of a nomination.
READINESS_GATE_KEYS: tuple[str, ...] = (
    "independent_reproduction",
    "untouched_out_of_sample_completed",
    "development_gate_completed",
    "final_holdout_completed",
    "realistic_cost_suite_completed",
    "survives_realistic_costs",
    "parameter_sensitivity_completed",
    "not_single_parameter_dependent",
    "bootstrap_monte_carlo_completed",
    "capacity_estimate_completed",
    "forward_shadow_record_completed",
    "unattended_operation_demonstrated",
    "deployment_failure_controls_tested",
    "uncontrolled_exposure_prevented",
    "buyer_can_evaluate_without_repository",
    "buyer_can_deploy_without_source",
    "claims_fully_evidence_backed",
    "legal_terms_reviewed",
    "project_license_chosen",
    "contributor_ip_clearance_complete",
)

#: A False gate maps to its exact blocker sentence (verifier recomputes and compares this list).
_GATE_BLOCKERS: dict[str, str] = {
    "untouched_out_of_sample_completed": (
        "out_of_sample_not_completed: no untouched out-of-sample evaluation has been completed"
    ),
    "development_gate_completed": (
        "development_gate_not_completed: the sealed development-gate access ledger is byte-empty"
    ),
    "final_holdout_completed": (
        "final_holdout_not_completed: the sealed final-holdout access ledger is byte-empty"
    ),
    "survives_realistic_costs": (
        "edge_does_not_survive_realistic_costs: no nominated edge, so cost survival is not shown"
    ),
    "not_single_parameter_dependent": (
        "single_parameter_dependence_not_ruled_out: no nominee cleared parameter sensitivity"
    ),
    "capacity_estimate_completed": (
        "no_capacity_estimate: no capacity artifact is committed (proxy-only)"
    ),
    "forward_shadow_record_completed": (
        "no_forward_shadow_record: the sealed prospective ledger is byte-empty"
    ),
    "unattended_operation_demonstrated": (
        "unattended_operation_not_demonstrated: shadow is synthetic and offline only"
    ),
    "deployment_failure_controls_tested": (
        "deployment_failure_controls_not_tested: controls exercised synthetically only"
    ),
    "uncontrolled_exposure_prevented": (
        "uncontrolled_exposure_not_proven_prevented: no live evidence exists"
    ),
    "buyer_can_evaluate_without_repository": (
        "buyer_cannot_evaluate_without_repository: no standalone evaluation bundle is committed"
    ),
    "buyer_can_deploy_without_source": (
        "buyer_cannot_deploy_without_source: source and the governed run are withheld"
    ),
    "legal_terms_reviewed": ("legal_terms_not_reviewed: no legal-terms review record is committed"),
    "project_license_chosen": "no_project_license: the repository ships no LICENSE",
    "contributor_ip_clearance_complete": (
        "contributor_ip_clearance_incomplete: no contributor IP-clearance record is committed"
    ),
    "independent_reproduction": (
        "independent_reproduction_missing: the governed null results do not reproduce"
    ),
    "realistic_cost_suite_completed": (
        "realistic_cost_suite_missing: the cost-aware research suite did not run"
    ),
    "parameter_sensitivity_completed": (
        "parameter_sensitivity_missing: the sensitivity suite did not run"
    ),
    "bootstrap_monte_carlo_completed": (
        "bootstrap_monte_carlo_missing: the bootstrap or Monte-Carlo suite did not run"
    ),
    "claims_fully_evidence_backed": (
        "claims_not_fully_evidence_backed: a required claim has no committed evidence path"
    ),
}

_NO_NOMINATION_BLOCKER: str = (
    "no_nominated_candidate: zero of the evaluated V2 candidates were nominated"
)

_PACK_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "readiness",
        "nominated_candidate_count",
        "candidates_evaluated",
        "programs",
        "claims",
        "sell_ready_blockers",
        "evidence",
        "posture",
        "truth_digest",
    }
)

_CLAIM_KEYS: frozenset[str] = frozenset(
    {"claim_id", "statement", "status", "evidence_path", "evidence_pointer"}
)
_PROGRAM_KEYS: frozenset[str] = frozenset(
    {"program", "run_id", "candidates_evaluated", "nominated"}
)
_EVIDENCE_KEYS: frozenset[str] = frozenset({"path", "sha256", "byte_count"})


class CommercialTruthError(V2ValidationError):
    """The commercial-truth pack was malformed, tampered, or disagreed with the evidence."""


# --- required, evidence-backed claims (a fixed catalogue, like the buyer claims catalogue) -------


@dataclass(frozen=True, slots=True)
class TruthClaim:
    """One commercial-truth claim: a scan-clean statement bound to a checkable evidence path."""

    claim_id: str
    statement: str
    status: str
    evidence_path: str
    evidence_pointer: str

    def to_canonical(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "status": self.status,
            "evidence_path": self.evidence_path,
            "evidence_pointer": self.evidence_pointer,
        }


_OBS: str = "research_only_observation"


def required_claims() -> tuple[TruthClaim, ...]:
    """The fixed set of required commercial-truth claims, each traceable to committed evidence."""
    claims = (
        TruthClaim(
            "two_governed_programs_completed",
            "Two governed V2 research programs (V2A and V2B) ran to completion under a "
            "pre-registered, hash-pinned protocol.",
            _OBS,
            _V2B_RESULTS,
            "run_id",
        ),
        TruthClaim(
            "five_candidates_evaluated",
            "Five V2 candidate families were evaluated in total: three in V2A and two in V2B.",
            _OBS,
            _V2A_RESULTS,
            "evaluation.evaluations",
        ),
        TruthClaim(
            "zero_nominated",
            "Zero of the evaluated candidates were nominated; both governed decisions are null.",
            _OBS,
            _V2B_RESULTS,
            "result.decision.nominated_candidate_id",
        ),
        TruthClaim(
            "no_development_gate_access",
            "The sealed development-gate partition was never read; its access ledger is "
            "byte-empty.",
            _OBS,
            _DEV_GATE_LEDGER,
            "byte_count",
        ),
        TruthClaim(
            "no_final_holdout_access",
            "The sealed final-holdout partition was never read; its access ledger is byte-empty.",
            _OBS,
            _HOLDOUT_LEDGER,
            "byte_count",
        ),
        TruthClaim(
            "no_forward_strategy_record",
            "No forward or prospective strategy record exists; the prospective ledger is "
            "byte-empty.",
            _OBS,
            _PROSPECTIVE_LEDGER,
            "byte_count",
        ),
        TruthClaim(
            "no_validated_edge",
            "No validated edge was established; no candidate cleared the eligibility gates.",
            _OBS,
            _V2B_RESULTS,
            "result.decision.eligible_candidate_ids",
        ),
        TruthClaim(
            "offline_operational_platform_exists",
            "An offline, signal-only operational platform exists for the ETH/BTC/cash universe.",
            _OBS,
            _MULTI_ASSET_SHADOW,
            "signal_only",
        ),
        TruthClaim(
            "signal_risk_killswitch_tested_synthetically",
            "Signal generation, risk limits, and the kill switch are exercised on synthetic "
            "panels only.",
            _OBS,
            "src/eth_research/shadow/kill_switch.py",
            "module",
        ),
        TruthClaim(
            "no_live_adapter",
            "There is no live exchange adapter; the platform never connects to a network.",
            _OBS,
            _MULTI_ASSET_SHADOW,
            "prohibitions",
        ),
        TruthClaim(
            "no_money_movement",
            "No money movement is possible; the platform holds no credentials and places no "
            "orders.",
            _OBS,
            _MULTI_ASSET_SHADOW,
            "prohibitions",
        ),
        TruthClaim(
            "buyer_interface_is_reference_boundary",
            "The buyer interface is a source-free reference boundary, not a deployable product.",
            _OBS,
            "src/eth_research/buyer/contract.py",
            "module",
        ),
        TruthClaim(
            "source_free_deployment_not_complete",
            "Source-free commercial deployment is not complete; source and the governed run are "
            "withheld.",
            _OBS,
            "src/eth_research/buyer/contract.py",
            "WITHHELD",
        ),
        TruthClaim(
            "no_project_license",
            "The repository ships no project license; license selection is an external human "
            "decision.",
            _OBS,
            "pyproject.toml",
            "classifiers",
        ),
        TruthClaim(
            "ip_transferability_unresolved",
            "Contributor IP transferability is unresolved and documented as a readiness gap.",
            _OBS,
            "docs/V2A_IP_READINESS.md",
            "document",
        ),
        TruthClaim(
            "v2_not_sell_ready",
            "V2 is not sell-ready; the standing commercial posture is not_sell_ready.",
            STANDING_POSTURE,
            _BUYER_EVIDENCE,
            "posture",
        ),
    )
    # Fail closed if any claim ever reaches for a reserved (overclaiming) status.
    for claim in claims:
        require_v2a_emittable_status(f"claim {claim.claim_id}", claim.status)
    assert_no_reserved_status("required_claims.status", [c.status for c in claims])
    return claims


# --- evidence facts + readiness derivation -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Facts:
    """The primitive facts, read from committed evidence, that the readiness gates derive from."""

    v2a_reproduces_null: bool
    v2b_reproduces_null: bool
    nominated_count: int
    candidates_evaluated: int
    programs: tuple[tuple[str, str, int, bool], ...]
    dev_gate_untouched: bool
    holdout_untouched: bool
    prospective_untouched: bool
    bootstrap_ran: bool
    mc_ran: bool
    sensitivity_ran: bool
    costs_ran: bool
    any_edge_survives_costs: bool
    any_nominee_single_param_cleared: bool
    claims_paths_exist: bool
    completion_present: dict[str, bool]
    license_present: bool


def _read_json(root: Path, relpath: str) -> dict[str, Any]:
    return require_mapping(relpath, strict_json_loads((root / relpath).read_bytes()))


def _ledger_untouched(root: Path, relpath: str) -> bool:
    path = root / relpath
    return path.is_file() and path.stat().st_size == 0


def _v2a_facts(root: Path) -> tuple[bool, int, str, bool]:
    """(reproduces_null, candidate_count, run_id, nominated_is_null) for V2A."""
    data = _read_json(root, _V2A_RESULTS)
    decision = require_mapping(f"{_V2A_RESULTS}.decision", data["decision"])
    outcomes = require_list(
        f"{_V2A_RESULTS}.decision.outcomes", decision["outcomes"], require_mapping
    )
    stored_null = decision["nominated_candidate_id"] is None
    # Independently recompute the null: an outcome is a nominee only if every criterion is true.
    any_nominee = False
    for i, outcome in enumerate(outcomes):
        criteria = require_mapping(f"{_V2A_RESULTS}.outcomes[{i}].criteria", outcome["criteria"])
        if all(require_bool(f"{_V2A_RESULTS}.criteria[{k}]", v) for k, v in criteria.items()):
            any_nominee = True
    run_id = require_nonempty_str(f"{_V2A_RESULTS}.run_id", data["run_id"])
    return (stored_null and not any_nominee), len(outcomes), run_id, stored_null


def _v2b_facts(root: Path) -> tuple[bool, int, str, bool, bool, bool, bool, bool, bool, bool]:
    """Read every V2B fact the derivation needs from the committed cross-asset result set."""
    data = _read_json(root, _V2B_RESULTS)
    result = require_mapping(f"{_V2B_RESULTS}.result", data["result"])
    decision = require_mapping(f"{_V2B_RESULTS}.result.decision", result["decision"])
    candidates = require_list(
        f"{_V2B_RESULTS}.result.candidates", result["candidates"], require_mapping
    )
    stored_null = decision["nominated_candidate_id"] is None
    any_eligible = False
    bootstrap_ran = bool(candidates)
    mc_ran = bool(candidates)
    sensitivity_ran = bool(candidates)
    any_edge_survives = False
    any_single_param_cleared = False
    for i, cand in enumerate(candidates):
        gates_obj = require_mapping(f"{_V2B_RESULTS}.candidates[{i}].gates", cand["gates"])
        gates = require_mapping(f"{_V2B_RESULTS}.candidates[{i}].gates.gates", gates_obj["gates"])
        gate_values = {k: require_bool(f"gates[{k}]", v) for k, v in gates.items()}
        if all(gate_values.values()):
            any_eligible = True
        boot = require_mapping(f"candidates[{i}].corrected_bootstrap", cand["corrected_bootstrap"])
        if require_nonnegative_int("resamples", boot["resamples"]) < 1:
            bootstrap_ran = False
        require_real("mc_sign_flip_p_value", cand["mc_sign_flip_p_value"])
        sens = require_mapping(f"candidates[{i}].sensitivity", cand["sensitivity"])
        if require_nonnegative_int("neighbor_count", sens["neighbor_count"]) < 1:
            sensitivity_ran = False
        if gate_values.get("corrected_lower_above_zero", False) and gate_values.get(
            "stressed_lower_above_zero", False
        ):
            any_edge_survives = True
        if require_bool("sensitivity.all_above_zero", sens["all_above_zero"]):
            any_single_param_cleared = True
    run_id = require_nonempty_str(f"{_V2B_RESULTS}.run_id", data["run_id"])
    alpha = require_real(f"{_V2B_RESULTS}.result.corrected_alpha", result["corrected_alpha"])
    costs_ran = alpha > 0
    return (
        stored_null and not any_eligible,
        len(candidates),
        run_id,
        stored_null,
        bootstrap_ran,
        mc_ran,
        sensitivity_ran,
        costs_ran,
        any_edge_survives,
        any_single_param_cleared,
    )


def _claims_paths_exist(root: Path) -> bool:
    return all((root / claim.evidence_path).exists() for claim in required_claims())


def _read_facts(root: Path) -> _Facts:
    """Read every primitive fact the readiness gates derive from (never mutates anything)."""
    # Assert the buyer boundary and shadow policy are the honest, offline, not-sell-ready ones.
    buyer = _read_json(root, _BUYER_EVIDENCE)
    if require_nonempty_str(f"{_BUYER_EVIDENCE}.posture", buyer["posture"]) != STANDING_POSTURE:
        raise CommercialTruthError("buyer evidence posture is not the standing not_sell_ready")
    shadow = _read_json(root, _MULTI_ASSET_SHADOW)
    require_bool(f"{_MULTI_ASSET_SHADOW}.signal_only", shadow["signal_only"])

    v2a_repro, v2a_count, v2a_run, v2a_null = _v2a_facts(root)
    (
        v2b_repro,
        v2b_count,
        v2b_run,
        v2b_null,
        bootstrap_ran,
        mc_ran,
        sensitivity_ran,
        costs_ran,
        any_edge_survives,
        any_single_param_cleared,
    ) = _v2b_facts(root)

    nominated_count = (0 if v2a_null else 1) + (0 if v2b_null else 1)
    completion_present = {key: (root / rel).exists() for key, rel in _COMPLETION_RECORDS.items()}
    return _Facts(
        v2a_reproduces_null=v2a_repro,
        v2b_reproduces_null=v2b_repro,
        nominated_count=nominated_count,
        candidates_evaluated=v2a_count + v2b_count,
        programs=(("v2a", v2a_run, v2a_count, v2a_null), ("v2b", v2b_run, v2b_count, v2b_null)),
        dev_gate_untouched=_ledger_untouched(root, _DEV_GATE_LEDGER),
        holdout_untouched=_ledger_untouched(root, _HOLDOUT_LEDGER),
        prospective_untouched=_ledger_untouched(root, _PROSPECTIVE_LEDGER),
        bootstrap_ran=bootstrap_ran,
        mc_ran=mc_ran,
        sensitivity_ran=sensitivity_ran,
        costs_ran=costs_ran,
        any_edge_survives_costs=any_edge_survives,
        any_nominee_single_param_cleared=any_single_param_cleared,
        claims_paths_exist=_claims_paths_exist(root),
        completion_present=completion_present,
        license_present=any((root / name).exists() for name in _LICENSE_CANDIDATES),
    )


def _derive_gates(facts: _Facts) -> dict[str, bool]:
    """Compute the 20 readiness gates from the primitive evidence facts (documented per key)."""
    return {
        # Both governed programs reproduce a null nomination from their own evaluation evidence.
        "independent_reproduction": facts.v2a_reproduces_null and facts.v2b_reproduces_null,
        # An out-of-sample evaluation is completed only if a sealed OOS partition was consumed.
        "untouched_out_of_sample_completed": (
            (not facts.dev_gate_untouched) or (not facts.holdout_untouched)
        ),
        "development_gate_completed": not facts.dev_gate_untouched,
        "final_holdout_completed": not facts.holdout_untouched,
        "realistic_cost_suite_completed": facts.costs_ran,
        # Survival of realistic costs requires a nominated edge; there is none.
        "survives_realistic_costs": facts.any_edge_survives_costs,
        "parameter_sensitivity_completed": facts.sensitivity_ran,
        "not_single_parameter_dependent": facts.any_nominee_single_param_cleared,
        "bootstrap_monte_carlo_completed": facts.bootstrap_ran and facts.mc_ran,
        "capacity_estimate_completed": facts.completion_present["capacity_estimate_completed"],
        "forward_shadow_record_completed": not facts.prospective_untouched,
        "unattended_operation_demonstrated": facts.completion_present[
            "unattended_operation_demonstrated"
        ],
        "deployment_failure_controls_tested": facts.completion_present[
            "deployment_failure_controls_tested"
        ],
        "uncontrolled_exposure_prevented": facts.completion_present[
            "uncontrolled_exposure_prevented"
        ],
        "buyer_can_evaluate_without_repository": facts.completion_present[
            "buyer_can_evaluate_without_repository"
        ],
        "buyer_can_deploy_without_source": facts.completion_present[
            "buyer_can_deploy_without_source"
        ],
        "claims_fully_evidence_backed": facts.claims_paths_exist,
        "legal_terms_reviewed": facts.completion_present["legal_terms_reviewed"],
        "project_license_chosen": facts.license_present,
        "contributor_ip_clearance_complete": facts.completion_present[
            "contributor_ip_clearance_complete"
        ],
    }


def pure_sell_ready(gates: Mapping[str, bool], nominated_count: int) -> bool:
    """The ONLY definition of sell-readiness: a nomination AND every readiness gate holding.

    This is a pure function of the derived gates and the nomination count. It returns false whenever
    zero candidates are nominated, regardless of any other value, so no stored field, forged result,
    or removed limitation can force it true while the governed decisions stay null.
    """
    if nominated_count < 1:
        return False
    return all(gates[key] for key in READINESS_GATE_KEYS)


def derive_readiness(repo_root: str | Path) -> dict[str, bool]:
    """Derive the readiness map (20 gates plus the pure ``sell_ready``) from committed evidence."""
    facts = _read_facts(Path(repo_root).resolve())
    gates = _derive_gates(facts)
    readiness = dict(gates)
    readiness["sell_ready"] = pure_sell_ready(gates, facts.nominated_count)
    return readiness


def _derive_blockers(gates: Mapping[str, bool], nominated_count: int) -> list[str]:
    """The exact ``sell_ready`` blockers: the no-nomination blocker plus every False gate."""
    blockers: list[str] = []
    if nominated_count < 1:
        blockers.append(_NO_NOMINATION_BLOCKER)
    for key in READINESS_GATE_KEYS:
        if not gates[key]:
            blockers.append(_GATE_BLOCKERS[key])
    return blockers


# --- build + parse + verify ----------------------------------------------------------------------


def _evidence_records(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for relpath in _BOUND_EVIDENCE:
        data = (root / relpath).read_bytes()
        records.append({"path": relpath, "sha256": sha256_bytes(data), "byte_count": len(data)})
    return records


def _pack_body(root: Path) -> dict[str, object]:
    facts = _read_facts(root)
    gates = _derive_gates(facts)
    readiness = dict(gates)
    readiness["sell_ready"] = pure_sell_ready(gates, facts.nominated_count)
    return {
        "schema_version": COMMERCIAL_TRUTH_SCHEMA_VERSION,
        "readiness": dict(sorted(readiness.items())),
        "nominated_candidate_count": facts.nominated_count,
        "candidates_evaluated": facts.candidates_evaluated,
        "programs": [
            {
                "program": program,
                "run_id": run_id,
                "candidates_evaluated": count,
                "nominated": not is_null,
            }
            for program, run_id, count, is_null in facts.programs
        ],
        "claims": [c.to_canonical() for c in required_claims()],
        "sell_ready_blockers": _derive_blockers(gates, facts.nominated_count),
        "evidence": _evidence_records(root),
        "posture": STANDING_POSTURE,
    }


def _digest_of_body(body: dict[str, object]) -> str:
    return sha256_bytes(_DIGEST_DOMAIN + canonical_json_bytes(body))


def build_commercial_truth(repo_root: str | Path) -> dict[str, object]:
    """Derive the canonical, self-digest-bound commercial-truth pack (never mutates anything)."""
    root = Path(repo_root).resolve()
    body = _pack_body(root)
    pack = dict(body)
    pack["truth_digest"] = _digest_of_body(body)
    return pack


def _parse_claim(label: str, raw: object) -> TruthClaim:
    obj = require_mapping(label, raw)
    require_exact_keys(label, obj, _CLAIM_KEYS)
    return TruthClaim(
        claim_id=require_nonempty_str(f"{label}.claim_id", obj["claim_id"]),
        statement=require_nonempty_str(f"{label}.statement", obj["statement"]),
        status=require_v2a_emittable_status(f"{label}.status", obj["status"]),
        evidence_path=require_nonempty_str(f"{label}.evidence_path", obj["evidence_path"]),
        evidence_pointer=require_nonempty_str(f"{label}.evidence_pointer", obj["evidence_pointer"]),
    )


def parse_commercial_truth(raw_bytes: bytes) -> dict[str, object]:
    """Strictly parse committed pack bytes and re-verify the self-binding digest."""
    obj = require_mapping("commercial_truth", strict_json_loads(raw_bytes))
    require_exact_keys("commercial_truth", obj, _PACK_KEYS)
    if obj["schema_version"] != COMMERCIAL_TRUTH_SCHEMA_VERSION:
        raise CommercialTruthError("unexpected commercial-truth schema_version")
    readiness = require_mapping("commercial_truth.readiness", obj["readiness"])
    for key in (*READINESS_GATE_KEYS, "sell_ready"):
        require_bool(f"commercial_truth.readiness.{key}", readiness.get(key))
    if set(readiness) != {*READINESS_GATE_KEYS, "sell_ready"}:
        raise CommercialTruthError("commercial-truth readiness keys drifted from the fixed set")
    require_list("commercial_truth.claims", obj["claims"], _parse_claim)
    body = {k: obj[k] for k in obj if k != "truth_digest"}
    recomputed = _digest_of_body(body)
    committed = require_sha256_fingerprint("commercial_truth.truth_digest", obj["truth_digest"])
    if recomputed != committed:
        raise CommercialTruthError("commercial-truth self digest does not bind the committed body")
    return obj


def verify_commercial_truth(repo_root: str | Path) -> list[str]:
    """Recompute readiness from the committed evidence and reject any disagreeing/forced pack.

    Returns problems (empty list == OK). It recomputes every readiness boolean and the pure
    ``sell_ready`` derivation from the accepted evidence, so a manually toggled field, a forged
    result, or a removed limitation cannot make ``sell_ready`` true without being detected.
    """
    root = Path(repo_root).resolve()
    path = root / COMMERCIAL_TRUTH_RELPATH
    if path.is_symlink():
        return [f"commercial-truth pack must not be a symlink: {COMMERCIAL_TRUTH_RELPATH}"]
    if not path.exists():
        return [f"commercial-truth pack is missing at {COMMERCIAL_TRUTH_RELPATH}"]
    try:
        obj = parse_commercial_truth(path.read_bytes())
    except V2ValidationError as exc:
        return [f"commercial-truth pack failed strict parse: {exc}"]

    problems: list[str] = []
    try:
        facts = _read_facts(root)
    except V2ValidationError as exc:
        return [f"could not read committed evidence: {exc}"]
    gates = _derive_gates(facts)
    recomputed = dict(gates)
    recomputed["sell_ready"] = pure_sell_ready(gates, facts.nominated_count)

    stored_readiness = require_mapping("readiness", obj["readiness"])
    for key in (*READINESS_GATE_KEYS, "sell_ready"):
        if bool(stored_readiness[key]) != recomputed[key]:
            problems.append(
                f"readiness.{key} stored {stored_readiness[key]!r} disagrees with the "
                f"evidence-derived {recomputed[key]!r}"
            )

    # sell_ready is a pure derivation; a stored true can never stand against a derived false.
    derived_sell_ready = recomputed["sell_ready"]
    if bool(stored_readiness["sell_ready"]) != derived_sell_ready:
        problems.append(
            "sell_ready is a derived value; the stored flag disagrees with the pure derivation"
        )
    if facts.nominated_count < 1 and derived_sell_ready:
        problems.append("invariant violated: sell_ready derived true with zero nominations")

    # Evidence bytes must match what the pack bound (forged result / removed limitation detection).
    stored_evidence = {
        require_nonempty_str("evidence.path", require_mapping("evidence", e)["path"]): e
        for e in require_list("commercial_truth.evidence", obj["evidence"], require_mapping)
    }
    for relpath in _BOUND_EVIDENCE:
        record = stored_evidence.get(relpath)
        if record is None:
            problems.append(f"evidence binding missing for {relpath}")
            continue
        rec = require_mapping("evidence", record)
        live = (root / relpath).read_bytes()
        if rec["sha256"] != sha256_bytes(live) or rec["byte_count"] != len(live):
            problems.append(f"evidence bytes changed since the pack was built: {relpath}")

    # Fixed catalogues and derived fields must not have drifted.
    committed_claims = require_list("commercial_truth.claims", obj["claims"], _parse_claim)
    if tuple(committed_claims) != required_claims():
        problems.append("claims catalogue drifted from the fixed required-claims definition")
    if [str(b) for b in require_list("blk", obj["sell_ready_blockers"], require_nonempty_str)] != (
        _derive_blockers(gates, facts.nominated_count)
    ):
        problems.append("sell_ready_blockers disagree with the evidence-derived blockers")
    if obj["nominated_candidate_count"] != facts.nominated_count:
        problems.append("nominated_candidate_count disagrees with the committed decisions")
    if obj["posture"] != STANDING_POSTURE:
        problems.append("posture is not the standing not_sell_ready")

    # Final catch-all: the whole pack must be exactly what a fresh evidence-only build produces.
    if canonical_json_bytes(obj) != canonical_json_bytes(build_commercial_truth(root)):
        problems.append("committed pack does not match a fresh evidence-only rebuild")
    return problems


# --- adversarial sales-material scanner ----------------------------------------------------------

#: Unsupported marketing superlatives. Stored in normalized (hyphen-free, lowercase) form; matching
#: is whole-phrase with word boundaries, so "deployment readiness" never matches "deployment ready".
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "proven alpha",
    "validated alpha",
    "profitable system",
    "market beating",
    "institutional grade",
    "production ready",
    "deployment ready",
    "sell ready",
    "live tested",
    "out of sample proven",
    "robustly profitable",
    "guaranteed",
    "low risk",
)

#: Case-insensitive markers that identify a line as a false-claim / forbidden-phrase example or as
#: the governance vocabulary that names the prohibition itself. See the module docstring.
EXAMPLE_MARKERS: tuple[str, ...] = (
    "false claim example",
    "forbidden phrase",
    "unsupported superlative",
    "unsupported phrase",
    "prohibited phrase",
    "sales material scanner",
)

_BLOCK_BEGIN: str = "false claim examples begin"
_BLOCK_END: str = "false claim examples end"

_NEGATORS: frozenset[str] = frozenset(
    {
        "no",
        "not",
        "never",
        "non",
        "without",
        "cannot",
        "cant",
        "nor",
        "neither",
        "none",
        "dont",
        "doesnt",
        "didnt",
        "isnt",
        "arent",
        "wasnt",
        "werent",
        "wont",
        "couldnt",
        "shouldnt",
        "wouldnt",
        "hasnt",
        "havent",
        "hadnt",
        "aint",
    }
)

#: How many preceding words (spanning the previous physical line) count as a negation window.
_NEGATION_WINDOW: int = 4

#: Adverbs that, placed between a negator and the phrase, AFFIRM the claim rather than negate it
#: ("not merely a proven alpha" asserts the claim more strongly). A negator followed by one of
#: these never exempts the phrase (F5-C3).
_AFFIRMING_ADVERBS: frozenset[str] = frozenset({"merely", "just", "only", "simply", "purely"})

#: Each phrase also matches a simple plural/-es inflection of its final word ("proven alphas",
#: "profitable systems") — the same overclaim hidden behind an inflection (F5-C3).
_PHRASE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (phrase, re.compile(rf"\b{re.escape(phrase)}(?:e?s)?\b")) for phrase in FORBIDDEN_PHRASES
)

#: The buyer/commercial-facing surface scanned by ``scan_repo_sales_material`` (plus generated
#: reports appended at scan time). The three docs are the ones named by the acceptance plan.
SALES_MATERIAL_RELPATHS: tuple[str, ...] = (
    "README.md",
    "docs/V2B_COMMERCIAL_EVIDENCE.md",
    "docs/V2AB_STACK_ACCEPTANCE_PLAN.md",
    "research/v2b/buyer_evidence.json",
)

#: Generated reports this package produces that are also scanned when present.
_GENERATED_REPORTS: tuple[str, ...] = (COMMERCIAL_TRUTH_RELPATH,)


_APOSTROPHES: tuple[str, ...] = ("'", chr(0x2019))


def _normalize(line: str) -> str:
    """Lowercase; drop apostrophes; turn hyphens and colons into spaces (offsets preserved)."""
    out = line.lower()
    for mark in _APOSTROPHES:
        out = out.replace(mark, "")
    return out.replace("-", " ").replace(":", " ")


def _collapse(line: str) -> str:
    return " ".join(line.split())


def _is_block_sentinel(collapsed: str) -> bool:
    return _BLOCK_BEGIN in collapsed or _BLOCK_END in collapsed


_CLAUSE_TERMINATORS: tuple[str, ...] = (".", ";", "!", "?")


def _is_negated(norm_lines: list[str], index: int, start: int) -> bool:
    """A forbidden phrase counts as negated only when a negator sits within a short window
    immediately before it, in the same clause, with no affirming adverb in between.

    Earlier this scanned any negator within a 12-word window that even spanned the previous line,
    which fails OPEN: a distant or cross-clause negator ("this is *not* a drill: ... proven alpha",
    "there is *no* reason to doubt ... validated alpha") silently exempted a genuine overclaim. The
    window is now short and stops at a clause boundary. A negator followed by an affirming adverb
    ("not *merely* a proven alpha") asserts the claim rather than negating it, so it never exempts
    (F5-C3). An immediate genuine negation ("not a proven alpha") — including one that wraps to the
    previous physical line — is still recognised. This remains a short-window heuristic over the
    project's own committed sales text, not a semantic parser.
    """
    context = ""
    if index > 0:
        context = norm_lines[index - 1] + " "
    context += norm_lines[index][:start]
    words = context.split()
    between: list[str] = []
    for word in reversed(words[-_NEGATION_WINDOW:]):
        if word in _NEGATORS:
            # "not merely/just/only ... <phrase>" affirms the phrase; do not exempt it.
            return not any(w in _AFFIRMING_ADVERBS for w in between)
        if any(word.endswith(term) for term in _CLAUSE_TERMINATORS):
            break  # a clause boundary separates the phrase from any earlier negator
        between.append(word)
    return False


def _paragraph_marker_flags(lines: list[str], collapsed: list[str]) -> list[bool]:
    """Flag each line whose paragraph (a run of non-blank lines) carries an example marker.

    Markers are paragraph-scoped so a specification/example that names the forbidden phrases still
    passes when the marker and the enumerated phrases wrap across adjacent physical lines (the
    committed acceptance plan relies on exactly this: an enumeration line sits next to its
    "false-claim examples" marker line). This scope is a deliberate, author-controlled exemption
    over
    the project's *own* committed sales/spec text — it is not an adversarial-input boundary — and it
    cannot be tightened to line scope without flagging that legitimate enumeration. The Fable 5
    audit
    reviewed and accepted this as a low-severity, author-controlled property; the fenced
    ``FALSE-CLAIM-EXAMPLES`` block remains the primary mechanism for anything sensitive.
    """
    count = len(lines)
    flags = [False] * count
    i = 0
    while i < count:
        if not lines[i].strip():
            i += 1
            continue
        j = i
        while j < count and lines[j].strip():
            j += 1
        # Fenced-block sentinels carry a marker substring but are handled by the block mechanism;
        # they must not exempt neighbouring lines that merely share the paragraph.
        if any(
            marker in collapsed[k]
            for k in range(i, j)
            if not _is_block_sentinel(collapsed[k])
            for marker in EXAMPLE_MARKERS
        ):
            for k in range(i, j):
                flags[k] = True
        i = j
    return flags


def scan_sales_material(text: str, *, source: str) -> list[str]:
    """Return the unsupported-superlative violations in ``text`` (empty list == clean).

    Case-insensitive. A forbidden phrase is permitted only when negated, inside a paragraph that
    carries an example marker, or inside a fenced ``FALSE-CLAIM-EXAMPLES`` block (module docstring).
    """
    lines = text.splitlines()
    norm_lines = [_normalize(line) for line in lines]
    collapsed = [_collapse(nline) for nline in norm_lines]
    para_exempt = _paragraph_marker_flags(lines, collapsed)
    violations: list[str] = []
    in_block = False
    for i, nline in enumerate(norm_lines):
        if _BLOCK_BEGIN in collapsed[i]:
            in_block = True
            continue
        if _BLOCK_END in collapsed[i]:
            in_block = False
            continue
        if in_block or para_exempt[i]:
            continue
        for phrase, pattern in _PHRASE_PATTERNS:
            for match in pattern.finditer(nline):
                if _is_negated(norm_lines, i, match.start()):
                    continue
                violations.append(f"{source}:{i + 1}: unsupported sales phrase {phrase!r}")
    return violations


def scan_repo_sales_material(repo_root: str | Path) -> list[str]:
    """Scan the buyer/commercial-facing surface and generated reports; return all violations."""
    root = Path(repo_root).resolve()
    problems: list[str] = []
    for relpath in (*SALES_MATERIAL_RELPATHS, *_GENERATED_REPORTS):
        path = root / relpath
        if not path.is_file():
            continue
        problems.extend(scan_sales_material(path.read_text(encoding="utf-8"), source=relpath))
    return problems


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(description="Build or verify the V2 commercial-truth pack.")
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true", help="Print the canonical pack to stdout.")
    group.add_argument("--check", action="store_true", help="Verify the committed pack + scan.")
    args = parser.parse_args(argv)

    if args.build:
        os.write(1, canonical_json_bytes(build_commercial_truth(args.repo_root)))
        return 0
    problems = verify_commercial_truth(args.repo_root)
    problems.extend(scan_repo_sales_material(args.repo_root))
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "COMMERCIAL_TRUTH_RELPATH",
    "COMMERCIAL_TRUTH_SCHEMA_VERSION",
    "EXAMPLE_MARKERS",
    "FORBIDDEN_PHRASES",
    "READINESS_GATE_KEYS",
    "SALES_MATERIAL_RELPATHS",
    "CommercialTruthError",
    "TruthClaim",
    "build_commercial_truth",
    "derive_readiness",
    "parse_commercial_truth",
    "pure_sell_ready",
    "required_claims",
    "scan_repo_sales_material",
    "scan_sales_material",
    "verify_commercial_truth",
]
