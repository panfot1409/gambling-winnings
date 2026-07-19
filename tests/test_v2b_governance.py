"""V2B §23 governance: one-shot budget, protocol identity, and append-only registry lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eth_research
from eth_research.v2b import governance as gov
from eth_research.v2b.folds import OOS_FOLD_COUNT

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
FP = "a" * 64


def test_committed_budget_reproduces_and_reasserts_one_shot() -> None:
    gov.verify_budget(REPO_ROOT)
    committed = (REPO_ROOT / gov.V2B_BUDGET_RELPATH).read_bytes()
    doc = json.loads(committed)
    assert doc["max_research_executions"] == 1
    assert doc["consume_on_start"] is True
    assert doc["allow_repair_or_reset"] is False


def test_committed_protocol_identity_reproduces_and_binds_components() -> None:
    gov.verify_protocol_identity(REPO_ROOT)
    doc = json.loads((REPO_ROOT / gov.V2B_PROTOCOL_RELPATH).read_bytes())
    comp = doc["components"]
    for key in (
        "candidate_source_freeze_sha256",
        "joint_partition_identity_sha256",
        "execution_scenarios_sha256",
        "multiplicity_state_sha256",
    ):
        assert len(comp[key]) == 64
    assert comp["fold_structure"]["oos_fold_count"] == OOS_FOLD_COUNT
    assert doc["protocol_fingerprint"] == gov.protocol_fingerprint(REPO_ROOT)


def test_registry_lifecycle_registered_started_completed(tmp_path: Path) -> None:
    path = tmp_path / "reg.jsonl"
    gov.append_event(path, "registered", "v2b_run_001", protocol_fingerprint=FP, timestamp="t0")
    gov.append_event(path, "started", "v2b_run_001", protocol_fingerprint=FP, timestamp="t1")
    gov.append_event(
        path,
        "completed",
        "v2b_run_001",
        protocol_fingerprint=FP,
        timestamp="t2",
        payload={"verdict": "no_nomination"},
    )
    events = gov.read_events(path)
    assert [e.event for e in events] == ["registered", "started", "completed"]
    assert gov.verify_registry(path) == []


def test_second_started_is_rejected_one_shot_budget(tmp_path: Path) -> None:
    path = tmp_path / "reg.jsonl"
    gov.append_event(path, "registered", "v2b_run_001", protocol_fingerprint=FP, timestamp="t0")
    gov.append_event(path, "started", "v2b_run_001", protocol_fingerprint=FP, timestamp="t1")
    with pytest.raises(gov.V2BGovernanceError, match="one-shot budget"):
        gov.append_event(path, "started", "v2b_run_002", protocol_fingerprint=FP, timestamp="t2")


def test_started_requires_a_prior_registered(tmp_path: Path) -> None:
    path = tmp_path / "reg.jsonl"
    with pytest.raises(gov.V2BGovernanceError, match="no prior registered"):
        gov.append_event(path, "started", "v2b_run_001", protocol_fingerprint=FP, timestamp="t0")


def test_terminal_requires_a_prior_started(tmp_path: Path) -> None:
    path = tmp_path / "reg.jsonl"
    gov.append_event(path, "registered", "v2b_run_001", protocol_fingerprint=FP, timestamp="t0")
    with pytest.raises(gov.V2BGovernanceError, match="no started"):
        gov.append_event(path, "completed", "v2b_run_001", protocol_fingerprint=FP, timestamp="t1")


def test_double_terminal_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "reg.jsonl"
    gov.append_event(path, "registered", "v2b_run_001", protocol_fingerprint=FP, timestamp="t0")
    gov.append_event(path, "started", "v2b_run_001", protocol_fingerprint=FP, timestamp="t1")
    gov.append_event(path, "completed", "v2b_run_001", protocol_fingerprint=FP, timestamp="t2")
    with pytest.raises(gov.V2BGovernanceError, match="already terminal"):
        gov.append_event(path, "failed", "v2b_run_001", protocol_fingerprint=FP, timestamp="t3")


def test_tampering_a_committed_event_breaks_the_chain(tmp_path: Path) -> None:
    path = tmp_path / "reg.jsonl"
    gov.append_event(path, "registered", "v2b_run_001", protocol_fingerprint=FP, timestamp="t0")
    gov.append_event(
        path,
        "started",
        "v2b_run_001",
        protocol_fingerprint=FP,
        timestamp="t1",
        payload={"k": "original"},
    )
    tampered = path.read_bytes().replace(b"original", b"tampered!")
    path.write_bytes(tampered)
    assert gov.verify_registry(path)  # non-empty problems


def test_run_id_must_be_a_slug(tmp_path: Path) -> None:
    path = tmp_path / "reg.jsonl"
    with pytest.raises(Exception, match="slug"):
        gov.append_event(path, "registered", "v2b-run-001", protocol_fingerprint=FP, timestamp="t0")
