"""The hash-chained artifact annotation registry is tamper-evident."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.fractional.artifact_annotations import (
    ARTIFACT_ANNOTATIONS_RELPATH,
    ArtifactAnnotation,
    ArtifactAnnotationError,
    append_artifact_annotation,
    read_artifact_annotations,
    verify_artifact_annotations,
)

REPO = Path(eth_research.__file__).resolve().parents[2]
_LEGACY_TARGET = "research/m3b/run001_legacy_completion_audit.json"


def _copy_m3b(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "research" / "m3b", tmp_path / "research" / "m3b")
    return tmp_path


def test_committed_annotations_verify() -> None:
    assert verify_artifact_annotations(REPO) == (
        "annotation_chain_intact",
        "annotated_targets_present_and_matching",
    )


def test_committed_annotations_cover_the_closure_artifacts() -> None:
    annotations = read_artifact_annotations(REPO)
    types = [a.annotation_type for a in annotations]
    assert types == [
        "immutable_archive_v2",
        "execution_trace_commitments",
        "legacy_completion_audit",
    ]
    assert all(a.experiment_id.endswith("run-001") for a in annotations)


def test_annotation_line_round_trips() -> None:
    annotation = read_artifact_annotations(REPO)[0]
    assert ArtifactAnnotation.from_json_line(annotation.to_json_line()) == annotation


def test_tampered_target_is_detected(tmp_path: Path) -> None:
    root = _copy_m3b(tmp_path)
    target = root / _LEGACY_TARGET
    target.write_bytes(target.read_bytes() + b" ")  # one trailing byte changes the digest
    with pytest.raises(ArtifactAnnotationError, match="digest disagrees"):
        verify_artifact_annotations(root)


def test_broken_chain_is_detected(tmp_path: Path) -> None:
    root = _copy_m3b(tmp_path)
    path = root / ARTIFACT_ANNOTATIONS_RELPATH
    lines = path.read_bytes().split(b"\n")
    # flip one hex digit of the first line's chain root -> the chain no longer joins
    lines[0] = lines[0].replace(
        b'"previous_annotation_sha256":"e3b0c442', b'"previous_annotation_sha256":"e3b0c443', 1
    )
    path.write_bytes(b"\n".join(lines))
    with pytest.raises(ArtifactAnnotationError, match="broken chain"):
        verify_artifact_annotations(root)


def test_append_extends_the_chain(tmp_path: Path) -> None:
    root = _copy_m3b(tmp_path)
    before = len(read_artifact_annotations(root))
    append_artifact_annotation(
        root,
        annotation_type="report_erratum",
        target_relpath=_LEGACY_TARGET,  # any existing m3b file, for the append test
        note="test append",
    )
    after = read_artifact_annotations(root)
    assert len(after) == before + 1
    assert after[-1].annotation_type == "report_erratum"
    assert verify_artifact_annotations(root) == (
        "annotation_chain_intact",
        "annotated_targets_present_and_matching",
    )
