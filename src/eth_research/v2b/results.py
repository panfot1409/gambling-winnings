"""The immutable V2B one-shot results: the pure program result plus the identity that binds it.

A results artifact is a deterministic, hashable record of the one governed cross-asset evaluation:
which run it was, under which frozen protocol, at which package version, and the pure
:class:`~eth_research.v2b.orchestrator.ProgramResult` (every candidate's evidence, the ``<= 1``
nomination decision, and the terminal verdict). It carries no wall-clock time and no live-only
state, so it reproduces byte-for-byte from the same committed universe.

The pure ``ProgramResult`` already serialises and fingerprints itself, so this layer only *wraps* it
with the run identity; a committed document is re-verified by re-canonicalising its bytes
(idempotent for the canonical form) rather than by reconstructing the nested dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_exact_keys,
    require_hex64,
    require_mapping,
    require_nonempty_str,
    require_slug,
    strict_json_loads,
)
from eth_research.v2b.orchestrator import OneShotOutcome, ProgramResult

V2B_RESULTS_SCHEMA_VERSION: int = 1


class V2BResultsError(V2ValidationError):
    """A V2B results artifact was malformed or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class FrozenV2BResults:
    """The committed, hashable one-shot V2B results (run identity + the pure program result)."""

    schema_version: int
    run_id: str
    package_version: str
    protocol_fingerprint: str
    result: ProgramResult

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "package_version": self.package_version,
            "protocol_fingerprint": self.protocol_fingerprint,
            "result": self.result.to_canonical(),
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @property
    def nominated_candidate_id(self) -> str | None:
        return self.result.decision.nominated_candidate_id

    @property
    def verdict(self) -> str:
        return self.result.verdict


def build_results(
    outcome: OneShotOutcome, *, run_id: str, package_version: str
) -> FrozenV2BResults:
    """Wrap a one-shot :class:`OneShotOutcome` with its run identity (pure; no side effects)."""
    return FrozenV2BResults(
        schema_version=V2B_RESULTS_SCHEMA_VERSION,
        run_id=require_slug("v2b_results.run_id", run_id),
        package_version=require_nonempty_str("v2b_results.package_version", package_version),
        protocol_fingerprint=require_hex64(
            "v2b_results.protocol_fingerprint", outcome.protocol_fingerprint
        ),
        result=outcome.result,
    )


_RESULTS_KEYS = frozenset(
    {"schema_version", "run_id", "package_version", "protocol_fingerprint", "result"}
)


@dataclass(frozen=True, slots=True)
class CommittedResultsSummary:
    """A committed results document's identity + decision summary (strict, no reconstruction)."""

    run_id: str
    protocol_fingerprint: str
    fingerprint: str
    nominated_candidate_id: str | None
    verdict: str


def summarize_committed(raw_bytes: bytes) -> CommittedResultsSummary:
    """Strictly navigate committed results bytes to their identity + decision (no nested parse).

    The document's fingerprint is the canonical hash of its own bytes, so it equals
    :meth:`FrozenV2BResults.fingerprint` for a document written by :func:`build_results` — the
    canonical form is idempotent under ``strict_json_loads`` → ``canonical_sha256``.
    """
    obj = require_mapping("v2b_results", strict_json_loads(raw_bytes))
    require_exact_keys("v2b_results", obj, _RESULTS_KEYS)
    require_nonempty_str("v2b_results.package_version", obj["package_version"])
    result = require_mapping("v2b_results.result", obj["result"])
    decision = require_mapping("v2b_results.result.decision", result["decision"])
    nominated = decision["nominated_candidate_id"]
    if nominated is not None:
        nominated = require_slug("v2b_results.result.decision.nominated_candidate_id", nominated)
    return CommittedResultsSummary(
        run_id=require_slug("v2b_results.run_id", obj["run_id"]),
        protocol_fingerprint=require_hex64(
            "v2b_results.protocol_fingerprint", obj["protocol_fingerprint"]
        ),
        fingerprint=canonical_sha256(obj),
        nominated_candidate_id=nominated,
        verdict=require_nonempty_str("v2b_results.result.verdict", result["verdict"]),
    )


__all__ = [
    "V2B_RESULTS_SCHEMA_VERSION",
    "CommittedResultsSummary",
    "FrozenV2BResults",
    "V2BResultsError",
    "build_results",
    "summarize_committed",
]
