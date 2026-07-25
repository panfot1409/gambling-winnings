"""Proposal assembly + the 35-check whole-proposal verifier (commit 11).

The append-only arithmetic is pinned against the committed *governance acceptance
evidence* -- the authority that is independent of the assembler under test -- rather
than re-derived from the same ``verify_accepted_base`` call the assembler itself makes
(Auditor C finding B-2: such a pin is circular and can only catch a wiring error).
"""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import eth_research
from conftest import M3E_DEFAULT_NEW_DAYS
from eth_research.m3e.accepted_base import (
    ACCEPTED_BASE_DOMAIN,
    AcceptedProspectiveBase,
    verify_accepted_base,
)
from eth_research.m3e.proposal import (
    COMPARISON_NAME,
    PROPOSAL_MANIFEST_DOMAIN,
    PROPOSAL_MANIFEST_NAME,
    AssembledProposal,
)
from eth_research.m3e.transition import build_update_transition
from eth_research.m3e.validation import M3EValidationError, canonical_json_bytes, domain_sha256
from eth_research.m3e.verify_m3e_program import verify_proposals_root, verify_update_proposal

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

_ACCEPTANCE_REGISTRY = "research/m3e/acceptance_registry.jsonl"
_ACCEPTANCES_DIR = "research/m3e/acceptances"

# The genesis facts the committed acceptance evidence pins. These are literals on
# purpose -- they are the same constants ``tests/test_m3e_accepted_base.py`` asserts
# (``previous["row_count"] == 3``, ``previous["last_open"] == "2026-07-14T00:00:00Z"``),
# so the cohort chain below bottoms out in a constant rather than in anything the code
# under test re-derives.
_GENESIS_ROW_COUNT = 3
_GENESIS_LAST_OPEN = "2026-07-14T00:00:00Z"


def _rehash_manifest(doc: dict[str, Any]) -> bytes:
    body = {k: v for k, v in doc.items() if k != "manifest_sha256"}
    doc = dict(doc)
    doc["manifest_sha256"] = domain_sha256(PROPOSAL_MANIFEST_DOMAIN, body)
    return canonical_json_bytes(doc)


def _acceptance_records() -> list[dict[str, Any]]:
    """Every committed acceptance record, in the order the registry chains them."""
    lines = (REPO_ROOT / _ACCEPTANCE_REGISTRY).read_text().splitlines()
    entries = [json.loads(line) for line in lines]
    ids = [str(e["proposal_id"]) for e in entries if e.get("entry_kind") == "acceptance"]
    assert ids, "the acceptance registry must record at least one accepted proposal"
    records = []
    for proposal_id in ids:
        record = json.loads(
            (REPO_ROOT / _ACCEPTANCES_DIR / proposal_id / "acceptance.json").read_text()
        )
        assert isinstance(record, dict)
        records.append(record)
    return records


def _cohort_governance_accepted() -> dict[str, Any]:
    """The ``new_accepted`` block of the newest acceptance -- the INDEPENDENT authority.

    ``verify_accepted_base`` re-derives the cohort from committed M3D bytes at read
    time; these records were written when governance accepted each proposal. Walking
    the append intervals from the genesis literals and requiring the walk to land on
    the recorded result means the returned facts are anchored on a constant, not on a
    second call to the function whose output we are checking.
    """
    records = _acceptance_records()
    genesis = records[0]["previous_accepted"]
    assert genesis["row_count"] == _GENESIS_ROW_COUNT
    assert genesis["last_open"] == _GENESIS_LAST_OPEN
    rows = _GENESIS_ROW_COUNT
    for record in records:
        assert record["append_only_proof"]["is_append_only"] is True
        rows += int(record["append_interval"]["row_count"])
    latest = records[-1]["new_accepted"]
    assert isinstance(latest, dict)
    assert latest["row_count"] == rows, "the recorded append chain does not reach new_accepted"
    return latest


# --------------------------------------------------------------------------- #
# Adversarial case table (Auditor C finding B-2 meta-check)                    #
# --------------------------------------------------------------------------- #
# Every negative/tamper case in this module carries a stable id. The meta-test
# below proves the ids are unique and name real, unskipped, collected tests, and
# the module-scoped guard proves every selected case actually ran and recorded
# itself -- so an id can never sit in the table describing a case that silently
# never executes.


@dataclass(frozen=True)
class AdversarialCase:
    case_id: str
    test_name: str
    refusal: str


ADVERSARIAL_CASES: tuple[AdversarialCase, ...] = (
    AdversarialCase(
        "M3E-PROP-01", "test_a_tampered_comparison_file_is_caught", "comparison rebuild mismatch"
    ),
    AdversarialCase(
        "M3E-PROP-02", "test_a_set_governance_flag_is_rejected", "governance flag is set"
    ),
    AdversarialCase("M3E-PROP-03", "test_a_flipped_review_policy_is_rejected", "auto-merge"),
    AdversarialCase(
        "M3E-PROP-04",
        "test_a_forbidden_evaluation_artifact_in_the_proposal_is_caught",
        "unexpected entries / forbidden evaluation artifact",
    ),
    AdversarialCase(
        "M3E-PROP-05",
        "test_a_forged_manifest_self_hash_is_rejected",
        "manifest_sha256 does not match",
    ),
    AdversarialCase(
        "M3E-PROP-06", "test_proposals_root_rejects_a_manifest_less_sibling", "manifest-less"
    ),
    AdversarialCase(
        "M3E-PROP-07", "test_proposals_root_rejects_a_stray_top_level_file", "non-directory entry"
    ),
    AdversarialCase(
        "M3E-PROP-08",
        "test_a_base_that_is_not_the_accepted_cohort_is_refused",
        "accepted cohort fingerprint drifted from the base",
    ),
)

_OBSERVED: set[str] = set()


def record_case(case_id: str) -> None:
    """Mark an adversarial case as actually executed."""
    assert any(case.case_id == case_id for case in ADVERSARIAL_CASES), (
        f"{case_id} is not in ADVERSARIAL_CASES"
    )
    _OBSERVED.add(case_id)


def _selected_case_ids(session: pytest.Session) -> set[str]:
    """The catalogued ids whose tests pytest actually selected for this run."""
    this_file = Path(__file__).name
    selected = {
        item.nodeid.split("::")[-1]
        for item in session.items
        if item.nodeid.split("::")[0].endswith(this_file)
    }
    return {case.case_id for case in ADVERSARIAL_CASES if case.test_name in selected}


@pytest.fixture(scope="module", autouse=True)
def _adversarial_cases_all_observed(request: pytest.FixtureRequest) -> Iterator[None]:
    """Module teardown: every selected adversarial case must have recorded itself.

    Scoped to the module and order-independent, so a case that is silently skipped,
    renamed out of existence, or never reached surfaces as a loud teardown error
    rather than as a quietly shrinking suite.
    """
    yield
    expected = _selected_case_ids(request.session)
    missing = expected - _OBSERVED
    assert not missing, f"adversarial cases selected but never observed: {sorted(missing)}"
    catalogued = {case.case_id for case in ADVERSARIAL_CASES}
    stray = _OBSERVED - catalogued
    assert not stray, f"observed ids that are not in the case table: {sorted(stray)}"


def test_a_clean_proposal_passes_all_35_checks(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    checks = verify_update_proposal(REPO_ROOT, tmp_path / "prop")
    names = [name for name, _ in checks]
    assert len(names) == 35
    assert len(set(names)) == 35
    assert names[0] == "01_accepted_base_rebuilds"
    assert names[-1] == "35_no_smuggled_field_or_artifact"


def test_verifier_has_no_skip_parameter() -> None:
    params = list(inspect.signature(verify_update_proposal).parameters)
    assert params == ["repo_root", "proposal_dir"]


def test_assembled_branch_is_a_bot_proposal_branch(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    assembled = m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    assert assembled.proposal_branch.startswith("bot/m3e-prospective-update/")
    # Append-only: the proposal extends the accepted base by exactly the new window.
    #
    # Auditor C finding B-2: this pin used to read ``verify_accepted_base(REPO_ROOT)``,
    # which ``assemble_proposal`` calls itself -- and ``verify_cohort_manifest`` rebuilds
    # that row count from the very rows the transition counts, so the two operands were
    # one number reached by two names and no repository state could make them differ.
    # The expected cohort now comes from the committed governance acceptance evidence.
    accepted = _cohort_governance_accepted()
    accepted_rows = int(accepted["row_count"])
    assert assembled.transition.old_row_count == accepted_rows
    assert assembled.transition.old_last_open == accepted["last_open"]
    assert assembled.transition.old_fingerprint == accepted["canonical_content_fingerprint"]
    assert assembled.transition.proposed_row_count == accepted_rows + M3E_DEFAULT_NEW_DAYS


def test_a_base_that_is_not_the_accepted_cohort_is_refused(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    """M3E-PROP-08: what makes ``old_row_count`` mean "the accepted cohort".

    ``build_update_transition`` re-derives the old cohort from committed M3D bytes and
    refuses unless its fingerprint is the one the supplied base claims. Without that
    guard ``old_row_count`` is just "however many rows happen to be on disk", which is
    exactly why restating it against ``verify_accepted_base`` proved nothing.
    """
    record_case("M3E-PROP-08")
    assembled = m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    rows = [list(row) for row in assembled.transition.appended_rows]
    fingerprint = assembled.transition.new_window_fingerprint
    base = verify_accepted_base(REPO_ROOT)

    # Control: the unmutated base rebuilds the transition, and it extends exactly the
    # cohort the acceptance evidence records.
    control = build_update_transition(
        REPO_ROOT, base, new_window_rows=rows, new_window_fingerprint=fingerprint
    )
    assert control.old_row_count == int(_cohort_governance_accepted()["row_count"])
    assert control.to_dict() == assembled.transition.to_dict()

    # Exactly one semantic mutation: the content fingerprint the base claims.
    forged_doc = dict(base.document)
    forged_doc["canonical_content_fingerprint"] = "0" * 64
    # Re-seal the self-hash, as a forger would. Prove the re-seal did NOT repair the
    # mutation -- the mutated field is still mutated after resealing.
    forged_doc["base_sha256"] = domain_sha256(
        ACCEPTED_BASE_DOMAIN, {k: v for k, v in forged_doc.items() if k != "base_sha256"}
    )
    forged = AcceptedProspectiveBase(document=forged_doc)
    assert forged.canonical_content_fingerprint == "0" * 64
    assert forged.canonical_content_fingerprint != base.canonical_content_fingerprint
    assert forged.base_sha256 != base.base_sha256

    with pytest.raises(M3EValidationError, match="fingerprint drifted from the base"):
        build_update_transition(
            REPO_ROOT, forged, new_window_rows=rows, new_window_fingerprint=fingerprint
        )


def test_a_tampered_comparison_file_is_caught(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    record_case("M3E-PROP-01")
    m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    comp = tmp_path / "prop" / COMPARISON_NAME
    doc = json.loads(comp.read_text())
    doc["row_count"] = 999
    comp.write_bytes(canonical_json_bytes(doc))
    with pytest.raises(M3EValidationError):
        verify_update_proposal(REPO_ROOT, tmp_path / "prop")


def test_a_set_governance_flag_is_rejected(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    record_case("M3E-PROP-02")
    assembled = m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    doc = dict(assembled.manifest_document)
    doc["governance_flags"] = {**doc["governance_flags"], "strategy_evaluated": True}
    (tmp_path / "prop" / PROPOSAL_MANIFEST_NAME).write_bytes(_rehash_manifest(doc))
    with pytest.raises(M3EValidationError, match="governance flag is set"):
        verify_update_proposal(REPO_ROOT, tmp_path / "prop")


def test_a_flipped_review_policy_is_rejected(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    record_case("M3E-PROP-03")
    assembled = m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    doc = dict(assembled.manifest_document)
    doc["review_policy"] = {**doc["review_policy"], "auto_merge_forbidden": False}
    (tmp_path / "prop" / PROPOSAL_MANIFEST_NAME).write_bytes(_rehash_manifest(doc))
    with pytest.raises(M3EValidationError, match="auto-merge"):
        verify_update_proposal(REPO_ROOT, tmp_path / "prop")


def test_a_forbidden_evaluation_artifact_in_the_proposal_is_caught(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    record_case("M3E-PROP-04")
    m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    (tmp_path / "prop" / "candidate_results.json").write_text("{}")
    # The closed expected-file-set check refuses any unexpected top-level entry
    # (stronger than the name-marker scan, which still guards the runner subtrees).
    with pytest.raises(
        M3EValidationError, match=r"unexpected entries|forbidden evaluation artifact"
    ):
        verify_update_proposal(REPO_ROOT, tmp_path / "prop")


def test_a_forged_manifest_self_hash_is_rejected(
    m3e_stage_proposal: Callable[..., AssembledProposal], tmp_path: Path
) -> None:
    record_case("M3E-PROP-05")
    assembled = m3e_stage_proposal(tmp_path / "prop", repo_root=REPO_ROOT)
    doc = dict(assembled.manifest_document)
    doc["idempotency_key"] = "0" * 64  # a lie, without recomputing the self-hash
    (tmp_path / "prop" / PROPOSAL_MANIFEST_NAME).write_bytes(canonical_json_bytes(doc))
    with pytest.raises(M3EValidationError, match="manifest_sha256 does not match"):
        verify_update_proposal(REPO_ROOT, tmp_path / "prop")


# --------------------------------------------------------------------------- #
# audit §17 (Auditor B finding 3): the proposals root is a closed set         #
# --------------------------------------------------------------------------- #
def test_proposals_root_is_empty_returns_no_proposals(tmp_path: Path) -> None:
    # A repo with no proposals root at all yields the empty list, not an error.
    assert verify_proposals_root(tmp_path) == []


def test_proposals_root_accepts_a_manifest_bearing_directory(tmp_path: Path) -> None:
    root = tmp_path / "research/m3e/proposals"
    (root / "good").mkdir(parents=True)
    (root / "good" / PROPOSAL_MANIFEST_NAME).write_text("{}")
    assert verify_proposals_root(tmp_path) == [root / "good"]


def test_proposals_root_rejects_a_manifest_less_sibling(tmp_path: Path) -> None:
    record_case("M3E-PROP-06")
    # A sibling directory without a manifest would be skipped by a per-proposal check
    # that only visits manifest-bearing dirs — a place to smuggle unverified files.
    root = tmp_path / "research/m3e/proposals"
    (root / "good").mkdir(parents=True)
    (root / "good" / PROPOSAL_MANIFEST_NAME).write_text("{}")
    (root / "smuggled").mkdir()
    (root / "smuggled" / "aux.json").write_text('{"sharpe": 2.1}')
    with pytest.raises(M3EValidationError, match="manifest-less"):
        verify_proposals_root(tmp_path)


def test_proposals_root_rejects_a_stray_top_level_file(tmp_path: Path) -> None:
    record_case("M3E-PROP-07")
    root = tmp_path / "research/m3e/proposals"
    root.mkdir(parents=True)
    (root / "stowaway.json").write_text('{"pnl": 1.0}')
    with pytest.raises(M3EValidationError, match="non-directory entry"):
        verify_proposals_root(tmp_path)


# --------------------------------------------------------------------------- #
# Meta-check on the case table itself (Auditor C finding B-2)                  #
# --------------------------------------------------------------------------- #
def test_every_adversarial_case_id_is_unique_executed_and_observed(
    request: pytest.FixtureRequest,
) -> None:
    """The case table cannot describe a case that does not run.

    Uniqueness and "names a real test" are checked here; "actually executed and
    observed" is enforced order-independently by the module-scoped
    ``_adversarial_cases_all_observed`` guard, which fails at module teardown if a
    selected case never recorded itself.
    """
    ids = [case.case_id for case in ADVERSARIAL_CASES]
    assert len(ids) == len(set(ids)), f"duplicate adversarial case ids: {ids}"

    names = [case.test_name for case in ADVERSARIAL_CASES]
    assert len(names) == len(set(names)), f"duplicate adversarial test names: {names}"

    module = sys.modules[__name__]
    for case in ADVERSARIAL_CASES:
        func = getattr(module, case.test_name, None)
        assert callable(func), f"{case.case_id} names no test function in this module"
        assert case.test_name.startswith("test_"), f"{case.case_id} does not name a test"
        marks = {mark.name for mark in getattr(func, "pytestmark", ())}
        assert not marks & {"skip", "skipif", "xfail"}, (
            f"{case.case_id} ({case.test_name}) is skip/xfail-marked; an adversarial case "
            "must never be silently disabled"
        )
        assert case.refusal, f"{case.case_id} records no expected refusal"

    # Every catalogued case must have been COLLECTED for this run when the whole
    # module is selected -- a case deleted or renamed away would drop out here.
    this_file = Path(__file__).name
    collected = {
        item.nodeid.split("::")[-1]
        for item in request.session.items
        if item.nodeid.split("::")[0].endswith(this_file)
    }
    if collected >= {case.test_name for case in ADVERSARIAL_CASES}:
        assert _selected_case_ids(request.session) == set(ids)
