"""V2A-V2B commercial-truth pack: readiness derivation + adversarial sales-material scanner.

Two test surfaces: a hermetic synthetic evidence tree (for the build/verify/derivation and the
tamper matrix) and the real repository (for the clean happy path and the real-doc scan).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eth_research.v2.strict import V2ValidationError, canonical_json_bytes, strict_json_loads
from eth_research.v2ab.commercial_truth import (
    COMMERCIAL_TRUTH_RELPATH,
    FORBIDDEN_PHRASES,
    READINESS_GATE_KEYS,
    CommercialTruthError,
    _digest_of_body,  # private: digest re-binding tests
    build_commercial_truth,
    derive_readiness,
    parse_commercial_truth,
    pure_sell_ready,
    required_claims,
    scan_repo_sales_material,
    scan_sales_material,
    verify_commercial_truth,
)

# --- synthetic evidence tree ---------------------------------------------------------------------

_NULL_GATES: dict[str, bool] = {
    "strict_fold_majority": True,
    "primary_lower_above_zero": False,
    "corrected_lower_above_zero": False,
    "stressed_lower_above_zero": False,
    "latency_lower_above_zero": False,
    "mc_supports": False,
    "sensitivity_all_above_zero": False,
}
_ELIGIBLE_GATES: dict[str, bool] = dict.fromkeys(_NULL_GATES, True)

_CLAIM_EVIDENCE_FILES: tuple[str, ...] = (
    "src/eth_research/shadow/kill_switch.py",
    "src/eth_research/buyer/contract.py",
    "pyproject.toml",
    "docs/V2A_IP_READINESS.md",
)


def _write(root: Path, relpath: str, payload: object) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _v2b_candidate(neighbors: int, gates: dict[str, bool]) -> dict[str, Any]:
    return {
        "gates": {"gates": dict(gates)},
        "corrected_bootstrap": {"resamples": 20000},
        "mc_sign_flip_p_value": 0.14,
        "sensitivity": {
            "neighbor_count": neighbors,
            "all_above_zero": gates["sensitivity_all_above_zero"],
        },
    }


def _seed(
    root: Path,
    *,
    v2a_nominated: str | None = None,
    v2b_nominated: str | None = None,
    v2b_gates: tuple[dict[str, bool], dict[str, bool]] = (_NULL_GATES, _NULL_GATES),
) -> None:
    """A minimal but valid committed-evidence tree the derivation can read end to end."""
    _write(
        root,
        "research/v2a/results.json",
        {
            "run_id": "run_001",
            "decision": {
                "nominated_candidate_id": v2a_nominated,
                "outcomes": [
                    {"criteria": {"positive_sharpe": True, "folds_beating_benchmark": False}},
                    {"criteria": {"positive_sharpe": True, "folds_beating_benchmark": False}},
                    {"criteria": {"positive_sharpe": True, "folds_beating_benchmark": False}},
                ],
            },
        },
    )
    _write(
        root,
        "research/v2b/v2b_results.json",
        {
            "run_id": "v2b_run_001",
            "result": {
                "corrected_alpha": 0.005,
                "decision": {"nominated_candidate_id": v2b_nominated},
                "candidates": [
                    _v2b_candidate(9, v2b_gates[0]),
                    _v2b_candidate(3, v2b_gates[1]),
                ],
            },
        },
    )
    _write(root, "research/v2b/buyer_evidence.json", {"posture": "not_sell_ready"})
    _write(root, "research/v2b/research_multiplicity_state.json", {"total_family_count": 10})
    _write(
        root,
        "research/v2b/multi_asset_shadow.json",
        {"signal_only": True, "prohibitions": ["no_network", "no_money_movement"]},
    )
    for rel in (
        "research/m3a/development_gate_access.jsonl",
        "research/m2b/test_evaluations.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"")
    for rel in _CLAIM_EVIDENCE_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("# placeholder\n", encoding="utf-8")


def _build_to_disk(root: Path) -> dict[str, object]:
    pack = build_commercial_truth(root)
    (root / COMMERCIAL_TRUTH_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    (root / COMMERCIAL_TRUTH_RELPATH).write_bytes(canonical_json_bytes(pack))
    return pack


def _reserialize(root: Path, obj: dict[str, Any]) -> None:
    """Rewrite the pack after re-binding its self digest (a sophisticated forger)."""
    body = {k: obj[k] for k in obj if k != "truth_digest"}
    obj["truth_digest"] = _digest_of_body(body)
    (root / COMMERCIAL_TRUTH_RELPATH).write_bytes(canonical_json_bytes(obj))


# --- build + derivation --------------------------------------------------------------------------


def test_build_and_verify_clean(tmp_path: Path) -> None:
    _seed(tmp_path)
    _build_to_disk(tmp_path)
    assert verify_commercial_truth(tmp_path) == []


def test_derived_readiness_matches_specification(tmp_path: Path) -> None:
    _seed(tmp_path)
    readiness = derive_readiness(tmp_path)
    expected = {
        "independent_reproduction": True,
        "untouched_out_of_sample_completed": False,
        "development_gate_completed": False,
        "final_holdout_completed": False,
        "realistic_cost_suite_completed": True,
        "survives_realistic_costs": False,
        "parameter_sensitivity_completed": True,
        "not_single_parameter_dependent": False,
        "bootstrap_monte_carlo_completed": True,
        "capacity_estimate_completed": False,
        "forward_shadow_record_completed": False,
        "unattended_operation_demonstrated": False,
        "deployment_failure_controls_tested": False,
        "uncontrolled_exposure_prevented": False,
        "buyer_can_evaluate_without_repository": False,
        "buyer_can_deploy_without_source": False,
        "claims_fully_evidence_backed": True,
        "legal_terms_reviewed": False,
        "project_license_chosen": False,
        "contributor_ip_clearance_complete": False,
        "sell_ready": False,
    }
    assert readiness == expected


def test_pack_counts_and_blockers(tmp_path: Path) -> None:
    _seed(tmp_path)
    pack = build_commercial_truth(tmp_path)
    assert pack["nominated_candidate_count"] == 0
    assert pack["candidates_evaluated"] == 5
    assert pack["posture"] == "not_sell_ready"
    blockers = pack["sell_ready_blockers"]
    assert isinstance(blockers, list)
    # one no-nomination blocker plus one per False gate.
    false_gates = sum(1 for k in READINESS_GATE_KEYS if not derive_readiness(tmp_path)[k])
    assert len(blockers) == 1 + false_gates
    assert any("no_nominated_candidate" in b for b in blockers)


def test_all_required_claim_paths_exist_in_seed(tmp_path: Path) -> None:
    _seed(tmp_path)
    for claim in required_claims():
        assert (tmp_path / claim.evidence_path).exists()


def test_digest_binds_body(tmp_path: Path) -> None:
    _seed(tmp_path)
    pack = _build_to_disk(tmp_path)
    obj = strict_json_loads((tmp_path / COMMERCIAL_TRUTH_RELPATH).read_bytes())
    body = {k: obj[k] for k in obj if k != "truth_digest"}
    assert _digest_of_body(body) == pack["truth_digest"]


# --- sell_ready is a pure derivation, not a trusted field ----------------------------------------


def test_pure_sell_ready_requires_nomination_and_every_gate() -> None:
    all_true = dict.fromkeys(READINESS_GATE_KEYS, True)
    assert pure_sell_ready(all_true, 1) is True  # the only shape that is sell-ready
    assert pure_sell_ready(all_true, 0) is False  # no nomination -> never
    one_false = dict(all_true)
    one_false["development_gate_completed"] = False
    assert pure_sell_ready(one_false, 1) is False  # a single open gate blocks it


def test_toggled_sell_ready_field_is_rejected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _build_to_disk(tmp_path)
    obj = strict_json_loads((tmp_path / COMMERCIAL_TRUTH_RELPATH).read_bytes())
    obj["readiness"]["sell_ready"] = True
    _reserialize(tmp_path, obj)  # even with a re-bound self digest...
    problems = verify_commercial_truth(tmp_path)
    assert any("sell_ready" in p for p in problems)  # ...the derivation still rejects it


def test_toggled_gate_field_is_rejected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _build_to_disk(tmp_path)
    obj = strict_json_loads((tmp_path / COMMERCIAL_TRUTH_RELPATH).read_bytes())
    obj["readiness"]["development_gate_completed"] = True
    _reserialize(tmp_path, obj)
    problems = verify_commercial_truth(tmp_path)
    assert any("development_gate_completed" in p for p in problems)


def test_forged_nomination_cannot_force_sell_ready(tmp_path: Path) -> None:
    # Forge the strongest possible result: a nominated, fully-eligible candidate whose
    # corrected/stressed intervals and sensitivity all clear. The sealed ledgers stay empty.
    _seed(
        tmp_path,
        v2b_nominated="cross_asset_btc_confirmed_eth_trend",
        v2b_gates=(_ELIGIBLE_GATES, _NULL_GATES),
    )
    readiness = derive_readiness(tmp_path)
    assert readiness["survives_realistic_costs"] is True  # forged edge fields took effect...
    assert readiness["sell_ready"] is False  # ...yet sell_ready stays false (gates untouched)


def test_forced_all_gates_but_zero_nomination_still_not_sell_ready(tmp_path: Path) -> None:
    _seed(tmp_path)
    _build_to_disk(tmp_path)
    obj = strict_json_loads((tmp_path / COMMERCIAL_TRUTH_RELPATH).read_bytes())
    for key in READINESS_GATE_KEYS:
        obj["readiness"][key] = True
    obj["readiness"]["sell_ready"] = True
    _reserialize(tmp_path, obj)
    problems = verify_commercial_truth(tmp_path)
    assert problems  # every fabricated gate disagrees with the evidence-derived false


def test_forged_result_bytes_detected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _build_to_disk(tmp_path)
    # Change the accepted result bytes after the pack was built (a forged result).
    _write(
        tmp_path,
        "research/v2b/v2b_results.json",
        {
            "run_id": "v2b_run_001",
            "result": {
                "corrected_alpha": 0.005,
                "decision": {"nominated_candidate_id": "cross_asset_btc_confirmed_eth_trend"},
                "candidates": [_v2b_candidate(9, _ELIGIBLE_GATES), _v2b_candidate(3, _NULL_GATES)],
            },
        },
    )
    problems = verify_commercial_truth(tmp_path)
    assert any("evidence bytes changed" in p for p in problems)


def test_removed_limitation_detected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _build_to_disk(tmp_path)
    # Mutate the buyer-evidence bytes (as if a limitation were removed).
    _write(tmp_path, "research/v2b/buyer_evidence.json", {"posture": "not_sell_ready", "x": 1})
    problems = verify_commercial_truth(tmp_path)
    assert any("evidence bytes changed" in p and "buyer_evidence" in p for p in problems)


def test_missing_pack_detected(tmp_path: Path) -> None:
    _seed(tmp_path)
    problems = verify_commercial_truth(tmp_path)
    assert any("missing" in p for p in problems)


def test_tampered_digest_detected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _build_to_disk(tmp_path)
    obj = strict_json_loads((tmp_path / COMMERCIAL_TRUTH_RELPATH).read_bytes())
    obj["readiness"]["development_gate_completed"] = True  # change body, keep old digest
    (tmp_path / COMMERCIAL_TRUTH_RELPATH).write_bytes(canonical_json_bytes(obj))
    problems = verify_commercial_truth(tmp_path)
    assert any("self digest" in p or "strict parse" in p for p in problems)


def test_blockers_drift_detected(tmp_path: Path) -> None:
    _seed(tmp_path)
    _build_to_disk(tmp_path)
    obj = strict_json_loads((tmp_path / COMMERCIAL_TRUTH_RELPATH).read_bytes())
    obj["sell_ready_blockers"] = ["nothing is blocking anymore"]
    _reserialize(tmp_path, obj)
    problems = verify_commercial_truth(tmp_path)
    assert any("blockers" in p for p in problems)


def test_parse_rejects_bool_as_int(tmp_path: Path) -> None:
    _seed(tmp_path)
    _build_to_disk(tmp_path)
    obj = strict_json_loads((tmp_path / COMMERCIAL_TRUTH_RELPATH).read_bytes())
    obj["readiness"]["development_gate_completed"] = 0  # not a JSON bool
    _reserialize(tmp_path, obj)
    with pytest.raises(V2ValidationError):
        parse_commercial_truth((tmp_path / COMMERCIAL_TRUTH_RELPATH).read_bytes())


def test_parse_rejects_broken_self_digest(tmp_path: Path) -> None:
    _seed(tmp_path)
    _build_to_disk(tmp_path)
    obj = strict_json_loads((tmp_path / COMMERCIAL_TRUTH_RELPATH).read_bytes())
    digest = str(obj["truth_digest"])
    obj["truth_digest"] = ("0" if digest[0] != "0" else "1") + digest[1:]
    (tmp_path / COMMERCIAL_TRUTH_RELPATH).write_bytes(canonical_json_bytes(obj))
    with pytest.raises(CommercialTruthError):
        parse_commercial_truth((tmp_path / COMMERCIAL_TRUTH_RELPATH).read_bytes())


# --- adversarial sales-material scanner ----------------------------------------------------------


def test_each_forbidden_phrase_is_flagged_affirmatively() -> None:
    for phrase in FORBIDDEN_PHRASES:
        text = f"Our system is {phrase} today."
        assert scan_sales_material(text, source="x") != [], phrase


def test_negation_permits_the_phrase() -> None:
    assert scan_sales_material("This program is not sell-ready.", source="x") == []
    assert scan_sales_material("There is no guaranteed return here.", source="x") == []
    assert scan_sales_material("We never claim production ready status.", source="x") == []


def test_paragraph_marker_permits_multiline_specification() -> None:
    # A specification paragraph whose marker and enumerated phrases wrap across lines.
    text = (
        "The scanner fails on unsupported superlatives such as\n"
        "market-beating, guaranteed, low-risk, sell-ready claims,\n"
        "except inside clearly-quoted false-claim examples.\n"
    )
    assert scan_sales_material(text, source="x") == []


def test_fenced_example_block_permits_then_blocks_outside() -> None:
    text = (
        "<!-- FALSE-CLAIM-EXAMPLES: BEGIN -->\n"
        "This product is production ready and guaranteed low risk.\n"
        "<!-- FALSE-CLAIM-EXAMPLES: END -->\n"
        "This product is production ready.\n"
    )
    problems = scan_sales_material(text, source="doc.md")
    assert any("doc.md:4" in p for p in problems)
    assert not any("doc.md:2" in p for p in problems)


def test_scanner_is_case_insensitive() -> None:
    assert scan_sales_material("GUARANTEED PROFITABLE SYSTEM", source="x") != []
    assert scan_sales_material("This is NOT SELL-READY.", source="x") == []


def test_cross_line_negation_handles_wrapping() -> None:
    # The negator ends one physical line and the phrase begins the next (a wrapped verdict).
    text = "... ALL SEALED PARTITIONS UNTOUCHED; V2 NOT\n  SELL-READY.\n"
    assert scan_sales_material(text, source="x") == []


def test_word_boundaries_avoid_false_positives() -> None:
    # "deployment readiness" is not "deployment ready"; "below risk" is not "low risk";
    # the underscore field name "sell_ready" is not the phrase "sell ready".
    assert scan_sales_material("deployment readiness is discussed.", source="x") == []
    assert scan_sales_material("well below risk tolerance.", source="x") == []
    assert scan_sales_material("the sell_ready flag is false.", source="x") == []


def test_reports_line_numbers_and_source() -> None:
    text = "line one\nOur system is market-beating.\nline three\n"
    problems = scan_sales_material(text, source="README.md")
    assert problems == ["README.md:2: unsupported sales phrase 'market beating'"]


# --- real repository -----------------------------------------------------------------------------


def test_real_repo_pack_verifies_clean() -> None:
    assert verify_commercial_truth(".") == []


def test_real_repo_sales_scan_is_clean() -> None:
    assert scan_repo_sales_material(".") == []


def test_committed_pack_is_not_sell_ready() -> None:
    obj = parse_commercial_truth(Path(COMMERCIAL_TRUTH_RELPATH).read_bytes())
    readiness = obj["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["sell_ready"] is False
    assert obj["nominated_candidate_count"] == 0
    assert obj["posture"] == "not_sell_ready"


def test_generated_pack_passes_its_own_scanner() -> None:
    text = Path(COMMERCIAL_TRUTH_RELPATH).read_text(encoding="utf-8")
    assert scan_sales_material(text, source=COMMERCIAL_TRUTH_RELPATH) == []


def test_scan_repo_catches_injected_violation(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Our product is a proven alpha engine.\n", encoding="utf-8")
    problems = scan_repo_sales_material(tmp_path)
    assert any("README.md" in p and "proven alpha" in p for p in problems)
