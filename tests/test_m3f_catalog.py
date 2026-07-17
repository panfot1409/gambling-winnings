"""Freeze-catalog generation, strict verification, and anti-orphan (commit 4)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from eth_research.m3f.catalog import (
    CATALOG_RELPATH,
    CatalogError,
    build_catalog,
    render_catalog_bytes,
    verify_catalog,
)
from eth_research.m3f.validation import canonical_json_bytes


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def _mini_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "a@b.c")
    _git(repo, "config", "user.name", "T")
    (repo / "research/m2b").mkdir(parents=True)
    (repo / "research/m3a").mkdir(parents=True)
    (repo / "research/m3c").mkdir(parents=True)
    (repo / "research/m3d").mkdir(parents=True)
    (repo / "research/m3e").mkdir(parents=True)
    # three sealed ledgers (byte-empty)
    (repo / "research/m2b/test_evaluations.jsonl").write_bytes(b"")
    (repo / "research/m3a/development_gate_access.jsonl").write_bytes(b"")
    (repo / "research/m3d/prospective_evaluations.jsonl").write_bytes(b"")
    # governance artifacts (canonical bytes)
    (repo / "research/m3c/candidate_decision.json").write_bytes(
        canonical_json_bytes({"outcome": "rejected_for_development_gate_promotion"})
    )
    (repo / "research/m3e/accepted_base.json").write_bytes(
        canonical_json_bytes(
            {"row_count": 3, "maturity_state": "immature", "evaluation_authorized": False}
        )
    )
    (repo / "research/m3e/proposal_registry.jsonl").write_text(
        '{"kind": "genesis"}\n{"kind": "audit_noop", "proposal_created": false}\n'
    )
    (repo / "research/m2b/README.md").write_text("# m2b\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "seed")
    return repo, _git(repo, "rev-parse", "HEAD").strip()


def _generate_and_write(repo: Path, sha: str) -> None:
    catalog = build_catalog(
        repo, source_freeze_sha=sha, accepted_main_sha=sha, package_version="0.9.0"
    )
    (repo / "research/m3f").mkdir(parents=True, exist_ok=True)
    (repo / CATALOG_RELPATH).write_bytes(render_catalog_bytes(catalog))


def test_generated_catalog_verifies(tmp_path: Path) -> None:
    repo, sha = _mini_repo(tmp_path)
    _generate_and_write(repo, sha)
    result = verify_catalog(repo)
    result.raise_for_status()
    assert result.ok
    assert result.artifact_count >= 7  # ledgers + governance + readme


def test_generation_is_deterministic(tmp_path: Path) -> None:
    repo, sha = _mini_repo(tmp_path)
    a = render_catalog_bytes(
        build_catalog(repo, source_freeze_sha=sha, accepted_main_sha=sha, package_version="0.9.0")
    )
    b = render_catalog_bytes(
        build_catalog(repo, source_freeze_sha=sha, accepted_main_sha=sha, package_version="0.9.0")
    )
    assert a == b


def test_tampered_artifact_hash_is_caught(tmp_path: Path) -> None:
    repo, sha = _mini_repo(tmp_path)
    _generate_and_write(repo, sha)
    (repo / "research/m2b/README.md").write_text("# tampered\n")
    result = verify_catalog(repo)
    assert not result.ok
    assert any("hash" in f for f in result.failures)


def test_orphan_governed_file_is_caught(tmp_path: Path) -> None:
    repo, sha = _mini_repo(tmp_path)
    _generate_and_write(repo, sha)
    # add a new tracked governed file that the catalog does not know about
    (repo / "research/m3d/stowaway.json").write_bytes(canonical_json_bytes({"x": 1}))
    _git(repo, "add", "-A")
    result = verify_catalog(repo)
    assert not result.ok
    assert any("orphan" in f or "uncatalogued" in f for f in result.failures)


def test_m3f_layer_files_are_excluded_not_orphaned(tmp_path: Path) -> None:
    # Registration (R) adds self-verifying artifacts under research/m3f/ after the
    # source freeze the catalog binds; they must be neither catalogued nor orphaned.
    repo, sha = _mini_repo(tmp_path)
    _generate_and_write(repo, sha)
    (repo / "research/m3f/honest_state.json").write_bytes(canonical_json_bytes({"any": 1}))
    _git(repo, "add", "-A")  # tracks the catalog + honest_state.json under research/m3f/
    result = verify_catalog(repo)
    result.raise_for_status()
    assert result.ok
    catalog = build_catalog(
        repo, source_freeze_sha=sha, accepted_main_sha=sha, package_version="0.9.0"
    )
    assert not any(a["path"].startswith("research/m3f/") for a in catalog["artifacts"])


def test_nonempty_ledger_is_caught(tmp_path: Path) -> None:
    repo, sha = _mini_repo(tmp_path)
    _generate_and_write(repo, sha)
    (repo / "research/m2b/test_evaluations.jsonl").write_text('{"leak": 1}\n')
    result = verify_catalog(repo)
    assert not result.ok
    assert any("ledger" in f for f in result.failures)


def test_m3c_outcome_drift_is_caught(tmp_path: Path) -> None:
    repo, sha = _mini_repo(tmp_path)
    _generate_and_write(repo, sha)
    (repo / "research/m3c/candidate_decision.json").write_bytes(
        canonical_json_bytes({"outcome": "eligible_for_development_gate_promotion"})
    )
    result = verify_catalog(repo)
    assert not result.ok


def test_missing_catalog_raises(tmp_path: Path) -> None:
    repo, _sha = _mini_repo(tmp_path)
    result = verify_catalog(repo)
    assert not result.ok
    with pytest.raises(CatalogError):
        result.raise_for_status()
