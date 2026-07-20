"""V2C sections 15-19: prospective-cohort governance, proposal format/generator, maturity, template.

These lock in the "prepare-but-never-activate" invariants of the V2C prospective layer:

* A cohort descriptor is candidate-free, its lifecycle state must match its row count, and no state
  it can reach authorizes evaluation (:data:`evaluation_authorization` is permanently ``False``).
* The offline generator computes the due completed-observation window deterministically from an
  explicit as-of instant (the forming observation is always excluded), is idempotent, no-ops when
  nothing is due, and hard-stops on a clock rewind -- fetching nothing.
* A proposal is source-independent (no endpoint/URL/secret) and data-only (every governance flag
  ``False``).
* Maturity is data-availability only and never authorizes evaluation, even when mature.
* The activation workflow is an inert template outside ``.github/workflows`` that cannot be loaded.
* Importing the whole V2C governance surface loads no candidate/strategy/evaluator/engine module.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eth_research.v2c.activation_template import (
    INACTIVE_TEMPLATE_RELPATH,
    verify_inactive_activation_template,
)
from eth_research.v2c.firewall import KNOWN_LEGACY_CANDIDATE_IDS, V2CFirewallError
from eth_research.v2c.maturity import (
    MATURITY_POLICY,
    MaturityAssessment,
    V2CMaturityError,
    assess_prospective_maturity,
    verify_maturity_policy,
)
from eth_research.v2c.proposal import GOVERNANCE_FLAGS, ProspectiveUpdateProposal, V2CProposalError
from eth_research.v2c.proposal_generator import (
    OUTCOME_NO_UPDATE_DUE,
    OUTCOME_PROPOSAL,
    generate_offline_proposal,
)
from eth_research.v2c.prospective import (
    ProspectiveCohortDescriptor,
    V2CProspectiveError,
    advance_cohort_state,
    advance_proposal_state,
    derive_cohort_state,
    require_evaluation_not_authorized,
)

REPO = Path(__file__).resolve().parents[1]


def _descriptor(**overrides: object) -> ProspectiveCohortDescriptor:
    base: dict[str, object] = {
        "cohort_id": "eth_usd_daily_prospective_v1",
        "product": "ETH-USD",
        "venue": "coinbase-exchange",
        "interval_seconds": 86400,
        "cohort_start": "2026-07-12T00:00:00Z",
        "accumulated_last_open": "2026-07-20T00:00:00Z",
        "row_count": 9,
        "minimum_maturity_rows": 365,
        "cohort_state": "accumulating",
        "proposal_state": "no_proposal",
        "evaluation_authorization": False,
    }
    base.update(overrides)
    return ProspectiveCohortDescriptor(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Section 15: cohort descriptor + state machine                               #
# --------------------------------------------------------------------------- #
def test_descriptor_roundtrips_and_digest_binds() -> None:
    d = _descriptor()
    restored = ProspectiveCohortDescriptor.from_mapping("c", d.to_canonical())
    assert restored == d
    assert len(d.descriptor_digest()) == 64


def test_descriptor_refuses_evaluation_authorization_true() -> None:
    with pytest.raises(V2CProspectiveError, match="evaluation_authorization must be False"):
        _descriptor(evaluation_authorization=True)


@pytest.mark.parametrize("candidate_id", sorted(KNOWN_LEGACY_CANDIDATE_IDS))
def test_descriptor_refuses_a_candidate_id_as_product(candidate_id: str) -> None:
    with pytest.raises(V2CFirewallError, match="legacy candidate id"):
        _descriptor(product=candidate_id)


def test_descriptor_state_must_match_row_count() -> None:
    # 9 rows implies "accumulating", not "data_mature".
    with pytest.raises(V2CProspectiveError, match="disagrees with the row count"):
        _descriptor(cohort_state="data_mature")


def test_descriptor_last_open_present_iff_rows() -> None:
    with pytest.raises(V2CProspectiveError, match="accumulated_last_open"):
        _descriptor(
            row_count=0, cohort_state="declared", accumulated_last_open="2026-07-20T00:00:00Z"
        )
    with pytest.raises(V2CProspectiveError, match="accumulated_last_open"):
        _descriptor(row_count=9, accumulated_last_open=None)


def test_derive_cohort_state() -> None:
    assert derive_cohort_state(0, 365) == "declared"
    assert derive_cohort_state(9, 365) == "accumulating"
    assert derive_cohort_state(365, 365) == "data_mature"
    assert derive_cohort_state(400, 365) == "data_mature"


def test_cohort_transitions_are_fail_closed() -> None:
    assert advance_cohort_state("accumulating", "data_mature") == "data_mature"
    assert advance_cohort_state("declared", "accumulating") == "accumulating"
    for bad_from, bad_to in [("data_mature", "accumulating"), ("declared", "data_mature")]:
        with pytest.raises(V2CProspectiveError, match="not allowed"):
            advance_cohort_state(bad_from, bad_to)


def test_proposal_transitions_are_fail_closed() -> None:
    assert advance_proposal_state("no_proposal", "prepared") == "prepared"
    assert advance_proposal_state("under_review", "accepted") == "accepted"
    for bad_from, bad_to in [("no_proposal", "accepted"), ("accepted", "prepared")]:
        with pytest.raises(V2CProspectiveError, match="not allowed"):
            advance_proposal_state(bad_from, bad_to)


def test_from_mapping_rejects_extra_or_missing_keys_and_tamper() -> None:
    good = _descriptor().to_canonical()
    with pytest.raises(V2CProspectiveError, match="keys mismatch"):
        ProspectiveCohortDescriptor.from_mapping("c", {**good, "extra": 1})
    tampered = dict(good)
    tampered["row_count"] = 10  # changes the body but not the recorded digest
    with pytest.raises(V2CProspectiveError, match="descriptor_digest does not bind"):
        ProspectiveCohortDescriptor.from_mapping("c", tampered)


def test_require_evaluation_not_authorized_passes_on_a_valid_descriptor() -> None:
    require_evaluation_not_authorized(_descriptor())  # does not raise


# --------------------------------------------------------------------------- #
# Sections 16-17: proposal format + offline generator                         #
# --------------------------------------------------------------------------- #
def test_generator_computes_the_completed_window_excluding_the_forming_observation() -> None:
    d = _descriptor()  # accumulated through 2026-07-20
    result = generate_offline_proposal(d, "2026-07-25T12:00:00Z")
    assert result.status == OUTCOME_PROPOSAL
    assert result.proposal is not None
    # completed days 07-21..07-24 (07-25 is forming and excluded).
    assert result.proposal.first_missing_open == "2026-07-21T00:00:00+00:00"
    assert result.proposal.completed_exclusive_end == "2026-07-25T00:00:00+00:00"
    assert result.proposal.expected_row_count == 4


def test_generator_is_idempotent_within_the_same_completed_boundary() -> None:
    d = _descriptor()
    a = generate_offline_proposal(d, "2026-07-25T01:00:00Z").proposal
    b = generate_offline_proposal(d, "2026-07-25T23:59:59Z").proposal
    assert a is not None
    assert b is not None
    assert a.idempotency_key() == b.idempotency_key()
    assert a.proposal_digest() == b.proposal_digest()


def test_generator_no_ops_when_nothing_is_due() -> None:
    d = _descriptor()
    # as_of on the day right after the last accumulated open: nothing completed is missing yet.
    result = generate_offline_proposal(d, "2026-07-21T00:00:00Z")
    assert result.status == OUTCOME_NO_UPDATE_DUE
    assert result.proposal is None


def test_generator_hard_stops_on_a_clock_rewind_before_the_cohort() -> None:
    d = _descriptor()
    with pytest.raises(V2CProposalError, match="clock rewind"):
        generate_offline_proposal(d, "2026-07-01T00:00:00Z")


def test_generator_rejects_a_misaligned_accumulated_open() -> None:
    d = _descriptor(accumulated_last_open="2026-07-20T06:00:00Z")
    with pytest.raises(V2CProposalError, match="not aligned"):
        generate_offline_proposal(d, "2026-07-25T00:00:00Z")


def test_generator_from_a_declared_cohort_starts_at_cohort_start() -> None:
    d = _descriptor(row_count=0, cohort_state="declared", accumulated_last_open=None)
    result = generate_offline_proposal(d, "2026-07-15T00:00:00Z")
    assert result.status == OUTCOME_PROPOSAL
    assert result.proposal is not None
    # completed days 07-12, 07-13, 07-14 (07-15 forming).
    assert result.proposal.first_missing_open == "2026-07-12T00:00:00+00:00"
    assert result.proposal.expected_row_count == 3


def test_proposal_governance_flags_are_all_false() -> None:
    d = _descriptor()
    proposal = generate_offline_proposal(d, "2026-07-25T00:00:00Z").proposal
    assert proposal is not None
    flags = proposal.to_canonical()["governance_flags"]
    assert flags == GOVERNANCE_FLAGS
    assert all(v is False for v in GOVERNANCE_FLAGS.values())


def test_proposal_is_source_independent_no_endpoint_or_secret() -> None:
    d = _descriptor()
    proposal = generate_offline_proposal(d, "2026-07-25T00:00:00Z").proposal
    assert proposal is not None
    blob = json.dumps(proposal.to_canonical()).lower()
    # Genuine source/credential markers. (The word "authorization" legitimately appears inside the
    # ``evaluation_authorization`` governance-flag name, which proves the *absence* of authority.)
    for forbidden in ("http", "://", "secret", "password", "api_key", "bearer", "credential"):
        assert forbidden not in blob, forbidden


def test_proposal_roundtrips_and_digests_bind() -> None:
    d = _descriptor()
    proposal = generate_offline_proposal(d, "2026-07-25T00:00:00Z").proposal
    assert proposal is not None
    restored = ProspectiveUpdateProposal.from_mapping("p", proposal.to_canonical())
    assert restored == proposal


def test_proposal_from_mapping_rejects_a_flipped_governance_flag() -> None:
    d = _descriptor()
    proposal = generate_offline_proposal(d, "2026-07-25T00:00:00Z").proposal
    assert proposal is not None
    tampered = proposal.to_canonical()
    tampered["governance_flags"] = {**GOVERNANCE_FLAGS, "evaluation_authorization": True}
    with pytest.raises(V2CProposalError, match="data-only"):
        ProspectiveUpdateProposal.from_mapping("p", tampered)


def test_proposal_from_mapping_rejects_a_tampered_window() -> None:
    d = _descriptor()
    proposal = generate_offline_proposal(d, "2026-07-25T00:00:00Z").proposal
    assert proposal is not None
    tampered = proposal.to_canonical()
    tampered["expected_row_count"] = 999  # changes the window but not the recorded keys/digest
    with pytest.raises(V2CProposalError, match="idempotency_key does not bind"):
        ProspectiveUpdateProposal.from_mapping("p", tampered)


# --------------------------------------------------------------------------- #
# Section 19: maturity policy                                                 #
# --------------------------------------------------------------------------- #
def test_immature_cohort_assessment() -> None:
    m = assess_prospective_maturity(_descriptor())
    assert m.is_data_mature is False
    assert m.remaining_rows == 356
    assert m.evaluation_authorized is False


def test_mature_cohort_is_data_available_but_still_unauthorized() -> None:
    d = _descriptor(row_count=400, cohort_state="data_mature")
    m = assess_prospective_maturity(d)
    assert m.is_data_mature is True
    assert m.remaining_rows == 0
    # Maturity does not authorize evaluation -- that is a separate future human decision.
    assert m.evaluation_authorized is False


def test_maturity_assessment_cannot_authorize_evaluation() -> None:
    with pytest.raises(V2CMaturityError, match="never authorize evaluation"):
        MaturityAssessment(
            cohort_id="c",
            row_count=400,
            minimum_maturity_rows=365,
            remaining_rows=0,
            is_data_mature=True,
            evaluation_authorized=True,
        )


def test_maturity_policy_pins_the_commitments() -> None:
    assert verify_maturity_policy() == []
    assert MATURITY_POLICY["maturity_authorizes_evaluation"] is False
    assert MATURITY_POLICY["maturity_depends_on_strategy_outcome"] is False
    assert MATURITY_POLICY["evaluation_requires_separate_future_human_authorization"] is True


# --------------------------------------------------------------------------- #
# Section 18: inactive activation-workflow template                           #
# --------------------------------------------------------------------------- #
def test_inactive_template_verifies_on_the_real_repo() -> None:
    assert verify_inactive_activation_template(REPO) == []


def test_inactive_template_is_outside_workflows_with_a_nonloadable_suffix() -> None:
    assert not INACTIVE_TEMPLATE_RELPATH.startswith(".github/workflows")
    assert INACTIVE_TEMPLATE_RELPATH.endswith(".yml.inactive")
    assert not (REPO / ".github" / "workflows" / Path(INACTIVE_TEMPLATE_RELPATH).name).exists()


def _write_template(root: Path, text: str) -> None:
    path = root / INACTIVE_TEMPLATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_verifier_flags_a_missing_template(tmp_path: Path) -> None:
    problems = verify_inactive_activation_template(tmp_path)
    assert any("missing" in p for p in problems)


def test_verifier_flags_a_write_capable_or_active_template(tmp_path: Path) -> None:
    _write_template(
        tmp_path,
        "# INACTIVE TEMPLATE - NOT INSTALLED\n"
        "permissions:\n  contents: write\n"
        "jobs:\n  x:\n    steps:\n      - uses: actions/checkout@main\n"
        "        run: git push origin main\n",
    )
    problems = verify_inactive_activation_template(tmp_path)
    assert any("contents: write" in p for p in problems)
    assert any("uses:" in p for p in problems)
    assert any("git push" in p for p in problems)


def test_verifier_flags_a_template_not_declared_inactive(tmp_path: Path) -> None:
    _write_template(tmp_path, "permissions:\n  contents: read\nname: something\n")
    problems = verify_inactive_activation_template(tmp_path)
    assert any("INACTIVE TEMPLATE" in p for p in problems)


# --------------------------------------------------------------------------- #
# The whole governance surface imports no candidate/engine module             #
# --------------------------------------------------------------------------- #
def test_v2c_governance_imports_no_candidate_or_engine_module() -> None:
    banned = [
        "eth_research.v2.candidates",
        "eth_research.v2.evaluator",
        "eth_research.v2b.candidates",
        "eth_research.v2b.evaluation",
        "eth_research.portfolio.engine",
        "eth_research.fractional.engine",
    ]
    code = (
        "import sys, json\n"
        "import eth_research.v2c.prospective\n"
        "import eth_research.v2c.proposal\n"
        "import eth_research.v2c.proposal_generator\n"
        "import eth_research.v2c.maturity\n"
        "import eth_research.v2c.activation_template\n"
        f"banned = {banned!r}\n"
        "print(json.dumps(sorted(m for m in banned if m in sys.modules)))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert json.loads(proc.stdout) == []
