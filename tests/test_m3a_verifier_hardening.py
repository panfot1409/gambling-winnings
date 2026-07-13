"""Regression tests for two merge-readiness verifier gaps (both class C).

- F-4.7-1: ``verify_experiment_archive`` enumerates the on-disk experiments tree,
  so a stray file, a rogue experiment directory (even with a self-consistent
  manifest), or a symlink is rejected — the "no extra archive" guarantee its
  docstring makes is now actually enforced.
- F-4.7-2: the six-line registry-v1 prefix is byte-pinned by the CI verifier
  ``.github/scripts/verify_m3a_registry.py`` (not only by a unit test), so a
  monotonic-preserving edit to a v1 prefix line — which ``read_registry``'s
  append-chain does not bind — is caught at the merge gate.

Neither can affect run-003 financials; both close a gap between a claimed
protection and its enforcement.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.experiment_archive import ArchiveError, verify_experiment_archive

REPO = Path(eth_research.__file__).resolve().parents[2]
_RUN003 = "research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003"
_REGISTRY = "research/m3a/experiment_registry.jsonl"
_V1_PREFIX_SHA256 = "7920d9fdf4e936ef6c6d79dfd1c10cdd12dcb9b2db264b9ab9d5640332e9af67"


def _make_m3a_copy(tmp_path: Path) -> Path:
    """A copy carrying just enough for verify_experiment_archive to run."""
    root = tmp_path / "repo"
    (root / "research/m3a").mkdir(parents=True)
    shutil.copy(REPO / _REGISTRY, root / _REGISTRY)
    shutil.copytree(REPO / "research/m3a/experiments", root / "research/m3a/experiments")
    return root


class TestArchiveTreeEnumeration:
    def test_real_tree_verifies(self, tmp_path: Path) -> None:
        root = _make_m3a_copy(tmp_path)
        assert verify_experiment_archive(root) == (
            "m3a-fixed-baseline-comparison-v1-run-001",
            "m3a-fixed-baseline-comparison-v1-run-002",
            "m3a-fixed-baseline-comparison-v2-run-003",
        )

    def test_stray_file_inside_an_archive_dir_is_rejected(self, tmp_path: Path) -> None:
        root = _make_m3a_copy(tmp_path)
        (root / _RUN003 / "FINDINGS.md").write_bytes(b"rogue\n")
        with pytest.raises(ArchiveError, match="undeclared file in archive"):
            verify_experiment_archive(root)

    def test_rogue_experiment_directory_is_rejected(self, tmp_path: Path) -> None:
        root = _make_m3a_copy(tmp_path)
        rogue = root / "research/m3a/experiments/m3a-ghost-comparison-v9-run-042"
        shutil.copytree(root / _RUN003, rogue)  # a fully self-consistent manifest
        with pytest.raises(ArchiveError, match="rogue experiment directory"):
            verify_experiment_archive(root)

    def test_symlinked_archive_file_is_rejected(self, tmp_path: Path) -> None:
        root = _make_m3a_copy(tmp_path)
        target = root / _RUN003 / "development_report.md"
        outside = tmp_path / "outside.md"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
        with pytest.raises(ArchiveError, match="symlink"):
            verify_experiment_archive(root)


class TestV1PrefixPin:
    def _prefix_sha256(self, registry: Path, n: int = 6) -> str:
        lines = [line for line in registry.read_bytes().split(b"\n") if line]
        return hashlib.sha256(b"".join(line + b"\n" for line in lines[:n])).hexdigest()

    def test_committed_prefix_matches_the_pin(self) -> None:
        assert self._prefix_sha256(REPO / _REGISTRY) == _V1_PREFIX_SHA256

    def test_ci_verifier_pins_the_same_hash(self) -> None:
        # The CI gate embeds the identical pin, so the immutability is enforced by
        # the verifier the contract points at — not only by a unit test.
        script = (REPO / ".github/scripts/verify_m3a_registry.py").read_text("utf-8")
        assert _V1_PREFIX_SHA256 in script
        assert "_verify_v1_prefix()" in script

    def test_monotonic_preserving_prefix_edit_changes_the_pin(self, tmp_path: Path) -> None:
        # run-001 completed at 12:39:28; shifting it to 12:39:29 stays monotonic
        # (>= started 12:38:44), so read_registry's checks pass — yet the prefix
        # hash changes, which the pin catches.
        registry = tmp_path / "registry.jsonl"
        raw = (REPO / _REGISTRY).read_bytes()
        mutated = raw.replace(
            b'"event_time_utc":"2026-07-13T12:39:28+00:00"',
            b'"event_time_utc":"2026-07-13T12:39:29+00:00"',
            1,
        )
        assert mutated != raw, "the monotonic-safe mutation must apply"
        registry.write_bytes(mutated)
        assert self._prefix_sha256(registry) != _V1_PREFIX_SHA256


class TestCanonicalFileNewline:
    """A6-1: a committed artifact *file* must be a serialize fixed point — it must
    end with the canonical trailing newline. ``from_json_bytes`` stays a lenient
    parser (registry/errata lines carry no newline); the file-load boundary and
    the downstream SHA-256 binding together enforce canonical bytes.
    """

    def test_committed_artifacts_load_and_de_newlined_files_are_rejected(
        self, tmp_path: Path
    ) -> None:
        from eth_research.development_results_v2 import (
            DevelopmentResultsV2Error,
            load_development_results_v2,
        )
        from eth_research.experiment_archive import ArchiveError, load_artifact_manifest
        from eth_research.methodology_v2 import MethodologyError, load_methodology_v2
        from eth_research.return_evidence import ReturnEvidenceError, load_return_evidence

        cases = [
            (
                load_development_results_v2,
                DevelopmentResultsV2Error,
                f"{_RUN003}/development_results.json",
            ),
            (load_return_evidence, ReturnEvidenceError, f"{_RUN003}/return_evidence.json"),
            (load_artifact_manifest, ArchiveError, f"{_RUN003}/artifact_manifest.json"),
            (load_methodology_v2, MethodologyError, "research/m3a/walk_forward_protocol_v2.json"),
        ]
        for loader, error, rel in cases:
            loader(REPO / rel)  # committed file (has newline) loads
            stripped = tmp_path / Path(rel).name
            stripped.write_bytes((REPO / rel).read_bytes().rstrip(b"\n"))
            with pytest.raises(error, match="trailing newline"):
                loader(stripped)
