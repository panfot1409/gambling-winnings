"""Adversarial drift/tamper matrix for Milestone 3D (section 26).

Each test tampers with one artifact inside a disposable full clone of the real
repository (the ``m3a_checkout`` fixture carries the complete committed layer,
including M3D) and proves the whole-program verifier, a specific verifier, or the
firewall fails closed. The clone's own ``src/eth_research`` is the running
package's source, so source-level tampering (a prohibited import) is caught too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eth_research.m3d.cohort import verify_cohort_manifest
from eth_research.m3d.raw_bundle import build_raw_bundles
from eth_research.m3d.reacquisition_audit import verify_reacquisition_audit
from eth_research.m3d.segment import verify_prospective_segments
from eth_research.m3d.validation import M3DValidationError, canonical_json_bytes, sha256_bytes
from eth_research.m3d.verify_m3d_program import _scan_prohibited_imports, verify_m3d_program

_GENESIS = "coinbase-eth-usd-prospective-genesis-001"
_RAW = f"research/m3d/raw/coinbase/{_GENESIS}/coinbase-eth-usd-1d_0000_20260712_20260715.json"


def test_clean_clone_passes_the_full_graph(m3a_checkout: Path) -> None:
    # Sanity: the untampered clone verifies, so every failure below is the tamper.
    assert len(verify_m3d_program(m3a_checkout)) == 25


def test_a_contaminated_prospective_ledger_hard_stops(m3a_checkout: Path) -> None:
    (m3a_checkout / "research/m3d/prospective_evaluations.jsonl").write_bytes(
        b'{"evaluated": true}\n'
    )
    with pytest.raises(M3DValidationError, match="prospective evaluation ledger is non-empty"):
        verify_m3d_program(m3a_checkout)


def test_a_contaminated_sealed_ledger_hard_stops(m3a_checkout: Path) -> None:
    (m3a_checkout / "research/m3a/development_gate_access.jsonl").write_bytes(b'{"touch": 1}\n')
    with pytest.raises(M3DValidationError, match="sealed ledger development_gate"):
        verify_m3d_program(m3a_checkout)


def test_flipping_the_m3c_verdict_is_rejected(m3a_checkout: Path) -> None:
    path = m3a_checkout / "research/m3c/candidate_decision.json"
    decision = json.loads(path.read_text())
    decision["outcome"] = "accepted_for_development_gate_promotion"
    path.write_text(json.dumps(decision))
    with pytest.raises(M3DValidationError, match="M3C candidate outcome changed"):
        verify_m3d_program(m3a_checkout)


def test_a_smuggled_evaluation_artifact_is_rejected(m3a_checkout: Path) -> None:
    (m3a_checkout / "research/m3d/candidate_results.json").write_text('{"sharpe": 2.0}')
    with pytest.raises(M3DValidationError, match="forbidden evaluation-output"):
        verify_m3d_program(m3a_checkout)


def test_forcing_maturity_in_the_manifest_is_rejected(m3a_checkout: Path) -> None:
    path = m3a_checkout / "research/m3d/prospective_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["maturity_state"] = "mature"
    manifest["evaluation_authorized"] = True
    # Write it back in canonical form so the tamper reaches the rebuild-mismatch
    # check rather than tripping the strict canonical-format loader first.
    path.write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(M3DValidationError, match="does not match the rebuilt manifest"):
        verify_cohort_manifest(m3a_checkout)


def test_tampering_a_raw_candle_byte_breaks_rebuild(m3a_checkout: Path) -> None:
    raw = m3a_checkout / _RAW
    rows = json.loads(raw.read_text())
    rows[0][4] = rows[0][4] + 5.0  # perturb a close price
    raw.write_text(json.dumps(rows))
    with pytest.raises(M3DValidationError, match="SHA-256 does not match the receipt"):
        build_raw_bundles(m3a_checkout, _GENESIS)


def test_tampering_the_segment_chain_is_rejected(m3a_checkout: Path) -> None:
    path = m3a_checkout / "research/m3d/prospective_segments.jsonl"
    lines = path.read_bytes().splitlines()
    record = json.loads(lines[1])
    record["row_count"] = 999
    lines[1] = json.dumps(record, sort_keys=True).encode()
    path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(M3DValidationError):
        verify_prospective_segments(m3a_checkout)


def test_injecting_a_prohibited_import_is_caught(m3a_checkout: Path) -> None:
    # An engine module absent from the deny-list intuition (fractional.accounting)
    # is still caught because the scan is an allow-list.
    target = m3a_checkout / "src/eth_research/m3d/status.py"
    target.write_text("import eth_research.fractional.accounting\n" + target.read_text())
    with pytest.raises(M3DValidationError, match="non-allowlisted eth_research modules"):
        _scan_prohibited_imports(m3a_checkout)


def test_a_non_independent_audit_reacquisition_is_rejected(m3a_checkout: Path) -> None:
    base = "research/m3d/raw/coinbase"
    genesis_receipt = json.loads(
        (m3a_checkout / base / _GENESIS / "acquisition_receipt.json").read_text()
    )
    audit_dir = m3a_checkout / base / "coinbase-eth-usd-prospective-audit-002"
    audit_path = audit_dir / "acquisition_receipt.json"
    audit = json.loads(audit_path.read_text())
    audit["source_commit"] = genesis_receipt["source_commit"]  # forge non-independence
    audit_path.write_bytes(canonical_json_bytes(audit))
    with pytest.raises(M3DValidationError, match="distinct source commits"):
        verify_reacquisition_audit(m3a_checkout)


def test_a_truncated_cohort_tail_is_rejected(m3a_checkout: Path) -> None:
    raw = m3a_checkout / _RAW
    rows = json.loads(raw.read_text())  # descending [07-14, 07-13, 07-12]
    raw.write_bytes(json.dumps(rows[1:]).encode())  # drop the newest completed day
    receipt_path = m3a_checkout / f"research/m3d/raw/coinbase/{_GENESIS}/acquisition_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["responses"][0]["response_sha256"] = sha256_bytes(raw.read_bytes())
    receipt["responses"][0]["response_byte_length"] = len(raw.read_bytes())
    receipt_path.write_bytes(canonical_json_bytes(receipt))
    with pytest.raises(M3DValidationError, match=r"planned|reach the plan window end"):
        build_raw_bundles(m3a_checkout, _GENESIS)
