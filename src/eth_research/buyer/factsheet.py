"""The research factsheet: a concise, source-free summary bound to what it summarizes.

The factsheet is the one-page overview a buyer reads first. It carries a title, an honest summary, a
handful of headline points, the standing posture, and the fingerprints of the contract, claims
catalogue, and scorecard it summarizes — so a reviewer can confirm the factsheet describes exactly
those committed artifacts and nothing else. Its markdown rendering is plain prose: no source, no
numbers presented as forward performance, no sealed data.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.buyer.claims import ClaimsCatalog
from eth_research.buyer.contract import EvaluationContract
from eth_research.buyer.scorecard import ReadinessScorecard
from eth_research.v2.constitution import STANDING_POSTURE
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_choice,
    require_exact_keys,
    require_hex64,
    require_list,
    require_mapping,
    require_nonempty_str,
)

FACTSHEET_SCHEMA_VERSION: int = 1

_FACTSHEET_KEYS = frozenset(
    {
        "schema_version",
        "title",
        "summary",
        "headlines",
        "posture",
        "contract_fingerprint",
        "claims_fingerprint",
        "scorecard_fingerprint",
    }
)


class FactsheetError(V2ValidationError):
    """A factsheet violated its contract."""


@dataclass(frozen=True, slots=True)
class Factsheet:
    """A concise research factsheet bound by fingerprint to its source artifacts."""

    title: str
    summary: str
    headlines: tuple[str, ...]
    posture: str
    contract_fingerprint: str
    claims_fingerprint: str
    scorecard_fingerprint: str

    @staticmethod
    def build(
        contract: EvaluationContract, claims: ClaimsCatalog, scorecard: ReadinessScorecard
    ) -> Factsheet:
        return Factsheet(
            title="ETH/USD research program — buyer evaluation factsheet",
            summary=(
                "A research-stage evaluation of a pre-registered ETH/USD candidate program on the "
                "authorized research-train partition, with cost-aware, bootstrapped statistics and "
                "a single governed execution. This is not an out-of-sample, forward, or live "
                "performance claim, and it is not an offer to sell."
            ),
            headlines=(
                "Pre-registered protocol: folds, costs, bootstrap, and nomination rule fixed and "
                "hash-pinned before any candidate runs.",
                "Exactly one governed execution, mediated by an append-only hash-chained registry.",
                "Sealed development-gate and final-holdout partitions are never read (byte-empty "
                "access ledgers).",
                "Signal-only shadow operations: no network, no orders, no credentials, no money.",
                "Standing commercial posture is not_sell_ready.",
            ),
            posture=STANDING_POSTURE,
            contract_fingerprint=contract.fingerprint(),
            claims_fingerprint=claims.fingerprint(),
            scorecard_fingerprint=scorecard.fingerprint(),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": FACTSHEET_SCHEMA_VERSION,
            "title": self.title,
            "summary": self.summary,
            "headlines": list(self.headlines),
            "posture": self.posture,
            "contract_fingerprint": self.contract_fingerprint,
            "claims_fingerprint": self.claims_fingerprint,
            "scorecard_fingerprint": self.scorecard_fingerprint,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    def render_markdown(self) -> str:
        lines = [f"# {self.title}", "", self.summary, "", "## Highlights"]
        lines.extend(f"- {point}" for point in self.headlines)
        lines.extend(["", f"**Commercial posture:** {self.posture}", ""])
        return "\n".join(lines)

    @staticmethod
    def parse(raw: object) -> Factsheet:
        obj = require_mapping("factsheet", raw)
        require_exact_keys("factsheet", obj, _FACTSHEET_KEYS)
        headlines = tuple(
            require_list("factsheet.headlines", obj["headlines"], require_nonempty_str)
        )
        if not headlines:
            raise FactsheetError("factsheet must have at least one headline")
        return Factsheet(
            title=require_nonempty_str("factsheet.title", obj["title"]),
            summary=require_nonempty_str("factsheet.summary", obj["summary"]),
            headlines=headlines,
            posture=require_choice(
                "factsheet.posture", obj["posture"], frozenset({STANDING_POSTURE})
            ),
            contract_fingerprint=require_hex64(
                "factsheet.contract_fingerprint", obj["contract_fingerprint"]
            ),
            claims_fingerprint=require_hex64(
                "factsheet.claims_fingerprint", obj["claims_fingerprint"]
            ),
            scorecard_fingerprint=require_hex64(
                "factsheet.scorecard_fingerprint", obj["scorecard_fingerprint"]
            ),
        )
