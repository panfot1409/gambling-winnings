"""Tests for the V2A one-shot pre-registration (checkpoint R).

The pre-registration pins the protocol / constitution / budget / contract / candidate fingerprints
of the frozen source and round-trips byte-for-byte. Because it is a pure function of that source,
``parse`` re-asserts every pin against the current code, rejecting any drift. It writes and loads
durably under ``research/v2a`` and its verifier passes on both the pristine (absent) and the
present-and-sound states while flagging a tampered artifact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eth_research.buyer.contract import EvaluationContract
from eth_research.v2.budget import OneShotResearchBudget
from eth_research.v2.candidates import V2A_CANDIDATES
from eth_research.v2.constitution import CommercialEvidenceConstitution
from eth_research.v2.preregistration import (
    PREREGISTRATION_NAME,
    V2A_DIR,
    PreRegistrationError,
    V2APreRegistration,
    load_preregistration,
    verify_preregistration,
    write_preregistration,
)
from eth_research.v2.protocol import ResearchProtocol
from eth_research.v2.strict import canonical_json_bytes, load_canonical_json


def test_build_pins_the_frozen_source_fingerprints() -> None:
    prereg = V2APreRegistration.build("run_001")
    assert prereg.run_id == "run_001"
    assert prereg.protocol_fingerprint == ResearchProtocol.current().fingerprint()
    assert prereg.constitution_fingerprint == CommercialEvidenceConstitution.current().fingerprint()
    assert prereg.budget_fingerprint == OneShotResearchBudget.current().fingerprint()
    assert prereg.contract_fingerprint == EvaluationContract.current().fingerprint()
    expected_cf = {s.candidate_id: s.fingerprint() for s in V2A_CANDIDATES}
    assert prereg.candidate_fingerprints == expected_cf


def test_roundtrips_and_fingerprint_is_stable() -> None:
    prereg = V2APreRegistration.build("run_001")
    assert V2APreRegistration.parse(prereg.to_canonical()).fingerprint() == prereg.fingerprint()
    # Deterministic: rebuilding gives the identical fingerprint.
    assert V2APreRegistration.build("run_001").fingerprint() == prereg.fingerprint()


def test_parse_rejects_drift_from_the_frozen_source() -> None:
    bad = V2APreRegistration.build("run_001").to_canonical()
    bad["protocol_fingerprint"] = "a" * 64  # well-formed hex, but not the real protocol fingerprint
    with pytest.raises(PreRegistrationError, match="drifted"):
        V2APreRegistration.parse(bad)


def test_write_and_load_roundtrip(tmp_path: Path) -> None:
    prereg = V2APreRegistration.build("run_001")
    path = write_preregistration(tmp_path, prereg)
    assert path == tmp_path / V2A_DIR / PREREGISTRATION_NAME
    # Bytes are the canonical encoding, and load re-verifies against the current source.
    assert path.read_bytes() == canonical_json_bytes(prereg.to_canonical())
    assert load_preregistration(tmp_path).fingerprint() == prereg.fingerprint()


def test_verify_is_clean_when_absent_or_sound_and_flags_tamper(tmp_path: Path) -> None:
    # Absent (pristine, pre-R): no problem.
    assert verify_preregistration(tmp_path) == []
    # Present and sound: no problem.
    write_preregistration(tmp_path, V2APreRegistration.build("run_001"))
    assert verify_preregistration(tmp_path) == []
    # Tampered on disk: flagged.
    path = tmp_path / V2A_DIR / PREREGISTRATION_NAME
    obj = load_canonical_json(path)
    obj["budget_fingerprint"] = "b" * 64
    path.write_bytes(canonical_json_bytes(obj))
    problems = verify_preregistration(tmp_path)
    assert any("invalid" in p for p in problems)
