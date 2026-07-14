"""Immutable artifact manifest + replay verifier for the M3C candidate run.

The published run writes four immutable files: the strict results JSON, the
deterministic Markdown report, the mechanical decision JSON, and this manifest,
which binds their exact digests and the ``bundle_sha256`` (the SHA-256 of the
results bytes concatenated with the report bytes and the decision bytes) to the
two hash-chained registry lines the run has appended so far (``registered`` and
``started``) and to the mechanical promotion verdict. The ``completed`` registry
event carries the same four digests and verdict, so the manifest and the registry
corroborate each other.

:func:`verify_published_run` is the replay check (CI, audits, fresh clones): it
re-reads the registry, the committed artifacts, and the manifest, and proves the
results re-validate, the **decision re-derives mechanically from the committed
results**, the report re-renders byte-for-byte from the results and that decision,
and every digest and the verdict agree across the registry, the manifest, and the
recomputed bundle. Nothing here writes a file or reads a sealed row.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research._json import require_canonical_file_bytes, strict_json_loads
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.development import DEVELOPMENT_PARTITION_RELPATH, FROZEN_M2_DOSSIER_RELPATH
from eth_research.m3c.decision import (
    M3C_DECISION_RELPATH,
    CandidateDecision,
    evaluate_candidate_decision,
)
from eth_research.m3c.registry import (
    EVENT_COMPLETED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3C_REGISTRY_RELPATH,
    read_registry,
)
from eth_research.m3c.results import (
    M3C_EXPERIMENT_FAMILY,
    M3C_EXPERIMENT_ID,
    M3C_LINEAGE_RELPATH,
    M3C_PROTOCOL_RELPATH,
    M3C_REPORT_RELPATH,
    M3C_RESULTS_RELPATH,
    M3CResults,
    render_m3c_report,
)
from eth_research.m3c.validation import (
    canonical_json_bytes,
    require_exact_keys,
    require_hex64,
    require_int,
    require_nonempty_str,
    require_safe_relative_path,
)

M3C_MANIFEST_SCHEMA_VERSION: int = 1
_RUN_SLUG: str = "run-001"
M3C_MANIFEST_RELPATH: str = f"research/m3c/experiments/{_RUN_SLUG}/manifest.json"
_BUDGET_RELPATH: str = "research/m3c/research_budget.json"


class M3CArchiveError(RuntimeError):
    """A published M3C run failed manifest validation or replay."""


def bundle_sha256(results_bytes: bytes, report_bytes: bytes, decision_bytes: bytes) -> str:
    """SHA-256 of results + report + decision bytes, concatenated in that order."""
    return sha256_bytes(results_bytes + report_bytes + decision_bytes)


_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "manifest_schema_version",
        "experiment_id",
        "experiment_family",
        "package_version",
        "results_path",
        "results_sha256",
        "report_path",
        "report_sha256",
        "decision_path",
        "decision_sha256",
        "bundle_sha256",
        "promotion_status",
        "registered_event_sha256",
        "started_event_sha256",
    }
)


@dataclass(frozen=True)
class M3CArtifactManifest:
    """The immutable manifest binding the run's artifacts to its registry lines."""

    manifest_schema_version: int
    experiment_id: str
    experiment_family: str
    package_version: str
    results_path: str
    results_sha256: str
    report_path: str
    report_sha256: str
    decision_path: str
    decision_sha256: str
    bundle_sha256: str
    promotion_status: str
    registered_event_sha256: str
    started_event_sha256: str

    def __post_init__(self) -> None:
        if self.manifest_schema_version != M3C_MANIFEST_SCHEMA_VERSION:
            raise M3CArchiveError("unexpected manifest schema version")
        if self.experiment_family != M3C_EXPERIMENT_FAMILY:
            raise M3CArchiveError("wrong experiment family")
        if not self.experiment_id.startswith(M3C_EXPERIMENT_FAMILY):
            raise M3CArchiveError("experiment_id must belong to the family")
        require_nonempty_str("package_version", self.package_version)
        if self.results_path != M3C_RESULTS_RELPATH:
            raise M3CArchiveError(f"results_path must be {M3C_RESULTS_RELPATH!r}")
        if self.report_path != M3C_REPORT_RELPATH:
            raise M3CArchiveError(f"report_path must be {M3C_REPORT_RELPATH!r}")
        if self.decision_path != M3C_DECISION_RELPATH:
            raise M3CArchiveError(f"decision_path must be {M3C_DECISION_RELPATH!r}")
        require_nonempty_str("promotion_status", self.promotion_status)
        for label in (
            "results_sha256",
            "report_sha256",
            "decision_sha256",
            "bundle_sha256",
            "registered_event_sha256",
            "started_event_sha256",
        ):
            require_hex64(label, getattr(self, label))

    def to_json_bytes(self) -> bytes:
        payload = {
            "manifest_schema_version": self.manifest_schema_version,
            "experiment_id": self.experiment_id,
            "experiment_family": self.experiment_family,
            "package_version": self.package_version,
            "results_path": self.results_path,
            "results_sha256": self.results_sha256,
            "report_path": self.report_path,
            "report_sha256": self.report_sha256,
            "decision_path": self.decision_path,
            "decision_sha256": self.decision_sha256,
            "bundle_sha256": self.bundle_sha256,
            "promotion_status": self.promotion_status,
            "registered_event_sha256": self.registered_event_sha256,
            "started_event_sha256": self.started_event_sha256,
        }
        return canonical_json_bytes(payload)

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> M3CArtifactManifest:
        payload: Any = strict_json_loads(raw)
        if not isinstance(payload, dict):
            raise M3CArchiveError("manifest must be a JSON object")
        require_exact_keys("m3c_manifest", payload, _MANIFEST_KEYS)
        return cls(
            manifest_schema_version=require_int(
                "manifest_schema_version", payload["manifest_schema_version"]
            ),
            experiment_id=require_nonempty_str("experiment_id", payload["experiment_id"]),
            experiment_family=require_nonempty_str(
                "experiment_family", payload["experiment_family"]
            ),
            package_version=require_nonempty_str("package_version", payload["package_version"]),
            results_path=require_safe_relative_path(
                "results_path", payload["results_path"], prefix="research/"
            ),
            results_sha256=require_hex64("results_sha256", payload["results_sha256"]),
            report_path=require_safe_relative_path(
                "report_path", payload["report_path"], prefix="research/"
            ),
            report_sha256=require_hex64("report_sha256", payload["report_sha256"]),
            decision_path=require_safe_relative_path(
                "decision_path", payload["decision_path"], prefix="research/"
            ),
            decision_sha256=require_hex64("decision_sha256", payload["decision_sha256"]),
            bundle_sha256=require_hex64("bundle_sha256", payload["bundle_sha256"]),
            promotion_status=require_nonempty_str("promotion_status", payload["promotion_status"]),
            registered_event_sha256=require_hex64(
                "registered_event_sha256", payload["registered_event_sha256"]
            ),
            started_event_sha256=require_hex64(
                "started_event_sha256", payload["started_event_sha256"]
            ),
        )


def load_artifact_manifest(path: str | Path) -> M3CArtifactManifest:
    """Strictly parse a committed M3C manifest file."""
    raw = require_canonical_file_bytes(Path(path).read_bytes(), "m3c manifest")
    return M3CArtifactManifest.from_json_bytes(raw)


def rederive_committed_decision(
    results: M3CResults, committed: CandidateDecision
) -> CandidateDecision:
    """Re-run the mechanical rule against committed results; require byte-equality.

    The committed decision's ``verification_passed`` (the P6 flag supplied at
    execution) is fed back in, and the decision is required to re-derive
    byte-for-byte — so the committed decision must be exactly what the frozen rule
    produces from the committed results, never a hand-edited outcome.
    """
    rederived = evaluate_candidate_decision(
        results, verification_passed=committed.verification_passed
    )
    if rederived.to_json_bytes() != committed.to_json_bytes():
        raise M3CArchiveError("committed decision does not re-derive from the committed results")
    return rederived


def verify_published_run(repo_root: str | Path) -> tuple[str, ...]:
    """Replay-verify the one published M3C candidate run end-to-end.

    Proves the registry carries ``registered`` → ``started`` → ``completed`` for
    run-001; the committed results re-validate and re-serialize to the recorded
    digest; the committed decision re-derives mechanically from those results; the
    committed report re-renders byte-for-byte from the results and that decision;
    the manifest binds the same four digests, the two chained event hashes, and the
    verdict; and the recomputed bundle and the promotion verdict match the
    ``completed`` event. Returns the ordered passed checks; raises
    :class:`M3CArchiveError` on the first violation.
    """
    root = Path(repo_root)
    checks: list[str] = []

    events = read_registry(root / M3C_REGISTRY_RELPATH)
    run_events = [e for e in events if e.experiment_id == M3C_EXPERIMENT_ID]
    lifecycle = [e.event for e in run_events]
    if lifecycle != [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]:
        raise M3CArchiveError(
            f"run-001 lifecycle is {lifecycle!r}, expected registered/started/completed"
        )
    registered, started, completed = run_events
    checks.append("registry_lifecycle_complete")

    # Re-bind every committed input to the digest the run registered, so a post-run
    # edit to the protocol, lineage, budget, development partition, or frozen dossier
    # is caught here (not left to git history alone). The partition and dossier are
    # additionally re-derived by the offline dataset reconstruction in the replay.
    for label, relpath, recorded in (
        ("protocol", M3C_PROTOCOL_RELPATH, registered.protocol_sha256),
        ("lineage", M3C_LINEAGE_RELPATH, registered.lineage_sha256),
        ("budget", _BUDGET_RELPATH, registered.research_budget_sha256),
        (
            "development partition",
            DEVELOPMENT_PARTITION_RELPATH,
            registered.development_partition_sha256,
        ),
        ("frozen dossier", FROZEN_M2_DOSSIER_RELPATH, registered.frozen_m2_dossier_sha256),
    ):
        if sha256_file(root / relpath) != recorded:
            raise M3CArchiveError(f"committed {label} digest disagrees with the registered event")
    checks.append("committed_inputs_match_registration")

    results_bytes = require_canonical_file_bytes(
        (root / M3C_RESULTS_RELPATH).read_bytes(), "m3c results"
    )
    results = M3CResults.from_json_bytes(results_bytes)
    if results.experiment_id != M3C_EXPERIMENT_ID:
        raise M3CArchiveError("results experiment_id disagrees with run-001")
    if results.to_json_bytes() != results_bytes:
        raise M3CArchiveError("committed results are not byte-canonical for the model")
    checks.append("results_revalidate")

    decision_bytes = require_canonical_file_bytes(
        (root / M3C_DECISION_RELPATH).read_bytes(), "m3c decision"
    )
    committed_decision = CandidateDecision.from_json_bytes(decision_bytes)
    if committed_decision.to_json_bytes() != decision_bytes:
        raise M3CArchiveError("committed decision is not byte-canonical for the model")
    if sha256_bytes(results_bytes) != committed_decision.results_sha256:
        raise M3CArchiveError("decision results_sha256 disagrees with the committed results")
    if committed_decision.protocol_sha256 != results.protocol_sha256:
        raise M3CArchiveError("decision protocol_sha256 disagrees with the committed results")
    decision = rederive_committed_decision(results, committed_decision)
    checks.append("decision_rederives_mechanically")

    report_bytes = (root / M3C_REPORT_RELPATH).read_bytes()
    if render_m3c_report(results, decision).encode("utf-8") != report_bytes:
        raise M3CArchiveError("committed report does not re-render byte-for-byte")
    checks.append("report_rerenders")

    results_sha = sha256_bytes(results_bytes)
    report_sha = sha256_bytes(report_bytes)
    decision_sha = sha256_bytes(decision_bytes)
    if results_sha != completed.results_json_sha256:
        raise M3CArchiveError("committed results digest disagrees with the completed event")
    if report_sha != completed.report_markdown_sha256:
        raise M3CArchiveError("committed report digest disagrees with the completed event")
    if decision_sha != completed.decision_json_sha256:
        raise M3CArchiveError("committed decision digest disagrees with the completed event")
    checks.append("committed_artifact_digests_match_registry")

    bundle = bundle_sha256(results_bytes, report_bytes, decision_bytes)
    if bundle != completed.result_bundle_sha256:
        raise M3CArchiveError("recomputed bundle disagrees with the completed event")
    if completed.promotion_status != decision.outcome:
        raise M3CArchiveError("registry promotion_status disagrees with the mechanical decision")
    checks.append("bundle_and_verdict_match_registry")

    manifest = load_artifact_manifest(root / M3C_MANIFEST_RELPATH)
    if (
        manifest.results_sha256 != results_sha
        or manifest.report_sha256 != report_sha
        or manifest.decision_sha256 != decision_sha
    ):
        raise M3CArchiveError("manifest artifact digests disagree with the committed artifacts")
    if manifest.bundle_sha256 != bundle:
        raise M3CArchiveError("manifest bundle digest disagrees with the recomputed bundle")
    if manifest.promotion_status != decision.outcome:
        raise M3CArchiveError("manifest promotion_status disagrees with the mechanical decision")
    if manifest.registered_event_sha256 != sha256_bytes(registered.to_json_line()[:-1]):
        raise M3CArchiveError("manifest registered_event_sha256 disagrees with the registry line")
    if manifest.started_event_sha256 != sha256_bytes(started.to_json_line()[:-1]):
        raise M3CArchiveError("manifest started_event_sha256 disagrees with the registry line")
    checks.append("manifest_binds_artifacts_and_registry")

    return tuple(checks)
