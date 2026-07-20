"""V2A-V2B acceptance: the independent V2B decision-reconstruction oracle + adversarial tamper set.

Every tamper mutates an in-memory copy of the committed evidence and asserts the oracle refuses it.
The real committed repo must reconstruct cleanly to the accepted null (both candidates ineligible).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eth_research.v2.strict import V2ValidationError, strict_json_loads
from eth_research.v2ab.v2b_oracle import (
    V2B_MULTIPLICITY_RELPATH,
    V2B_RESULTS_RELPATH,
    V2BOracleError,
    _corrected_alpha_for,
    _interval_lower_above_zero,
    _mc_supports,
    _nominate,
    _reconstruct_v2b_from_bytes,
    _reconstruct_v2b_from_obj,
    _strict_fold_majority,
    reconstruct_v2b,
    verify_v2b_reconstruction,
)

REPO = Path(__file__).resolve().parents[1]
CAND_A = "cross_asset_btc_confirmed_eth_trend"
CAND_B = "cross_asset_eth_btc_relative_strength_rotation"


def _fresh_results() -> Any:
    return strict_json_loads((REPO / V2B_RESULTS_RELPATH).read_bytes())


def _fresh_mult() -> Any:
    return strict_json_loads((REPO / V2B_MULTIPLICITY_RELPATH).read_bytes())


def _mult_bytes() -> bytes:
    return (REPO / V2B_MULTIPLICITY_RELPATH).read_bytes()


def _cand(obj: Any, cid: str) -> Any:
    return next(c for c in obj["result"]["candidates"] if c["evaluation"]["candidate_id"] == cid)


def _run(obj: Any, mult: Any | None = None) -> object:
    return _reconstruct_v2b_from_obj(obj, mult if mult is not None else _fresh_mult())


# --------------------------------------------------------------------------- #
# clean reconstruction of the real committed evidence                          #
# --------------------------------------------------------------------------- #
def test_clean_repo_reconstructs_to_null() -> None:
    reconstruction = reconstruct_v2b(REPO)
    assert reconstruction.nominated_candidate_id is None
    assert reconstruction.committed_nominated_candidate_id is None
    assert reconstruction.eligible_candidate_ids == ()
    assert reconstruction.corrected_alpha == reconstruction.expected_alpha == 0.005
    assert reconstruction.total_family_count == 10
    assert verify_v2b_reconstruction(REPO) == []


def test_reconstructed_seven_gate_vectors_pass_exactly_one_gate() -> None:
    reconstruction = reconstruct_v2b(REPO)
    assert reconstruction.candidate_ids == (CAND_A, CAND_B)
    for candidate in reconstruction.candidates:
        assert candidate.gates == {
            "primary_lower_above_zero": False,
            "stressed_lower_above_zero": False,
            "latency_lower_above_zero": False,
            "corrected_lower_above_zero": False,
            "mc_supports": False,
            "sensitivity_all_above_zero": False,
            "strict_fold_majority": True,
        }
        assert candidate.eligible is False
        assert candidate.passed_gate_count == 1
        assert candidate.passes_uncorrected is False


def test_independent_primitives() -> None:
    assert _mc_supports(0.005, 0.005) is True  # inclusive threshold
    assert _mc_supports(0.0050001, 0.005) is False
    assert _strict_fold_majority(4, 6) is True
    assert _strict_fold_majority(3, 6) is False
    assert _interval_lower_above_zero(0.0) is False
    assert _corrected_alpha_for(0.05, 10) == 0.005
    assert _nominate([]) is None
    assert _nominate([("a", 2.0), ("b", 1.0)]) == "a"
    assert _nominate([("a", 1.0), ("b", 1.0)]) is None


# --------------------------------------------------------------------------- #
# multiplicity / corrected-alpha tampers                                       #
# --------------------------------------------------------------------------- #
def test_alpha_reset_to_uncorrected_detected() -> None:
    obj = _fresh_results()
    obj["result"]["corrected_alpha"] = 0.05  # the uncorrected nominal level
    with pytest.raises(V2BOracleError):
        _run(obj)


def test_negative_alpha_rejected() -> None:
    obj = _fresh_results()
    obj["result"]["corrected_alpha"] = -0.005
    with pytest.raises(V2ValidationError):
        _run(obj)


def test_total_family_count_reduced_detected() -> None:
    mult = _fresh_mult()
    mult["total_family_count"] = 8
    with pytest.raises(V2BOracleError):
        _run(_fresh_results(), mult)


def test_historical_family_count_reduced_detected() -> None:
    mult = _fresh_mult()
    mult["historical_family_count"] = 7
    with pytest.raises(V2BOracleError):
        _run(_fresh_results(), mult)


def test_family_basis_candidate_omitted_detected() -> None:
    mult = _fresh_mult()
    mult["v2b_max_family_count"] = 1  # a family dropped from the correction basis
    with pytest.raises(V2BOracleError):
        _run(_fresh_results(), mult)


def test_multiplicity_missing_key_rejected() -> None:
    mult = _fresh_mult()
    del mult["total_family_count"]
    with pytest.raises(V2ValidationError):
        _run(_fresh_results(), mult)


def test_candidate_bootstrap_alpha_inconsistent_detected() -> None:
    obj = _fresh_results()
    _cand(obj, CAND_A)["corrected_bootstrap"]["corrected_alpha"] = 0.01
    with pytest.raises(V2BOracleError):
        _run(obj)


# --------------------------------------------------------------------------- #
# gate / evidence tampers                                                      #
# --------------------------------------------------------------------------- #
def test_candidate_duplicated_under_alias_detected() -> None:
    obj = _fresh_results()
    clone = json.loads(json.dumps(_cand(obj, CAND_A)))
    clone["evaluation"]["candidate_id"] = "cross_asset_btc_confirmed_eth_trend_alias"
    obj["result"]["candidates"].append(clone)
    with pytest.raises(V2BOracleError):
        _run(obj)


def test_p_value_rounded_below_threshold_detected() -> None:
    obj = _fresh_results()
    _cand(obj, CAND_A)["mc_sign_flip_p_value"] = 0.004  # rounded under alpha; gate still says False
    with pytest.raises(V2BOracleError):
        _run(obj)


def test_p_value_equal_to_threshold_detected() -> None:
    obj = _fresh_results()
    _cand(obj, CAND_A)["mc_sign_flip_p_value"] = 0.005  # p == alpha -> supports (inclusive)
    with pytest.raises(V2BOracleError):
        _run(obj)


def test_nan_p_value_rejected_by_strict_loader() -> None:
    obj = _fresh_results()
    _cand(obj, CAND_A)["mc_sign_flip_p_value"] = float("nan")
    raw = json.dumps(obj, allow_nan=True).encode("utf-8")
    with pytest.raises(V2ValidationError):
        _reconstruct_v2b_from_bytes(raw, _mult_bytes())


def test_bool_as_number_rejected() -> None:
    obj = _fresh_results()
    _cand(obj, CAND_A)["corrected_bootstrap"]["observation_count"] = True
    with pytest.raises(V2ValidationError):
        _run(obj)


def test_reordered_candidate_records_detected() -> None:
    obj = _fresh_results()
    obj["result"]["candidates"].reverse()  # the registered family order is pinned
    with pytest.raises(V2BOracleError):
        _run(obj)


def test_omitted_monte_carlo_cell_detected() -> None:
    obj = _fresh_results()
    del _cand(obj, CAND_A)["mc_sign_flip_p_value"]
    with pytest.raises(V2ValidationError):
        _run(obj)


def test_omitted_sensitivity_neighbor_detected() -> None:
    obj = _fresh_results()
    del _cand(obj, CAND_A)["sensitivity"]["neighbor_count"]
    with pytest.raises(V2ValidationError):
        _run(obj)


def test_sensitivity_fraction_inconsistent_detected() -> None:
    obj = _fresh_results()
    _cand(obj, CAND_A)["sensitivity"]["neighbors_lower_above_zero"] = 1  # 1/9 != committed 0.0
    with pytest.raises(V2BOracleError):
        _run(obj)


def test_benchmark_substitution_detected() -> None:
    obj = _fresh_results()
    _cand(obj, CAND_A)["evaluation"]["benchmark"] = "buy_and_hold"
    with pytest.raises(V2BOracleError):
        _run(obj)


def test_gate_key_silently_removed_detected() -> None:
    obj = _fresh_results()
    del _cand(obj, CAND_A)["gates"]["gates"]["mc_supports"]
    with pytest.raises(V2ValidationError):
        _run(obj)


def test_six_of_seven_faked_eligibility_detected() -> None:
    obj = _fresh_results()
    _cand(obj, CAND_A)["gates"]["gates"]["mc_supports"] = True  # evidence unchanged
    with pytest.raises(V2BOracleError):
        _run(obj)


def test_diagnostic_substituted_for_primary_detected() -> None:
    obj = _fresh_results()
    _cand(obj, CAND_A)["evaluation"]["primary_lower_above_zero"] = True  # bound stays negative
    with pytest.raises(V2BOracleError):
        _run(obj)


# --------------------------------------------------------------------------- #
# decision / nomination tampers                                               #
# --------------------------------------------------------------------------- #
def test_second_place_candidate_nominated_detected() -> None:
    obj = _fresh_results()
    obj["result"]["decision"]["nominated_candidate_id"] = CAND_B  # nobody is eligible
    with pytest.raises(V2BOracleError):
        _run(obj)


def test_both_candidates_nominated_detected() -> None:
    obj = _fresh_results()
    decision = obj["result"]["decision"]
    decision["eligible_candidate_ids"] = [CAND_A, CAND_B]
    decision["nominated_candidate_id"] = CAND_A
    with pytest.raises(V2BOracleError):
        _run(obj)


def test_empty_string_nomination_rejected() -> None:
    obj = _fresh_results()
    obj["result"]["decision"]["nominated_candidate_id"] = ""  # not a valid null
    with pytest.raises(V2ValidationError):
        _run(obj)


def test_missing_result_key_rejected() -> None:
    obj = _fresh_results()
    del obj["result"]["verdict"]
    with pytest.raises(V2ValidationError):
        _run(obj)
