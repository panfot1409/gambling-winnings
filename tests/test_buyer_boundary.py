"""Tests for the buyer-evaluation boundary (§19-26).

Coverage: the redaction scanner detects secrets, embedded source, and raw/sealed tabular data while
passing honest governance prose; the contract / claims / scorecard / factsheet round-trip strictly
and re-assert their fixed definitions; the diligence bundle assembles source-free and the assembled
artifacts carry zero redaction violations; and the reference gateway serves only redacted artifacts,
refuses every withheld item, and fails closed when the redaction policy is not satisfied.
"""

from __future__ import annotations

import pytest

from eth_research.buyer import redaction
from eth_research.buyer.claims import ClaimsCatalog, ClaimsError
from eth_research.buyer.contract import ContractError, EvaluationContract, parse_contract
from eth_research.buyer.diligence import assemble_diligence_bundle
from eth_research.buyer.factsheet import Factsheet
from eth_research.buyer.gateway import GatewayError, ReferenceEvaluationGateway
from eth_research.buyer.redaction import RedactionPolicy, scan_text
from eth_research.buyer.scorecard import ReadinessScorecard
from eth_research.v2.constitution import STANDING_POSTURE

# --- redaction scanner --------------------------------------------------------


def test_scan_passes_honest_governance_prose() -> None:
    # Naming the sealed partitions in prose is allowed; only their *data* is forbidden.
    text = (
        "The development_gate and final_holdout partitions are never read; the program is "
        "not_sell_ready and makes no forward claim."
    )
    assert scan_text("factsheet", text) == []


@pytest.mark.parametrize(
    "text",
    [
        "-----BEGIN RSA PRIVATE KEY-----",
        "AKIAABCDEFGHIJKLMNOP",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
        "api_key = 'abcdef0123456789'",
    ],
)
def test_scan_detects_secrets(text: str) -> None:
    violations = scan_text("artifact", text)
    assert any(v.category == "secret" for v in violations)


def test_scan_detects_embedded_source() -> None:
    src = "import os\nfrom sys import argv\ndef run():\n    return 1\n"
    violations = scan_text("artifact", src)
    assert any(v.category == "embedded_source" for v in violations)


@pytest.mark.parametrize(
    "text",
    [
        "timestamp,open,high,low,close,volume",
        "1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0",
        "[1.1, 2.2, 3.3, 4.4, 5.5, 6.6, 7.7, 8.8, 9.9, 10.1, 11.1]",
    ],
)
def test_scan_detects_raw_data(text: str) -> None:
    violations = scan_text("artifact", text)
    assert any(v.category == "raw_data" for v in violations)


def test_policy_rejects_forbidden_kind() -> None:
    policy = RedactionPolicy.current()
    violations = policy.scan_artifact("x", "source", "hello")
    assert any(v.category == "forbidden_kind" for v in violations)


# --- contract -----------------------------------------------------------------


def test_contract_roundtrips_and_rejects_drift() -> None:
    contract = EvaluationContract.current()
    assert parse_contract(contract.to_canonical()).fingerprint() == contract.fingerprint()
    assert contract.posture == STANDING_POSTURE
    bad = contract.to_canonical()
    bad["terms_summary"] = "this is an offer to sell with guaranteed live returns"
    with pytest.raises(ContractError):
        parse_contract(bad)


# --- claims -------------------------------------------------------------------


def test_claims_catalog_all_emittable_and_roundtrips() -> None:
    catalog = ClaimsCatalog.current()
    assert catalog.claims
    parsed = ClaimsCatalog.parse(catalog.to_canonical())
    assert parsed.fingerprint() == catalog.fingerprint()


def test_claims_reject_reserved_status() -> None:
    catalog = ClaimsCatalog.current().to_canonical()
    claims = catalog["claims"]
    assert isinstance(claims, list)
    claims[0]["status"] = "live_deployed"  # a reserved / non-emittable status
    with pytest.raises((ClaimsError, ValueError, TypeError)):
        ClaimsCatalog.parse(catalog)


# --- scorecard ----------------------------------------------------------------


def test_scorecard_is_not_sell_ready_and_roundtrips() -> None:
    scorecard = ReadinessScorecard.current()
    assert scorecard.overall_posture == STANDING_POSTURE
    levels = {d.dimension_id: d.level for d in scorecard.dimensions}
    assert levels["commercial_readiness"] == "absent"
    assert (
        ReadinessScorecard.parse(scorecard.to_canonical()).fingerprint() == scorecard.fingerprint()
    )


# --- factsheet ----------------------------------------------------------------


def test_factsheet_binds_sources_and_renders_cleanly() -> None:
    contract = EvaluationContract.current()
    claims = ClaimsCatalog.current()
    scorecard = ReadinessScorecard.current()
    factsheet = Factsheet.build(contract, claims, scorecard)
    assert factsheet.contract_fingerprint == contract.fingerprint()
    assert factsheet.claims_fingerprint == claims.fingerprint()
    assert factsheet.scorecard_fingerprint == scorecard.fingerprint()
    # The rendered markdown must itself be redaction-clean.
    assert scan_text("factsheet.md", factsheet.render_markdown()) == []
    assert Factsheet.parse(factsheet.to_canonical()).fingerprint() == factsheet.fingerprint()


# --- diligence bundle ---------------------------------------------------------


def test_bundle_assembles_source_free_and_clean() -> None:
    bundle = assemble_diligence_bundle()
    assert [a.name for a in bundle.manifest()] == [
        "contract",
        "claims_catalog",
        "factsheet",
        "readiness_scorecard",
    ]
    # Every assembled artifact carries zero redaction violations.
    assert bundle.scan(RedactionPolicy.current()) == []
    # Assembly is deterministic.
    assert assemble_diligence_bundle().fingerprint() == bundle.fingerprint()


# --- gateway ------------------------------------------------------------------


def test_gateway_serves_only_redacted_and_refuses_withheld() -> None:
    gateway = ReferenceEvaluationGateway.open()
    assert gateway.available() == (
        "claims_catalog",
        "contract",
        "factsheet",
        "readiness_scorecard",
    )
    assert gateway.serve("factsheet")
    for withheld in EvaluationContract.current().withheld:
        with pytest.raises(GatewayError):
            gateway.request(withheld)
    with pytest.raises(GatewayError):
        gateway.serve("nonexistent_artifact")


def test_gateway_fails_closed_when_policy_not_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    # Build a clean bundle first, then force every artifact kind non-allowlisted; on re-scan the
    # gateway must refuse to open (fail closed).
    bundle = assemble_diligence_bundle()
    empty_policy = RedactionPolicy(allowed_kinds=frozenset())
    monkeypatch.setattr(redaction.RedactionPolicy, "current", staticmethod(lambda: empty_policy))
    with pytest.raises(GatewayError):
        ReferenceEvaluationGateway.open(bundle)
