"""Immutable artifact manifest + replay verifier for the M3B fractional run.

Each published fractional experiment writes three immutable files: the strict
results JSON, the deterministic Markdown report, and this manifest, which binds
their exact digests and the ``bundle_sha256`` (the SHA-256 of the results bytes
concatenated with the report bytes) to the two hash-chained registry lines the
run has appended so far (``registered`` and ``started``). The ``completed``
registry event carries the same three digests, so the manifest and the registry
corroborate each other.

:func:`verify_published_run` is the replay check (CI, audits, fresh clones): it
re-reads the registry, the committed artifacts, and the manifest, and proves the
results re-validate, the report re-renders byte-for-byte, and every digest agrees
across the registry, the manifest, and the recomputed bundle. Nothing here writes
a file or reads a sealed row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research._json import require_canonical_file_bytes, strict_json_loads
from eth_research.data.provenance import (
    require_hex64,
    require_int,
    require_nonempty_str,
    sha256_bytes,
)
from eth_research.fractional.protocol import EXPERIMENT_FAMILY, RUN_001_EXPERIMENT_ID
from eth_research.fractional.registry import (
    EVENT_COMPLETED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3B_REGISTRY_RELPATH,
    read_registry,
)
from eth_research.fractional.results import (
    FRACTIONAL_REPORT_RELPATH,
    FRACTIONAL_RESULTS_RELPATH,
    FractionalResults,
    render_fractional_report,
)

FRACTIONAL_MANIFEST_SCHEMA_VERSION: int = 1
_RUN_SLUG: str = "run-001"
FRACTIONAL_MANIFEST_RELPATH: str = f"research/m3b/experiments/{_RUN_SLUG}/manifest.json"


class ArchiveError(RuntimeError):
    """A published fractional run failed manifest validation or replay."""


def bundle_sha256(results_bytes: bytes, report_bytes: bytes) -> str:
    """SHA-256 of the results bytes concatenated with the report bytes."""
    return sha256_bytes(results_bytes + report_bytes)


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
        "bundle_sha256",
        "registered_event_sha256",
        "started_event_sha256",
    }
)


@dataclass(frozen=True)
class FractionalArtifactManifest:
    """The immutable manifest binding the run's artifacts to its registry lines."""

    manifest_schema_version: int
    experiment_id: str
    experiment_family: str
    package_version: str
    results_path: str
    results_sha256: str
    report_path: str
    report_sha256: str
    bundle_sha256: str
    registered_event_sha256: str
    started_event_sha256: str

    def __post_init__(self) -> None:
        if self.manifest_schema_version != FRACTIONAL_MANIFEST_SCHEMA_VERSION:
            raise ArchiveError("unexpected manifest schema version")
        if self.experiment_family != EXPERIMENT_FAMILY:
            raise ArchiveError("wrong experiment family")
        if not self.experiment_id.startswith(EXPERIMENT_FAMILY):
            raise ArchiveError("experiment_id must belong to the family")
        require_nonempty_str("package_version", self.package_version)
        if self.results_path != FRACTIONAL_RESULTS_RELPATH:
            raise ArchiveError(f"results_path must be {FRACTIONAL_RESULTS_RELPATH!r}")
        if self.report_path != FRACTIONAL_REPORT_RELPATH:
            raise ArchiveError(f"report_path must be {FRACTIONAL_REPORT_RELPATH!r}")
        for label in (
            "results_sha256",
            "report_sha256",
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
            "bundle_sha256": self.bundle_sha256,
            "registered_event_sha256": self.registered_event_sha256,
            "started_event_sha256": self.started_event_sha256,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> FractionalArtifactManifest:
        payload: Any = strict_json_loads(raw)
        if not isinstance(payload, dict) or set(payload) != _MANIFEST_KEYS:
            raise ArchiveError("manifest keys do not match the schema")
        return cls(
            manifest_schema_version=require_int(
                "manifest_schema_version", payload["manifest_schema_version"]
            ),
            experiment_id=require_nonempty_str("experiment_id", payload["experiment_id"]),
            experiment_family=require_nonempty_str(
                "experiment_family", payload["experiment_family"]
            ),
            package_version=require_nonempty_str("package_version", payload["package_version"]),
            results_path=require_nonempty_str("results_path", payload["results_path"]),
            results_sha256=str(payload["results_sha256"]),
            report_path=require_nonempty_str("report_path", payload["report_path"]),
            report_sha256=str(payload["report_sha256"]),
            bundle_sha256=str(payload["bundle_sha256"]),
            registered_event_sha256=str(payload["registered_event_sha256"]),
            started_event_sha256=str(payload["started_event_sha256"]),
        )


def load_artifact_manifest(path: str | Path) -> FractionalArtifactManifest:
    """Strictly parse a committed fractional manifest file."""
    raw = require_canonical_file_bytes(Path(path).read_bytes(), "fractional manifest")
    return FractionalArtifactManifest.from_json_bytes(raw)


def verify_published_run(repo_root: str | Path) -> tuple[str, ...]:
    """Replay-verify the one published fractional run end-to-end.

    Proves the registry carries ``registered`` → ``started`` → ``completed`` for
    run-001; the committed results re-validate and re-serialize to the recorded
    digest; the committed report re-renders byte-for-byte; the manifest binds the
    same digests and the two chained event hashes; and the recomputed bundle
    matches both the manifest and the ``completed`` event. Returns the ordered
    list of passed checks; raises :class:`ArchiveError` on the first violation.
    """
    root = Path(repo_root)
    checks: list[str] = []

    events = read_registry(root / M3B_REGISTRY_RELPATH)
    run_events = [e for e in events if e.experiment_id == RUN_001_EXPERIMENT_ID]
    lifecycle = [e.event for e in run_events]
    if lifecycle != [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]:
        raise ArchiveError(
            f"run-001 lifecycle is {lifecycle!r}, expected registered/started/completed"
        )
    registered, started, completed = run_events
    checks.append("registry_lifecycle_complete")

    results_bytes = require_canonical_file_bytes(
        (root / FRACTIONAL_RESULTS_RELPATH).read_bytes(), "fractional results"
    )
    report_bytes = (root / FRACTIONAL_REPORT_RELPATH).read_bytes()
    results_sha = sha256_bytes(results_bytes)
    report_sha = sha256_bytes(report_bytes)
    if results_sha != completed.results_json_sha256:
        raise ArchiveError("committed results digest disagrees with the completed event")
    if report_sha != completed.report_markdown_sha256:
        raise ArchiveError("committed report digest disagrees with the completed event")
    checks.append("committed_artifact_digests_match_registry")

    bundle = bundle_sha256(results_bytes, report_bytes)
    if bundle != completed.result_bundle_sha256:
        raise ArchiveError("recomputed bundle disagrees with the completed event")
    checks.append("bundle_matches_registry")

    results = FractionalResults.from_json_bytes(results_bytes)
    if results.experiment_id != RUN_001_EXPERIMENT_ID:
        raise ArchiveError("results experiment_id disagrees with run-001")
    if results.to_json_bytes() != results_bytes:
        raise ArchiveError("committed results are not byte-canonical for the model")
    checks.append("results_revalidate")

    if render_fractional_report(results).encode("utf-8") != report_bytes:
        raise ArchiveError("committed report does not re-render byte-for-byte from the results")
    checks.append("report_rerenders")

    manifest = load_artifact_manifest(root / FRACTIONAL_MANIFEST_RELPATH)
    if manifest.results_sha256 != results_sha or manifest.report_sha256 != report_sha:
        raise ArchiveError("manifest artifact digests disagree with the committed artifacts")
    if manifest.bundle_sha256 != bundle:
        raise ArchiveError("manifest bundle digest disagrees with the recomputed bundle")
    if manifest.registered_event_sha256 != sha256_bytes(registered.to_json_line()[:-1]):
        raise ArchiveError("manifest registered_event_sha256 disagrees with the registry line")
    if manifest.started_event_sha256 != sha256_bytes(started.to_json_line()[:-1]):
        raise ArchiveError("manifest started_event_sha256 disagrees with the registry line")
    checks.append("manifest_binds_artifacts_and_registry")

    return tuple(checks)
