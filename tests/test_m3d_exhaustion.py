"""Tests for the M3D research-train exhaustion policy and guard."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from eth_research.m3d import _upstream as up
from eth_research.m3d.exhaustion import (
    ALLOWED_OPERATIONS,
    DECISION_PATH,
    FORBIDDEN_OPERATIONS,
    ExhaustedPartitionError,
    ResearchTrainExhaustionDecision,
    build_research_train_exhaustion,
    is_protected_partition,
    require_operation_allowed,
    verify_research_train_exhaustion,
)

_REPO = Path(__file__).resolve().parents[1]


def _built() -> dict[str, Any]:
    return copy.deepcopy(build_research_train_exhaustion(_REPO).document)


def test_build_is_deterministic_and_committed_matches() -> None:
    a = build_research_train_exhaustion(_REPO).to_json_bytes()
    b = build_research_train_exhaustion(_REPO).to_json_bytes()
    assert a == b
    assert (_REPO / DECISION_PATH).read_bytes() == a
    verify_research_train_exhaustion(_REPO)


def test_classification_and_outcome() -> None:
    doc = _built()
    assert doc["classification"] == "exhausted_for_new_candidate_research"
    assert doc["m3c_outcome"] == "rejected_for_development_gate_promotion"


@pytest.mark.parametrize("operation", sorted(FORBIDDEN_OPERATIONS))
def test_guard_forbids_every_forbidden_operation_on_research_train(operation: str) -> None:
    with pytest.raises(ExhaustedPartitionError):
        require_operation_allowed(up.RESEARCH_TRAIN_FINGERPRINT, operation)


@pytest.mark.parametrize("operation", sorted(ALLOWED_OPERATIONS))
def test_guard_allows_every_allowed_operation(operation: str) -> None:
    require_operation_allowed(up.RESEARCH_TRAIN_FINGERPRINT, operation)  # no raise


@pytest.mark.parametrize(
    "identity",
    [
        "research_train",
        "development_gate",
        "final_holdout",
        "m2b_train",
        "m2b_validation",
        up.RESEARCH_TRAIN_FINGERPRINT,
        up.DEVELOPMENT_GATE_FINGERPRINT,
        up.FINAL_HOLDOUT_FINGERPRINT,
    ],
)
def test_guard_forbids_new_research_on_every_protected_partition_and_alias(identity: str) -> None:
    assert is_protected_partition(identity)
    with pytest.raises(ExhaustedPartitionError):
        require_operation_allowed(identity, "new_candidate_generation")


def test_guard_is_fail_closed_on_unknown_operation() -> None:
    with pytest.raises(ValueError, match="fail-closed"):
        require_operation_allowed("research_train", "sneaky_relabelled_op")


def test_guard_passes_through_unprotected_partition() -> None:
    # A genuinely different (future) fingerprint is out of this guard's scope.
    require_operation_allowed("sha256:" + "a" * 64, "new_candidate_generation")


def test_unprotected_partition_is_not_protected() -> None:
    assert not is_protected_partition("sha256:" + "b" * 64)
    assert not is_protected_partition("m3d_prospective_cohort")


def test_from_mapping_rejects_changed_classification() -> None:
    doc = _built()
    doc["classification"] = "still_open_for_research"
    with pytest.raises(ValueError, match="must be exactly"):
        ResearchTrainExhaustionDecision.from_mapping(doc)


def test_from_mapping_rejects_mutated_operation_vocabulary() -> None:
    doc = _built()
    doc["forbidden_operations"] = [o for o in doc["forbidden_operations"] if o != "new_bootstrap"]
    with pytest.raises(ValueError, match="forbidden_operations must match"):
        ResearchTrainExhaustionDecision.from_mapping(doc)


def test_from_mapping_rejects_bound_hash_tamper() -> None:
    doc = _built()
    doc["bound_hashes"]["m3c_decision"] = "0" * 64
    # Structurally valid but no longer a byte-for-byte rebuild.
    with pytest.raises(ValueError, match="does not match the rebuilt"):
        _write_and_verify(doc)


def _write_and_verify(doc: dict[str, Any]) -> None:
    from eth_research.m3d.validation import canonical_json_bytes

    path = _REPO / DECISION_PATH
    original = path.read_bytes()
    try:
        path.write_bytes(canonical_json_bytes(doc))
        verify_research_train_exhaustion(_REPO)
    finally:
        path.write_bytes(original)
