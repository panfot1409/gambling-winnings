"""Adversarial drift/tamper matrix for Milestone 3E (commit 22).

Each test tampers with exactly one artifact inside a disposable full clone of the
real repository (the ``m3a_checkout`` fixture carries the complete committed
layer — the M3E accepted base, the append-only proposal registry, the sealed
ledgers, and the running ``src/eth_research`` overlay) and proves a specific M3E
verifier fails closed: the accepted-base binder, the append-only registry chain,
the offline deep replay, the isolated-import firewall, or the workflow-security
scan. The clean clone passes every verifier first, so each failure below is the
injected tamper and nothing else.

M3E evaluates nothing, so none of these paths touch a strategy, a candidate, a
metric, money, or the accepted branch — they only prove that a corrupted data
proposal or a corrupted base can never be presented as verified.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eth_research.m3e.accepted_base import (
    ACCEPTED_BASE_DOMAIN,
    load_accepted_base,
    verify_accepted_base,
)
from eth_research.m3e.registry import verify_registry
from eth_research.m3e.replay import replay
from eth_research.m3e.validation import M3EValidationError, canonical_json_bytes, domain_sha256
from eth_research.m3e.verify_m3e_program import _no_unsafe_workflow, _scan_m3e_imports

_ACCEPTED = "research/m3e/accepted_base.json"
_REGISTRY = "research/m3e/proposal_registry.jsonl"
_M3C_DECISION = "research/m3c/candidate_decision.json"
_PROSPECTIVE_LEDGER = "research/m3d/prospective_evaluations.jsonl"
_GATE_LEDGER = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER = "research/m2b/test_evaluations.jsonl"


def _resign_accepted(doc: dict[str, object]) -> bytes:
    """Re-sign a tampered accepted-base document so it passes the self-hash gate
    and the tamper reaches the rebuild-mismatch check rather than tripping the
    base_sha256 self-check first."""
    body = {k: v for k, v in doc.items() if k != "base_sha256"}
    doc = dict(doc)
    doc["base_sha256"] = domain_sha256(ACCEPTED_BASE_DOMAIN, body)
    return canonical_json_bytes(doc)


# --------------------------------------------------------------------------- #
# sanity: the untampered clone verifies end to end                            #
# --------------------------------------------------------------------------- #
def test_clean_clone_passes_every_m3e_verifier(m3a_checkout: Path) -> None:
    verify_accepted_base(m3a_checkout)
    verify_registry(m3a_checkout)
    replay(m3a_checkout, deep=True)  # rebuild byte-exact, ledgers empty before/after
    _scan_m3e_imports(m3a_checkout)
    _no_unsafe_workflow(m3a_checkout)


# --------------------------------------------------------------------------- #
# sealed / prospective ledger contamination                                   #
# --------------------------------------------------------------------------- #
def test_a_contaminated_prospective_ledger_hard_stops(m3a_checkout: Path) -> None:
    (m3a_checkout / _PROSPECTIVE_LEDGER).write_bytes(b'{"evaluated": true}\n')
    with pytest.raises(M3EValidationError, match="byte-empty"):
        verify_accepted_base(m3a_checkout)


def test_a_contaminated_gate_ledger_hard_stops(m3a_checkout: Path) -> None:
    (m3a_checkout / _GATE_LEDGER).write_bytes(b'{"touch": 1}\n')
    with pytest.raises(M3EValidationError, match="byte-empty"):
        verify_accepted_base(m3a_checkout)


def test_a_contaminated_holdout_ledger_hard_stops(m3a_checkout: Path) -> None:
    (m3a_checkout / _HOLDOUT_LEDGER).write_bytes(b'{"touch": 1}\n')
    with pytest.raises(M3EValidationError, match="byte-empty"):
        verify_accepted_base(m3a_checkout)


def test_replay_hard_stops_on_a_contaminated_ledger(m3a_checkout: Path) -> None:
    # The deep replay independently re-asserts the three ledgers are byte-empty.
    (m3a_checkout / _PROSPECTIVE_LEDGER).write_bytes(b'{"evaluated": true}\n')
    with pytest.raises(M3EValidationError):
        replay(m3a_checkout, deep=True)


# --------------------------------------------------------------------------- #
# accepted-base tampering                                                     #
# --------------------------------------------------------------------------- #
def test_tampering_the_cohort_fingerprint_is_rejected(m3a_checkout: Path) -> None:
    # Load the tampered snapshot directly: the self-hash gate refuses a document
    # whose base_sha256 no longer signs its (fingerprint-mutated) content.
    path = m3a_checkout / _ACCEPTED
    doc = json.loads(path.read_text())
    doc["canonical_content_fingerprint"] = "0" * 64  # a lie, without re-signing
    path.write_bytes(canonical_json_bytes(doc))
    with pytest.raises(M3EValidationError, match="base_sha256 does not match"):
        load_accepted_base(path)


def test_verify_rebuild_binding_rejects_a_mutated_snapshot(m3a_checkout: Path) -> None:
    # Even a self-consistent forgery (re-signed) is caught: verify re-derives the
    # snapshot from M3D evidence and compares bytes, so any drift is rejected.
    path = m3a_checkout / _ACCEPTED
    doc = json.loads(path.read_text())
    doc["canonical_content_fingerprint"] = "0" * 64
    path.write_bytes(_resign_accepted(doc))
    with pytest.raises(M3EValidationError, match="does not match the rebuild"):
        verify_accepted_base(m3a_checkout)


def test_forcing_maturity_in_the_accepted_base_is_rejected(m3a_checkout: Path) -> None:
    path = m3a_checkout / _ACCEPTED
    doc = json.loads(path.read_text())
    doc["maturity_state"] = "mature"
    doc["evaluation_authorized"] = True
    # Re-sign so the tamper survives the self-hash gate and reaches the rebuild.
    path.write_bytes(_resign_accepted(doc))
    with pytest.raises(M3EValidationError, match="does not match the rebuild"):
        verify_accepted_base(m3a_checkout)


def test_flipping_the_m3c_verdict_is_rejected(m3a_checkout: Path) -> None:
    path = m3a_checkout / _M3C_DECISION
    decision = json.loads(path.read_text())
    decision["outcome"] = "accepted_for_development_gate_promotion"
    path.write_bytes(canonical_json_bytes(decision))
    with pytest.raises(M3EValidationError, match="M3C candidate outcome changed"):
        verify_accepted_base(m3a_checkout)


# --------------------------------------------------------------------------- #
# append-only registry tampering                                              #
# --------------------------------------------------------------------------- #
def test_a_tampered_registry_record_is_rejected(m3a_checkout: Path) -> None:
    path = m3a_checkout / _REGISTRY
    lines = path.read_bytes().splitlines()
    record = json.loads(lines[-1])
    record["reason"] = "tampered reason text"
    lines[-1] = json.dumps(record, sort_keys=True).encode()
    path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(M3EValidationError):
        verify_registry(m3a_checkout)


def test_an_audit_record_claiming_a_proposal_is_rejected(m3a_checkout: Path) -> None:
    path = m3a_checkout / _REGISTRY
    lines = path.read_bytes().splitlines()
    record = json.loads(lines[-1])  # the audit_noop record
    record["proposal_created"] = True  # forge a proposal claim
    lines[-1] = json.dumps(record, sort_keys=True).encode()
    path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(M3EValidationError):
        verify_registry(m3a_checkout)


# --------------------------------------------------------------------------- #
# source + workflow firewall tampering                                        #
# --------------------------------------------------------------------------- #
def test_injecting_a_prohibited_import_is_caught(m3a_checkout: Path) -> None:
    # An engine module absent from any deny-list intuition is still caught because
    # the m3e import scan is an allow-list, not a block-list.
    target = m3a_checkout / "src/eth_research/m3e/status.py"
    target.write_text("import eth_research.fractional.accounting\n" + target.read_text())
    with pytest.raises(M3EValidationError, match="non-allowlisted"):
        _scan_m3e_imports(m3a_checkout)


def test_injecting_a_relative_engine_import_is_caught(m3a_checkout: Path) -> None:
    # A RELATIVE import into a sibling engine (``from ..fractional.engine``) resolves
    # to the real off-limits module and is caught — the scan resolves node.level.
    target = m3a_checkout / "src/eth_research/m3e/status.py"
    target.write_text("from ..fractional.engine import x  # noqa\n" + target.read_text())
    with pytest.raises(M3EValidationError, match="non-allowlisted"):
        _scan_m3e_imports(m3a_checkout)


def test_injecting_a_network_import_is_caught(m3a_checkout: Path) -> None:
    # An m3e module opening a socket / http client is refused: it holds no key and
    # opens no socket, so its own source must never import a network module.
    target = m3a_checkout / "src/eth_research/m3e/status.py"
    target.write_text("import socket\n" + target.read_text())
    with pytest.raises(M3EValidationError, match="network"):
        _scan_m3e_imports(m3a_checkout)


def test_a_content_writing_workflow_is_caught(m3a_checkout: Path) -> None:
    # Any workflow at HEAD granting write to repository contents is rejected.
    hostile = m3a_checkout / ".github/workflows/zz_hostile.yml"
    hostile.write_text(
        "name: hostile\non: push\npermissions:\n  contents: write\njobs:\n"
        "  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    )
    with pytest.raises(M3EValidationError):
        _no_unsafe_workflow(m3a_checkout)
