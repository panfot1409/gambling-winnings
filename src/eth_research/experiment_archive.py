"""Immutable per-experiment artifact archive (Milestone 3A closure).

Every completed M3A experiment gets a directory under
``research/m3a/experiments/<experiment_id>/`` holding its exact published
results JSON, report Markdown, optional return-evidence, and a strict
``artifact_manifest.json``. The archive makes historical bodies **directly
verifiable at HEAD** rather than only recoverable from Git history (closure
defect R6), and a strict, deterministic ``experiment_index.json`` enumerates
every archived experiment.

Every manifest hash is bound to that experiment's registry ``completed`` event,
so CI verifies **every** completed experiment, not only the latest. The
top-level ``development_results.json`` / ``development_report.md`` remain as
compatibility aliases of the most recent completed experiment.

The manifest records whether the bytes were ``originally_present`` in the tree
at publication or ``recovered_from_history`` from a specific commit — the
provenance is stated honestly, never blurred.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.provenance import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
    sha256_bytes,
)
from eth_research.data.validation import require_commit_sha, require_evaluation_id
from eth_research.experiment_registry import ExperimentEvent

ARCHIVE_SCHEMA_VERSION: int = 1
EXPERIMENTS_RELDIR: str = "research/m3a/experiments"
EXPERIMENT_INDEX_RELPATH: str = "research/m3a/experiments/experiment_index.json"

MATERIALIZATION_ORIGINAL: str = "originally_present"
MATERIALIZATION_RECOVERED: str = "recovered_from_history"
_MATERIALIZATIONS: tuple[str, ...] = (MATERIALIZATION_ORIGINAL, MATERIALIZATION_RECOVERED)

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "artifact_schema_version",
        "experiment_id",
        "experiment_family",
        "results_schema_version",
        "materialization",
        "source_commit",
        "results_relpath",
        "report_relpath",
        "return_evidence_relpath",
        "results_sha256",
        "report_sha256",
        "return_evidence_sha256",
        "bundle_sha256",
        "registry_event_position",
        "registry_completed_event_sha256",
    }
)

_INDEX_KEYS: frozenset[str] = frozenset({"archive_schema_version", "entries"})
_ENTRY_KEYS: frozenset[str] = frozenset(
    {
        "experiment_id",
        "experiment_family",
        "manifest_relpath",
        "manifest_sha256",
        "results_sha256",
        "report_sha256",
        "registry_event_position",
    }
)


class ArchiveError(RuntimeError):
    """The experiment archive is invalid, unsafe, or fails to verify."""


def require_safe_experiment_relpath(label: str, value: object) -> str:
    """A canonical repository-relative path strictly under the archive dir.

    Rejects absolute paths, backslashes, empty/``.``/``..`` components, trailing
    whitespace, and anything outside ``research/m3a/experiments/``.
    """
    text = require_nonempty_str(label, value)
    if text != text.strip() or text.startswith("/") or "\\" in text or "\x00" in text:
        raise ValueError(f"{label} must be a clean relative path, got {text!r}")
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"{label} must have no empty or dot components, got {text!r}")
    if any(not _SAFE_COMPONENT.match(part) for part in parts):
        raise ValueError(f"{label} has an unsafe path component, got {text!r}")
    if not text.startswith(EXPERIMENTS_RELDIR + "/"):
        raise ValueError(f"{label} must live under {EXPERIMENTS_RELDIR!r}, got {text!r}")
    return text


def bundle_sha256(results_bytes: bytes, report_bytes: bytes) -> str:
    """SHA-256 of results bytes concatenated with report bytes (the M3A bundle)."""
    return sha256_bytes(results_bytes + report_bytes)


@dataclass(frozen=True)
class ArtifactManifest:
    """The immutable manifest for one archived experiment; fully validated."""

    artifact_schema_version: int
    experiment_id: str
    experiment_family: str
    results_schema_version: int
    materialization: str
    source_commit: str
    results_relpath: str
    report_relpath: str
    return_evidence_relpath: str | None
    results_sha256: str
    report_sha256: str
    return_evidence_sha256: str | None
    bundle_sha256: str
    registry_event_position: int
    registry_completed_event_sha256: str

    def __post_init__(self) -> None:
        version = require_int("artifact_schema_version", self.artifact_schema_version)
        if version != ARCHIVE_SCHEMA_VERSION:
            raise ValueError(f"unsupported artifact schema version {version!r}")
        require_evaluation_id("experiment_id", self.experiment_id)
        require_evaluation_id("experiment_family", self.experiment_family)
        require_int("results_schema_version", self.results_schema_version)
        if require_str("materialization", self.materialization) not in _MATERIALIZATIONS:
            raise ValueError(
                f"materialization must be one of {_MATERIALIZATIONS}, got {self.materialization!r}"
            )
        require_commit_sha("source_commit", self.source_commit)
        require_safe_experiment_relpath("results_relpath", self.results_relpath)
        require_safe_experiment_relpath("report_relpath", self.report_relpath)
        if self.return_evidence_relpath is not None:
            require_safe_experiment_relpath("return_evidence_relpath", self.return_evidence_relpath)
        require_hex64("results_sha256", self.results_sha256)
        require_hex64("report_sha256", self.report_sha256)
        if self.return_evidence_relpath is None:
            if self.return_evidence_sha256 is not None:
                raise ValueError("return_evidence_sha256 must be null without an evidence path")
        else:
            require_hex64("return_evidence_sha256", self.return_evidence_sha256)
        require_hex64("bundle_sha256", self.bundle_sha256)
        position = require_int("registry_event_position", self.registry_event_position)
        if position < 1:
            raise ValueError("registry_event_position must be a 1-based line number")
        require_hex64("registry_completed_event_sha256", self.registry_completed_event_sha256)

    def to_json_bytes(self) -> bytes:
        payload = {
            "artifact_schema_version": self.artifact_schema_version,
            "experiment_id": self.experiment_id,
            "experiment_family": self.experiment_family,
            "results_schema_version": self.results_schema_version,
            "materialization": self.materialization,
            "source_commit": self.source_commit,
            "results_relpath": self.results_relpath,
            "report_relpath": self.report_relpath,
            "return_evidence_relpath": self.return_evidence_relpath,
            "results_sha256": self.results_sha256,
            "report_sha256": self.report_sha256,
            "return_evidence_sha256": self.return_evidence_sha256,
            "bundle_sha256": self.bundle_sha256,
            "registry_event_position": self.registry_event_position,
            "registry_completed_event_sha256": self.registry_completed_event_sha256,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> ArtifactManifest:
        payload = _strict_object(raw, _MANIFEST_KEYS, "artifact manifest")
        return cls(
            artifact_schema_version=payload["artifact_schema_version"],
            experiment_id=payload["experiment_id"],
            experiment_family=payload["experiment_family"],
            results_schema_version=payload["results_schema_version"],
            materialization=payload["materialization"],
            source_commit=payload["source_commit"],
            results_relpath=payload["results_relpath"],
            report_relpath=payload["report_relpath"],
            return_evidence_relpath=payload["return_evidence_relpath"],
            results_sha256=payload["results_sha256"],
            report_sha256=payload["report_sha256"],
            return_evidence_sha256=payload["return_evidence_sha256"],
            bundle_sha256=payload["bundle_sha256"],
            registry_event_position=payload["registry_event_position"],
            registry_completed_event_sha256=payload["registry_completed_event_sha256"],
        )


@dataclass(frozen=True)
class ExperimentIndexEntry:
    """One row of the experiment index."""

    experiment_id: str
    experiment_family: str
    manifest_relpath: str
    manifest_sha256: str
    results_sha256: str
    report_sha256: str
    registry_event_position: int

    def __post_init__(self) -> None:
        require_evaluation_id("experiment_id", self.experiment_id)
        require_evaluation_id("experiment_family", self.experiment_family)
        require_safe_experiment_relpath("manifest_relpath", self.manifest_relpath)
        require_hex64("manifest_sha256", self.manifest_sha256)
        require_hex64("results_sha256", self.results_sha256)
        require_hex64("report_sha256", self.report_sha256)
        if require_int("registry_event_position", self.registry_event_position) < 1:
            raise ValueError("registry_event_position must be a 1-based line number")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "experiment_family": self.experiment_family,
            "manifest_relpath": self.manifest_relpath,
            "manifest_sha256": self.manifest_sha256,
            "results_sha256": self.results_sha256,
            "report_sha256": self.report_sha256,
            "registry_event_position": self.registry_event_position,
        }


@dataclass(frozen=True)
class ExperimentIndex:
    """The strict, deterministic index over every archived experiment."""

    archive_schema_version: int
    entries: tuple[ExperimentIndexEntry, ...]

    def __post_init__(self) -> None:
        version = require_int("archive_schema_version", self.archive_schema_version)
        if version != ARCHIVE_SCHEMA_VERSION:
            raise ValueError(f"unsupported archive schema version {version!r}")
        seen: set[str] = set()
        positions: list[int] = []
        for entry in self.entries:
            if entry.experiment_id in seen:
                raise ValueError(f"duplicate experiment id in index: {entry.experiment_id!r}")
            seen.add(entry.experiment_id)
            positions.append(entry.registry_event_position)
        if positions != sorted(positions):
            raise ValueError("index entries must be ordered by registry event position")

    def to_json_bytes(self) -> bytes:
        payload = {
            "archive_schema_version": self.archive_schema_version,
            "entries": [entry.to_json_dict() for entry in self.entries],
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> ExperimentIndex:
        payload = _strict_object(raw, _INDEX_KEYS, "experiment index")
        entries_raw = payload["entries"]
        if not isinstance(entries_raw, list):
            raise ValueError("experiment index entries must be a list")
        entries: list[ExperimentIndexEntry] = []
        for item in entries_raw:
            if not isinstance(item, dict) or set(item) != _ENTRY_KEYS:
                raise ValueError("experiment index entry keys do not match schema")
            entries.append(
                ExperimentIndexEntry(
                    experiment_id=item["experiment_id"],
                    experiment_family=item["experiment_family"],
                    manifest_relpath=item["manifest_relpath"],
                    manifest_sha256=item["manifest_sha256"],
                    results_sha256=item["results_sha256"],
                    report_sha256=item["report_sha256"],
                    registry_event_position=item["registry_event_position"],
                )
            )
        return cls(archive_schema_version=payload["archive_schema_version"], entries=tuple(entries))


def _strict_object(raw: bytes, keys: frozenset[str], label: str) -> dict[str, Any]:
    try:
        payload: Any = strict_json_loads(raw)
    except StrictJSONError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object")
    present = set(payload)
    if present != keys:
        unknown = sorted(present - keys)
        missing = sorted(keys - present)
        raise ValueError(f"{label} keys do not match schema: unknown={unknown}, missing={missing}")
    return payload


def load_artifact_manifest(path: str | Path) -> ArtifactManifest:
    try:
        return ArtifactManifest.from_json_bytes(Path(path).read_bytes())
    except ValueError as exc:
        raise ArchiveError(f"invalid artifact manifest {Path(path).name!r}: {exc}") from exc


def load_experiment_index(path: str | Path) -> ExperimentIndex:
    try:
        return ExperimentIndex.from_json_bytes(Path(path).read_bytes())
    except ValueError as exc:
        raise ArchiveError(f"invalid experiment index: {exc}") from exc


def _read_under_root(repo_root: Path, relpath: str) -> bytes:
    """Read a repo-relative archive file, refusing symlinks and escapes."""
    require_safe_experiment_relpath("relpath", relpath)
    target = repo_root / relpath
    if target.is_symlink():
        raise ArchiveError(f"archive artifact is a symlink: {relpath}")
    resolved = target.resolve()
    if repo_root.resolve() not in resolved.parents:
        raise ArchiveError(f"archive artifact escapes the repository: {relpath}")
    if not target.is_file():
        raise ArchiveError(f"archive artifact missing: {relpath}")
    return target.read_bytes()


def verify_archived_experiment(
    repo_root: str | Path, manifest: ArtifactManifest, completed_event: ExperimentEvent
) -> None:
    """Verify one archived experiment's bytes and its binding to the registry.

    The archived results/report/(evidence) must hash to the manifest, the
    manifest hashes must equal the experiment's completed-event hashes, and the
    completed event's exact line bytes must hash to the recorded position hash.
    """
    root = Path(repo_root)
    if manifest.experiment_id != completed_event.experiment_id:
        raise ArchiveError(
            f"manifest experiment id {manifest.experiment_id!r} != completed event "
            f"{completed_event.experiment_id!r}"
        )
    results_bytes = _read_under_root(root, manifest.results_relpath)
    report_bytes = _read_under_root(root, manifest.report_relpath)
    if sha256_bytes(results_bytes) != manifest.results_sha256:
        raise ArchiveError(f"{manifest.experiment_id}: archived results hash mismatch")
    if sha256_bytes(report_bytes) != manifest.report_sha256:
        raise ArchiveError(f"{manifest.experiment_id}: archived report hash mismatch")
    if bundle_sha256(results_bytes, report_bytes) != manifest.bundle_sha256:
        raise ArchiveError(f"{manifest.experiment_id}: archived bundle hash mismatch")
    if manifest.return_evidence_relpath is not None:
        evidence_bytes = _read_under_root(root, manifest.return_evidence_relpath)
        if sha256_bytes(evidence_bytes) != manifest.return_evidence_sha256:
            raise ArchiveError(f"{manifest.experiment_id}: archived return-evidence hash mismatch")
    # Bind to the completed event.
    if manifest.results_sha256 != completed_event.results_json_sha256:
        raise ArchiveError(f"{manifest.experiment_id}: manifest results hash != completed event")
    if manifest.report_sha256 != completed_event.report_markdown_sha256:
        raise ArchiveError(f"{manifest.experiment_id}: manifest report hash != completed event")
    if manifest.bundle_sha256 != completed_event.result_bundle_sha256:
        raise ArchiveError(f"{manifest.experiment_id}: manifest bundle hash != completed event")
    if sha256_bytes(completed_event.to_json_line()) != manifest.registry_completed_event_sha256:
        raise ArchiveError(f"{manifest.experiment_id}: completed-event line hash mismatch")


def verify_experiment_archive(repo_root: str | Path) -> tuple[str, ...]:
    """Verify the whole archive against the registry; return the archived ids.

    Every completed registry event must have exactly one archived experiment
    whose manifest and bytes verify, the index must list exactly those
    experiments (by manifest hash), and no extra archived experiment may exist.
    """
    from eth_research.experiment_registry import EXPERIMENT_REGISTRY_RELPATH, read_registry

    root = Path(repo_root)
    events = read_registry(root / EXPERIMENT_REGISTRY_RELPATH)
    completed = {
        e.experiment_id: (position + 1, e)
        for position, e in enumerate(events)
        if e.event == "completed"
    }
    index = load_experiment_index(root / EXPERIMENT_INDEX_RELPATH)
    index_ids = [entry.experiment_id for entry in index.entries]
    if index_ids != sorted(completed, key=lambda cid: completed[cid][0]):
        raise ArchiveError(
            f"experiment index {index_ids} does not match completed registry events "
            f"{sorted(completed, key=lambda cid: completed[cid][0])}"
        )
    for entry in index.entries:
        position, event = completed[entry.experiment_id]
        if entry.registry_event_position != position:
            raise ArchiveError(
                f"{entry.experiment_id}: index position {entry.registry_event_position} "
                f"disagrees with registry position {position}"
            )
        manifest_bytes = _read_under_root(root, entry.manifest_relpath)
        if sha256_bytes(manifest_bytes) != entry.manifest_sha256:
            raise ArchiveError(f"{entry.experiment_id}: index manifest hash mismatch")
        manifest = ArtifactManifest.from_json_bytes(manifest_bytes)
        if manifest.registry_event_position != position:
            raise ArchiveError(f"{entry.experiment_id}: manifest position != registry position")
        verify_archived_experiment(root, manifest, event)
    return tuple(index_ids)
