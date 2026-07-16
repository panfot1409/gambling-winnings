"""M3F independent-acceptance hardening regressions (Milestone 4A §3).

Three independent auditors re-reviewed the accepted M3F verification/recovery layer
before it became the M4A base. The genuine Class B/C defense-in-depth gaps they
reproduced are pinned here as regressions, each written to fail against the pre-fix
code and pass once the fix landed. See docs/M3F_INDEPENDENT_ACCEPTANCE_AUDIT.md.

Findings: A1 (m3f-layer completeness + accepted-stack scoping), A2 (independent-verifier
finite parity), A3 (accepted evidence anchored to immutable main), A4 (independent-verifier
symlink guard), A5 (catalog labels recomputed from path), B1 (workflow git -c push/tag +
market host), B2 (dependency registry hash), plus the bundle symlink-read guard.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

import eth_research
from eth_research.m3f.bundle import CapsuleError, build_manifest
from eth_research.m3f.catalog import CATALOG_RELPATH, verify_catalog
from eth_research.m3f.dependency_inventory import build_inventory
from eth_research.m3f.register import write_registration_artifacts
from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
    sha256_bytes,
)
from eth_research.m3f.workflow_inventory import _scan_one, workflow_grants_write

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
_INDEPENDENT_TOOL = REPO_ROOT / "tools/m3f_independent_verify.py"


def _independent_module() -> object:
    spec = importlib.util.spec_from_file_location("m3f_iv_h", _INDEPENDENT_TOOL)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def registered_clone(tmp_path: Path) -> Path:
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", "--local", str(REPO_ROOT), str(clone)], check=True)
    _git(clone, "config", "user.email", "a@b.c")
    _git(clone, "config", "user.name", "T")
    _git(clone, "rm", "-r", "-q", "--ignore-unmatch", "research/m3f")
    if _git(clone, "status", "--porcelain").strip():
        _git(clone, "commit", "-q", "-m", "reset to pre-registration")
    freeze = _git(clone, "rev-parse", "HEAD").strip()
    write_registration_artifacts(clone, source_freeze_sha=freeze, accepted_main_sha=freeze)
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "R")
    return clone


# --------------------------------------------------------------------------- #
# A1 — the M3F layer file-set is pinned; later layers (m4a) are out of scope   #
# --------------------------------------------------------------------------- #
def test_stray_file_under_research_m3f_is_caught(registered_clone: Path) -> None:
    (registered_clone / "research/m3f/backdoor.json").write_text('{"x": 1}\n', encoding="utf-8")
    _git(registered_clone, "add", "-A")
    _git(registered_clone, "commit", "-q", "-m", "stray")
    result = verify_catalog(registered_clone)
    assert result.ok is False
    assert any("08b_m3f_layer_allowlist" in f for f in result.failures)


def test_later_layer_research_m4a_is_not_orphaned(registered_clone: Path) -> None:
    # A later release-candidate layer must not trip the accepted-stack anti-orphan.
    (registered_clone / "research/m4a").mkdir()
    (registered_clone / "research/m4a/state.json").write_text("{}\n", encoding="utf-8")
    _git(registered_clone, "add", "-A")
    _git(registered_clone, "commit", "-q", "-m", "m4a layer")
    result = verify_catalog(registered_clone)
    assert result.ok is True, result.failures


# --------------------------------------------------------------------------- #
# A3 — accepted evidence anchored to the immutable accepted-main commit        #
# --------------------------------------------------------------------------- #
def test_lockstep_accepted_forgery_is_caught_by_anchor(registered_clone: Path) -> None:
    # Tamper an accepted artifact AND forge its catalog entry so the working-tree/catalog
    # hashes agree — the immutable-main anchor (check 15) must still catch it.
    target = registered_clone / "research/m2b/README.md"
    tampered = target.read_bytes() + b"\n<!-- payload -->\n"
    target.write_bytes(tampered)
    catalog_path = registered_clone / CATALOG_RELPATH
    catalog = load_canonical_json(catalog_path.read_bytes(), "catalog")
    for entry in catalog["artifacts"]:
        if entry["path"] == "research/m2b/README.md":
            entry["sha256"] = sha256_bytes(tampered)
            entry["byte_length"] = len(tampered)
    catalog_path.write_bytes(canonical_json_bytes(catalog))
    result = verify_catalog(registered_clone)
    assert result.ok is False
    # The source-pinned anchor catches the tamper even though the catalog entry was forged.
    assert any("14_accepted_stack_anchored" in f for f in result.failures)


def test_repointed_accepted_main_sha_is_caught(registered_clone: Path) -> None:
    # Repointing the catalog's accepted-main fields to a bogus commit is caught (the tree
    # cannot be recomputed); the accepted-stack anchor is independent of these fields anyway.
    catalog_path = registered_clone / CATALOG_RELPATH
    catalog = load_canonical_json(catalog_path.read_bytes(), "catalog")
    catalog["accepted_main_sha"] = "0" * 40
    catalog["accepted_main_tree_sha"] = "0" * 40
    catalog_path.write_bytes(canonical_json_bytes(catalog))
    result = verify_catalog(registered_clone)
    assert result.ok is False


# --------------------------------------------------------------------------- #
# A5 — catalog labels are recomputed from the path, not merely vocab-checked   #
# --------------------------------------------------------------------------- #
def test_relabelled_artifact_milestone_is_caught(registered_clone: Path) -> None:
    catalog_path = registered_clone / CATALOG_RELPATH
    catalog = load_canonical_json(catalog_path.read_bytes(), "catalog")
    for entry in catalog["artifacts"]:
        if entry["path"] == "research/m2b/README.md":
            entry["milestone"] = "m3e"  # forged label, still in the vocab
    catalog_path.write_bytes(canonical_json_bytes(catalog))
    result = verify_catalog(registered_clone)
    assert result.ok is False
    assert any("05_milestone_matches_path" in f for f in result.failures)


# --------------------------------------------------------------------------- #
# A2 / A4 — independent verifier parity (finite numbers + symlink guard)       #
# --------------------------------------------------------------------------- #
def test_independent_verifier_rejects_exponent_overflow() -> None:
    mod = _independent_module()
    with pytest.raises(Exception, match="non-finite"):
        mod._loads(b'{"x": 1e999}')  # type: ignore[attr-defined]
    with pytest.raises(Exception, match="non-finite"):
        mod._loads(b'{"x": -1e999}')  # type: ignore[attr-defined]
    assert mod._loads(b'{"x": 1.5}') == {"x": 1.5}  # type: ignore[attr-defined]


def test_independent_verifier_refuses_symlinked_artifact(tmp_path: Path) -> None:
    mod = _independent_module()
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "link.json").symlink_to(outside)
    with pytest.raises(Exception, match="unsafe path"):
        mod._read_bytes(root, "link.json")  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# B1 — workflow scanner sees git -c push/tag and market-data hosts             #
# --------------------------------------------------------------------------- #
def _scan_run(tmp_path: Path, command: str) -> dict[str, object]:
    body = f"jobs:\n  a:\n    steps:\n      - run: {command}\n"
    path = tmp_path / "w.yml"
    path.write_text("name: x\npermissions:\n  contents: read\n" + body, encoding="utf-8")
    return _scan_one(path)


_EVASIONS = [
    (
        "git_c_push",
        'git -c http.extraheader="AUTHORIZATION: bearer x" push origin HEAD:main',
        "can_push",
    ),
    ("git_c_tag", "git -c user.name=ci tag nightly-$GITHUB_SHA", "can_merge_or_release_or_tag"),
    ("gh_pr_repo_merge", "gh pr --repo o/r merge 12", "can_merge_or_release_or_tag"),
]


@pytest.mark.parametrize(("name", "command", "flag"), _EVASIONS, ids=[e[0] for e in _EVASIONS])
def test_workflow_scanner_sees_git_c_evasions(
    tmp_path: Path, name: str, command: str, flag: str
) -> None:
    assert _scan_run(tmp_path, command)[flag] is True


@pytest.mark.parametrize("host", ["data.binance.com", "binance.com", "api.kraken.com"])
def test_workflow_scanner_sees_subdomained_market_host(tmp_path: Path, host: str) -> None:
    assert _scan_run(tmp_path, f"curl https://{host}/v1/x")["contacts_market_host"] is True


def test_read_only_workflow_not_falsely_flagged(tmp_path: Path) -> None:
    # The broadened patterns must not false-positive a benign read-only step.
    facts = _scan_run(tmp_path, "git status && echo pushing docs && python -m pytest")
    assert facts["can_push"] is False
    assert facts["can_merge_or_release_or_tag"] is False
    assert workflow_grants_write("permissions:\n  contents: read\n") is False


# --------------------------------------------------------------------------- #
# B2 — dependency inventory requires a registry package to carry a hash        #
# --------------------------------------------------------------------------- #
def test_hashless_registry_package_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "hashless"\nversion = "9.9.9"\n'
        'source = { registry = "https://pypi.org/simple" }\n',
        encoding="utf-8",
    )
    with pytest.raises(M3FValidationError, match="no wheel or sdist hash"):
        build_inventory(tmp_path)


def test_real_lock_still_passes_dependency_inventory() -> None:
    # No drift: the real repo's registry packages all carry a hash.
    inv = build_inventory(REPO_ROOT)
    assert inv["locked_package_count"] > 0


# --------------------------------------------------------------------------- #
# bundle — a tracked symlink capsule file fails closed, not with an OSError    #
# --------------------------------------------------------------------------- #
def test_capsule_manifest_refuses_symlinked_file(registered_clone: Path) -> None:
    target = registered_clone / "research/m2b/README.md"
    target.unlink()
    target.symlink_to("/etc/hostname")
    _git(registered_clone, "add", "-A")
    with pytest.raises(CapsuleError):
        build_manifest(registered_clone)


# --------------------------------------------------------------------------- #
# frozen inventories: a later governed layer (M4A) that bumps the version and  #
# adds a workflow must NOT drift the accepted M3F inventories (verify against   #
# the source-freeze commit, not the live tree).                                #
# --------------------------------------------------------------------------- #
def test_frozen_inventories_survive_version_bump_and_new_workflow(registered_clone: Path) -> None:
    from eth_research.m3f.dependency_inventory import verify_inventory as verify_dep
    from eth_research.m3f.workflow_inventory import verify_inventory as verify_wf

    # Simulate the M4A layer: bump the package version (rewrites uv.lock/pyproject) and
    # add a new workflow — exactly what would drift a live-tree inventory verifier.
    pyproject = registered_clone / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('version = "0.9.0"', 'version = "1.0.0"', 1),
        encoding="utf-8",
    )
    lock = registered_clone / "uv.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace('version = "0.9.0"', 'version = "1.0.0"', 1),
        encoding="utf-8",
    )
    (registered_clone / ".github/workflows/m4a-rc.yml").write_text(
        "name: m4a\non:\n  push:\npermissions:\n  contents: read\njobs:\n"
        "  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        encoding="utf-8",
    )
    _git(registered_clone, "add", "-A")
    _git(registered_clone, "commit", "-q", "-m", "simulate M4A layer")

    # The frozen inventories still verify against the source-freeze commit, unaffected by
    # the live version bump and the added workflow.
    verify_dep(registered_clone)
    verify_wf(registered_clone)
