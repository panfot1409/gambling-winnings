"""Deterministic recovery capsule + disposable-clone drill (commit: recovery)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import eth_research
from eth_research.m3f.bundle import (
    CAPSULE_MANIFEST_RELPATH,
    CapsuleError,
    build_manifest,
    render_manifest_bytes,
    verify_materialized,
)
from eth_research.m3f.recovery import build_drill_record, failure_drills, recovery_drill

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def test_manifest_is_deterministic_and_excludes_the_m3f_layer() -> None:
    a = build_manifest(REPO_ROOT)
    b = build_manifest(REPO_ROOT)
    assert render_manifest_bytes(a) == render_manifest_bytes(b)
    assert a["file_count"] == len(a["files"]) > 0
    assert all(not f["path"].startswith("research/m3f/") for f in a["files"])
    assert a["contains_sealed_partition_contents"] is False
    assert a["sealed_ledger_count"] == 3


def test_capsule_manifest_relpath_is_under_m3f() -> None:
    assert CAPSULE_MANIFEST_RELPATH == "research/m3f/recovery_capsule_manifest.json"


def test_recovery_drill_reconstructs_and_reverifies() -> None:
    report = recovery_drill(REPO_ROOT)
    assert report["ok"] is True
    assert report["byte_reproduced"] is True
    assert report["honest_state_derived"] is True
    assert report["oracles_ok"] is True
    assert report["capsule_file_count"] > 0


def test_failure_drills_are_all_detected() -> None:
    report = failure_drills(REPO_ROOT)
    assert report["all_detected"] is True
    names = {d["name"] for d in report["drills"]}
    expected = {
        "dropped_file",
        "flipped_byte",
        "injected_proposal",
        "nonempty_sealed_ledger",
        "broken_registry_chain",
    }
    # Post-acceptance repositories additionally drill the acceptance chain: dropping
    # an acceptance record must strand its production proposal and be detected.
    if (REPO_ROOT / "research/m3e/acceptance_registry.jsonl").is_file():
        expected.add("dropped_acceptance_record")
    assert names == expected
    for drill in report["drills"]:
        assert drill["detected"] is True, drill["name"]


def test_drill_record_is_deterministic_and_reports_success() -> None:
    a = build_drill_record(REPO_ROOT)
    b = build_drill_record(REPO_ROOT)
    assert a == b
    assert a["reconstruction_ok"] is True
    assert a["all_failure_drills_detected"] is True


def test_verify_materialized_flags_missing_and_corrupt(tmp_path: Path) -> None:
    manifest = build_manifest(REPO_ROOT)
    # Materialize just the first two files, then corrupt one and drop the digest set.
    first = manifest["files"][0]
    target = tmp_path / first["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"corrupted")
    failures = verify_materialized(manifest, tmp_path)
    assert any(f.startswith("hash mismatch") or f.startswith("missing") for f in failures)


# --------------------------------------------------------------------------- #
# defense-in-depth: build_manifest refuses to bundle a leaked sealed ledger    #
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def test_build_manifest_refuses_a_nonempty_sealed_ledger(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "a@b.c")
    _git(repo, "config", "user.name", "T")
    (repo / "research/m2b").mkdir(parents=True)
    (repo / "research/m3a").mkdir(parents=True)
    (repo / "research/m3d").mkdir(parents=True)
    # a LEAKED (non-empty) sealed ledger
    (repo / "research/m2b/test_evaluations.jsonl").write_text('{"leak":true}\n')
    (repo / "research/m3a/development_gate_access.jsonl").write_bytes(b"")
    (repo / "research/m3d/prospective_evaluations.jsonl").write_bytes(b"")
    (repo / "research/m2b/README.md").write_text("# m2b\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "seed")
    with pytest.raises(CapsuleError, match="byte-empty"):
        build_manifest(repo)
