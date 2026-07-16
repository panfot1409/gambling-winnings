"""Transactional output-bundle publication."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from eth_research import api
from eth_research.api.publish import publish_bundle


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_publish_writes_all_files_and_returns_digests(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    files = {"result.json": b'{"a": 1}\n', "report.md": b"# report\n"}
    digests = publish_bundle(out, files)
    for name, data in files.items():
        assert (out / name).read_bytes() == data
        assert digests[name] == _sha(data)


def test_completeness_marker_written_last(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    files = {"result.json": b"{}\n", "manifest.json": b"{}\n"}
    # marker must be part of the bundle
    with pytest.raises(api.OutputCollisionError):
        publish_bundle(out, files, completeness_marker="absent.json")
    digests = publish_bundle(out, files, completeness_marker="manifest.json")
    assert set(digests) == {"result.json", "manifest.json"}


def test_collision_refused_and_nothing_partial(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "b.txt").write_bytes(b"old\n")
    with pytest.raises(api.OutputCollisionError):
        publish_bundle(out, {"a.txt": b"new\n", "b.txt": b"new\n"})
    # the new file was never created, and the existing file is untouched
    assert not (out / "a.txt").exists()
    assert (out / "b.txt").read_bytes() == b"old\n"


def test_overwrite_replaces_and_restores_are_consistent(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "a.txt").write_bytes(b"old\n")
    publish_bundle(out, {"a.txt": b"new\n"}, overwrite=True)
    assert (out / "a.txt").read_bytes() == b"new\n"


def test_unsafe_filenames_rejected(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    for bad in ("../escape", "a/b.txt", ".hidden", "a\x00b"):
        with pytest.raises(api.OutputCollisionError):
            publish_bundle(out, {bad: b"x\n"})


def test_symlink_target_refused(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "link.txt").symlink_to(tmp_path / "elsewhere.txt")
    with pytest.raises(api.OutputCollisionError):
        publish_bundle(out, {"link.txt": b"x\n"}, overwrite=True)


def test_symlinked_output_dir_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(api.OutputCollisionError):
        publish_bundle(link, {"a.txt": b"x\n"})
