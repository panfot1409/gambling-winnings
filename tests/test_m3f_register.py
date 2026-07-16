"""End-to-end registration (R) + drill (P) round-trip (commit: register).

Clones the real repository into a temp directory, runs the registration writer,
commits the artifacts, and confirms the whole-graph freeze verifier goes green —
the exact sequence the milestone performs for real. Uses a local clone so it never
touches the live working tree (readiness tests bind to live git state).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import eth_research
from eth_research.m3f.audit import verify_repository_freeze
from eth_research.m3f.register import write_drill_record, write_registration_artifacts

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

_R_ARTIFACTS = {
    "research/m3f/freeze_catalog.json",
    "research/m3f/honest_state.json",
    "research/m3f/HONEST_STATE.md",
    "research/m3f/dependency_inventory.json",
    "research/m3f/workflow_inventory.json",
    "research/m3f/recovery_capsule_manifest.json",
    "research/m3f/RECOVERY_CAPSULE_NOTICE.md",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def _clone(tmp_path: Path) -> tuple[Path, str]:
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", "--local", str(REPO_ROOT), str(clone)], check=True)
    _git(clone, "config", "user.email", "a@b.c")
    _git(clone, "config", "user.name", "T")
    return clone, _git(clone, "rev-parse", "HEAD").strip()


def test_registration_roundtrip_verifies(tmp_path: Path) -> None:
    clone, freeze = _clone(tmp_path)

    written = write_registration_artifacts(
        clone, source_freeze_sha=freeze, accepted_main_sha=freeze
    )
    assert set(written) == _R_ARTIFACTS
    _git(clone, "add", "-A")
    _git(clone, "commit", "--quiet", "-m", "R")

    write_drill_record(clone)
    _git(clone, "add", "-A")
    _git(clone, "commit", "--quiet", "-m", "P")

    result = verify_repository_freeze(clone)
    result.raise_for_status()
    assert result.ok
    # every check ran and passed, including the post-registration ones
    for expected in (
        "04_freeze_catalog",
        "05_honest_state_reproduces",
        "06_dependency_inventory",
        "07_workflow_inventory",
        "08_semantic_oracles",
        "09_recovery_capsule",
        "10_recovery_drill",
    ):
        assert expected in {name for name, _ in result.checks}
        assert not any(f.startswith(expected) for f in result.failures)


def test_registration_is_byte_deterministic(tmp_path: Path) -> None:
    clone, freeze = _clone(tmp_path)
    write_registration_artifacts(clone, source_freeze_sha=freeze, accepted_main_sha=freeze)
    first = {rel: (clone / rel).read_bytes() for rel in _R_ARTIFACTS}
    # re-run over the same tree; the bytes must be identical
    write_registration_artifacts(clone, source_freeze_sha=freeze, accepted_main_sha=freeze)
    for rel, data in first.items():
        assert (clone / rel).read_bytes() == data, rel
