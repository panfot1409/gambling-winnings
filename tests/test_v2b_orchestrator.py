"""V2B §29 — the fail-closed one-shot orchestrator on synthetic panels (not the real partition)."""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd

from eth_research.v2b import orchestrator as orch
from eth_research.v2b.folds import EXPECTED_ROWS, V2BFold, build_oos_folds
from eth_research.v2b.scenarios import COST_SCENARIOS, PRIMARY_COST, STRESSED_COST

CORRECTED_ALPHA = 0.005


def _panel(seed: int = 20260726) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = EXPECTED_ROWS
    idx = pd.date_range("2016-05-23", periods=n, freq="D", tz="UTC")
    eth = 10.0 * np.cumprod(1.0 + rng.normal(0.0008, 0.03, n))
    btc = 450.0 * np.cumprod(1.0 + rng.normal(0.0006, 0.025, n))
    frame = {}
    for name, close in (("eth", eth), ("btc", btc)):
        frame[f"{name}_open"] = close * 0.999
        frame[f"{name}_high"] = close * 1.02
        frame[f"{name}_low"] = close * 0.98
        frame[f"{name}_close"] = close
        frame[f"{name}_volume"] = np.full(n, 1_000.0)
    return pd.DataFrame(frame, index=idx)


def _folds(panel: pd.DataFrame) -> tuple[V2BFold, ...]:
    return build_oos_folds(pd.DatetimeIndex(panel.index))


def test_evaluate_program_produces_two_candidates_and_a_verdict() -> None:
    panel = _panel()
    result = orch.evaluate_program(
        panel,
        _folds(panel),
        primary_cost=COST_SCENARIOS[PRIMARY_COST],
        stressed_cost=COST_SCENARIOS[STRESSED_COST],
        corrected_alpha=CORRECTED_ALPHA,
    )
    assert len(result.candidates) == 2
    assert result.verdict in (orch.VERDICT_NOMINATION, orch.VERDICT_NO_NOMINATION)
    # On a random-walk synthetic panel neither candidate should clear every stringent gate.
    assert result.decision.nominated_candidate_id is None
    assert result.verdict == orch.VERDICT_NO_NOMINATION
    # Each candidate carries its full evidence and a seven-gate assembly.
    for cand in result.candidates:
        assert set(cand.gates.gate_flags()) >= {
            "primary_lower_above_zero",
            "corrected_lower_above_zero",
            "mc_supports",
            "sensitivity_all_above_zero",
        }


def test_result_fingerprint_is_deterministic() -> None:
    panel = _panel()
    folds = _folds(panel)
    primary, stressed = COST_SCENARIOS[PRIMARY_COST], COST_SCENARIOS[STRESSED_COST]
    a = orch.evaluate_program(
        panel, folds, primary_cost=primary, stressed_cost=stressed, corrected_alpha=CORRECTED_ALPHA
    )
    b = orch.evaluate_program(
        panel, folds, primary_cost=primary, stressed_cost=stressed, corrected_alpha=CORRECTED_ALPHA
    )
    assert a.result_fingerprint() == b.result_fingerprint()
    assert a.to_canonical() == b.to_canonical()


def test_candidate_full_gate_wiring_matches_evidence() -> None:
    panel = _panel()
    from eth_research.v2b.candidates import CANDIDATE_A

    full = orch.evaluate_candidate_full(
        CANDIDATE_A,
        panel,
        _folds(panel),
        primary_cost=COST_SCENARIOS[PRIMARY_COST],
        stressed_cost=COST_SCENARIOS[STRESSED_COST],
        corrected_alpha=CORRECTED_ALPHA,
    )
    # The corrected-lower gate mirrors the corrected bootstrap, and mc_supports mirrors the p-value.
    assert full.gates.corrected_lower_above_zero == full.corrected.corrected_lower_above_zero
    assert full.gates.mc_supports == (full.mc_p_value <= CORRECTED_ALPHA)
    assert full.gates.primary_lower_above_zero == full.evaluation.primary_lower_above_zero


def test_run_one_shot_takes_only_repo_root() -> None:
    # The real research-train entry point is invoked exactly once at P; here we only check its
    # shape, never call it (calling it would evaluate the real partition outside the governed run).
    assert list(inspect.signature(orch.run_one_shot).parameters) == ["repo_root"]
