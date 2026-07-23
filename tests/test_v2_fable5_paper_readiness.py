"""Fable 5 paper-readiness derivation tests.

The paper-readiness gate is the single most safety-critical artifact of this audit: it decides
whether paper trading may honestly begin. The controlling scientific fact is that accepted V2 has
**zero nominated candidates** (V2A ``nominated_candidate_id == null``; V2B ``eligible_candidate_ids
== []``), so on the real committed tree ``paper_activation_authorized`` MUST derive false.

These tests prove three things:

1. **No forcing literal.** On the real repository the derived state has every safety flag false, and
   there is no literal / env var / builder that flips ``paper_activation_authorized`` (or
   ``paper_trading_active`` / ``sell_ready``) true without a genuine nomination.
2. **Honest gate mechanics.** Each gate is derived from committed bytes; a synthetic tree that
   supplies the missing evidence advances exactly the corresponding gate and nothing else, and only
   a *complete* set — including a genuine nomination — could ever authorize. (No such complete set
   exists in accepted V2; the synthetic fixtures never touch the real tree.)
3. **Fail-closed verification.** ``verify_paper_readiness`` rejects any committed state that
   disagrees with the derivation, and additionally refuses (regardless of the committed file) any
   derivation in which authorization / active trading / sell-readiness is true.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eth_research.v2.fable5.paper_readiness import (
    PAPER_ACTIVATION_GATES,
    PaperReadinessError,
    derive_paper_readiness,
    verify_paper_readiness,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------------------------------
# 1. The real committed tree — the honest terminal state
# --------------------------------------------------------------------------------------------------


def test_real_tree_authorizes_nothing() -> None:
    state = derive_paper_readiness(REPO_ROOT)
    # The three standing safety flags are false on the accepted V2 tree.
    assert state.paper_activation_authorized is False
    assert state.paper_trading_active is False
    assert state.sell_ready is False
    # The load-bearing scientific gate: no eligible candidate exists.
    assert state.eligible_paper_candidate_present is False
    assert state.gates["eligible_paper_candidate_present"] is False


def test_real_tree_eligibility_reads_committed_null_results() -> None:
    # eligible_paper_candidate_present is derived from the committed V2A/V2B decision artifacts,
    # both of which nominate zero candidates. If either file were relabeled to nominate a candidate
    # this test would change — that is the point: eligibility is byte-derived, not asserted.
    v2a = json.loads((REPO_ROOT / "research/v2a/results.json").read_text())
    v2b = json.loads((REPO_ROOT / "research/v2b/v2b_results.json").read_text())
    assert v2a["decision"]["nominated_candidate_id"] is None
    assert v2b["result"]["decision"]["nominated_candidate_id"] is None
    assert v2b["result"]["decision"]["eligible_candidate_ids"] == []
    assert derive_paper_readiness(REPO_ROOT).eligible_paper_candidate_present is False


def test_real_tree_sealed_and_private_gates_hold() -> None:
    state = derive_paper_readiness(REPO_ROOT)
    assert state.gates["sealed_partitions_untouched"] is True
    assert state.gates["repository_private"] is True


def test_gate_vector_covers_exactly_the_declared_gates() -> None:
    state = derive_paper_readiness(REPO_ROOT)
    assert tuple(state.gates.keys()) == PAPER_ACTIVATION_GATES
    # authorization is the conjunction of the full declared gate set — nothing hidden.
    assert state.paper_activation_authorized == all(state.gates[g] for g in PAPER_ACTIVATION_GATES)


def test_blocking_gates_are_exactly_the_false_gates() -> None:
    state = derive_paper_readiness(REPO_ROOT)
    assert set(state.blocking_gates) == {g for g in PAPER_ACTIVATION_GATES if not state.gates[g]}
    assert state.eligible_paper_candidate_present is False
    assert "eligible_paper_candidate_present" in state.blocking_gates


# --------------------------------------------------------------------------------------------------
# 2. Synthetic gate mechanics — evidence advances exactly its own gate (never the real tree)
# --------------------------------------------------------------------------------------------------


def _write(root: Path, rel: str, obj: object) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _touch_empty_ledgers(root: Path) -> None:
    for rel in (
        "research/m2b/test_evaluations.jsonl",
        "research/m3a/development_gate_access.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    ):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")


def _private_pyproject(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nclassifiers = ["Private :: Do Not Upload"]\n', encoding="utf-8"
    )


def _null_result_decisions(root: Path) -> None:
    _write(root, "research/v2a/results.json", {"decision": {"nominated_candidate_id": None}})
    _write(
        root,
        "research/v2b/v2b_results.json",
        {"result": {"decision": {"nominated_candidate_id": None, "eligible_candidate_ids": []}}},
    )


def test_empty_tree_blocks_everything(tmp_path: Path) -> None:
    # No committed evidence at all: every gate false, nothing authorized.
    state = derive_paper_readiness(tmp_path)
    assert state.paper_activation_authorized is False
    assert all(v is False for v in state.gates.values())


def test_remediation_freeze_advances_only_platform_gates(tmp_path: Path) -> None:
    _null_result_decisions(tmp_path)
    _touch_empty_ledgers(tmp_path)
    _private_pyproject(tmp_path)
    _write(
        tmp_path,
        "governance/v2/fable5_remediation_state.json",
        {"all_findings_resolved": True, "unresolved_class_abd_count": 0},
    )
    _write(tmp_path, "governance/v2/fable5_audit_manifest.json", {"audit": "fable5"})
    state = derive_paper_readiness(tmp_path)
    assert state.gates["platform_audit_complete"] is True
    assert state.gates["platform_hardened"] is True
    assert state.gates["no_unresolved_class_abd_finding"] is True
    # ...but with no candidate the eligibility-dependent gates stay false, so still not authorized.
    assert state.eligible_paper_candidate_present is False
    assert state.paper_activation_authorized is False


def test_unresolved_class_abd_finding_keeps_platform_unhardened(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "governance/v2/fable5_remediation_state.json",
        {"all_findings_resolved": False, "unresolved_class_abd_count": 1},
    )
    _write(tmp_path, "governance/v2/fable5_audit_manifest.json", {"audit": "fable5"})
    state = derive_paper_readiness(tmp_path)
    assert state.gates["platform_audit_complete"] is False
    assert state.gates["platform_hardened"] is False
    assert state.gates["no_unresolved_class_abd_finding"] is False


def test_a_genuine_nomination_advances_the_eligibility_family(tmp_path: Path) -> None:
    # A synthetic *nominated* candidate (this is NOT the real tree) advances the eligibility-
    # derived gates — proving the gate is byte-derived, not hard-wired false. It still does not by
    # itself authorize: the release-freeze / preregistration / human-approval gates remain unmet.
    _write(
        tmp_path,
        "research/v2a/results.json",
        {"decision": {"nominated_candidate_id": "cand-synthetic"}},
    )
    _write(
        tmp_path,
        "research/v2b/v2b_results.json",
        {"result": {"decision": {"nominated_candidate_id": None, "eligible_candidate_ids": []}}},
    )
    state = derive_paper_readiness(tmp_path)
    assert state.eligible_paper_candidate_present is True
    assert state.gates["candidate_lineage_valid"] is True
    assert state.gates["strategy_specification_immutable"] is True
    # freeze / preregistration still require a freeze artifact AND eligibility:
    assert state.gates["paper_release_candidate_frozen"] is False
    assert state.paper_activation_authorized is False


def test_v2b_eligible_list_also_counts_as_a_candidate(tmp_path: Path) -> None:
    _write(tmp_path, "research/v2a/results.json", {"decision": {"nominated_candidate_id": None}})
    _write(
        tmp_path,
        "research/v2b/v2b_results.json",
        {
            "result": {
                "decision": {"nominated_candidate_id": None, "eligible_candidate_ids": ["c1"]}
            }
        },
    )
    assert derive_paper_readiness(tmp_path).eligible_paper_candidate_present is True


def test_fully_provisioned_synthetic_tree_can_authorize(tmp_path: Path) -> None:
    # The ONLY way authorization derives true is a complete, genuine evidence set. We prove the
    # conjunction is honest (not tautologically false) by constructing every gate's evidence in a
    # throwaway tree. Accepted V2 lacks the nomination + freeze + approval, so this never fires on
    # the real repository — but the gate must be reachable in principle, or it would be theater.
    _write(
        tmp_path,
        "research/v2a/results.json",
        {"decision": {"nominated_candidate_id": "cand-synthetic"}},
    )
    _write(
        tmp_path,
        "research/v2b/v2b_results.json",
        {
            "result": {
                "decision": {
                    "nominated_candidate_id": "cand-synthetic",
                    "eligible_candidate_ids": ["cand-synthetic"],
                }
            }
        },
    )
    _touch_empty_ledgers(tmp_path)
    _private_pyproject(tmp_path)
    _write(
        tmp_path,
        "governance/v2/fable5_remediation_state.json",
        {"all_findings_resolved": True, "unresolved_class_abd_count": 0},
    )
    _write(tmp_path, "governance/v2/fable5_audit_manifest.json", {"audit": "fable5"})
    _write(tmp_path, "governance/v2/paper_release_freeze.json", {"frozen": True})
    _write(tmp_path, "governance/v2/paper_activation_approval.json", {"approved_by": "human"})
    state = derive_paper_readiness(tmp_path)
    assert state.paper_activation_authorized is True  # reachable in principle...
    # sell_ready is independent of the paper gate and still false (its own governance gates unmet).
    assert state.sell_ready is False


def test_sealed_ledger_nonempty_blocks_sealed_gate(tmp_path: Path) -> None:
    _touch_empty_ledgers(tmp_path)
    (tmp_path / "research/m2b/test_evaluations.jsonl").write_bytes(b'{"x":1}\n')
    assert derive_paper_readiness(tmp_path).gates["sealed_partitions_untouched"] is False


def test_missing_sealed_ledger_blocks_sealed_gate(tmp_path: Path) -> None:
    # Absence is not emptiness: a missing ledger is not proof of untouched sealed state.
    assert derive_paper_readiness(tmp_path).gates["sealed_partitions_untouched"] is False


def test_paper_trading_record_presence_flips_active(tmp_path: Path) -> None:
    _write(tmp_path, "governance/v2/paper_trading_record.json", {"started": True})
    # trading_active reflects the *observed* record, independent of authorization; the verifier
    # (below) then refuses such a state in this milestone.
    assert derive_paper_readiness(tmp_path).paper_trading_active is True


# --------------------------------------------------------------------------------------------------
# 3. Fail-closed verification
# --------------------------------------------------------------------------------------------------


def test_verify_accepts_the_matching_committed_state(tmp_path: Path) -> None:
    state = derive_paper_readiness(tmp_path)
    verify_paper_readiness(tmp_path, state.to_canonical())  # must not raise


def test_verify_rejects_forged_authorization(tmp_path: Path) -> None:
    state = derive_paper_readiness(tmp_path).to_canonical()
    state["paper_activation_authorized"] = True
    with pytest.raises(PaperReadinessError, match="paper_activation_authorized"):
        verify_paper_readiness(tmp_path, state)


def test_verify_rejects_forged_eligibility(tmp_path: Path) -> None:
    state = derive_paper_readiness(tmp_path).to_canonical()
    state["eligible_paper_candidate_present"] = True
    with pytest.raises(PaperReadinessError, match="eligible_paper_candidate_present"):
        verify_paper_readiness(tmp_path, state)


def test_verify_rejects_gate_vector_drift(tmp_path: Path) -> None:
    state = derive_paper_readiness(tmp_path).to_canonical()
    gates = state["gates"]
    assert isinstance(gates, dict)
    gates["repository_private"] = not gates["repository_private"]
    with pytest.raises(PaperReadinessError, match="gate vector drift"):
        verify_paper_readiness(tmp_path, state)


def test_verify_rejects_forged_sell_ready(tmp_path: Path) -> None:
    state = derive_paper_readiness(tmp_path).to_canonical()
    state["sell_ready"] = True
    with pytest.raises(PaperReadinessError, match="sell_ready"):
        verify_paper_readiness(tmp_path, state)


def test_verify_real_committed_state_if_present() -> None:
    # If the committed paper_readiness_state.json exists on the real tree, it must verify and must
    # encode a fully-blocked, unauthorized state.
    committed_path = REPO_ROOT / "governance/v2/paper_readiness_state.json"
    if not committed_path.is_file():
        pytest.skip("committed paper-readiness state not present yet (pre-freeze)")
    committed = json.loads(committed_path.read_text())
    verify_paper_readiness(REPO_ROOT, committed)
    assert committed["paper_activation_authorized"] is False
    assert committed["paper_trading_active"] is False
    assert committed["sell_ready"] is False
    assert committed["eligible_paper_candidate_present"] is False
