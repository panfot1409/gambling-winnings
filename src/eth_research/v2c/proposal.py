"""V2C section 16: the source-independent, idempotent prospective-update proposal format.

A :class:`ProspectiveUpdateProposal` describes -- as pure data, computed offline -- a *plan* to
extend a prospective cohort by the completed observations in a half-open window
``[first_missing_open, completed_exclusive_end)``. It is deliberately **source-independent**: it
embeds no endpoint URL, credential, host, or command, and its ``idempotency_key`` is a function of
the base binding and the window only. The same base and window therefore yield byte-identical
proposals no matter who or what generates them.

It is also **candidate-free and data-only**. Its :data:`GOVERNANCE_FLAGS` are all ``False``:
generating or accepting a proposal never fetches real data, declares a candidate, computes a
performance metric, or authorizes evaluation. Those remain separate, future, human-authorized steps
outside V2C. This module builds the *format*; :mod:`eth_research.v2c.proposal_generator` computes
one offline from a cohort descriptor and an explicit as-of instant.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.m3d.validation import (
    M3DValidationError,
    domain_sha256,
    require_exact,
    require_mapping,
    require_nonempty_str,
    require_positive_int,
    require_sha256_hex,
)
from eth_research.v2c.firewall import assert_no_candidate_reference

SCHEMA_VERSION: int = 1
_PROPOSAL_DOMAIN: str = "v2c/prospective_update_proposal.v1"
_IDEMPOTENCY_DOMAIN: str = "v2c/prospective_update_idempotency.v1"

#: Every governance flag a proposal carries is permanently ``False``: a proposal is a data-update
#: *plan*, never a fetch, a candidate, a performance computation, or an evaluation authorization.
GOVERNANCE_FLAGS: dict[str, bool] = {
    "real_data_fetched": False,
    "candidate_declared": False,
    "strategy_evaluation_requested": False,
    "performance_metrics_requested": False,
    "evaluation_authorization": False,
}

_PROPOSAL_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "base_cohort_id",
        "base_descriptor_digest",
        "product",
        "venue",
        "interval_seconds",
        "first_missing_open",
        "completed_exclusive_end",
        "expected_row_count",
        "idempotency_key",
        "governance_flags",
        "proposal_digest",
    }
)


class V2CProposalError(M3DValidationError):
    """A prospective-update proposal was malformed, non-idempotent, or not data-only."""


@dataclass(frozen=True, slots=True)
class ProspectiveUpdateProposal:
    """A source-independent, idempotent plan to extend a cohort by a completed window."""

    base_cohort_id: str
    base_descriptor_digest: str
    product: str
    venue: str
    interval_seconds: int
    first_missing_open: str
    completed_exclusive_end: str
    expected_row_count: int

    def __post_init__(self) -> None:
        require_nonempty_str("base_cohort_id", self.base_cohort_id)
        require_sha256_hex("base_descriptor_digest", self.base_descriptor_digest)
        assert_no_candidate_reference("proposal.product", self.product)
        assert_no_candidate_reference("proposal.venue", self.venue)
        require_nonempty_str("product", self.product)
        require_nonempty_str("venue", self.venue)
        require_positive_int("interval_seconds", self.interval_seconds)
        require_nonempty_str("first_missing_open", self.first_missing_open)
        require_nonempty_str("completed_exclusive_end", self.completed_exclusive_end)
        # A proposal exists only when at least one completed observation is due.
        rows = require_positive_int("expected_row_count", self.expected_row_count)
        if rows < 1:  # pragma: no cover - require_positive_int already enforces this
            raise V2CProposalError("a proposal must cover at least one completed observation")

    def idempotency_key(self) -> str:
        """Runner-independent key: identical base binding + window -> identical key."""
        return domain_sha256(
            _IDEMPOTENCY_DOMAIN,
            {
                "base_descriptor_digest": self.base_descriptor_digest,
                "first_missing_open": self.first_missing_open,
                "completed_exclusive_end": self.completed_exclusive_end,
                "expected_row_count": self.expected_row_count,
            },
        )

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "base_cohort_id": self.base_cohort_id,
            "base_descriptor_digest": self.base_descriptor_digest,
            "product": self.product,
            "venue": self.venue,
            "interval_seconds": self.interval_seconds,
            "first_missing_open": self.first_missing_open,
            "completed_exclusive_end": self.completed_exclusive_end,
            "expected_row_count": self.expected_row_count,
            "idempotency_key": self.idempotency_key(),
            "governance_flags": dict(GOVERNANCE_FLAGS),
        }

    def proposal_digest(self) -> str:
        """Domain-separated SHA-256 self-digest binding every proposal field."""
        return domain_sha256(_PROPOSAL_DOMAIN, self._body())

    def to_canonical(self) -> dict[str, object]:
        body = self._body()
        body["proposal_digest"] = self.proposal_digest()
        return body

    @staticmethod
    def from_mapping(label: str, value: object) -> ProspectiveUpdateProposal:
        obj = require_mapping(label, value)
        extra = set(obj) - _PROPOSAL_KEYS
        missing = _PROPOSAL_KEYS - set(obj)
        if extra or missing:
            raise V2CProposalError(
                f"{label} keys mismatch (unexpected={sorted(extra)}, missing={sorted(missing)})"
            )
        require_exact(f"{label}.schema_version", obj["schema_version"], SCHEMA_VERSION)
        _require_governance_flags(f"{label}.governance_flags", obj["governance_flags"])
        proposal = ProspectiveUpdateProposal(
            base_cohort_id=require_nonempty_str(f"{label}.base_cohort_id", obj["base_cohort_id"]),
            base_descriptor_digest=require_sha256_hex(
                f"{label}.base_descriptor_digest", obj["base_descriptor_digest"]
            ),
            product=require_nonempty_str(f"{label}.product", obj["product"]),
            venue=require_nonempty_str(f"{label}.venue", obj["venue"]),
            interval_seconds=require_positive_int(
                f"{label}.interval_seconds", obj["interval_seconds"]
            ),
            first_missing_open=require_nonempty_str(
                f"{label}.first_missing_open", obj["first_missing_open"]
            ),
            completed_exclusive_end=require_nonempty_str(
                f"{label}.completed_exclusive_end", obj["completed_exclusive_end"]
            ),
            expected_row_count=require_positive_int(
                f"{label}.expected_row_count", obj["expected_row_count"]
            ),
        )
        if require_nonempty_str(f"{label}.idempotency_key", obj["idempotency_key"]) != (
            proposal.idempotency_key()
        ):
            raise V2CProposalError(f"{label}.idempotency_key does not bind the window")
        if require_nonempty_str(f"{label}.proposal_digest", obj["proposal_digest"]) != (
            proposal.proposal_digest()
        ):
            raise V2CProposalError(f"{label}.proposal_digest does not bind the proposal body")
        return proposal


def _require_governance_flags(label: str, value: object) -> None:
    obj = require_mapping(label, value)
    if set(obj) != set(GOVERNANCE_FLAGS):
        raise V2CProposalError(f"{label} keys must be exactly {sorted(GOVERNANCE_FLAGS)}")
    for key, expected in GOVERNANCE_FLAGS.items():
        if obj[key] is not expected:
            raise V2CProposalError(f"{label}.{key} must be {expected!r}; a proposal is data-only")


__all__ = [
    "GOVERNANCE_FLAGS",
    "SCHEMA_VERSION",
    "ProspectiveUpdateProposal",
    "V2CProposalError",
]
