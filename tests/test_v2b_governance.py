"""V2B §23 governance: one-shot budget, protocol identity, and append-only registry lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eth_research
from eth_research.v2.strict import V2ValidationError
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


# --------------------------------------------------------------------------- #
# §26 pre-registration red-team regressions (Auditor E findings)               #
# --------------------------------------------------------------------------- #
def _seed_protocol_inputs(dst: Path) -> None:
    """Copy the four committed protocol-input artifacts so protocol_fingerprint(dst) reproduces."""
    import shutil

    src = REPO_ROOT / "research" / "v2b"
    (dst / "research" / "v2b").mkdir(parents=True, exist_ok=True)
    for name in (
        "candidate_source_freeze.json",
        "joint_partition_identity.json",
        "execution_scenarios.json",
        "research_multiplicity_state.json",
    ):
        shutil.copy(src / name, dst / "research" / "v2b" / name)


def test_append_event_rejects_a_non_hex64_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "reg.jsonl"
    with pytest.raises(V2ValidationError):
        gov.append_event(
            path, "registered", "v2b_run_001", protocol_fingerprint="not_hex", timestamp="t0"
        )


def test_reader_rejects_a_hash_valid_but_non_hex64_fingerprint(tmp_path: Path) -> None:
    from eth_research.v2.registry import GENESIS_PREV_HASH, RegistryEvent

    # A hand-forged line whose entry_hash MATCHES its body, but whose protocol_fingerprint is not
    # 64-hex. The hash check alone would pass; the strict field validation must still reject it.
    partial = RegistryEvent(
        seq=0,
        event="registered",
        run_id="v2b_run_001",
        protocol_fingerprint="deadbeef",  # too short to be a 64-hex digest
        timestamp="t0",
        payload={},
        prev_entry_hash=GENESIS_PREV_HASH,
        entry_hash="",
    )
    forged = RegistryEvent(
        seq=0,
        event="registered",
        run_id="v2b_run_001",
        protocol_fingerprint="deadbeef",
        timestamp="t0",
        payload={},
        prev_entry_hash=GENESIS_PREV_HASH,
        entry_hash=partial.recompute_hash(),
    )
    path = tmp_path / "reg.jsonl"
    path.write_bytes(forged.to_line())
    problems = gov.verify_registry(path)
    assert problems
    assert "protocol_fingerprint" in problems[0]


def test_reader_rejects_a_non_mapping_payload(tmp_path: Path) -> None:
    record = {
        "seq": 0,
        "event": "registered",
        "run_id": "v2b_run_001",
        "protocol_fingerprint": FP,
        "timestamp": "t0",
        "payload": [],  # not a JSON object
        "prev_entry_hash": "0" * 64,
        "entry_hash": "0" * 64,
    }
    line = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = tmp_path / "reg.jsonl"
    path.write_bytes(line)
    problems = gov.verify_registry(path)
    assert problems
    assert "payload" in problems[0]


def test_reader_rejects_an_unexpected_key(tmp_path: Path) -> None:
    record = {
        "seq": 0,
        "event": "registered",
        "run_id": "v2b_run_001",
        "protocol_fingerprint": FP,
        "timestamp": "t0",
        "payload": {},
        "prev_entry_hash": "0" * 64,
        "entry_hash": "0" * 64,
        "surprise": 1,  # an extra key the exact-key set must reject
    }
    line = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = tmp_path / "reg.jsonl"
    path.write_bytes(line)
    assert gov.verify_registry(path)  # non-empty problems


def test_verify_registry_bound_passes_for_the_committed_fingerprint(tmp_path: Path) -> None:
    _seed_protocol_inputs(tmp_path)
    fp = gov.protocol_fingerprint(tmp_path)
    reg = tmp_path / gov.V2B_REGISTRY_RELPATH
    gov.append_event(reg, "registered", "v2b_run_001", protocol_fingerprint=fp, timestamp="t0")
    gov.append_event(reg, "started", "v2b_run_001", protocol_fingerprint=fp, timestamp="t1")
    assert gov.verify_registry_bound(tmp_path) == []


def test_verify_registry_bound_flags_a_foreign_fingerprint(tmp_path: Path) -> None:
    _seed_protocol_inputs(tmp_path)
    reg = tmp_path / gov.V2B_REGISTRY_RELPATH
    # FP is valid hex64 but is not the committed protocol fingerprint.
    gov.append_event(reg, "registered", "v2b_run_001", protocol_fingerprint=FP, timestamp="t0")
    problems = gov.verify_registry_bound(tmp_path)
    assert problems
    assert "does not match the committed protocol" in problems[0]
