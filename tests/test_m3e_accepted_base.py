"""The accepted prospective base is M3E's verified trusted input (commit 3).

The expected base facts are not hard-coded: they are read from the committed
governance acceptance evidence (``research/m3e/acceptance_registry.jsonl`` and the
per-proposal ``acceptance.json``), so the verified base is cross-checked against
exactly the state governance accepted — for the genesis snapshot and after every
append-only acceptance alike.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.m3d.protocol import COHORT_START
from eth_research.m3e.accepted_base import (
    ACCEPTED_BASE_PATH,
    build_accepted_base_bytes,
    build_accepted_base_document,
    load_accepted_base,
    verify_accepted_base,
)
from eth_research.m3e.validation import M3EValidationError, canonical_json_bytes

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
_ACCEPTANCE_REGISTRY = "research/m3e/acceptance_registry.jsonl"
_ACCEPTANCES_DIR = "research/m3e/acceptances"


def _acceptance_registry_entries() -> list[dict[str, Any]]:
    lines = (REPO_ROOT / _ACCEPTANCE_REGISTRY).read_text().splitlines()
    return [json.loads(line) for line in lines]


def _acceptance_record(proposal_id: str) -> dict[str, Any]:
    path = REPO_ROOT / _ACCEPTANCES_DIR / proposal_id / "acceptance.json"
    record = json.loads(path.read_text())
    assert isinstance(record, dict)
    return record


def _accepted_proposal_ids() -> list[str]:
    ids = [
        str(e["proposal_id"])
        for e in _acceptance_registry_entries()
        if e.get("entry_kind") == "acceptance"
    ]
    assert ids, "the acceptance registry must record at least one accepted proposal"
    return ids


def test_verify_accepted_base_binds_the_accepted_cohort() -> None:
    base = verify_accepted_base(REPO_ROOT)
    accepted = _acceptance_record(_accepted_proposal_ids()[-1])["new_accepted"]
    # The verified (rebuilt-from-M3D-evidence) base is exactly the state the latest
    # governance acceptance bound — boundaries, row count, and content fingerprint.
    assert base.first_open == COHORT_START  # append-only growth never moves the genesis open
    assert base.document["cohort_start"] == COHORT_START
    assert base.last_open == accepted["last_open"]
    assert base.row_count == accepted["row_count"]
    assert base.canonical_content_fingerprint == accepted["canonical_content_fingerprint"]
    # ... and the committed snapshot is byte-bound by the acceptance evidence.
    committed = (REPO_ROOT / ACCEPTED_BASE_PATH).read_bytes()
    assert hashlib.sha256(committed).hexdigest() == accepted["accepted_base_file_sha256"]
    assert base.document["maturity_state"] == "immature"
    assert base.document["evaluation_authorized"] is False


def test_acceptance_evidence_pins_the_genesis_state_and_append_only_growth() -> None:
    # The historical genesis facts are pinned by the committed acceptance evidence,
    # not by git history: the first acceptance binds the pre-acceptance cohort
    # (3 rows, last open 2026-07-14, fingerprint bb6dd392…) and proves the growth
    # was a strict append with no prior row changed or deleted.
    first = _acceptance_record(_accepted_proposal_ids()[0])
    previous = first["previous_accepted"]
    assert previous["row_count"] == 3
    assert previous["last_open"] == "2026-07-14T00:00:00Z"
    assert (
        previous["canonical_content_fingerprint"]
        == "bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507"
    )
    assert first["append_only_proof"]["is_append_only"] is True
    assert first["append_only_proof"]["prior_rows_changed"] == 0
    assert first["append_only_proof"]["prior_rows_deleted"] == 0
    assert first["new_accepted"]["row_count"] == (
        previous["row_count"] + first["append_interval"]["row_count"]
    )
    # The registry's genesis entry pins the exact pre-acceptance snapshot bytes the
    # first acceptance grew from — the two committed sources must agree.
    genesis = _acceptance_registry_entries()[0]
    assert genesis["entry_kind"] == "genesis"
    assert (
        previous["state"]["research/m3e/accepted_base.json"]
        == genesis["pre_acceptance_state"]["research/m3e/accepted_base.json"]
    )


def test_build_is_deterministic_and_matches_committed() -> None:
    first = build_accepted_base_bytes(REPO_ROOT)
    second = build_accepted_base_bytes(REPO_ROOT)
    assert first == second
    assert first == (REPO_ROOT / ACCEPTED_BASE_PATH).read_bytes()


def test_the_three_ledgers_are_bound_byte_empty() -> None:
    base = verify_accepted_base(REPO_ROOT)
    ledgers = base.document["ledgers"]
    assert set(ledgers) == {"development_gate", "final_holdout", "prospective_evaluation"}
    empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    for facts in ledgers.values():
        assert facts["byte_count"] == 0
        assert facts["sha256"] == empty


def test_m3c_candidate_recorded_rejected_in_the_base() -> None:
    base = verify_accepted_base(REPO_ROOT)
    assert (
        base.document["provenance"]["m3c_candidate_decision_outcome"]
        == "rejected_for_development_gate_promotion"
    )


def test_load_round_trips_the_committed_snapshot() -> None:
    base = load_accepted_base(REPO_ROOT / ACCEPTED_BASE_PATH)
    assert base.base_sha256 == build_accepted_base_document(REPO_ROOT)["base_sha256"]


def test_a_tampered_base_hash_is_rejected(tmp_path: Path) -> None:
    doc = build_accepted_base_document(REPO_ROOT)
    doc["base_sha256"] = "0" * 64  # forge the self-hash
    path = tmp_path / "accepted_base.json"
    path.write_bytes(canonical_json_bytes(doc))
    with pytest.raises(M3EValidationError, match="base_sha256 does not match"):
        load_accepted_base(path)


def test_a_tampered_field_breaks_the_self_hash(tmp_path: Path) -> None:
    # Silently editing a bound field without recomputing the hash is caught.
    doc = build_accepted_base_document(REPO_ROOT)
    doc["row_count"] = int(doc["row_count"]) + 1  # a lie: one row the cohort does not hold
    path = tmp_path / "accepted_base.json"
    path.write_bytes(canonical_json_bytes(doc))
    with pytest.raises(M3EValidationError, match="base_sha256 does not match"):
        load_accepted_base(path)


def test_a_non_canonical_committed_snapshot_is_rejected(tmp_path: Path) -> None:
    doc = build_accepted_base_document(REPO_ROOT)
    path = tmp_path / "accepted_base.json"
    path.write_text(json.dumps(doc))  # compact, non-canonical bytes
    with pytest.raises(M3EValidationError):
        load_accepted_base(path)
