"""Regressions for the run-003 terminal defects N1-N10.

Each test asserts the corrected behavior; before the fix it failed on the
closure checkpoint 18de743 (see docs/M3A_BUG_LOG.md). Publication-primitive
attacks (N2-N5) live here; the remaining defects are covered alongside their
fixes in the module test files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eth_research import publication
from eth_research.publication import (
    Artifact,
    PublicationCatastrophe,
    PublicationError,
    prepare_batch,
    publish_batch,
)


def _art(rel: str, data: bytes, *, immutable: bool = False) -> Artifact:
    return Artifact(relpath=rel, data=data, immutable=immutable)


class TestN2PathTraversal:
    def test_dotdot_escape_is_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        with pytest.raises(PublicationError, match=r"dotdot|outside|relative"):
            publish_batch(root, [_art("../escape.txt", b"ESCAPED")])
        assert not (tmp_path / "escape.txt").exists()

    def test_absolute_path_is_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        with pytest.raises(PublicationError, match="relative"):
            publish_batch(root, [_art("/etc/passwd", b"X")])

    def test_symlinked_parent_is_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        (tmp_path / "outside").mkdir()
        (root / "a").symlink_to(tmp_path / "outside")  # a/ -> outside/
        with pytest.raises(PublicationError, match="symlink"):
            publish_batch(root, [_art("a/x.json", b"X")])
        assert not (tmp_path / "outside" / "x.json").exists()

    def test_backslash_and_dot_segments_are_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        for bad in ("a\\b", "a/./b", "a//b"):
            with pytest.raises(PublicationError):
                publish_batch(root, [_art(bad, b"X")])


class TestN3TempCollision:
    def test_preexisting_temp_name_is_not_clobbered(self, tmp_path: Path) -> None:
        # A file whose name matches the old pid-based temp pattern must survive:
        # temps are now unique O_EXCL, so an unrelated file is never truncated.
        import os

        decoy = tmp_path / f".results.json.{os.getpid()}.tmp"
        decoy.write_bytes(b"DECOY")
        publish_batch(tmp_path, [_art("results.json", b"NEW")])
        assert (tmp_path / "results.json").read_bytes() == b"NEW"
        assert decoy.read_bytes() == b"DECOY"  # untouched


class TestN4VerifyInsideRollback:
    def test_verify_failure_rolls_back_a_correction(self, tmp_path: Path) -> None:
        (tmp_path / "results.json").write_bytes(b"OLD")

        def bad_verify(_root: Path) -> None:
            raise RuntimeError("read-back mismatch")

        with pytest.raises(PublicationError, match=r"rolled back|read-back mismatch"):
            publish_batch(tmp_path, [_art("results.json", b"NEW")], verify=bad_verify)
        # The failed verification restored the prior bytes.
        assert (tmp_path / "results.json").read_bytes() == b"OLD"

    def test_verify_failure_leaves_no_new_finals(self, tmp_path: Path) -> None:
        def bad_verify(_root: Path) -> None:
            raise RuntimeError("parse failed")

        with pytest.raises(PublicationError):
            publish_batch(tmp_path, [_art("a/results.json", b"NEW")], verify=bad_verify)
        assert not (tmp_path / "a/results.json").exists()
        # The directory it created is removed on rollback.
        assert not (tmp_path / "a").exists()

    def test_successful_verify_commits(self, tmp_path: Path) -> None:
        seen: dict[str, bytes] = {}

        def good_verify(root: Path) -> None:
            seen["results"] = (root / "results.json").read_bytes()

        publish_batch(tmp_path, [_art("results.json", b"NEW")], verify=good_verify)
        assert seen["results"] == b"NEW"
        assert (tmp_path / "results.json").read_bytes() == b"NEW"


class TestN5RollbackDurability:
    def test_catastrophic_rollback_is_distinct(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "results.json").write_bytes(b"OLD")
        calls = {"n": 0}
        real = publication._replace

        def flaky(temp: Path, final: Path) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                real(temp, final)  # the forward replace succeeds
            else:
                raise OSError("restore replace failed")  # rollback restore fails

        def bad_verify(_root: Path) -> None:
            raise RuntimeError("trigger rollback")

        monkeypatch.setattr(publication, "_replace", flaky)
        with pytest.raises(PublicationCatastrophe, match="rollback failed"):
            publish_batch(tmp_path, [_art("results.json", b"NEW")], verify=bad_verify)

    def test_lock_refuses_concurrent_publication(self, tmp_path: Path) -> None:
        with (
            prepare_batch(tmp_path, [_art("a.json", b"1")]) as _txn,
            pytest.raises(PublicationError, match="another publication is in progress"),
        ):
            publish_batch(tmp_path, [_art("b.json", b"2")])
