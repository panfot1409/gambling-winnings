"""The buyer claims catalogue: honest, verifiable, constitution-validated statements only.

Every claim a buyer sees is decoded through the V2 commercial constitution, so no reserved or
forward/live status can ever be emitted. A claim binds a plain statement to an emittable status and
to the *provenance* a reviewer can check (a committed artifact path or module) — never to source or
sealed data. The standing catalogue makes only research-stage and governance claims, and states the
program is ``not_sell_ready``.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.constitution import STANDING_POSTURE, require_v2a_emittable_status
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_exact_keys,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_slug,
)

CLAIMS_SCHEMA_VERSION: int = 1

_CLAIM_KEYS = frozenset({"claim_id", "statement", "status", "evidence"})
_CATALOG_KEYS = frozenset({"schema_version", "claims"})


class ClaimsError(V2ValidationError):
    """A buyer claim or catalogue violated its contract."""


@dataclass(frozen=True, slots=True)
class BuyerClaim:
    """One verifiable claim: a statement, an emittable status, and its checkable provenance."""

    claim_id: str
    statement: str
    status: str
    evidence: str

    @staticmethod
    def create(*, claim_id: str, statement: str, status: str, evidence: str) -> BuyerClaim:
        return BuyerClaim(
            claim_id=require_slug("claim_id", claim_id),
            statement=require_nonempty_str("statement", statement),
            status=require_v2a_emittable_status("status", status),
            evidence=require_nonempty_str("evidence", evidence),
        )

    @staticmethod
    def parse(label: str, value: object) -> BuyerClaim:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _CLAIM_KEYS)
        return BuyerClaim(
            claim_id=require_slug(f"{label}.claim_id", obj["claim_id"]),
            statement=require_nonempty_str(f"{label}.statement", obj["statement"]),
            status=require_v2a_emittable_status(f"{label}.status", obj["status"]),
            evidence=require_nonempty_str(f"{label}.evidence", obj["evidence"]),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "status": self.status,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class ClaimsCatalog:
    """The full catalogue of buyer-facing claims (hashable, strictly round-tripping)."""

    claims: tuple[BuyerClaim, ...]

    @staticmethod
    def current() -> ClaimsCatalog:
        return ClaimsCatalog(
            claims=(
                BuyerClaim.create(
                    claim_id="research_program_scope",
                    statement=(
                        "The V2A program evaluates a small, pre-registered set of ETH/USD "
                        "candidate families on the authorized research-train partition only."
                    ),
                    status="research_only_observation",
                    evidence="src/eth_research/v2/candidates.py",
                ),
                BuyerClaim.create(
                    claim_id="pre_registered_protocol",
                    statement=(
                        "Folds, cost scenarios, bootstrap parameters, and the nomination rule are "
                        "fixed before any candidate is run and are hash-pinned."
                    ),
                    status="research_only_observation",
                    evidence="src/eth_research/v2/protocol.py",
                ),
                BuyerClaim.create(
                    claim_id="single_governed_execution",
                    statement=(
                        "The governed research evaluation runs exactly once, mediated by an "
                        "append-only hash-chained registry that consumes the one-shot budget."
                    ),
                    status="research_only_observation",
                    evidence="src/eth_research/v2/registry.py",
                ),
                BuyerClaim.create(
                    claim_id="sealed_partitions_untouched",
                    statement=(
                        "The development-gate and final-holdout partitions are never read by V2A; "
                        "their access ledgers are byte-empty."
                    ),
                    status="research_only_observation",
                    evidence="research/m3a/development_gate_access.jsonl",
                ),
                BuyerClaim.create(
                    claim_id="signal_only_operations",
                    statement=(
                        "The shadow-operations platform is signal-only: it never connects to a "
                        "network, places an order, holds a credential, or moves money."
                    ),
                    status="research_only_observation",
                    evidence="src/eth_research/shadow/domain.py",
                ),
                BuyerClaim.create(
                    claim_id="commercial_posture",
                    statement=(
                        "V2 is not sell-ready. Any nomination is only eligibility for independent "
                        "development-gate review, not evidence of live or forward performance."
                    ),
                    status=STANDING_POSTURE,
                    evidence="src/eth_research/v2/constitution.py",
                ),
            )
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": CLAIMS_SCHEMA_VERSION,
            "claims": [c.to_canonical() for c in self.claims],
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @staticmethod
    def parse(raw: object) -> ClaimsCatalog:
        obj = require_mapping("claims_catalog", raw)
        require_exact_keys("claims_catalog", obj, _CATALOG_KEYS)
        claims = tuple(require_list("claims_catalog.claims", obj["claims"], BuyerClaim.parse))
        if not claims:
            raise ClaimsError("claims catalogue must not be empty")
        return ClaimsCatalog(claims=claims)
