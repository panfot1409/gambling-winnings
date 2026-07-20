"""Evidence records: committed artifacts, hashed, that a commercial claim can be traced to.

An evidence record is a *pointer with a fingerprint*: it names a committed artifact (safe relative
path), pins its content by full SHA-256, states what kind of evidence it is, and records which V2A
component produced it. Claims are only credible when every one traces to evidence like this, so the
lineage graph (``eth_research.v2.lineage``) refuses any claim whose supporting evidence is absent.

Evidence records never assert a claim status themselves — they are inputs to claims, not claims.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_choice,
    require_exact_keys,
    require_hex64,
    require_mapping,
    require_nonempty_str,
    require_safe_relative_path,
    require_slug,
)

EVIDENCE_SCHEMA_VERSION: int = 1

# The kinds of evidence a V2A claim may be traced to. Deliberately closed: a claim can only rest on
# evidence the programme actually produces, and none of these kinds is an out-of-sample, forward, or
# live record (those partitions are never touched).
EVIDENCE_KINDS: frozenset[str] = frozenset(
    {
        "research_train_result",  # a metric/decision computed on the authorized research-train
        "preregistered_protocol",  # a frozen, hash-pinned research protocol
        "candidate_specification",  # a frozen candidate family definition
        "cost_model",  # the execution-cost / latency / impact stack
        "sensitivity_analysis",  # parameter / assumption sensitivity output
        "bootstrap_analysis",  # fold-aware bootstrap / Monte-Carlo output
        "partition_firewall",  # proof the sealed partitions were unreachable
        "code_freeze",  # a source-freeze checkpoint
        "registration",  # the one-shot registry record
        "reproduction",  # a byte-identical fresh-clone reproduction
        "shadow_run_log",  # a signal-only shadow-operations record (no orders)
        "methodology_note",  # a written methodology / limitation statement
    }
)


class EvidenceError(V2ValidationError):
    """An evidence record was malformed or referenced an unknown evidence kind."""


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """A single hashed pointer to a committed artifact that can back a claim."""

    evidence_id: str
    kind: str
    description: str
    artifact_path: str
    artifact_sha256: str
    produced_by: str

    def to_canonical(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "description": self.description,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "produced_by": self.produced_by,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


_EVIDENCE_KEYS = frozenset(
    {"evidence_id", "kind", "description", "artifact_path", "artifact_sha256", "produced_by"}
)


def parse_evidence(label: str, raw: object) -> EvidenceRecord:
    """Strictly decode one evidence record (exact keys, known kind, safe path, real SHA-256)."""
    obj = require_mapping(label, raw)
    require_exact_keys(label, obj, _EVIDENCE_KEYS)
    return EvidenceRecord(
        evidence_id=require_slug(f"{label}.evidence_id", obj["evidence_id"]),
        kind=require_choice(f"{label}.kind", obj["kind"], EVIDENCE_KINDS),
        description=require_nonempty_str(f"{label}.description", obj["description"]),
        artifact_path=require_safe_relative_path(f"{label}.artifact_path", obj["artifact_path"]),
        artifact_sha256=require_hex64(f"{label}.artifact_sha256", obj["artifact_sha256"]),
        produced_by=require_slug(f"{label}.produced_by", obj["produced_by"]),
    )
