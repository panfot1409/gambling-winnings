"""The claims-to-evidence lineage graph and its whole-graph verifier.

A commercial-evidence graph is a set of hashed evidence records plus a set of claims that reference
them. The verifier is where "no overclaim" stops being a slogan: it refuses the graph unless

* every claim resolves each of its ``supporting_evidence_ids`` to a present evidence record;
* every claim whose status demands specific evidence kinds actually has them
  (``STATUS_REQUIRED_EVIDENCE_KINDS``);
* **at most one** claim in the whole graph carries ``eligible_for_development_gate_review`` (the
  one-nomination cap — a claim that nominates a candidate for a later, independent gate review);
* the standing ``not_sell_ready`` posture claim is present (the programme always says so);
* no reserved status appears anywhere (belt-and-suspenders over the per-claim constitution check);
* evidence and claim ids are unique.

The graph is content-hashable so it can be committed as an artifact and reproduced byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.claims import STATUS_REQUIRED_EVIDENCE_KINDS, Claim, parse_claim
from eth_research.v2.constitution import (
    STANDING_POSTURE,
    CommercialEvidenceConstitution,
    assert_no_reserved_status,
)
from eth_research.v2.evidence import EvidenceRecord, parse_evidence
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_exact_keys,
    require_hex64,
    require_int,
    require_list,
    require_mapping,
)

LINEAGE_SCHEMA_VERSION: int = 1

NOMINATION_STATUS: str = "eligible_for_development_gate_review"


class LineageError(V2ValidationError):
    """The claims-to-evidence graph is inconsistent or overclaims."""


@dataclass(frozen=True, slots=True)
class ClaimsEvidenceGraph:
    """A committed, hashable commercial-evidence graph: constitution + evidence + claims."""

    schema_version: int
    constitution_fingerprint: str
    evidence: tuple[EvidenceRecord, ...]
    claims: tuple[Claim, ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "constitution_fingerprint": self.constitution_fingerprint,
            "evidence": [e.to_canonical() for e in self.evidence],
            "claims": [c.to_canonical() for c in self.claims],
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    def evidence_by_id(self) -> dict[str, EvidenceRecord]:
        return {e.evidence_id: e for e in self.evidence}

    def nominated_claims(self) -> tuple[Claim, ...]:
        return tuple(c for c in self.claims if c.claimed_status == NOMINATION_STATUS)


def build_graph(
    evidence: tuple[EvidenceRecord, ...], claims: tuple[Claim, ...]
) -> ClaimsEvidenceGraph:
    """Assemble a graph bound to the current constitution's fingerprint."""
    return ClaimsEvidenceGraph(
        schema_version=LINEAGE_SCHEMA_VERSION,
        constitution_fingerprint=CommercialEvidenceConstitution.current().fingerprint(),
        evidence=evidence,
        claims=claims,
    )


def verify_problems(graph: ClaimsEvidenceGraph) -> list[str]:
    """Return every lineage violation as a human-readable string (empty == the graph is sound)."""
    problems: list[str] = []

    if graph.schema_version != LINEAGE_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {LINEAGE_SCHEMA_VERSION}, got {graph.schema_version}"
        )

    expected_fp = CommercialEvidenceConstitution.current().fingerprint()
    if graph.constitution_fingerprint != expected_fp:
        problems.append("constitution_fingerprint does not match the current constitution")

    evidence_ids = [e.evidence_id for e in graph.evidence]
    if len(set(evidence_ids)) != len(evidence_ids):
        problems.append("duplicate evidence ids present")
    by_id = graph.evidence_by_id()

    claim_ids = [c.claim_id for c in graph.claims]
    if len(set(claim_ids)) != len(claim_ids):
        problems.append("duplicate claim ids present")

    # Every claim's evidence must resolve, and status-required evidence kinds must be present.
    for claim in graph.claims:
        present_kinds: set[str] = set()
        for eid in claim.supporting_evidence_ids:
            record = by_id.get(eid)
            if record is None:
                problems.append(f"claim {claim.claim_id!r} references unknown evidence id {eid!r}")
                continue
            present_kinds.add(record.kind)
        required = STATUS_REQUIRED_EVIDENCE_KINDS.get(claim.claimed_status, frozenset())
        missing = required - present_kinds
        if missing:
            problems.append(
                f"claim {claim.claim_id!r} status {claim.claimed_status!r} is missing required "
                f"evidence kinds {sorted(missing)!r}"
            )

    # The one-nomination cap.
    nominated = graph.nominated_claims()
    if len(nominated) > 1:
        ids = sorted(c.claim_id for c in nominated)
        problems.append(f"more than one nomination claim present: {ids!r}")

    # The standing posture claim must be present.
    if not any(c.claimed_status == STANDING_POSTURE for c in graph.claims):
        problems.append(f"no standing {STANDING_POSTURE!r} posture claim present")

    # Defence in depth: no reserved status may appear on any claim.
    try:
        assert_no_reserved_status("graph.claims.status", [c.claimed_status for c in graph.claims])
    except V2ValidationError as exc:  # pragma: no cover - per-claim parse already blocks this
        problems.append(str(exc))

    return problems


def assert_valid(graph: ClaimsEvidenceGraph) -> None:
    """Raise :class:`LineageError` if the graph has any violation."""
    problems = verify_problems(graph)
    if problems:
        raise LineageError("; ".join(problems))


_GRAPH_KEYS = frozenset({"schema_version", "constitution_fingerprint", "evidence", "claims"})


def parse_graph(raw: object) -> ClaimsEvidenceGraph:
    """Strictly decode a committed graph artifact and verify it before returning."""
    obj = require_mapping("graph", raw)
    require_exact_keys("graph", obj, _GRAPH_KEYS)
    graph = ClaimsEvidenceGraph(
        schema_version=require_int("graph.schema_version", obj["schema_version"]),
        constitution_fingerprint=require_hex64(
            "graph.constitution_fingerprint", obj["constitution_fingerprint"]
        ),
        evidence=tuple(require_list("graph.evidence", obj["evidence"], parse_evidence)),
        claims=tuple(require_list("graph.claims", obj["claims"], parse_claim)),
    )
    assert_valid(graph)
    return graph
