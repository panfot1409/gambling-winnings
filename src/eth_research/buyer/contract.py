"""The evaluation contract: exactly what a buyer evaluation offers and what it withholds.

The contract is the honest, hashable statement of the boundary. It names the redacted artifacts a
buyer *receives* and, just as explicitly, the things the evaluation *never* provides — source code,
any sealed partition, credentials, live/paper exchange access, and the ability to run the single
governed experiment. Its standing commercial posture is ``not_sell_ready``: an evaluation is a look
at research-stage evidence, not an offer to sell.

The contract binds the redaction policy's allowed kinds, so the promise "source-free, redacted only"
is machine-checkable against what a bundle actually contains.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.buyer.redaction import ALLOWED_ARTIFACT_KINDS
from eth_research.v2.constitution import STANDING_POSTURE
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_choice,
    require_exact_keys,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_slug,
)

CONTRACT_SCHEMA_VERSION: int = 1

OFFERED: tuple[str, ...] = (
    "redacted_claims_catalog",
    "research_factsheet",
    "commercial_readiness_scorecard",
    "public_partition_reproduction_instructions",
    "governance_and_provenance_summary",
)

WITHHELD: tuple[str, ...] = (
    "source_code",
    "development_gate_partition",
    "final_holdout_partition",
    "prospective_cohort_data",
    "exchange_or_wallet_credentials",
    "live_or_paper_exchange_access",
    "ability_to_run_the_governed_experiment",
    "raw_or_canonical_price_data",
)

_CONTRACT_KEYS = frozenset(
    {"schema_version", "posture", "offered", "withheld", "allowed_kinds", "terms_summary"}
)


class ContractError(V2ValidationError):
    """The evaluation contract was malformed or drifted from its fixed definition."""


@dataclass(frozen=True, slots=True)
class EvaluationContract:
    """The fixed, hashable buyer-evaluation contract."""

    posture: str
    offered: tuple[str, ...]
    withheld: tuple[str, ...]
    allowed_kinds: tuple[str, ...]
    terms_summary: str

    @staticmethod
    def current() -> EvaluationContract:
        return EvaluationContract(
            posture=STANDING_POSTURE,
            offered=OFFERED,
            withheld=WITHHELD,
            allowed_kinds=tuple(sorted(ALLOWED_ARTIFACT_KINDS)),
            terms_summary=(
                "A buyer evaluation is a source-free, redacted look at research-stage evidence for "
                "one ETH/USD research program. It conveys no license, no source, no sealed data, "
                "no live or paper trading access, and no ability to run the governed experiment. "
                "standing posture is not_sell_ready; nothing here is an out-of-sample, forward, or "
                "live performance claim, and nothing here is an offer to sell."
            ),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "posture": self.posture,
            "offered": list(self.offered),
            "withheld": list(self.withheld),
            "allowed_kinds": list(self.allowed_kinds),
            "terms_summary": self.terms_summary,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


def parse_contract(raw: object) -> EvaluationContract:
    """Strictly decode a committed contract and re-assert the fixed definition by fingerprint."""
    obj = require_mapping("contract", raw)
    require_exact_keys("contract", obj, _CONTRACT_KEYS)
    posture = require_choice("contract.posture", obj["posture"], frozenset({STANDING_POSTURE}))
    offered = tuple(require_list("contract.offered", obj["offered"], require_slug))
    withheld = tuple(require_list("contract.withheld", obj["withheld"], require_slug))
    allowed = tuple(require_list("contract.allowed_kinds", obj["allowed_kinds"], require_slug))
    terms = require_nonempty_str("contract.terms_summary", obj["terms_summary"])
    contract = EvaluationContract(
        posture=posture,
        offered=offered,
        withheld=withheld,
        allowed_kinds=allowed,
        terms_summary=terms,
    )
    if contract.fingerprint() != EvaluationContract.current().fingerprint():
        raise ContractError("contract content drifted from the fixed evaluation contract")
    return contract
