"""The commercial-readiness scorecard: an honest, dimension-by-dimension rating.

The scorecard rates the program across five dimensions on an ordered scale and states an overall
commercial posture. It is deliberately not a sales sheet: commercial readiness is rated ``absent``
and the overall posture is ``not_sell_ready``, consistent with the constitution. Each dimension
carries a short rationale a reviewer can check against the committed evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

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

SCORECARD_SCHEMA_VERSION: int = 1

# Ordered from least to most mature.
READINESS_LEVELS: tuple[str, ...] = ("absent", "emerging", "established", "strong")
_LEVELS: frozenset[str] = frozenset(READINESS_LEVELS)

_DIMENSION_KEYS = frozenset({"dimension_id", "level", "rationale"})
_SCORECARD_KEYS = frozenset({"schema_version", "dimensions", "overall_posture"})


class ScorecardError(V2ValidationError):
    """A scorecard dimension or the scorecard as a whole violated its contract."""


@dataclass(frozen=True, slots=True)
class ScorecardDimension:
    """One rated dimension with its rationale."""

    dimension_id: str
    level: str
    rationale: str

    @staticmethod
    def parse(label: str, value: object) -> ScorecardDimension:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _DIMENSION_KEYS)
        return ScorecardDimension(
            dimension_id=require_slug(f"{label}.dimension_id", obj["dimension_id"]),
            level=require_choice(f"{label}.level", obj["level"], _LEVELS),
            rationale=require_nonempty_str(f"{label}.rationale", obj["rationale"]),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "dimension_id": self.dimension_id,
            "level": self.level,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class ReadinessScorecard:
    """The full scorecard: rated dimensions + the overall (not-sell-ready) posture."""

    dimensions: tuple[ScorecardDimension, ...]
    overall_posture: str

    @staticmethod
    def current() -> ReadinessScorecard:
        return ReadinessScorecard(
            dimensions=(
                ScorecardDimension(
                    dimension_id="research_evidence",
                    level="established",
                    rationale=(
                        "Candidates are evaluated on the research-train partition under a "
                        "pre-registered, cost-aware, bootstrapped protocol — but on that partition "
                        "only; there is no out-of-sample or forward evidence."
                    ),
                ),
                ScorecardDimension(
                    dimension_id="reproducibility",
                    level="strong",
                    rationale=(
                        "Every artifact is strict canonical JSON with no wall-clock; results and "
                        "journals are hash-chained and reproduce byte for byte."
                    ),
                ),
                ScorecardDimension(
                    dimension_id="governance",
                    level="strong",
                    rationale=(
                        "Sealed partitions are firewalled with byte-empty access ledgers; the "
                        "governed experiment is one-shot and registry-mediated."
                    ),
                ),
                ScorecardDimension(
                    dimension_id="operational_readiness",
                    level="emerging",
                    rationale=(
                        "A signal-only shadow platform exists (risk limits, latching kill switch, "
                        "paper accounting, journalling) but there is no live or paper connectivity."
                    ),
                ),
                ScorecardDimension(
                    dimension_id="commercial_readiness",
                    level="absent",
                    rationale=(
                        "No license, no productized offering, no forward or live performance "
                        "evidence. The program is not sell-ready."
                    ),
                ),
            ),
            overall_posture=STANDING_POSTURE,
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": SCORECARD_SCHEMA_VERSION,
            "dimensions": [d.to_canonical() for d in self.dimensions],
            "overall_posture": self.overall_posture,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @staticmethod
    def parse(raw: object) -> ReadinessScorecard:
        obj = require_mapping("scorecard", raw)
        require_exact_keys("scorecard", obj, _SCORECARD_KEYS)
        dims = tuple(
            require_list("scorecard.dimensions", obj["dimensions"], ScorecardDimension.parse)
        )
        if not dims:
            raise ScorecardError("scorecard must have at least one dimension")
        posture = require_choice(
            "scorecard.overall_posture", obj["overall_posture"], frozenset({STANDING_POSTURE})
        )
        return ReadinessScorecard(dimensions=dims, overall_posture=posture)
