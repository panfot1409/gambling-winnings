"""V2A-V2B acceptance: the independent V2A decision-reconstruction oracle + adversarial tamper set.

Every tamper mutates an in-memory copy of the committed evidence (or a tmp-repo copy) and asserts
the oracle refuses it. The real committed repo must reconstruct cleanly to the accepted null.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eth_research.v2.strict import V2ValidationError, canonical_json_bytes, strict_json_loads
from eth_research.v2ab.v2a_oracle import (
    V2A_MANIFEST_RELPATH,
    V2A_PREREGISTRATION_RELPATH,
    V2A_RESULTS_RELPATH,
    V2AOracleError,
    _interval_lower_above_zero,
    _meets_fold_minimum,
    _nominate,
    _reconstruct_v2a_from_bytes,
    _reconstruct_v2a_from_obj,
    reconstruct_v2a,
    verify_v2a_reconstruction,
)

REPO = Path(__file__).resolve().parents[1]
MEANREV = "meanrev_zscore_accumulation"
VOL = "vol_scaled_hold_drawdown_guard"
TREND = "trend_regime_single_horizon"


def _fresh() -> Any:
    return strict_json_loads((REPO / V2A_RESULTS_RELPATH).read_bytes())


def _fresh_prereg() -> Any:
    return strict_json_loads((REPO / V2A_PREREGISTRATION_RELPATH).read_bytes())


def _eval(obj: Any, cid: str) -> Any:
    return next(e for e in obj["evaluation"]["evaluations"] if e["candidate_id"] == cid)


def _outcome(obj: Any, cid: str) -> Any:
    return next(o for o in obj["decision"]["outcomes"] if o["candidate_id"] == cid)


def _seed_v2a(
    tmp: Path,
    *,
    results: bytes | None = None,
    prereg: bytes | None = None,
    manifest: bytes | None = None,
) -> Path:
    d = tmp / "research" / "v2a"
    d.mkdir(parents=True)
    (d / "results.json").write_bytes(results or (REPO / V2A_RESULTS_RELPATH).read_bytes())
    (d / "pre_registration.json").write_bytes(
        prereg or (REPO / V2A_PREREGISTRATION_RELPATH).read_bytes()
    )
    (d / "results_manifest.json").write_bytes(
        manifest or (REPO / V2A_MANIFEST_RELPATH).read_bytes()
    )
    return tmp


# --------------------------------------------------------------------------- #
# clean reconstruction of the real committed evidence                          #
# --------------------------------------------------------------------------- #
def test_clean_repo_reconstructs_to_null() -> None:
    reconstruction = reconstruct_v2a(REPO)
    assert reconstruction.nominated_candidate_id is None
    assert reconstruction.committed_nominated_candidate_id is None
    assert reconstruction.eligible_candidate_ids == ()
    assert reconstruction.lenient_eligible_candidate_ids == ()
    assert verify_v2a_reconstruction(REPO) == []


def test_reconstructed_criteria_vectors_are_all_reject() -> None:
    reconstruction = reconstruct_v2a(REPO)
    assert {c.candidate_id for c in reconstruction.candidates} == {MEANREV, VOL, TREND}
    for candidate in reconstruction.candidates:
        assert candidate.criteria == {
            "folds_beating_benchmark": False,
            "positive_sharpe": True,
            "primary_lower_above_zero": False,
            "stressed_robustness": False,
        }
        assert candidate.eligible is False
        assert candidate.reconstructed_status == "research_stage_rejected"


def test_independent_primitives() -> None:
    assert _meets_fold_minimum(3, 3) is True
    assert _meets_fold_minimum(2, 3) is False
    assert _interval_lower_above_zero(0.0) is False
    assert _interval_lower_above_zero(1e-9) is True
    assert _nominate([]) is None
    assert _nominate([("a", 2.0), ("b", 1.0)]) == "a"
    assert _nominate([("a", 1.0), ("b", 1.0)]) is None


# --------------------------------------------------------------------------- #
# adversarial tampers (each must be detected)                                  #
# --------------------------------------------------------------------------- #
def test_faked_fold_majority_detected() -> None:
    obj = _fresh()
    _eval(obj, MEANREV)["folds_beating_benchmark"] = 4  # fake a 4-of-5 majority
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_changed_candidate_label_detected() -> None:
    obj = _fresh()
    _eval(obj, MEANREV)["candidate_id"] = "meanrev_relabelled"
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_changed_candidate_fingerprint_detected() -> None:
    obj = _fresh()
    obj["candidate_fingerprints"][MEANREV] = "0" * 64
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_changed_benchmark_via_protocol_fingerprint_detected() -> None:
    # The benchmark is a protocol field; changing it reruns the protocol and its fingerprint.
    obj = _fresh()
    obj["protocol_fingerprint"] = "0" * 64
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_changed_primary_endpoint_via_eval_fingerprint_detected() -> None:
    # The primary endpoint is a protocol field; the evaluation fingerprint must match the header.
    obj = _fresh()
    obj["evaluation"]["protocol_fingerprint"] = "0" * 64
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_sign_flipped_point_estimate_detected() -> None:
    obj = _fresh()
    entry = _eval(obj, MEANREV)
    entry["primary_point_estimate"] = -entry["primary_point_estimate"]  # push outside the interval
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_rounded_interval_bool_mismatch_detected() -> None:
    obj = _fresh()
    _eval(obj, MEANREV)["primary_lower_above_zero"] = True  # bool disagrees with negative bound
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_removed_stressed_cell_detected() -> None:
    obj = _fresh()
    del _eval(obj, MEANREV)["stressed_lower_above_zero"]
    with pytest.raises(V2ValidationError):
        _reconstruct_v2a_from_obj(obj)


def test_duplicated_candidate_cell_detected() -> None:
    obj = _fresh()
    obj["evaluation"]["evaluations"].append(dict(_eval(obj, MEANREV)))
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_changed_criterion_count_detected() -> None:
    obj = _fresh()
    _outcome(obj, MEANREV)["criteria"]["fabricated_extra_criterion"] = True
    with pytest.raises(V2ValidationError):
        _reconstruct_v2a_from_obj(obj)


def test_fabricated_nomination_detected() -> None:
    obj = _fresh()
    obj["decision"]["nominated_candidate_id"] = TREND  # evidence unchanged; nobody is eligible
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_changed_decision_status_detected() -> None:
    obj = _fresh()
    _outcome(obj, MEANREV)["status"] = "research_stage_supported"
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_flipped_committed_criterion_detected() -> None:
    obj = _fresh()
    _outcome(obj, MEANREV)["criteria"]["folds_beating_benchmark"] = True  # evidence still says 2
    with pytest.raises(V2AOracleError):
        _reconstruct_v2a_from_obj(obj)


def test_reordered_evaluations_still_reconstruct_null() -> None:
    obj = _fresh()
    obj["evaluation"]["evaluations"].reverse()
    obj["decision"]["outcomes"].reverse()
    reconstruction = _reconstruct_v2a_from_obj(obj)  # id-keyed, so order does not fool it
    assert reconstruction.nominated_candidate_id is None
    assert reconstruction.eligible_candidate_ids == ()


def test_nan_ci_lower_rejected_by_strict_loader() -> None:
    obj = _fresh()
    _eval(obj, MEANREV)["primary_ci_lower"] = float("nan")
    raw = json.dumps(obj, allow_nan=True).encode("utf-8")
    with pytest.raises(V2ValidationError):
        _reconstruct_v2a_from_bytes(raw)


def test_bool_as_number_rejected() -> None:
    obj = _fresh()
    _eval(obj, MEANREV)["folds_beating_benchmark"] = True
    with pytest.raises(V2ValidationError):
        _reconstruct_v2a_from_obj(obj)


def test_missing_top_level_key_rejected() -> None:
    obj = _fresh()
    del obj["decision"]
    with pytest.raises(V2ValidationError):
        _reconstruct_v2a_from_obj(obj)


def test_empty_string_nomination_rejected() -> None:
    obj = _fresh()
    obj["decision"]["nominated_candidate_id"] = ""  # not a valid null
    with pytest.raises(V2ValidationError):
        _reconstruct_v2a_from_obj(obj)


def test_manifest_sha_mismatch_detected(tmp_path: Path) -> None:
    obj = _fresh()
    obj["evaluation"]["periods_per_year"] = 365.0  # benign to the decision, breaks the manifest sha
    _seed_v2a(tmp_path, results=canonical_json_bytes(obj))
    assert verify_v2a_reconstruction(tmp_path)
    with pytest.raises(V2AOracleError):
        reconstruct_v2a(tmp_path)


def test_preregistration_binding_mismatch_detected(tmp_path: Path) -> None:
    prereg = _fresh_prereg()
    prereg["protocol_fingerprint"] = "0" * 64
    _seed_v2a(tmp_path, prereg=canonical_json_bytes(prereg))
    with pytest.raises(V2AOracleError):
        reconstruct_v2a(tmp_path)
