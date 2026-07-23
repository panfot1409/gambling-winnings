"""Fable 5 source-freeze + governance-artifact regression tests.

The Fable 5 audit freezes its own tooling, its two remediated source files, and its committed
governance records (inventory, findings, remediation state, audit manifest, paper-readiness state)
by sha256 in ``governance/v2/fable5_source_freeze.json``. These tests prove the freeze round-trips,
fails closed on any byte drift or an opened sealed ledger, and that the committed governance
artifacts encode the honest terminal state (zero unresolved Class A/B/D; paper activation blocked).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eth_research.v2.fable5.freeze import (
    FABLE5_SOURCE_FREEZE_RELPATH,
    Fable5FreezeError,
    build_source_freeze,
    load_committed_freeze,
    verify_source_freeze,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------------------------------
# Round-trip + real-tree acceptance
# --------------------------------------------------------------------------------------------------


def test_committed_source_freeze_verifies_on_the_real_tree() -> None:
    committed = load_committed_freeze(REPO_ROOT)
    checks = verify_source_freeze(REPO_ROOT, committed)
    assert "frozen_source_match" in checks
    assert "frozen_governance_match" in checks
    assert "sealed_ledgers_byte_empty" in checks
    assert "baseline_match" in checks


def test_build_equals_committed() -> None:
    committed = load_committed_freeze(REPO_ROOT)
    live = build_source_freeze(REPO_ROOT)
    assert live["frozen_source_sha256"] == committed["frozen_source_sha256"]
    assert live["frozen_governance_sha256"] == committed["frozen_governance_sha256"]
    assert live["expected_sealed_ledgers"] == committed["expected_sealed_ledgers"]
    assert live["baseline_merge_commit"] == committed["baseline_merge_commit"]


def test_freeze_pins_the_two_remediated_files() -> None:
    src = build_source_freeze(REPO_ROOT)["frozen_source_sha256"]
    assert isinstance(src, dict)
    assert "src/eth_research/fractional/engine.py" in src
    assert "src/eth_research/v2ab/commercial_truth.py" in src


# --------------------------------------------------------------------------------------------------
# Fail-closed drift detection (all against a disposable copy — never the real tree)
# --------------------------------------------------------------------------------------------------


def _minimal_frozen_tree(root: Path) -> None:
    """Reproduce, under ``root``, just enough of the frozen file set for build_source_freeze."""
    from eth_research.v2.fable5.freeze import (
        FROZEN_GOVERNANCE_RELPATHS,
        FROZEN_SOURCE_RELPATHS,
    )

    for rel in (*FROZEN_SOURCE_RELPATHS, *FROZEN_GOVERNANCE_RELPATHS):
        src = REPO_ROOT / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    for rel in (
        "research/m2b/test_evaluations.jsonl",
        "research/m3a/development_gate_access.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    ):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")


def test_verify_detects_source_drift(tmp_path: Path) -> None:
    _minimal_frozen_tree(tmp_path)
    committed = build_source_freeze(tmp_path)  # freeze the pristine copy
    # Catastrophe: tamper a frozen source file's bytes.
    target = tmp_path / "src/eth_research/v2ab/commercial_truth.py"
    target.write_bytes(target.read_bytes() + b"\n# tamper\n")
    with pytest.raises(Fable5FreezeError, match="frozen_source_sha256"):
        verify_source_freeze(tmp_path, committed)


def test_verify_detects_governance_drift(tmp_path: Path) -> None:
    _minimal_frozen_tree(tmp_path)
    committed = build_source_freeze(tmp_path)
    target = tmp_path / "governance/v2/fable5_findings.json"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(Fable5FreezeError, match="frozen_governance_sha256"):
        verify_source_freeze(tmp_path, committed)


def test_build_rejects_a_nonempty_sealed_ledger(tmp_path: Path) -> None:
    _minimal_frozen_tree(tmp_path)
    (tmp_path / "research/m3d/prospective_evaluations.jsonl").write_bytes(b'{"x":1}\n')
    with pytest.raises(Fable5FreezeError, match="sealed ledger not byte-empty"):
        build_source_freeze(tmp_path)


def test_build_rejects_a_missing_frozen_file(tmp_path: Path) -> None:
    _minimal_frozen_tree(tmp_path)
    (tmp_path / "src/eth_research/v2/fable5/freeze.py").unlink()
    with pytest.raises(Fable5FreezeError, match="frozen source file missing"):
        build_source_freeze(tmp_path)


def test_load_committed_freeze_fails_closed_when_absent(tmp_path: Path) -> None:
    with pytest.raises(Fable5FreezeError, match="missing committed source freeze"):
        load_committed_freeze(tmp_path)


# --------------------------------------------------------------------------------------------------
# Committed governance artifacts encode the honest terminal state
# --------------------------------------------------------------------------------------------------


def test_committed_findings_are_zero_class_abd() -> None:
    findings = json.loads((REPO_ROOT / "governance/v2/fable5_findings.json").read_text())
    counts = findings["class_counts"]
    assert counts["A"] == 0
    assert counts["B"] == 0
    assert counts["D"] == 0
    assert findings["no_unresolved_class_abd"] is True


def test_committed_remediation_state_is_fully_resolved() -> None:
    rem = json.loads((REPO_ROOT / "governance/v2/fable5_remediation_state.json").read_text())
    assert rem["all_findings_resolved"] is True
    assert rem["unresolved_class_abd_count"] == 0
    assert rem["sealed_partitions_untouched"] is True


def test_committed_manifest_encodes_blocked_state_and_verdict() -> None:
    manifest = json.loads((REPO_ROOT / "governance/v2/fable5_audit_manifest.json").read_text())
    assert manifest["paper_activation_authorized"] is False
    assert manifest["paper_trading_active"] is False
    assert manifest["prospective_collection_active"] is False
    assert manifest["sell_ready"] is False
    assert manifest["sealed_partitions_untouched"] is True
    assert manifest["terminal_verdict"] == (
        "FABLE 5 V2 FULL-SYSTEM AUDIT COMPLETE — PLATFORM HARDENED AND INDEPENDENTLY VERIFIED; "
        "NO ELIGIBLE PAPER-TRADING CANDIDATE EXISTS; PAPER ACTIVATION REMAINS BLOCKED; "
        "PROSPECTIVE COLLECTION INACTIVE; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY"
    )


def test_committed_paper_readiness_state_is_hardened_but_blocked() -> None:
    state = json.loads((REPO_ROOT / "governance/v2/paper_readiness_state.json").read_text())
    # Platform is audited + hardened (remediation state is frozen)...
    assert state["gates"]["platform_audit_complete"] is True
    assert state["gates"]["platform_hardened"] is True
    # ...but the scientific gate blocks and nothing is authorized.
    assert state["eligible_paper_candidate_present"] is False
    assert state["paper_activation_authorized"] is False
    assert state["paper_trading_active"] is False
    assert state["sell_ready"] is False


def test_source_freeze_relpath_is_stable() -> None:
    assert FABLE5_SOURCE_FREEZE_RELPATH == "governance/v2/fable5_source_freeze.json"
