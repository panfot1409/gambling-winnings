"""Durable batch publication: atomic, fsynced, rollback-safe under injected failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from eth_research import publication
from eth_research.publication import Artifact, PublicationError, publish_batch


def _art(rel: str, data: bytes, *, immutable: bool = False, marker: bool = False) -> Artifact:
    return Artifact(relpath=rel, data=data, immutable=immutable, is_completeness_marker=marker)


def _no_temps(root: Path) -> bool:
    return not list(root.rglob(".*.tmp"))


class TestSuccessfulBatch:
    def test_writes_all_and_leaves_no_temps(self, tmp_path: Path) -> None:
        publish_batch(
            tmp_path,
            [
                _art("a/results.json", b"NEW_RESULTS"),
                _art("a/report.md", b"NEW_REPORT"),
                _art("a/manifest.json", b"MARK", marker=True),
            ],
        )
        assert (tmp_path / "a/results.json").read_bytes() == b"NEW_RESULTS"
        assert (tmp_path / "a/report.md").read_bytes() == b"NEW_REPORT"
        assert (tmp_path / "a/manifest.json").read_bytes() == b"MARK"
        assert _no_temps(tmp_path)


class TestFreshPublishRollback:
    def test_replace_failure_leaves_no_finals(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}
        real = publication._replace

        def flaky(temp: Path, final: Path) -> None:
            calls["n"] += 1
            if calls["n"] == 2:  # fail on the second final
                raise OSError("injected replace failure")
            real(temp, final)

        monkeypatch.setattr(publication, "_replace", flaky)
        with pytest.raises(PublicationError, match="rolled back"):
            publish_batch(
                tmp_path,
                [
                    _art("results.json", b"NEW"),
                    _art("report.md", b"NEW2"),
                    _art("manifest.json", b"M", marker=True),
                ],
            )
        # A failed fresh publication leaves no final artifacts and no temps.
        assert not (tmp_path / "results.json").exists()
        assert not (tmp_path / "report.md").exists()
        assert not (tmp_path / "manifest.json").exists()
        assert _no_temps(tmp_path)


class TestCorrectionRollback:
    def test_failure_restores_every_prior_byte(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "results.json").write_bytes(b"OLD_RESULTS")
        (tmp_path / "report.md").write_bytes(b"OLD_REPORT")
        (tmp_path / "manifest.json").write_bytes(b"OLD_MARK")

        calls = {"n": 0}
        real = publication._replace

        def flaky(temp: Path, final: Path) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("injected replace failure")
            real(temp, final)

        monkeypatch.setattr(publication, "_replace", flaky)
        with pytest.raises(PublicationError, match="rolled back"):
            publish_batch(
                tmp_path,
                [
                    _art("results.json", b"NEW_RESULTS"),
                    _art("report.md", b"NEW_REPORT"),
                    _art("manifest.json", b"NEW_MARK", marker=True),
                ],
            )
        # Every prior byte is restored exactly; no mixed pair, no temps.
        assert (tmp_path / "results.json").read_bytes() == b"OLD_RESULTS"
        assert (tmp_path / "report.md").read_bytes() == b"OLD_REPORT"
        assert (tmp_path / "manifest.json").read_bytes() == b"OLD_MARK"
        assert _no_temps(tmp_path)

    def test_fsync_dir_failure_still_rolls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "results.json").write_bytes(b"OLD")

        def boom(path: Path) -> None:
            raise OSError("injected fsync failure")

        monkeypatch.setattr(publication, "_fsync_dir", boom)
        with pytest.raises(PublicationError, match="rolled back"):
            publish_batch(tmp_path, [_art("results.json", b"NEW")])
        assert (tmp_path / "results.json").read_bytes() == b"OLD"
        assert _no_temps(tmp_path)


class TestRefusals:
    def test_immutable_existing_target_refused(self, tmp_path: Path) -> None:
        (tmp_path / "run.json").write_bytes(b"EXISTING")
        with pytest.raises(PublicationError, match="never overwritten"):
            publish_batch(tmp_path, [_art("run.json", b"NEW", immutable=True)])
        assert (tmp_path / "run.json").read_bytes() == b"EXISTING"
        assert _no_temps(tmp_path)

    def test_symlink_target_refused(self, tmp_path: Path) -> None:
        (tmp_path / "real").write_bytes(b"x")
        link = tmp_path / "results.json"
        link.symlink_to(tmp_path / "real")
        with pytest.raises(PublicationError, match="not a regular file"):
            publish_batch(tmp_path, [_art("results.json", b"NEW")])
        assert _no_temps(tmp_path)

    def test_duplicate_path_refused(self, tmp_path: Path) -> None:
        with pytest.raises(PublicationError, match="duplicate artifact path"):
            publish_batch(tmp_path, [_art("a.json", b"1"), _art("a.json", b"2")])

    def test_empty_batch_refused(self, tmp_path: Path) -> None:
        with pytest.raises(PublicationError, match="no artifacts"):
            publish_batch(tmp_path, [])


class TestMarkerOrdering:
    def test_completeness_marker_replaced_last(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        order: list[str] = []
        real = publication._replace

        def spy(temp: Path, final: Path) -> None:
            order.append(final.name)
            real(temp, final)

        monkeypatch.setattr(publication, "_replace", spy)
        publish_batch(
            tmp_path,
            [_art("manifest.json", b"M", marker=True), _art("results.json", b"R")],
        )
        assert order[-1] == "manifest.json"  # marker written last despite listed first
