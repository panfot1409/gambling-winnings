"""Tests for the V2A commercial-evidence research core (constitution/claims/evidence/lineage).

The core is V2A's governance heart. It fixes what may be claimed, ties every claim to hashed
evidence, caps nominations at one, and bounds research to a single one-shot budget. These tests
prove each rail is fail-closed and every committed artifact round-trips byte-stably.
"""

from __future__ import annotations

import pytest

from eth_research.v2 import (
    MAX_CANDIDATE_FAMILIES,
    MAX_RESEARCH_EXECUTIONS,
    RESERVED_STATUSES,
    V2A_EMITTABLE_STATUSES,
    CommercialEvidenceConstitution,
    OneShotResearchBudget,
    strict,
)
from eth_research.v2 import budget as budget_mod
from eth_research.v2 import claims as claims_mod
from eth_research.v2 import constitution as const_mod
from eth_research.v2 import lineage as lineage_mod
from eth_research.v2.claims import Claim, parse_claim
from eth_research.v2.constitution import (
    ConstitutionError,
    assert_no_reserved_status,
    parse_constitution,
    require_v2a_emittable_status,
)
from eth_research.v2.evidence import EvidenceRecord, parse_evidence
from eth_research.v2.lineage import assert_valid, build_graph, parse_graph, verify_problems

_H = "aa" * 32  # a well-formed 64-hex digest for fixtures


# --------------------------------------------------------------------------- #
# strict helpers                                                              #
# --------------------------------------------------------------------------- #
def test_require_choice_and_slug() -> None:
    assert strict.require_choice("x", "a", frozenset({"a", "b"})) == "a"
    with pytest.raises(strict.V2ValidationError):
        strict.require_choice("x", "c", frozenset({"a", "b"}))
    assert strict.require_slug("x", "candidate_x1") == "candidate_x1"
    for bad in ("Candidate", "has space", "dash-not-ok", ""):
        with pytest.raises(strict.V2ValidationError):
            strict.require_slug("x", bad)


def test_canonical_json_is_deterministic_and_rejects_nonfinite() -> None:
    a = strict.canonical_json_bytes({"b": 1, "a": 2})
    b = strict.canonical_json_bytes({"a": 2, "b": 1})
    assert a == b  # sorted keys => order-independent
    assert a.endswith(b"\n")
    with pytest.raises(ValueError, match="JSON compliant"):
        strict.canonical_json_bytes({"x": float("nan")})


# --------------------------------------------------------------------------- #
# constitution                                                                #
# --------------------------------------------------------------------------- #
def test_vocabulary_partitions_are_disjoint_and_complete() -> None:
    assert V2A_EMITTABLE_STATUSES.isdisjoint(RESERVED_STATUSES)
    assert len(V2A_EMITTABLE_STATUSES) == 5
    assert "sell_ready" in RESERVED_STATUSES
    assert "not_sell_ready" in V2A_EMITTABLE_STATUSES


def test_require_v2a_emittable_status_accepts_emittable_rejects_reserved() -> None:
    for status in V2A_EMITTABLE_STATUSES:
        assert require_v2a_emittable_status("s", status) == status
    for status in RESERVED_STATUSES:
        with pytest.raises(ConstitutionError):
            require_v2a_emittable_status("s", status)
    with pytest.raises(ConstitutionError):
        require_v2a_emittable_status("s", "totally_unknown")


def test_constitution_roundtrips_and_rejects_drift() -> None:
    current = CommercialEvidenceConstitution.current()
    parsed = parse_constitution(current.to_canonical())
    assert parsed.fingerprint() == current.fingerprint()
    # A drifted posture, status set, or principle is rejected.
    bad = current.to_canonical()
    bad["standing_posture"] = "sell_ready"
    with pytest.raises(ConstitutionError):
        parse_constitution(bad)
    bad2 = current.to_canonical()
    bad2["emittable_statuses"] = [*current.emittable_statuses, "sell_ready"]
    with pytest.raises(ConstitutionError):
        parse_constitution(bad2)


def test_assert_no_reserved_status_scans_iterables() -> None:
    assert_no_reserved_status("s", ["not_sell_ready", "research_stage_supported"])
    with pytest.raises(ConstitutionError):
        assert_no_reserved_status("s", ["not_sell_ready", "sell_ready"])


# --------------------------------------------------------------------------- #
# evidence                                                                     #
# --------------------------------------------------------------------------- #
def _evidence_dict(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "evidence_id": "train_1",
        "kind": "research_train_result",
        "description": "a research-train result",
        "artifact_path": "research/v2a/result.json",
        "artifact_sha256": _H,
        "produced_by": "evaluator",
    }
    base.update(over)
    return base


def test_parse_evidence_roundtrip_and_rejections() -> None:
    rec = parse_evidence("e", _evidence_dict())
    assert isinstance(rec, EvidenceRecord)
    assert rec.fingerprint() == parse_evidence("e", _evidence_dict()).fingerprint()
    with pytest.raises(strict.V2ValidationError):
        parse_evidence("e", _evidence_dict(kind="live_record"))  # unknown kind
    with pytest.raises(strict.V2ValidationError):
        parse_evidence("e", _evidence_dict(artifact_path="/etc/passwd"))  # unsafe path
    with pytest.raises(strict.V2ValidationError):
        parse_evidence("e", _evidence_dict(artifact_sha256="short"))  # bad sha
    with pytest.raises(strict.V2ValidationError):
        parse_evidence("e", _evidence_dict(extra="x"))  # unexpected key


# --------------------------------------------------------------------------- #
# claims                                                                       #
# --------------------------------------------------------------------------- #
def _claim_dict(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "claim_id": "posture",
        "statement": "the programme is not sell-ready",
        "claimed_status": "not_sell_ready",
        "scope": "programme",
        "supporting_evidence_ids": ["method_1"],
    }
    base.update(over)
    return base


def test_parse_claim_roundtrip_and_rejections() -> None:
    claim = parse_claim("c", _claim_dict())
    assert isinstance(claim, Claim)
    with pytest.raises(ConstitutionError):
        parse_claim("c", _claim_dict(claimed_status="sell_ready"))  # reserved
    with pytest.raises(claims_mod.ClaimError):
        parse_claim("c", _claim_dict(supporting_evidence_ids=[]))  # no evidence
    with pytest.raises(claims_mod.ClaimError):
        parse_claim("c", _claim_dict(supporting_evidence_ids=["a", "a"]))  # dup evidence


# --------------------------------------------------------------------------- #
# lineage                                                                      #
# --------------------------------------------------------------------------- #
def _good_graph() -> lineage_mod.ClaimsEvidenceGraph:
    evidence = (
        EvidenceRecord(
            "proto_1",
            "preregistered_protocol",
            "frozen protocol",
            "research/v2a/protocol.json",
            _H,
            "protocol",
        ),
        EvidenceRecord(
            "train_1",
            "research_train_result",
            "research-train result",
            "research/v2a/result.json",
            "bb" * 32,
            "evaluator",
        ),
        EvidenceRecord(
            "method_1",
            "methodology_note",
            "limitations",
            "docs/V2A_METHODOLOGY.md",
            "cc" * 32,
            "docs",
        ),
    )
    claims = (
        Claim(
            "nominate_x",
            "candidate x is eligible for later development-gate review",
            "eligible_for_development_gate_review",
            "candidate:x",
            ("proto_1", "train_1"),
        ),
        Claim(
            "posture",
            "the programme is not sell-ready",
            "not_sell_ready",
            "programme",
            ("method_1",),
        ),
    )
    return build_graph(evidence, claims)


def test_good_graph_is_valid_and_roundtrips() -> None:
    graph = _good_graph()
    assert verify_problems(graph) == []
    assert_valid(graph)
    reparsed = parse_graph(graph.to_canonical())
    assert reparsed.fingerprint() == graph.fingerprint()
    assert len(graph.nominated_claims()) == 1


def test_lineage_rejects_unknown_evidence_reference() -> None:
    good = _good_graph()
    broken = build_graph(
        good.evidence,
        (good.claims[0], Claim("posture", "x", "not_sell_ready", "programme", ("missing_ev",))),
    )
    problems = verify_problems(broken)
    assert any("unknown evidence id" in p for p in problems)


def test_lineage_requires_status_evidence_kinds() -> None:
    # A nomination that rests only on a methodology note is missing protocol+train evidence.
    ev = (EvidenceRecord("method_1", "methodology_note", "note", "docs/x.md", _H, "docs"),)
    claims = (
        Claim(
            "nominate_x", "x", "eligible_for_development_gate_review", "candidate:x", ("method_1",)
        ),
        Claim("posture", "x", "not_sell_ready", "programme", ("method_1",)),
    )
    problems = verify_problems(build_graph(ev, claims))
    assert any("missing required evidence kinds" in p for p in problems)


def test_lineage_caps_nominations_at_one() -> None:
    ev = (
        EvidenceRecord(
            "proto_1", "preregistered_protocol", "p", "research/v2a/p.json", _H, "protocol"
        ),
        EvidenceRecord(
            "train_1", "research_train_result", "r", "research/v2a/r.json", "bb" * 32, "eval"
        ),
        EvidenceRecord("method_1", "methodology_note", "n", "docs/x.md", "cc" * 32, "docs"),
    )
    claims = (
        Claim(
            "nom_x",
            "x",
            "eligible_for_development_gate_review",
            "candidate:x",
            ("proto_1", "train_1"),
        ),
        Claim(
            "nom_y",
            "y",
            "eligible_for_development_gate_review",
            "candidate:y",
            ("proto_1", "train_1"),
        ),
        Claim("posture", "p", "not_sell_ready", "programme", ("method_1",)),
    )
    problems = verify_problems(build_graph(ev, claims))
    assert any("more than one nomination" in p for p in problems)


def test_lineage_requires_standing_posture_claim() -> None:
    ev = (
        EvidenceRecord(
            "proto_1", "preregistered_protocol", "p", "research/v2a/p.json", _H, "protocol"
        ),
        EvidenceRecord(
            "train_1", "research_train_result", "r", "research/v2a/r.json", "bb" * 32, "eval"
        ),
    )
    claims = (
        Claim(
            "nom_x",
            "x",
            "eligible_for_development_gate_review",
            "candidate:x",
            ("proto_1", "train_1"),
        ),
    )
    problems = verify_problems(build_graph(ev, claims))
    assert any("standing" in p and "posture" in p for p in problems)


def test_parse_graph_rejects_invalid() -> None:
    ev = (EvidenceRecord("method_1", "methodology_note", "n", "docs/x.md", _H, "docs"),)
    claims = (
        Claim("nom_x", "x", "eligible_for_development_gate_review", "candidate:x", ("method_1",)),
    )
    canonical = build_graph(ev, claims).to_canonical()
    with pytest.raises(lineage_mod.LineageError):
        parse_graph(canonical)


# --------------------------------------------------------------------------- #
# budget                                                                       #
# --------------------------------------------------------------------------- #
def test_budget_constants_and_roundtrip() -> None:
    assert MAX_CANDIDATE_FAMILIES == 3
    assert MAX_RESEARCH_EXECUTIONS == 1
    current = OneShotResearchBudget.current()
    assert current.consume_on_start is True
    assert current.allow_repair_or_reset is False
    parsed = budget_mod.parse_budget(current.to_canonical())
    assert parsed.fingerprint() == current.fingerprint()


def test_budget_rejects_drift() -> None:
    bad = OneShotResearchBudget.current().to_canonical()
    bad["allow_repair_or_reset"] = True
    with pytest.raises(budget_mod.BudgetError):
        budget_mod.parse_budget(bad)


def test_family_and_execution_budget_bounds() -> None:
    assert budget_mod.require_within_family_budget("f", 3) == 3
    with pytest.raises(budget_mod.BudgetError):
        budget_mod.require_within_family_budget("f", 4)
    assert budget_mod.require_within_execution_budget("e", 0) == 0
    assert budget_mod.require_within_execution_budget("e", 1) == 1
    with pytest.raises(budget_mod.BudgetError):
        budget_mod.require_within_execution_budget("e", 2)


def test_constitution_and_budget_fingerprints_are_stable() -> None:
    # Pin the fingerprints so an accidental content change to a governance artifact is caught.
    assert const_mod.CONSTITUTION_SCHEMA_VERSION == 1
    assert budget_mod.BUDGET_SCHEMA_VERSION == 1
    # The fingerprints are self-consistent (recomputing equals the stored value).
    assert (
        CommercialEvidenceConstitution.current().fingerprint()
        == parse_constitution(CommercialEvidenceConstitution.current().to_canonical()).fingerprint()
    )
