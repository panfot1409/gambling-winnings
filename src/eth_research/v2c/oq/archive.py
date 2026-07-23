"""V2C section 21: the immutable operational-qualification archive.

Assembles the qualification evidence into three immutable artifacts and publishes them as one
rollback-safe transaction (via :mod:`eth_research.publication`):

* ``oq_result.json`` -- the canonical operational result (screened free of financial-performance
  vocabulary);
* ``oq_report.md`` -- the human-readable report (also screened); and
* ``oq_archive_manifest.json`` -- the completeness marker binding both by hash, plus the semantic
  evidence digest.

The archive lives under ``governance/v2c/qualifications/<run-id>/`` -- **not** under the frozen
``research``/``release`` roots. The V2C evidence is governed by the OQ registry and the deep archive
verifier, so it is deliberately kept out of the V2A-V2B immutable freeze table (whose exhaustive
enumeration would otherwise force a regeneration of that accepted, immutable stack). The build binds
the five terminal hashes the registry's ``completed`` event certifies (result, report, evidence,
archive-manifest, and an aggregate result-bundle), so publication, completion, and the independent
oracle all measure against one set of digests. It computes no market performance.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.publication import Artifact, publish_batch
from eth_research.v2.strict import canonical_json_bytes, canonical_sha256, sha256_bytes
from eth_research.v2c.oq.registry import QualificationIdentity
from eth_research.v2c.oq.result import (
    build_oq_report,
    build_oq_result,
    render_oq_result_bytes,
    scan_for_forbidden_vocabulary,
)
from eth_research.v2c.oq.run import QualificationOutcome

OQ_QUALIFICATION_RUN_ID: str = "v2c_offline_operational_qualification_run_001"
OQ_ARCHIVE_DIR: str = f"governance/v2c/qualifications/{OQ_QUALIFICATION_RUN_ID}"
OQ_ARCHIVE_MANIFEST_SCHEMA_VERSION: int = 1

OQ_ARCHIVE_RESULT_RELNAME: str = "oq_result.json"
OQ_ARCHIVE_REPORT_RELNAME: str = "oq_report.md"
OQ_ARCHIVE_MANIFEST_RELNAME: str = "oq_archive_manifest.json"


def archive_relpath(relname: str) -> str:
    """The repo-relative path of one archive artifact under the run directory."""
    return f"{OQ_ARCHIVE_DIR}/{relname}"


@dataclass(frozen=True, slots=True)
class OQArchive:
    """The assembled, immutable qualification archive: bytes + the five terminal digests."""

    qualification_id: str
    verdict: str
    result_bytes: bytes
    report_bytes: bytes
    manifest_bytes: bytes
    result_sha256: str
    report_sha256: str
    evidence_sha256: str
    archive_manifest_sha256: str
    result_bundle_sha256: str


def build_oq_archive(
    outcome: QualificationOutcome, *, identity: QualificationIdentity
) -> OQArchive:
    """Assemble the immutable archive from a run outcome (screened free of forbidden vocabulary)."""
    result = build_oq_result(outcome, identity=identity)
    result_bytes = render_oq_result_bytes(result)
    report_bytes = build_oq_report(result).encode("utf-8")
    result_sha256 = sha256_bytes(result_bytes)
    report_sha256 = sha256_bytes(report_bytes)
    evidence_sha256 = str(result["result_digest"])  # the semantic evidence digest

    manifest_body: dict[str, Any] = {
        "schema_version": OQ_ARCHIVE_MANIFEST_SCHEMA_VERSION,
        "artifact_id": "v2c_oq_archive_manifest",
        "qualification_id": identity.qualification_id,
        "methodology_id": identity.methodology_id,
        "package_version": identity.package_version,
        "verdict": str(result["verdict"]),
        "artifacts": {
            OQ_ARCHIVE_RESULT_RELNAME: result_sha256,
            OQ_ARCHIVE_REPORT_RELNAME: report_sha256,
        },
        "evidence_sha256": evidence_sha256,
    }
    manifest_body["manifest_digest"] = canonical_sha256(manifest_body)
    scan_for_forbidden_vocabulary("oq_archive_manifest", manifest_body)
    manifest_bytes = canonical_json_bytes(manifest_body)
    archive_manifest_sha256 = sha256_bytes(manifest_bytes)

    # The aggregate bundle fingerprint over the four content/marker digests (non-circular: it is not
    # stored in the manifest, only in the registry's completed event).
    result_bundle_sha256 = canonical_sha256(
        {
            "result_sha256": result_sha256,
            "report_sha256": report_sha256,
            "evidence_sha256": evidence_sha256,
            "archive_manifest_sha256": archive_manifest_sha256,
        }
    )
    return OQArchive(
        qualification_id=identity.qualification_id,
        verdict=str(result["verdict"]),
        result_bytes=result_bytes,
        report_bytes=report_bytes,
        manifest_bytes=manifest_bytes,
        result_sha256=result_sha256,
        report_sha256=report_sha256,
        evidence_sha256=evidence_sha256,
        archive_manifest_sha256=archive_manifest_sha256,
        result_bundle_sha256=result_bundle_sha256,
    )


def archive_artifacts(archive: OQArchive) -> list[Artifact]:
    """The publication batch for an archive: result + report + the manifest completeness marker."""
    return [
        Artifact(archive_relpath(OQ_ARCHIVE_RESULT_RELNAME), archive.result_bytes, immutable=True),
        Artifact(archive_relpath(OQ_ARCHIVE_REPORT_RELNAME), archive.report_bytes, immutable=True),
        Artifact(
            archive_relpath(OQ_ARCHIVE_MANIFEST_RELNAME),
            archive.manifest_bytes,
            immutable=True,
            is_completeness_marker=True,
        ),
    ]


def archive_artifact_digests(archive: OQArchive) -> dict[str, str]:
    """The published artifact relpaths mapped to their byte SHA-256 (for the completion intent)."""
    return {
        archive_relpath(OQ_ARCHIVE_RESULT_RELNAME): archive.result_sha256,
        archive_relpath(OQ_ARCHIVE_REPORT_RELNAME): archive.report_sha256,
        archive_relpath(OQ_ARCHIVE_MANIFEST_RELNAME): archive.archive_manifest_sha256,
    }


def publish_oq_archive(repo_root: str | Path, archive: OQArchive) -> None:
    """Publish the archive as one durable, rollback-safe transaction (immutable per-run paths)."""
    publish_batch(repo_root, archive_artifacts(archive))


__all__ = [
    "OQ_ARCHIVE_DIR",
    "OQ_ARCHIVE_MANIFEST_RELNAME",
    "OQ_ARCHIVE_REPORT_RELNAME",
    "OQ_ARCHIVE_RESULT_RELNAME",
    "OQ_QUALIFICATION_RUN_ID",
    "OQArchive",
    "archive_artifact_digests",
    "archive_artifacts",
    "archive_relpath",
    "build_oq_archive",
    "publish_oq_archive",
]
