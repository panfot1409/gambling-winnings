"""Hash-chained artifact annotation registry for the fractional closure.

The closure adds several *additive* provenance artifacts beside the frozen run —
the immutable archive v2, the execution-trace commitments, the legacy completion
audit, and (later) the report erratum. This append-only, hash-chained JSONL log is
the single tamper-evident index of them: each line names one artifact, pins its
SHA-256, and chains onto the exact bytes of the line before it, so the whole file
is a single verifiable chain from line 1 (the first line chains onto the SHA-256
of zero bytes).

It never modifies or supersedes a frozen run-001 byte; it only records that an
additive artifact exists with a given digest. :func:`verify_artifact_annotations`
re-reads the chain and requires every annotated target to be present on disk with
the recorded digest, so a silently mutated (or vanished) closure artifact is
detected. There is no repair or rewrite path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.fractional.protocol import RUN_001_EXPERIMENT_ID
from eth_research.fractional.validation import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_safe_relative_path,
)

ARTIFACT_ANNOTATIONS_RELPATH: str = "research/m3b/artifact_annotations.jsonl"
ARTIFACT_ANNOTATION_SCHEMA_VERSION: int = 1

# SHA-256 of zero bytes: the chain root the first line points at.
EMPTY_CONTENT_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

ANNOTATION_TYPES: frozenset[str] = frozenset(
    {
        "immutable_archive_v2",
        "execution_trace_commitments",
        "legacy_completion_audit",
        "report_erratum",
    }
)

_ANNOTATION_KEYS: frozenset[str] = frozenset(
    {
        "annotation_schema_version",
        "annotation_type",
        "experiment_id",
        "target_relpath",
        "target_sha256",
        "note",
        "previous_annotation_sha256",
    }
)
_M3B_PREFIX: str = "research/m3b/"


class ArtifactAnnotationError(RuntimeError):
    """The artifact annotation registry is malformed or inconsistent with disk."""


@dataclass(frozen=True)
class ArtifactAnnotation:
    """One hash-chained annotation binding an additive artifact to its digest."""

    annotation_schema_version: int
    annotation_type: str
    experiment_id: str
    target_relpath: str
    target_sha256: str
    note: str
    previous_annotation_sha256: str

    def __post_init__(self) -> None:
        version = require_int("annotation_schema_version", self.annotation_schema_version)
        if version != ARTIFACT_ANNOTATION_SCHEMA_VERSION:
            raise ArtifactAnnotationError(f"unsupported annotation schema version {version!r}")
        if self.annotation_type not in ANNOTATION_TYPES:
            raise ArtifactAnnotationError(f"unknown annotation_type {self.annotation_type!r}")
        require_nonempty_str("experiment_id", self.experiment_id)
        require_safe_relative_path("target_relpath", self.target_relpath, prefix=_M3B_PREFIX)
        require_hex64("target_sha256", self.target_sha256)
        require_nonempty_str("note", self.note)
        require_hex64("previous_annotation_sha256", self.previous_annotation_sha256)

    def to_json_line(self) -> bytes:
        payload = {
            "annotation_schema_version": self.annotation_schema_version,
            "annotation_type": self.annotation_type,
            "experiment_id": self.experiment_id,
            "target_relpath": self.target_relpath,
            "target_sha256": self.target_sha256,
            "note": self.note,
            "previous_annotation_sha256": self.previous_annotation_sha256,
        }
        text = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_line(cls, line: bytes) -> ArtifactAnnotation:
        try:
            payload: Any = strict_json_loads(line)
        except StrictJSONError as exc:
            raise ArtifactAnnotationError(f"annotation line is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict) or set(payload) != _ANNOTATION_KEYS:
            raise ArtifactAnnotationError("annotation keys do not match the schema")
        return cls(
            annotation_schema_version=require_int(
                "annotation_schema_version", payload["annotation_schema_version"]
            ),
            annotation_type=require_nonempty_str("annotation_type", payload["annotation_type"]),
            experiment_id=require_nonempty_str("experiment_id", payload["experiment_id"]),
            target_relpath=require_nonempty_str("target_relpath", payload["target_relpath"]),
            target_sha256=require_hex64("target_sha256", payload["target_sha256"]),
            note=require_nonempty_str("note", payload["note"]),
            previous_annotation_sha256=require_hex64(
                "previous_annotation_sha256", payload["previous_annotation_sha256"]
            ),
        )


def _read_lines(path: Path) -> list[tuple[bytes, ArtifactAnnotation]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ArtifactAnnotationError("annotation registry must be a real regular file")
    raw = path.read_bytes()
    if raw == b"":
        return []
    if not raw.endswith(b"\n"):
        raise ArtifactAnnotationError("annotation registry does not end with a newline (partial)")
    out: list[tuple[bytes, ArtifactAnnotation]] = []
    for position, line in enumerate(raw.split(b"\n")[:-1]):
        try:
            out.append((line, ArtifactAnnotation.from_json_line(line)))
        except ArtifactAnnotationError as exc:
            raise ArtifactAnnotationError(
                f"annotation line {position + 1} is invalid: {exc}"
            ) from exc
    return out


def _check_chain(lines: list[tuple[bytes, ArtifactAnnotation]]) -> None:
    for position, (_raw, annotation) in enumerate(lines):
        expected = EMPTY_CONTENT_SHA256 if position == 0 else sha256_bytes(lines[position - 1][0])
        if annotation.previous_annotation_sha256 != expected:
            got = annotation.previous_annotation_sha256[:12]
            raise ArtifactAnnotationError(
                f"annotation line {position + 1}: broken chain "
                f"(expected previous {expected[:12]}, got {got})"
            )


def read_artifact_annotations(repo_root: str | Path) -> tuple[ArtifactAnnotation, ...]:
    """Strictly read + chain-validate the annotation registry (empty = none)."""
    lines = _read_lines(Path(repo_root) / ARTIFACT_ANNOTATIONS_RELPATH)
    _check_chain(lines)
    return tuple(annotation for _, annotation in lines)


def latest_annotation_sha256(repo_root: str | Path) -> str:
    """SHA-256 of the last annotation line, or the empty-content root sentinel."""
    lines = _read_lines(Path(repo_root) / ARTIFACT_ANNOTATIONS_RELPATH)
    return EMPTY_CONTENT_SHA256 if not lines else sha256_bytes(lines[-1][0])


def append_artifact_annotation(
    repo_root: str | Path,
    *,
    annotation_type: str,
    target_relpath: str,
    note: str,
) -> ArtifactAnnotation:
    """Append one annotation, pinning the target's current on-disk digest.

    Validates the whole chain before and after, then appends atomically. The
    target must already exist as a regular file under ``research/m3b/``.
    """
    root = Path(repo_root)
    if annotation_type not in ANNOTATION_TYPES:
        raise ArtifactAnnotationError(f"unknown annotation_type {annotation_type!r}")
    target = root / require_safe_relative_path("target_relpath", target_relpath, prefix=_M3B_PREFIX)
    if target.is_symlink() or not target.is_file():
        raise ArtifactAnnotationError(f"annotation target {target_relpath} is not a regular file")
    registry_path = root / ARTIFACT_ANNOTATIONS_RELPATH
    lines = _read_lines(registry_path)
    _check_chain(lines)
    annotation = ArtifactAnnotation(
        annotation_schema_version=ARTIFACT_ANNOTATION_SCHEMA_VERSION,
        annotation_type=annotation_type,
        experiment_id=RUN_001_EXPERIMENT_ID,
        target_relpath=target_relpath,
        target_sha256=sha256_file(target),
        note=note,
        previous_annotation_sha256=(
            EMPTY_CONTENT_SHA256 if not lines else sha256_bytes(lines[-1][0])
        ),
    )
    new_line = annotation.to_json_line()
    _check_chain([*lines, (new_line[:-1], annotation)])
    if not registry_path.exists():
        registry_path.write_bytes(b"")
    descriptor = os.open(str(registry_path), os.O_WRONLY | os.O_APPEND)
    try:
        if os.write(descriptor, new_line) != len(new_line):
            raise ArtifactAnnotationError("short write appending an annotation")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return annotation


def verify_artifact_annotations(repo_root: str | Path) -> tuple[str, ...]:
    """Verify the chain and that every annotated target matches its recorded digest.

    Read-only. Raises :class:`ArtifactAnnotationError` on a broken chain, a missing
    target, or a digest mismatch. Returns the ordered passed checks.
    """
    root = Path(repo_root)
    annotations = read_artifact_annotations(root)
    for annotation in annotations:
        target = root / annotation.target_relpath
        if target.is_symlink() or not target.is_file():
            raise ArtifactAnnotationError(
                f"annotated target {annotation.target_relpath} is missing on disk"
            )
        if sha256_file(target) != annotation.target_sha256:
            raise ArtifactAnnotationError(
                f"annotated target {annotation.target_relpath} digest disagrees with the chain"
            )
    return (
        "annotation_chain_intact",
        "annotated_targets_present_and_matching",
    )
