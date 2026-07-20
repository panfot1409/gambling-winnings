"""Commercial claims: statements bounded by the constitution and backed by referenced evidence.

A claim is the atom of commercial evidence. Each one carries exactly one **V2A-emittable** status
(the constitution rejects anything else, fail-closed), states its scope (what it is about — a
candidate family, the programme as a whole, an operational rehearsal), and lists the evidence
records that support it *by id*. Claims never carry raw numbers or artifacts; they point at
evidence, and the lineage graph is what checks the pointers resolve and the status is earned.

Two status rules are enforced here, at parse time, independent of the lineage graph:

* ``research_only_observation`` asserts nothing testable, so it may stand on any (>=1) evidence.
* ``eligible_for_development_gate_review`` is the strongest thing V2A can say and must rest on at
  least a preregistered protocol *and* a research-train result; the nomination rule (a later phase)
  adds the requirement that at most one claim in the whole programme carries this status.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.constitution import require_v2a_emittable_status
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_exact_keys,
    require_mapping,
    require_nonempty_str,
    require_slug,
)

CLAIMS_SCHEMA_VERSION: int = 1


class ClaimError(V2ValidationError):
    """A claim was malformed, overclaimed, or referenced no evidence."""


@dataclass(frozen=True, slots=True)
class Claim:
    """One commercial claim: a bounded statement, its status, and its supporting evidence ids."""

    claim_id: str
    statement: str
    claimed_status: str
    scope: str
    supporting_evidence_ids: tuple[str, ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "claimed_status": self.claimed_status,
            "scope": self.scope,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


_CLAIM_KEYS = frozenset(
    {"claim_id", "statement", "claimed_status", "scope", "supporting_evidence_ids"}
)

# Statuses that require specific evidence kinds present in the supporting set. Checked by the
# lineage graph, which can see the referenced evidence records; declared here so the requirement
# lives next to the claim definition.
STATUS_REQUIRED_EVIDENCE_KINDS: dict[str, frozenset[str]] = {
    "research_stage_supported": frozenset({"preregistered_protocol", "research_train_result"}),
    "research_stage_rejected": frozenset({"preregistered_protocol", "research_train_result"}),
    "eligible_for_development_gate_review": frozenset(
        {"preregistered_protocol", "research_train_result"}
    ),
}


def parse_claim(label: str, raw: object) -> Claim:
    """Strictly decode one claim; the status must be V2A-emittable and evidence non-empty."""
    obj = require_mapping(label, raw)
    require_exact_keys(label, obj, _CLAIM_KEYS)

    evidence_ids = _require_evidence_ids(
        f"{label}.supporting_evidence_ids", obj["supporting_evidence_ids"]
    )
    return Claim(
        claim_id=require_slug(f"{label}.claim_id", obj["claim_id"]),
        statement=require_nonempty_str(f"{label}.statement", obj["statement"]),
        claimed_status=require_v2a_emittable_status(
            f"{label}.claimed_status", obj["claimed_status"]
        ),
        scope=require_nonempty_str(f"{label}.scope", obj["scope"]),
        supporting_evidence_ids=evidence_ids,
    )


def _require_evidence_ids(label: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ClaimError(f"{label} must be a JSON array")
    if not value:
        raise ClaimError(f"{label} must reference at least one evidence record")
    ids = tuple(require_slug(f"{label}[{i}]", v) for i, v in enumerate(value))
    if len(set(ids)) != len(ids):
        raise ClaimError(f"{label} contains duplicate evidence ids")
    return ids
