"""Genuine per-run immutable archive v2 for run-001 (closure R2).

The v1 manifest (``archive.py``) binds digests but points at the *mutable*
singleton artifacts (``research/m3b/fractional_results.json`` and the report):
the "archive" holds no independent copy, so it is only a manifest, not a genuine
immutable body (defect R2). This module adds one — additively, without touching a
single committed byte of run-001.

Under ``research/m3b/experiments/run-001/immutable-v2/`` it places byte-identical
copies of the results JSON and the report Markdown, plus ``archive_v2.json``, a
self-contained record binding each copy's digest to the singleton it copies, to
the v1 manifest, to the recomputed bundle, and to the registry ``completed``
event. :func:`verify_archive_v2` re-proves the whole chain: each archived copy is
present and byte-identical to its singleton and to the manifest/registry digest,
and ``archive_v2.json`` re-derives byte-for-byte from the live repository. So the
archive can never silently diverge from — nor be divorced from — the published run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eth_research._json import require_canonical_file_bytes, strict_json_loads
from eth_research.data.provenance import sha256_bytes
from eth_research.fractional.archive import (
    FRACTIONAL_MANIFEST_RELPATH,
    bundle_sha256,
    load_artifact_manifest,
)
from eth_research.fractional.protocol import EXPERIMENT_FAMILY, RUN_001_EXPERIMENT_ID
from eth_research.fractional.registry import (
    EVENT_COMPLETED,
    M3B_REGISTRY_RELPATH,
    read_registry,
)
from eth_research.fractional.results import FRACTIONAL_REPORT_RELPATH, FRACTIONAL_RESULTS_RELPATH
from eth_research.publication import Artifact, publish_batch

_RUN_SLUG: str = "run-001"
FRACTIONAL_ARCHIVE_V2_DIR: str = f"research/m3b/experiments/{_RUN_SLUG}/immutable-v2"
FRACTIONAL_ARCHIVE_V2_RELPATH: str = f"{FRACTIONAL_ARCHIVE_V2_DIR}/archive_v2.json"
_ARCHIVED_RESULTS_RELPATH: str = f"{FRACTIONAL_ARCHIVE_V2_DIR}/fractional_results.json"
_ARCHIVED_REPORT_RELPATH: str = f"{FRACTIONAL_ARCHIVE_V2_DIR}/fractional_report.md"
ARCHIVE_V2_SCHEMA_VERSION: int = 1

#: Every committed file this archive contributes, for hygiene allowlisting.
FRACTIONAL_ARCHIVE_V2_TRACKED: tuple[str, ...] = (
    _ARCHIVED_RESULTS_RELPATH,
    _ARCHIVED_REPORT_RELPATH,
    FRACTIONAL_ARCHIVE_V2_RELPATH,
)


class ArchiveV2Error(RuntimeError):
    """The run-001 immutable archive v2 is missing, incomplete, or inconsistent."""


def _completed_run001_event(root: Path) -> Any:
    events = read_registry(root / M3B_REGISTRY_RELPATH)
    run_events = [e for e in events if e.experiment_id == RUN_001_EXPERIMENT_ID]
    if [e.event for e in run_events][-1:] != [EVENT_COMPLETED]:
        raise ArchiveV2Error("run-001 has no terminal 'completed' registry event")
    return run_events[-1]


def _completed_event_sha256(root: Path) -> str:
    return sha256_bytes(_completed_run001_event(root).to_json_line()[:-1])


def build_archive_v2(repo_root: str | Path) -> dict[str, Any]:
    """Derive the ``archive_v2.json`` record from the live singletons + manifest.

    Read-only. Binds each artifact's digest to the v1 manifest and to the
    recomputed bundle; raises :class:`ArchiveV2Error` on any disagreement.
    """
    root = Path(repo_root)
    manifest_path = root / FRACTIONAL_MANIFEST_RELPATH
    manifest = load_artifact_manifest(manifest_path)
    results_bytes = require_canonical_file_bytes(
        (root / FRACTIONAL_RESULTS_RELPATH).read_bytes(), "fractional results"
    )
    report_bytes = (root / FRACTIONAL_REPORT_RELPATH).read_bytes()
    results_sha = sha256_bytes(results_bytes)
    report_sha = sha256_bytes(report_bytes)
    if results_sha != manifest.results_sha256 or report_sha != manifest.report_sha256:
        raise ArchiveV2Error("singleton digests disagree with the v1 manifest")
    bundle = bundle_sha256(results_bytes, report_bytes)
    if bundle != manifest.bundle_sha256:
        raise ArchiveV2Error("recomputed bundle disagrees with the v1 manifest")
    return {
        "archive_v2_schema_version": ARCHIVE_V2_SCHEMA_VERSION,
        "experiment_id": RUN_001_EXPERIMENT_ID,
        "experiment_family": EXPERIMENT_FAMILY,
        "manifest_path": FRACTIONAL_MANIFEST_RELPATH,
        "manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
        "bundle_sha256": bundle,
        "completed_event_sha256": _completed_event_sha256(root),
        "artifacts": [
            {
                "role": "results",
                "source_path": FRACTIONAL_RESULTS_RELPATH,
                "archive_path": _ARCHIVED_RESULTS_RELPATH,
                "sha256": results_sha,
            },
            {
                "role": "report",
                "source_path": FRACTIONAL_REPORT_RELPATH,
                "archive_path": _ARCHIVED_REPORT_RELPATH,
                "sha256": report_sha,
            },
        ],
    }


def render_archive_v2(repo_root: str | Path) -> bytes:
    """Canonical JSON bytes of the derived ``archive_v2.json`` record."""
    payload = build_archive_v2(repo_root)
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def materialize_archive_v2(repo_root: str | Path) -> tuple[str, ...]:
    """Publish the immutable copies + ``archive_v2.json`` as one durable batch.

    Idempotent only in the sense that publication refuses to overwrite an
    existing immutable file; call it once to create the archive. Returns the
    verifier's passed checks.
    """
    root = Path(repo_root)
    results_bytes = (root / FRACTIONAL_RESULTS_RELPATH).read_bytes()
    report_bytes = (root / FRACTIONAL_REPORT_RELPATH).read_bytes()
    archive_bytes = render_archive_v2(root)
    artifacts = [
        Artifact(_ARCHIVED_RESULTS_RELPATH, results_bytes, immutable=True),
        Artifact(_ARCHIVED_REPORT_RELPATH, report_bytes, immutable=True),
        Artifact(
            FRACTIONAL_ARCHIVE_V2_RELPATH,
            archive_bytes,
            immutable=True,
            is_completeness_marker=True,
        ),
    ]
    publish_batch(root, artifacts)
    return verify_archive_v2(root)


def verify_archive_v2(repo_root: str | Path) -> tuple[str, ...]:
    """Verify the run-001 immutable archive v2 end-to-end. Read-only.

    Proves ``archive_v2.json`` is canonical and re-derives byte-for-byte; every
    archived copy is present as a regular file, byte-identical to its committed
    singleton, and matches the recorded digest; and the record still binds the
    live v1 manifest and registry. Raises :class:`ArchiveV2Error` on the first
    violation.
    """
    root = Path(repo_root)
    record_path = root / FRACTIONAL_ARCHIVE_V2_RELPATH
    if not record_path.exists() or record_path.is_symlink() or not record_path.is_file():
        raise ArchiveV2Error(f"{FRACTIONAL_ARCHIVE_V2_RELPATH} is missing or not a regular file")
    committed = record_path.read_bytes()
    try:
        require_canonical_file_bytes(committed, "archive v2")
        payload: Any = strict_json_loads(committed)
    except ValueError as exc:
        raise ArchiveV2Error(f"archive_v2.json is not canonical JSON: {exc}") from exc
    if committed != render_archive_v2(root):
        raise ArchiveV2Error("archive_v2.json does not re-derive from the live singletons/manifest")

    # The certified digests live in the hash-chained registry 'completed' event,
    # which is immutable and cannot be forged without breaking the chain. Anchor
    # the archived copies to THOSE (not only to the mutable manifest), so a
    # coordinated singleton+copy+manifest+record tamper is still caught here.
    completed = _completed_run001_event(root)
    if payload["completed_event_sha256"] != sha256_bytes(completed.to_json_line()[:-1]):
        raise ArchiveV2Error("archive_v2 completed_event_sha256 disagrees with the registry line")
    if payload["bundle_sha256"] != completed.result_bundle_sha256:
        raise ArchiveV2Error("archive_v2 bundle disagrees with the registry 'completed' event")
    certified = {
        "results": completed.results_json_sha256,
        "report": completed.report_markdown_sha256,
    }

    for artifact in payload["artifacts"]:
        source = root / artifact["source_path"]
        archived = root / artifact["archive_path"]
        if archived.is_symlink() or not archived.is_file():
            raise ArchiveV2Error(f"archived copy {artifact['archive_path']} is missing")
        archived_bytes = archived.read_bytes()
        if archived_bytes != source.read_bytes():
            raise ArchiveV2Error(
                f"archived copy {artifact['archive_path']} is not byte-identical to its singleton"
            )
        digest = sha256_bytes(archived_bytes)
        if digest != artifact["sha256"]:
            raise ArchiveV2Error(f"archived copy {artifact['archive_path']} digest disagrees")
        if digest != certified.get(artifact["role"]):
            raise ArchiveV2Error(
                f"archived {artifact['role']} digest disagrees with the registry 'completed' event"
            )
    return (
        "archive_v2_canonical",
        "archive_v2_rederives",
        "archived_copies_byte_identical_to_singletons",
        "archived_copies_bind_manifest_and_registry",
    )
