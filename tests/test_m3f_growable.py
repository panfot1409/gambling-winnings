"""V2D growable-surface lattice tests for the frozen M3F verification layer.

The committed M3F artifacts remain the immutable at-acceptance record. These tests
prove the supersession lattice: with zero growth every M3F verifier still passes
byte-static on the real tree (with the committed activation anchor present); the
anchor validator itself fails closed on tamper or the wrong mechanism; append-only
prefix proofs accept growth and refuse rewrites; and growth evidence WITHOUT the
anchor hard-stops. No test mutates the real repository.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from eth_research.m3f.growable import (
    GROWABLE_APPEND_CHAINS,
    GROWABLE_CURRENT_STATE,
    V2D_ANCHOR_RELPATH,
    is_growable_new_path,
    require_exact_prefix,
    v2d_activation_anchor_active,
)
from eth_research.m3f.honest_state import derive_honest_state, verify_honest_state
from eth_research.m3f.validation import M3FValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]

_HONEST_TREE_COPY: tuple[str, ...] = (
    "research/m3c/candidate_decision.json",
    "research/m3e/accepted_base.json",
    "research/m3e/proposal_registry.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
    "research/m3f/honest_state.json",
    "research/m3f/HONEST_STATE.md",
    V2D_ANCHOR_RELPATH,
)


@pytest.fixture
def honest_tree(tmp_path: Path) -> Path:
    for rel in _HONEST_TREE_COPY:
        src = REPO_ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return tmp_path


def _append_fake_proposal_record(root: Path) -> None:
    """Extend the registry chain with a structurally-valid proposal record."""
    from eth_research.m3d.chain import (
        PREVIOUS_FIELD,
        split_ledger_lines,
        verify_chain,
    )
    from eth_research.m3d.validation import canonical_jsonl_line, sha256_bytes

    path = root / "research/m3e/proposal_registry.jsonl"
    lines = split_ledger_lines(path.read_bytes())
    verify_chain(lines)
    record = {
        "schema_version": 1,
        "entry_kind": "proposal",
        "proposal_created": True,
        "proposal_id": "20260715-20260722-" + "a" * 16,
        "idempotency_key": "a" * 64,
        "proposal_branch": "bot/m3e-prospective-update/20260715-20260722-" + "a" * 16,
        "manifest_sha256": "b" * 64,
        "package_version": "0.8.0",
        PREVIOUS_FIELD: sha256_bytes(lines[-1]),
    }
    path.write_bytes(b"\n".join([*lines, canonical_jsonl_line(record)]) + b"\n")


# --------------------------------------------------------------------------------------------------
# Anchor validator
# --------------------------------------------------------------------------------------------------


def test_committed_anchor_is_active_on_the_real_tree() -> None:
    assert v2d_activation_anchor_active(REPO_ROOT) is True


def test_absent_anchor_is_inactive_never_an_error(tmp_path: Path) -> None:
    assert v2d_activation_anchor_active(tmp_path) is False


def test_tampered_anchor_hash_fails_closed(tmp_path: Path) -> None:
    src = (REPO_ROOT / V2D_ANCHOR_RELPATH).read_bytes()
    dst = tmp_path / V2D_ANCHOR_RELPATH
    dst.parent.mkdir(parents=True)
    dst.write_bytes(src.replace(b"2026-07-23", b"2026-07-24"))
    with pytest.raises(M3FValidationError, match="self-hash"):
        v2d_activation_anchor_active(tmp_path)


def test_anchor_for_another_workflow_fails_closed(tmp_path: Path) -> None:
    doc = json.loads((REPO_ROOT / V2D_ANCHOR_RELPATH).read_text())
    doc["mechanism"]["workflow_basename"] = "m3e-replay.yml"
    dst = tmp_path / V2D_ANCHOR_RELPATH
    dst.parent.mkdir(parents=True)
    dst.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")
    with pytest.raises(M3FValidationError):
        v2d_activation_anchor_active(tmp_path)


# --------------------------------------------------------------------------------------------------
# Append-only prefix proofs
# --------------------------------------------------------------------------------------------------


def test_prefix_proof_accepts_pure_appends_and_refuses_rewrites() -> None:
    baseline = b"line-1\nline-2\n"
    require_exact_prefix(baseline, baseline, "x")
    require_exact_prefix(baseline, baseline + b"line-3\n", "x")
    with pytest.raises(M3FValidationError, match="append-only"):
        require_exact_prefix(baseline, b"line-1\nline-X\nline-3\n", "x")
    with pytest.raises(M3FValidationError, match="append-only"):
        require_exact_prefix(baseline, baseline[:-1], "x")


def test_growable_surface_is_the_enumerated_set() -> None:
    assert "research/m3d/prospective_segments.jsonl" in GROWABLE_APPEND_CHAINS
    assert "research/m3e/accepted_base.json" in GROWABLE_CURRENT_STATE
    assert is_growable_new_path("research/m3d/update_attempts.jsonl")
    assert is_growable_new_path("research/m3e/proposals/x/proposal_manifest.json")
    assert is_growable_new_path(
        "research/m3d/raw/coinbase/coinbase-eth-usd-prospective-update-x/raw.json"
    )
    # The sealed evaluation ledger and genesis evidence are NEVER growable.
    assert not is_growable_new_path("research/m3d/prospective_evaluations.jsonl")
    assert not is_growable_new_path(
        "research/m3d/raw/coinbase/coinbase-eth-usd-prospective-genesis-001/raw.json"
    )


# --------------------------------------------------------------------------------------------------
# Honest-state lattice
# --------------------------------------------------------------------------------------------------


def test_honest_state_still_byte_reproduces_at_zero_growth() -> None:
    verify_honest_state(REPO_ROOT)


def test_growth_without_the_anchor_hard_stops(honest_tree: Path) -> None:
    (honest_tree / V2D_ANCHOR_RELPATH).unlink()
    _append_fake_proposal_record(honest_tree)
    with pytest.raises(M3FValidationError, match="without the V2D activation anchor"):
        derive_honest_state(honest_tree)


def test_growth_with_the_anchor_uses_floors(honest_tree: Path) -> None:
    _append_fake_proposal_record(honest_tree)
    verify_honest_state(honest_tree)  # floors hold: rows unchanged, still immature


def test_shrunken_cohort_is_refused_even_with_the_anchor(honest_tree: Path) -> None:
    _append_fake_proposal_record(honest_tree)
    base_path = honest_tree / "research/m3e/accepted_base.json"
    doc = json.loads(base_path.read_text())
    doc["row_count"] = 2  # below the accepted at-acceptance count
    base_path.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")
    with pytest.raises(M3FValidationError, match="shrank"):
        verify_honest_state(honest_tree)
