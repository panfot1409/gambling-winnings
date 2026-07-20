"""The source-free diligence bundle: assemble, scan, and fail closed before anything is disclosed.

A diligence bundle is the exact set of redacted artifacts a buyer receives — the contract, the
claims catalogue, the factsheet, and the readiness scorecard — plus a manifest that binds each by
kind and SHA-256. Assembly is fail-closed: every artifact's canonical text is run through the
redaction policy, and if *any* violation is found the bundle is refused, never returned. A returned
bundle is therefore guaranteed source-free, secret-free, and raw-data-free by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.buyer.claims import ClaimsCatalog
from eth_research.buyer.contract import EvaluationContract
from eth_research.buyer.factsheet import Factsheet
from eth_research.buyer.redaction import RedactionPolicy, RedactionViolation
from eth_research.buyer.scorecard import ReadinessScorecard
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    require_exact_keys,
    require_hex64,
    require_list,
    require_mapping,
    require_slug,
    sha256_bytes,
)

DILIGENCE_SCHEMA_VERSION: int = 1

CONTRACT_ARTIFACT: str = "contract"
CLAIMS_ARTIFACT: str = "claims_catalog"
FACTSHEET_ARTIFACT: str = "factsheet"
SCORECARD_ARTIFACT: str = "readiness_scorecard"

_MANIFEST_ENTRY_KEYS = frozenset({"name", "kind", "sha256"})
_MANIFEST_KEYS = frozenset({"schema_version", "artifacts"})


class DiligenceError(V2ValidationError):
    """A diligence bundle could not be assembled or failed the redaction gate."""


@dataclass(frozen=True, slots=True)
class DiligenceArtifact:
    """One manifest entry: an artifact's name, redacted kind, and content digest."""

    name: str
    kind: str
    sha256: str

    def to_canonical(self) -> dict[str, object]:
        return {"name": self.name, "kind": self.kind, "sha256": self.sha256}

    @staticmethod
    def parse(label: str, value: object) -> DiligenceArtifact:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _MANIFEST_ENTRY_KEYS)
        return DiligenceArtifact(
            name=require_slug(f"{label}.name", obj["name"]),
            kind=require_slug(f"{label}.kind", obj["kind"]),
            sha256=require_hex64(f"{label}.sha256", obj["sha256"]),
        )


@dataclass(frozen=True, slots=True)
class DiligenceBundle:
    """The redacted artifacts a buyer receives, plus a fingerprintable manifest."""

    contract: EvaluationContract
    claims: ClaimsCatalog
    factsheet: Factsheet
    scorecard: ReadinessScorecard

    def artifact_texts(self) -> tuple[tuple[str, str, str], ...]:
        """``(name, kind, canonical-text)`` per redacted artifact (kind is its allowlist kind)."""
        return (
            (
                CONTRACT_ARTIFACT,
                "contract",
                canonical_json_bytes(self.contract.to_canonical()).decode("utf-8"),
            ),
            (
                CLAIMS_ARTIFACT,
                "claims_catalog",
                canonical_json_bytes(self.claims.to_canonical()).decode("utf-8"),
            ),
            (
                FACTSHEET_ARTIFACT,
                "factsheet",
                canonical_json_bytes(self.factsheet.to_canonical()).decode("utf-8"),
            ),
            (
                SCORECARD_ARTIFACT,
                "readiness_scorecard",
                canonical_json_bytes(self.scorecard.to_canonical()).decode("utf-8"),
            ),
        )

    def manifest(self) -> tuple[DiligenceArtifact, ...]:
        return tuple(
            DiligenceArtifact(name=name, kind=kind, sha256=sha256_bytes(text.encode("utf-8")))
            for name, kind, text in self.artifact_texts()
        )

    def scan(self, policy: RedactionPolicy) -> list[RedactionViolation]:
        """Every redaction violation across every artifact (empty == safe to disclose)."""
        violations: list[RedactionViolation] = []
        for name, kind, text in self.artifact_texts():
            violations.extend(policy.scan_artifact(name, kind, text))
        return violations

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": DILIGENCE_SCHEMA_VERSION,
            "artifacts": [a.to_canonical() for a in self.manifest()],
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


def assemble_diligence_bundle() -> DiligenceBundle:
    """Build the standing diligence bundle and refuse it if the redaction scan is non-empty."""
    bundle = DiligenceBundle(
        contract=EvaluationContract.current(),
        claims=ClaimsCatalog.current(),
        factsheet=Factsheet.build(
            EvaluationContract.current(), ClaimsCatalog.current(), ReadinessScorecard.current()
        ),
        scorecard=ReadinessScorecard.current(),
    )
    violations = bundle.scan(RedactionPolicy.current())
    if violations:
        detail = "; ".join(f"{v.artifact}:{v.category}:{v.detail}" for v in violations)
        raise DiligenceError(f"diligence bundle failed the redaction gate: {detail}")
    return bundle


def parse_manifest(raw: object) -> tuple[DiligenceArtifact, ...]:
    """Strictly decode a committed diligence manifest into its artifact entries."""
    obj = require_mapping("diligence_manifest", raw)
    require_exact_keys("diligence_manifest", obj, _MANIFEST_KEYS)
    return tuple(
        require_list("diligence_manifest.artifacts", obj["artifacts"], DiligenceArtifact.parse)
    )
