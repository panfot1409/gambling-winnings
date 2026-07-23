"""V2C section 32: the qualification-readiness derivation (sell_ready is derived false).

Proves sell_ready is *derived* as the conjunction of the gates (not asserted): with every gate met
it would be true, but the committed inputs leave five gates unmet so it is false and the posture is
not_sell_ready. The record round-trips and fails closed on any sell_ready=true or mismatched
derivation.
"""

from __future__ import annotations

from typing import Any

import pytest

from eth_research.v2.constitution import RESERVED_STATUSES, STANDING_POSTURE
from eth_research.v2c.readiness import (
    READINESS_SCHEMA_VERSION,
    SELL_READY_GATES,
    QualificationReadiness,
    ReadinessError,
    ReadinessInputs,
    blocking_gates,
    derive_sell_ready,
)


def test_sell_ready_is_derived_false() -> None:
    readiness = QualificationReadiness.current()
    assert readiness.sell_ready is False
    assert readiness.posture == STANDING_POSTURE == "not_sell_ready"
    canonical: dict[str, Any] = readiness.to_canonical()
    assert canonical["sell_ready"] is False
    assert canonical["posture"] == "not_sell_ready"


def test_sell_ready_is_a_real_conjunction_not_a_constant() -> None:
    # With every gate met the derivation would be true -- proving it is computed, not hardcoded.
    all_met = ReadinessInputs(**dict.fromkeys(SELL_READY_GATES, True))
    assert derive_sell_ready(all_met) is True
    # The committed inputs leave the forward/live/license/authorization/review gates unmet.
    assert derive_sell_ready(ReadinessInputs.current()) is False


def test_blocking_gates_are_the_unmet_ones() -> None:
    readiness = QualificationReadiness.current()
    assert readiness.blocking_gates == blocking_gates(ReadinessInputs.current())
    assert set(readiness.blocking_gates) == {
        "forward_evidence_exists",
        "live_record_exists",
        "license_granted",
        "human_authorization",
        "security_legal_review_passed",
    }
    # Operational qualification passes offline, so it is not a blocking gate.
    assert "operational_qualification_passed" not in readiness.blocking_gates


def test_posture_is_emittable_and_never_the_reserved_sell_ready() -> None:
    assert QualificationReadiness.current().posture not in RESERVED_STATUSES
    assert "sell_ready" in RESERVED_STATUSES


def test_roundtrips_and_rejects_a_sell_ready_claim() -> None:
    readiness = QualificationReadiness.current()
    parsed = QualificationReadiness.parse(readiness.to_canonical())
    assert parsed.fingerprint() == readiness.fingerprint()
    tampered: dict[str, Any] = readiness.to_canonical()
    tampered["sell_ready"] = True
    with pytest.raises(ReadinessError):
        QualificationReadiness.parse(tampered)


def test_rejects_a_derivation_mismatch() -> None:
    # Flip a gate so the recorded sell_ready no longer matches the derivation from the gates.
    tampered: dict[str, Any] = QualificationReadiness.current().to_canonical()
    tampered["gates"]["forward_evidence_exists"] = True
    with pytest.raises(ReadinessError):
        QualificationReadiness.parse(tampered)


def test_rejects_a_non_standing_posture() -> None:
    tampered: dict[str, Any] = QualificationReadiness.current().to_canonical()
    tampered["posture"] = "research_only_observation"
    with pytest.raises(ReadinessError):
        QualificationReadiness.parse(tampered)


def test_rejects_a_schema_version_drift() -> None:
    tampered: dict[str, Any] = QualificationReadiness.current().to_canonical()
    tampered["schema_version"] = READINESS_SCHEMA_VERSION + 1
    with pytest.raises(ReadinessError, match="schema_version"):
        QualificationReadiness.parse(tampered)


def test_rejects_a_tampered_honest_limitation() -> None:
    tampered: dict[str, Any] = QualificationReadiness.current().to_canonical()
    tampered["honest_limitation"] = "a shorter, drifted limitation statement."
    with pytest.raises(ReadinessError, match="honest_limitation"):
        QualificationReadiness.parse(tampered)
