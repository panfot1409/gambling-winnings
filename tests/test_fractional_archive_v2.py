"""The run-001 immutable archive v2 is a genuine, self-verifying immutable body."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.data.provenance import sha256_bytes
from eth_research.fractional.archive import FRACTIONAL_MANIFEST_RELPATH, bundle_sha256
from eth_research.fractional.archive_v2 import (
    FRACTIONAL_ARCHIVE_V2_RELPATH,
    ArchiveV2Error,
    render_archive_v2,
    verify_archive_v2,
)
from eth_research.fractional.results import FRACTIONAL_REPORT_RELPATH, FRACTIONAL_RESULTS_RELPATH

REPO = Path(eth_research.__file__).resolve().parents[2]
_EXPECTED_CHECKS = (
    "archive_v2_canonical",
    "archive_v2_rederives",
    "archived_copies_byte_identical_to_singletons",
    "archived_copies_bind_manifest_and_registry",
)
_ARCHIVED_RESULTS = "research/m3b/experiments/run-001/immutable-v2/fractional_results.json"
_ARCHIVED_REPORT = "research/m3b/experiments/run-001/immutable-v2/fractional_report.md"


def _copy_m3b(tmp_path: Path) -> Path:
    """A throwaway repo root carrying a copy of the whole research/m3b tree."""
    dst = tmp_path / "research" / "m3b"
    shutil.copytree(REPO / "research" / "m3b", dst)
    return tmp_path


def test_committed_archive_v2_verifies() -> None:
    assert verify_archive_v2(REPO) == _EXPECTED_CHECKS


def test_archived_copies_are_byte_identical_to_singletons() -> None:
    assert (REPO / _ARCHIVED_RESULTS).read_bytes() == (
        REPO / FRACTIONAL_RESULTS_RELPATH
    ).read_bytes()


def test_tampered_archived_copy_is_rejected(tmp_path: Path) -> None:
    root = _copy_m3b(tmp_path)
    victim = root / _ARCHIVED_RESULTS
    victim.write_bytes(
        victim.read_bytes().replace(b"marked_total_return", b"marked_total_retvrn", 1)
    )
    with pytest.raises(ArchiveV2Error, match=r"byte-identical|re-derive"):
        verify_archive_v2(root)


def test_missing_archived_copy_is_rejected(tmp_path: Path) -> None:
    root = _copy_m3b(tmp_path)
    (root / _ARCHIVED_REPORT).unlink()
    with pytest.raises(ArchiveV2Error, match="missing"):
        verify_archive_v2(root)


def test_non_canonical_record_is_rejected(tmp_path: Path) -> None:
    root = _copy_m3b(tmp_path)
    record = root / FRACTIONAL_ARCHIVE_V2_RELPATH
    # collapse the canonical (indented, trailing-newline) bytes to a compact line
    record.write_bytes(b'{"archive_v2_schema_version":1}')
    with pytest.raises(ArchiveV2Error):
        verify_archive_v2(root)


def test_record_rederives_byte_for_byte() -> None:
    assert (REPO / FRACTIONAL_ARCHIVE_V2_RELPATH).read_bytes() == render_archive_v2(REPO)


def test_coordinated_tamper_with_untouched_registry_is_caught(tmp_path: Path) -> None:
    # Change the results singleton AND its immutable-v2 copy identically, then make
    # the mutable manifest + archive_v2.json self-consistent with the new bytes.
    # Only the hash-chained registry 'completed' event still carries the original
    # certified digests, so the registry anchor must reject this.
    root = _copy_m3b(tmp_path)
    tampered = (root / FRACTIONAL_RESULTS_RELPATH).read_bytes().replace(
        b'"marked_total_return"', b'"marked_total_retvrn"', 1
    )
    (root / FRACTIONAL_RESULTS_RELPATH).write_bytes(tampered)
    (root / _ARCHIVED_RESULTS).write_bytes(tampered)
    report_bytes = (root / FRACTIONAL_REPORT_RELPATH).read_bytes()

    manifest_path = root / FRACTIONAL_MANIFEST_RELPATH
    manifest = json.loads(manifest_path.read_bytes())
    manifest["results_sha256"] = sha256_bytes(tampered)
    manifest["bundle_sha256"] = bundle_sha256(tampered, report_bytes)
    manifest_path.write_bytes(
        (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )
    (root / FRACTIONAL_ARCHIVE_V2_RELPATH).write_bytes(render_archive_v2(root))

    with pytest.raises(ArchiveV2Error, match="registry"):
        verify_archive_v2(root)
