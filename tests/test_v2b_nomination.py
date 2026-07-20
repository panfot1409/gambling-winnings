"""V2B §20+22 — the frozen sensitivity neighborhood and the stringent ≤1 nomination rule."""

from __future__ import annotations

import numpy as np
import pandas as pd

from eth_research.v2b import folds as fld
from eth_research.v2b import nomination as nom
from eth_research.v2b import sensitivity as sens
from eth_research.v2b.candidates import CANDIDATE_A, CANDIDATE_B
from eth_research.v2b.scenarios import COST_SCENARIOS, PRIMARY_COST


def _synthetic_panel(rows: int = fld.EXPECTED_ROWS) -> pd.DataFrame:
    rng = np.random.default_rng(20260722)
    index = pd.date_range("2016-05-23", periods=rows, freq="D", tz="UTC")
    eth = 10.0 * np.cumprod(1.0 + rng.normal(0.0008, 0.03, rows))
    btc = 450.0 * np.cumprod(1.0 + rng.normal(0.0006, 0.025, rows))
    frame = {}
    for name, close in (("eth", eth), ("btc", btc)):
        frame[f"{name}_open"] = close * 0.999
        frame[f"{name}_high"] = close * 1.02
        frame[f"{name}_low"] = close * 0.98
        frame[f"{name}_close"] = close
        frame[f"{name}_volume"] = np.full(rows, 1_000.0)
    return pd.DataFrame(frame, index=index)


# --------------------------------------------------------------------------- #
# sensitivity neighborhood                                                     #
# --------------------------------------------------------------------------- #
def test_neighborhood_shapes_and_center_membership() -> None:
    a = sens.sensitivity_neighborhood(CANDIDATE_A)
    b = sens.sensitivity_neighborhood(CANDIDATE_B)
    assert len(a) == 9  # 3 x 3 grid
    assert len(b) == 3
    assert {"eth_horizon": 100, "btc_horizon": 100} in a  # center included
    assert {"lookback": 90} in b
    for params in (*a, *b):
        assert all(v > 0 for v in params.values())


def test_evaluate_sensitivity_scores_the_whole_neighborhood() -> None:
    panel = _synthetic_panel()
    folds = fld.build_oos_folds(pd.DatetimeIndex(panel.index))
    report = sens.evaluate_sensitivity(
        CANDIDATE_B, panel, folds, primary_cost=COST_SCENARIOS[PRIMARY_COST]
    )
    assert report.candidate_id == CANDIDATE_B.candidate_id
    assert report.neighbor_count == 3
    assert 0 <= report.neighbors_lower_above_zero <= 3
    assert report.all_above_zero == (report.neighbors_lower_above_zero == 3)
    assert report.min_primary_ci_lower <= 0.0 or report.all_above_zero


# --------------------------------------------------------------------------- #
# nomination rule                                                              #
# --------------------------------------------------------------------------- #
def test_strict_fold_majority() -> None:
    assert nom.strict_fold_majority(4, 6) is True
    assert nom.strict_fold_majority(3, 6) is False  # a tie is not a strict majority
    assert nom.strict_fold_majority(6, 6) is True


def _all_pass_gates(candidate_id: str, point: float) -> nom.CandidateGates:
    return nom.build_gates(
        candidate_id,
        primary_lower_above_zero=True,
        stressed_lower_above_zero=True,
        latency_lower_above_zero=True,
        folds_beating=5,
        fold_count=6,
        corrected_lower_above_zero=True,
        mc_p_value=0.001,
        corrected_alpha=0.005,
        sensitivity_all_above_zero=True,
        primary_point_estimate=point,
    )


def test_all_gates_pass_nominates_the_candidate() -> None:
    gates = (_all_pass_gates("cand_a", 0.01),)
    decision = nom.decide_nomination(gates)
    assert decision.nominated_candidate_id == "cand_a"
    assert decision.eligible_candidate_ids == ("cand_a",)


def test_one_failing_gate_blocks_nomination() -> None:
    # A single failed gate (the multiplicity-corrected bound) makes the candidate ineligible.
    g = _all_pass_gates("cand_a", 0.01)
    blocked = nom.CandidateGates(
        candidate_id=g.candidate_id,
        primary_lower_above_zero=g.primary_lower_above_zero,
        stressed_lower_above_zero=g.stressed_lower_above_zero,
        latency_lower_above_zero=g.latency_lower_above_zero,
        strict_fold_majority=g.strict_fold_majority,
        corrected_lower_above_zero=False,
        mc_supports=g.mc_supports,
        sensitivity_all_above_zero=g.sensitivity_all_above_zero,
        primary_point_estimate=g.primary_point_estimate,
    )
    decision = nom.decide_nomination((blocked,))
    assert decision.nominated_candidate_id is None
    assert decision.eligible_candidate_ids == ()


def test_mc_gate_respects_corrected_alpha() -> None:
    g = nom.build_gates(
        "cand_a",
        primary_lower_above_zero=True,
        stressed_lower_above_zero=True,
        latency_lower_above_zero=True,
        folds_beating=5,
        fold_count=6,
        corrected_lower_above_zero=True,
        mc_p_value=0.02,  # above the corrected alpha -> mc does not support
        corrected_alpha=0.005,
        sensitivity_all_above_zero=True,
        primary_point_estimate=0.01,
    )
    assert g.mc_supports is False
    assert g.eligible is False


def test_two_eligible_nominates_the_higher_point_estimate() -> None:
    gates = (_all_pass_gates("cand_a", 0.02), _all_pass_gates("cand_b", 0.01))
    decision = nom.decide_nomination(gates)
    assert decision.nominated_candidate_id == "cand_a"
    assert set(decision.eligible_candidate_ids) == {"cand_a", "cand_b"}


def test_exact_tie_nominates_none() -> None:
    gates = (_all_pass_gates("cand_a", 0.01), _all_pass_gates("cand_b", 0.01))
    decision = nom.decide_nomination(gates)
    assert decision.nominated_candidate_id is None


def test_no_candidate_passes_yields_no_nomination() -> None:
    a = _all_pass_gates("cand_a", 0.01)
    fail = nom.CandidateGates(
        candidate_id="cand_a",
        primary_lower_above_zero=False,
        stressed_lower_above_zero=False,
        latency_lower_above_zero=False,
        strict_fold_majority=False,
        corrected_lower_above_zero=False,
        mc_supports=False,
        sensitivity_all_above_zero=False,
        primary_point_estimate=a.primary_point_estimate,
    )
    decision = nom.decide_nomination((fail,))
    assert decision.nominated_candidate_id is None
    assert "no candidate cleared" in decision.reason
