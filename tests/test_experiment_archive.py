"""Immutable experiment archive: committed integrity + adversarial parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eth_research
from eth_research.data.provenance import sha256_bytes
from eth_research.experiment_archive import (
    EXPERIMENT_INDEX_RELPATH,
    EXPERIMENTS_RELDIR,
    ArchiveError,
    ArtifactManifest,
    ExperimentIndex,
    load_artifact_manifest,
    load_experiment_index,
    require_safe_experiment_relpath,
    verify_archived_experiment,
    verify_experiment_archive,
)
from eth_research.experiment_registry import EXPERIMENT_REGISTRY_RELPATH, read_registry

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
RUN1 = "m3a-fixed-baseline-comparison-v1-run-001"
RUN2 = "m3a-fixed-baseline-comparison-v1-run-002"


def _manifest(exp_id: str) -> ArtifactManifest:
    return load_artifact_manifest(
        REPO_ROOT / EXPERIMENTS_RELDIR / exp_id / "artifact_manifest.json"
    )


class TestCommittedArchive:
    def test_archive_verifies_against_the_registry(self) -> None:
        ids = verify_experiment_archive(REPO_ROOT)
        assert ids == (RUN1, RUN2)

    def test_run001_is_recovered_from_history(self) -> None:
        m = _manifest(RUN1)
        assert m.materialization == "recovered_from_history"
        assert m.source_commit == "bba0bd7c0737cadee4c169a9b3591119ef68a7b2"
        assert m.registry_event_position == 3

    def test_run002_is_originally_present(self) -> None:
        m = _manifest(RUN2)
        assert m.materialization == "originally_present"
        assert m.registry_event_position == 6

    def test_archived_bytes_match_the_completed_events(self) -> None:
        events = {
            e.experiment_id: e
            for e in read_registry(REPO_ROOT / EXPERIMENT_REGISTRY_RELPATH)
            if e.event == "completed"
        }
        for exp_id in (RUN1, RUN2):
            m = _manifest(exp_id)
            results = (REPO_ROOT / m.results_relpath).read_bytes()
            report = (REPO_ROOT / m.report_relpath).read_bytes()
            assert sha256_bytes(results) == events[exp_id].results_json_sha256
            assert sha256_bytes(report) == events[exp_id].report_markdown_sha256

    def test_index_lists_exactly_the_completed_experiments(self) -> None:
        index = load_experiment_index(REPO_ROOT / EXPERIMENT_INDEX_RELPATH)
        assert [e.experiment_id for e in index.entries] == [RUN1, RUN2]


class TestManifestValidation:
    def test_round_trip(self) -> None:
        m = _manifest(RUN1)
        assert ArtifactManifest.from_json_bytes(m.to_json_bytes()) == m

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(_manifest(RUN1).to_json_bytes())
        payload["extra"] = 1
        with pytest.raises(ValueError, match="unknown="):
            ArtifactManifest.from_json_bytes(json.dumps(payload).encode())

    def test_bad_schema_version_is_rejected(self) -> None:
        payload = json.loads(_manifest(RUN1).to_json_bytes())
        payload["artifact_schema_version"] = 999
        with pytest.raises(ValueError, match="unsupported artifact schema version"):
            ArtifactManifest.from_json_bytes(json.dumps(payload).encode())

    def test_unsafe_results_path_is_rejected(self) -> None:
        payload = json.loads(_manifest(RUN1).to_json_bytes())
        payload["results_relpath"] = "research/m3a/experiments/../../../etc/passwd"
        with pytest.raises(ValueError, match=r"dot components|must live under"):
            ArtifactManifest.from_json_bytes(json.dumps(payload).encode())


class TestSafePath:
    @pytest.mark.parametrize(
        "bad",
        [
            "/abs/path",
            "research/m3a/experiments/../x",
            "research/m3a/experiments/./x",
            "other/dir/x.json",
            "research/m3a/experiments/x\\y",
            "research/m3a/experiments/ x",
        ],
    )
    def test_unsafe_relpaths_refuse(self, bad: str) -> None:
        with pytest.raises(
            ValueError, match=r"relative path|dot components|unsafe path|live under"
        ):
            require_safe_experiment_relpath("p", bad)

    def test_safe_relpath_passes(self) -> None:
        safe = f"{EXPERIMENTS_RELDIR}/x/development_results.json"
        assert require_safe_experiment_relpath("p", safe) == safe


class TestAdversarialVerification:
    def test_tampered_archived_results_is_caught(self, tmp_path: Path) -> None:
        # Copy the archive into a temp root, tamper run-002's archived results,
        # and prove verification fails.
        import shutil

        root = tmp_path / "repo"
        shutil.copytree(REPO_ROOT / "research", root / "research")
        (root / ".git").mkdir()  # unused; verify reads files only
        tampered = root / EXPERIMENTS_RELDIR / RUN2 / "development_results.json"
        tampered.write_bytes(tampered.read_bytes() + b"\n")
        with pytest.raises(ArchiveError, match=r"hash mismatch|does not match"):
            verify_experiment_archive(root)

    def test_completed_event_binding_is_checked(self) -> None:
        events = {
            e.experiment_id: e
            for e in read_registry(REPO_ROOT / EXPERIMENT_REGISTRY_RELPATH)
            if e.event == "completed"
        }
        # run-001 manifest verified against run-002's completed event must fail.
        with pytest.raises(ArchiveError, match="experiment id"):
            verify_archived_experiment(REPO_ROOT, _manifest(RUN1), events[RUN2])


class TestIndexValidation:
    def test_round_trip(self) -> None:
        index = load_experiment_index(REPO_ROOT / EXPERIMENT_INDEX_RELPATH)
        assert ExperimentIndex.from_json_bytes(index.to_json_bytes()) == index

    def test_duplicate_experiment_id_refused(self) -> None:
        index = load_experiment_index(REPO_ROOT / EXPERIMENT_INDEX_RELPATH)
        payload = json.loads(index.to_json_bytes())
        payload["entries"].append(payload["entries"][0])
        with pytest.raises(ValueError, match=r"duplicate experiment id|ordered by registry"):
            ExperimentIndex.from_json_bytes(json.dumps(payload).encode())
