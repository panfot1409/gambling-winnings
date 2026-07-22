"""V2C sections 6 + 10: the OQ protocol bundle + cash-control identity.

Proves the five committed protocol artifacts reproduce byte-for-byte from the live qualification
source, that the protocol binds its four sub-artifacts by a content hash equal to each committed
file's byte hash, that the fault schedule provably reproduces the live per-slot schedule, that the
cash-control identity is cross-checked against the live firewall, and that every drift, symlink, and
firewall/schedule divergence is refused fail-closed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.v2c.oq import protocol as P
from eth_research.v2c.oq.events import (
    OQ_MIN_ACCEPTED_EVENTS,
    OQ_MIN_EVENT_SLOTS,
    _fault_for_slot,
)
from eth_research.v2c.oq.slo import QUALIFICATION_CRITERIA

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# The committed bundle                                                        #
# --------------------------------------------------------------------------- #
def test_committed_bundle_reproduces_from_live_source() -> None:
    P.verify_oq_protocol_bundle(REPO)  # must not raise


def test_every_committed_artifact_exists_and_is_nonempty() -> None:
    for relpath, _ in P._ARTIFACTS:
        path = REPO / relpath
        assert path.is_file(), relpath
        assert path.stat().st_size > 0, relpath


def test_protocol_binds_subartifacts_by_committed_file_hash() -> None:
    """The hashes the protocol embeds must equal the committed sub-artifact files' byte hashes, so
    a single hash identifies each sub-artifact for both the protocol and OQ-R."""
    protocol = P.build_oq_protocol()
    assert protocol["fixture_sha256"] == P.committed_artifact_sha256(
        REPO, P.OQ_FIXTURE_MANIFEST_RELPATH
    )
    assert protocol["fault_schedule_sha256"] == P.committed_artifact_sha256(
        REPO, P.OQ_FAULT_SCHEDULE_RELPATH
    )
    assert protocol["slo_contract_sha256"] == P.committed_artifact_sha256(
        REPO, P.OQ_SLO_CONTRACT_RELPATH
    )
    assert protocol["cash_control_identity_sha256"] == P.committed_artifact_sha256(
        REPO, P.OQ_CASH_CONTROL_IDENTITY_RELPATH
    )


def test_committed_artifact_sha256_matches_raw_file_hash() -> None:
    raw = (REPO / P.OQ_PROTOCOL_RELPATH).read_bytes()
    expected = hashlib.sha256(raw).hexdigest()
    assert P.committed_artifact_sha256(REPO, P.OQ_PROTOCOL_RELPATH) == expected


# --------------------------------------------------------------------------- #
# Determinism                                                                 #
# --------------------------------------------------------------------------- #
def test_identity_build_is_deterministic() -> None:
    assert P.build_oq_cash_control_identity() == P.build_oq_cash_control_identity()


def test_fault_schedule_build_is_deterministic() -> None:
    assert P.build_oq_fault_schedule() == P.build_oq_fault_schedule()


def test_slo_contract_build_is_deterministic() -> None:
    assert P.build_oq_slo_contract() == P.build_oq_slo_contract()


# --------------------------------------------------------------------------- #
# Section 10: the cash-control identity                                       #
# --------------------------------------------------------------------------- #
def test_identity_is_zero_exposure_cash_control() -> None:
    identity = P.build_oq_cash_control_identity()
    assert identity["target_id"] == "cash_control"
    assert identity["is_strategy"] is False
    assert identity["reads_market_data_for_decision"] is False
    invariant = identity["zero_exposure_invariant"]
    assert set(invariant) == set(P.OQ_ZERO_EXPOSURE_INVARIANT)
    assert all(value == 0 for value in invariant.values())
    assert identity["allowed_request_kinds"] == ["cash_control_operation"]
    assert "identity_digest" in identity


def test_identity_cross_check_fails_if_firewall_admits_extra_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(P, "ALLOWED_REQUEST_KINDS", frozenset({"cash_control_operation", "evil"}))
    with pytest.raises(P.OQProtocolError, match="request kind"):
        P.build_oq_cash_control_identity()


def test_identity_cross_check_fails_if_target_id_drifts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(P, "CASH_CONTROL_TARGET_ID", "not_cash_control")
    with pytest.raises(P.OQProtocolError, match="cash-control target id"):
        P.build_oq_cash_control_identity()


# --------------------------------------------------------------------------- #
# The deterministic fault schedule                                            #
# --------------------------------------------------------------------------- #
def test_declared_schedule_reproduces_live_schedule_slot_for_slot() -> None:
    schedule = P.build_oq_fault_schedule()
    slots = schedule["slots"]
    # Independently reproduce every slot from the committed rule table and compare to live source.
    for index in range(slots):
        assert P._scheduled_fault(index) == _fault_for_slot(index), index
    assert sum(schedule["scheduled_fault_counts"].values()) == slots


def test_fault_schedule_binds_the_actual_sequence() -> None:
    schedule = P.build_oq_fault_schedule()
    expected = hashlib.sha256(
        "\n".join(_fault_for_slot(i) for i in range(schedule["slots"])).encode("utf-8")
    ).hexdigest()
    assert schedule["fault_vector_sha256"] == expected


def test_fault_schedule_detects_a_wrong_rule_table(monkeypatch: pytest.MonkeyPatch) -> None:
    # Drop a rule so the declared table no longer reproduces the live schedule.
    monkeypatch.setattr(P, "_FAULT_SCHEDULE_RULES", P._FAULT_SCHEDULE_RULES[:-1])
    with pytest.raises(P.OQProtocolError, match="diverges from live source"):
        P.build_oq_fault_schedule()


# --------------------------------------------------------------------------- #
# The materialized fixture manifest                                           #
# --------------------------------------------------------------------------- #
def test_fixture_covers_both_instruments_above_the_floors() -> None:
    fixture = P.build_oq_fixture_manifest()
    assert fixture["slots"] >= OQ_MIN_EVENT_SLOTS
    instruments = fixture["instruments"]
    assert set(instruments) == {"eth_usd", "btc_usd"}
    for symbol, manifest in instruments.items():
        assert manifest["accepted_count"] >= OQ_MIN_ACCEPTED_EVENTS, symbol
        assert len(manifest["accepted_stream_sha256"]) == 64


def test_fixture_stream_hash_differs_between_instruments() -> None:
    instruments = P.build_oq_fixture_manifest()["instruments"]
    assert (
        instruments["eth_usd"]["accepted_stream_sha256"]
        != instruments["btc_usd"]["accepted_stream_sha256"]
    )


def test_fixture_below_floor_is_refused() -> None:
    with pytest.raises(P.OQProtocolError, match="minimum"):
        P.build_oq_fixture_manifest(slots=OQ_MIN_EVENT_SLOTS - 1)


# --------------------------------------------------------------------------- #
# The SLO contract                                                            #
# --------------------------------------------------------------------------- #
def test_slo_contract_matches_qualification_criteria() -> None:
    contract = P.build_oq_slo_contract()
    assert contract["criteria"] == list(QUALIFICATION_CRITERIA)
    assert tuple(contract["criterion_descriptions"]) == QUALIFICATION_CRITERIA
    assert contract["computes_market_performance"] is False


# --------------------------------------------------------------------------- #
# The protocol methodology                                                    #
# --------------------------------------------------------------------------- #
def test_protocol_identity_fields() -> None:
    protocol = P.build_oq_protocol()
    assert protocol["methodology_id"] == P.OQ_METHODOLOGY_ID
    assert protocol["qualification_id"] == P.OQ_QUALIFICATION_ID
    assert protocol["package_version"] == PACKAGE_VERSION
    assert protocol["criteria"] == list(QUALIFICATION_CRITERIA)
    assert protocol["instruments"] == ["btc_usd", "eth_usd"]
    assert "protocol_digest" in protocol


# --------------------------------------------------------------------------- #
# Drift / symlink / missing (fail-closed)                                     #
# --------------------------------------------------------------------------- #
def _materialize(tmp_path: Path) -> None:
    P.write_oq_protocol_bundle(tmp_path)


def test_mutated_artifact_is_refused(tmp_path: Path) -> None:
    _materialize(tmp_path)
    P.verify_oq_protocol_bundle(tmp_path)  # clean
    victim = tmp_path / P.OQ_SLO_CONTRACT_RELPATH
    victim.write_bytes(victim.read_bytes() + b"\n")
    with pytest.raises(P.OQProtocolError, match="does not reproduce"):
        P.verify_oq_protocol_bundle(tmp_path)


def test_symlinked_artifact_is_refused(tmp_path: Path) -> None:
    _materialize(tmp_path)
    victim = tmp_path / P.OQ_PROTOCOL_RELPATH
    victim.unlink()
    victim.symlink_to(tmp_path / P.OQ_SLO_CONTRACT_RELPATH)
    with pytest.raises(P.OQProtocolError, match="symlink"):
        P.verify_oq_protocol_bundle(tmp_path)


def test_missing_artifact_is_refused(tmp_path: Path) -> None:
    _materialize(tmp_path)
    (tmp_path / P.OQ_FIXTURE_MANIFEST_RELPATH).unlink()
    with pytest.raises(P.OQProtocolError, match="missing"):
        P.verify_oq_protocol_bundle(tmp_path)
