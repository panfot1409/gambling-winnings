"""Fable 5 synthetic catastrophe rehearsal.

A *disposable, zero-exposure* rehearsal of how the merged V2 platform behaves under catastrophic
conditions. Every scenario runs against a throwaway ``tmp_path`` tree or an in-memory frame; **none
touches the real repository, opens a sealed value, performs any network I/O, or routes any order.**
This is emphatically **not** paper trading — it is a fail-closed drill that proves catastrophes
degrade to a *refusal*, never to an activation.

The single invariant under test across every catastrophe: **paper activation stays OFF, prospective
collection stays OFF, sealed state stays untouched, and the platform fails closed** — under a
corrupted governed state, an injected candidate, tampered sealed ledgers, a forged authorization
file, and degenerate market data. See ``docs/V2_FABLE5_SYNTHETIC_CATASTROPHE.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eth_research.fractional.cost_model import (
    CAUSAL_PROXY_BASE,
    CAUSAL_PROXY_STRESSED,
    CostScenario,
)
from eth_research.fractional.engine import run_fractional_backtest
from eth_research.fractional.strategies import STRATEGIES_BY_NAME
from eth_research.v2.fable5.paper_readiness import (
    PaperReadinessError,
    derive_paper_readiness,
    verify_paper_readiness,
)

# --------------------------------------------------------------------------------------------------
# Disposable synthetic-tree builders (never the real repo)
# --------------------------------------------------------------------------------------------------


def _w(root: Path, rel: str, obj: object) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _empty_sealed_ledgers(root: Path) -> None:
    for rel in (
        "research/m2b/test_evaluations.jsonl",
        "research/m3a/development_gate_access.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    ):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")


def _private(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nclassifiers = ["Private :: Do Not Upload"]\n', encoding="utf-8"
    )


def _null_results(root: Path) -> None:
    _w(root, "research/v2a/results.json", {"decision": {"nominated_candidate_id": None}})
    _w(
        root,
        "research/v2b/v2b_results.json",
        {"result": {"decision": {"nominated_candidate_id": None, "eligible_candidate_ids": []}}},
    )


def _hardened_platform(root: Path) -> None:
    """A synthetic tree with the *platform* fully hardened: audit complete, zero unresolved
    Class A/B/D, sealed ledgers empty, repo private — but with the honest V2 null results."""
    _null_results(root)
    _empty_sealed_ledgers(root)
    _private(root)
    _w(
        root,
        "governance/v2/fable5_remediation_state.json",
        {"all_findings_resolved": True, "unresolved_class_abd_count": 0},
    )
    _w(root, "governance/v2/fable5_audit_manifest.json", {"audit": "fable5"})


# --------------------------------------------------------------------------------------------------
# Catastrophe 1 — a hardened platform with NO candidate never authorizes
# --------------------------------------------------------------------------------------------------


def test_cat1_hardened_platform_without_candidate_stays_blocked(tmp_path: Path) -> None:
    _hardened_platform(tmp_path)
    state = derive_paper_readiness(tmp_path)
    # The platform gates are green...
    assert state.gates["platform_audit_complete"] is True
    assert state.gates["platform_hardened"] is True
    # ...but the scientific gate blocks, so nothing activates.
    assert state.eligible_paper_candidate_present is False
    assert state.paper_activation_authorized is False
    assert state.paper_trading_active is False
    assert state.sell_ready is False
    assert "eligible_paper_candidate_present" in state.blocking_gates


# --------------------------------------------------------------------------------------------------
# Catastrophe 2 — an INJECTED candidate cannot self-authorize without the human gate
# --------------------------------------------------------------------------------------------------


def test_cat2_injected_candidate_still_needs_human_approval(tmp_path: Path) -> None:
    # Adversary edits the committed decisions to fabricate a nominated candidate and supplies every
    # other piece of evidence EXCEPT the on-file human activation approval. The human gate is the
    # final backstop: no code path authorizes paper trading without it.
    _empty_sealed_ledgers(tmp_path)
    _private(tmp_path)
    _w(tmp_path, "research/v2a/results.json", {"decision": {"nominated_candidate_id": "forged"}})
    _w(
        tmp_path,
        "research/v2b/v2b_results.json",
        {
            "result": {
                "decision": {
                    "nominated_candidate_id": "forged",
                    "eligible_candidate_ids": ["forged"],
                }
            }
        },
    )
    _w(
        tmp_path,
        "governance/v2/fable5_remediation_state.json",
        {"all_findings_resolved": True, "unresolved_class_abd_count": 0},
    )
    _w(tmp_path, "governance/v2/fable5_audit_manifest.json", {"audit": "fable5"})
    _w(tmp_path, "governance/v2/paper_release_freeze.json", {"frozen": True})
    # deliberately NO governance/v2/paper_activation_approval.json
    state = derive_paper_readiness(tmp_path)
    assert (
        state.eligible_paper_candidate_present is True
    )  # the injection is visible in the bytes...
    assert state.paper_activation_authorized is False  # ...but authorization is still refused
    assert state.blocking_gates == ("human_activation_approval_recorded",)


# --------------------------------------------------------------------------------------------------
# Catastrophe 3 — tampered sealed ledger is detected and blocks
# --------------------------------------------------------------------------------------------------


def test_cat3_tampered_sealed_ledger_blocks(tmp_path: Path) -> None:
    _hardened_platform(tmp_path)
    # Catastrophe: a sealed ledger is no longer byte-empty (someone wrote into a sealed partition).
    (tmp_path / "research/m3d/prospective_evaluations.jsonl").write_bytes(b'{"leak":1}\n')
    state = derive_paper_readiness(tmp_path)
    assert state.gates["sealed_partitions_untouched"] is False
    assert "sealed_partitions_untouched" in state.blocking_gates
    assert state.paper_activation_authorized is False


# --------------------------------------------------------------------------------------------------
# Catastrophe 4 — a forged committed authorization file is rejected by the verifier
# --------------------------------------------------------------------------------------------------


def test_cat4_forged_authorization_state_is_rejected(tmp_path: Path) -> None:
    _hardened_platform(tmp_path)
    derived = derive_paper_readiness(tmp_path)
    forged = derived.to_canonical()
    # Catastrophe: attacker hand-edits the committed state file to claim authorization.
    forged["paper_activation_authorized"] = True
    gates = forged["gates"]
    assert isinstance(gates, dict)
    gates["eligible_paper_candidate_present"] = True
    with pytest.raises(PaperReadinessError):
        verify_paper_readiness(tmp_path, forged)


def test_cat4b_forged_active_trading_flag_is_rejected(tmp_path: Path) -> None:
    _hardened_platform(tmp_path)
    forged = derive_paper_readiness(tmp_path).to_canonical()
    forged["paper_trading_active"] = True
    with pytest.raises(PaperReadinessError):
        verify_paper_readiness(tmp_path, forged)


# --------------------------------------------------------------------------------------------------
# Catastrophe 5 — degenerate market data never crashes the engine or produces a non-finite mark
# --------------------------------------------------------------------------------------------------


def _degenerate_frames(volume_tail: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    def _mk(start: str, periods: int, volume: float) -> pd.DataFrame:
        idx = pd.date_range(start, periods=periods, freq="D", tz="UTC")
        rows = [(100.0, 100.0, 100.0, 100.0, volume)] * periods
        return pd.DataFrame(
            rows, index=idx, columns=["open", "high", "low", "close", "volume"]
        ).astype(float)

    context = _mk("2021-01-01", 40, 1.0e9)
    head = _mk("2021-02-10", 1, 1.0e9)
    tail = _mk("2021-02-11", 40, volume_tail)
    return context, pd.concat([head, tail])


@pytest.mark.parametrize("scenario", [CAUSAL_PROXY_BASE, CAUSAL_PROXY_STRESSED])
def test_cat5_collapsed_liquidity_is_finite_and_safe(scenario: CostScenario) -> None:
    context, evaluation = _degenerate_frames(volume_tail=0.0)
    result = run_fractional_backtest(
        evaluation, STRATEGIES_BY_NAME["buy_and_hold"], scenario, context=context
    )
    assert np.isfinite(result.terminal_liquidation_equity)
    assert np.isfinite(result.terminal_equity)
    assert result.terminal_liquidation_equity > 0.0


# --------------------------------------------------------------------------------------------------
# Catastrophe 6 — a totally blank / wiped tree fails closed to a fully-blocked state
# --------------------------------------------------------------------------------------------------


def test_cat6_wiped_tree_fails_closed(tmp_path: Path) -> None:
    # Every committed artifact is gone (catastrophic data loss). The derivation must not raise and
    # must not authorize; sealed-untouched fails closed because absence is not proof of emptiness.
    state = derive_paper_readiness(tmp_path)
    assert state.paper_activation_authorized is False
    assert state.paper_trading_active is False
    assert state.sell_ready is False
    assert state.gates["sealed_partitions_untouched"] is False
    assert all(v is False for v in state.gates.values())


# --------------------------------------------------------------------------------------------------
# Zero-exposure assertion — the real repository is never mutated by this rehearsal
# --------------------------------------------------------------------------------------------------


def test_rehearsal_does_not_write_the_paper_readiness_artifact() -> None:
    # A defensive check that the rehearsal never accidentally activates by writing the governed
    # state onto the real tree: derivation is pure and returns a value; it must not create the file.
    repo_root = Path(__file__).resolve().parents[1]
    before = (repo_root / "governance/v2/paper_readiness_state.json").exists()
    derive_paper_readiness(repo_root)
    after = (repo_root / "governance/v2/paper_readiness_state.json").exists()
    assert before == after  # derivation created/removed nothing
