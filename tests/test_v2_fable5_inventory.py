"""Fable 5 system-inventory verifier: it passes on the real tree and fails closed on every
structural red flag and drift class. These are standing regression tests; none evaluates a strategy
or opens a sealed value."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from eth_research.v2.fable5.inventory import (
    FABLE5_INVENTORY_RELPATH,
    Fable5InventoryError,
    build_system_inventory,
    verify_system_inventory,
)

REPO = Path(__file__).resolve().parents[1]


def _committed() -> dict[str, object]:
    data: dict[str, object] = json.loads((REPO / FABLE5_INVENTORY_RELPATH).read_text())
    return data


def test_verify_passes_on_the_real_tree() -> None:
    checks = verify_system_inventory(REPO, _committed())
    assert "surface_digest_match" in checks
    assert "sealed_ledgers_byte_empty" in checks
    assert "no_workflow_write_permission" in checks


def _scratch_repo(tmp_path: Path) -> Path:
    """A minimal but structurally-complete copy sufficient to build the inventory."""
    dst = tmp_path / "repo"
    dst.mkdir()
    for rel in ("src", "governance", "research", ".github", "tools", "docs", "tests"):
        src = REPO / rel
        if src.exists():
            shutil.copytree(
                src, dst / rel, symlinks=True, ignore=shutil.ignore_patterns("__pycache__")
            )
    for rel in ("pyproject.toml", "uv.lock", "README.md"):
        if (REPO / rel).exists():
            shutil.copy2(REPO / rel, dst / rel)
    if (REPO / "release").exists():
        shutil.copytree(REPO / "release", dst / "release", symlinks=True)
    return dst


def test_snapshot_of_scratch_copy_self_verifies(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    assert verify_system_inventory(dst, inv)  # a freshly built snapshot verifies against itself


def test_governed_byte_drift_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    target = next(iter(inv["governed_artifacts"]))
    (dst / target).write_bytes((dst / target).read_bytes() + b"\n")  # 1-byte drift
    with pytest.raises(Fable5InventoryError, match=r"byte drift|surface_digest"):
        verify_system_inventory(dst, inv)


def test_symlink_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    link = dst / "src" / "eth_research" / "_evil_link.py"
    os.symlink(dst / "pyproject.toml", link)
    with pytest.raises(Fable5InventoryError, match=r"symlink"):
        verify_system_inventory(dst, inv)


def test_unexpected_executable_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    victim = dst / "src" / "eth_research" / "__init__.py"
    victim.chmod(victim.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(Fable5InventoryError, match=r"executable"):
        verify_system_inventory(dst, inv)


def test_added_module_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    (dst / "src" / "eth_research" / "_ungoverned_new.py").write_text("x = 1\n")
    with pytest.raises(Fable5InventoryError, match=r"package_modules|surface_digest"):
        verify_system_inventory(dst, inv)


def test_removed_module_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    # remove a leaf module that nothing else in the build imports at enumeration time
    (dst / "src" / "eth_research" / "v2" / "fable5" / "__main__.py").unlink()
    with pytest.raises(Fable5InventoryError, match=r"package_modules|missing|surface_digest"):
        verify_system_inventory(dst, inv)


def test_workflow_write_permission_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    wf = dst / ".github" / "workflows" / "ci.yml"
    text = wf.read_text().replace("contents: read", "contents: write", 1)
    wf.write_text(text)
    with pytest.raises(Fable5InventoryError, match=r"write permission|surface_digest"):
        verify_system_inventory(dst, inv)


def test_workflow_secret_reference_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    wf = dst / ".github" / "workflows" / "ci.yml"
    wf.write_text(wf.read_text() + "\n# leak ${{ secrets.PYPI_TOKEN }}\n")
    with pytest.raises(Fable5InventoryError, match=r"secret|surface_digest"):
        verify_system_inventory(dst, inv)


def test_unpinned_action_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    wf = dst / ".github" / "workflows" / "ci.yml"
    wf.write_text(wf.read_text() + "\n      - uses: actions/checkout@v4\n")
    with pytest.raises(Fable5InventoryError, match=r"unpinned|surface_digest"):
        verify_system_inventory(dst, inv)


def test_nonempty_sealed_ledger_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    (dst / "research" / "m2b" / "test_evaluations.jsonl").write_text("contaminated\n")
    with pytest.raises(Fable5InventoryError, match=r"sealed ledger|surface_digest"):
        verify_system_inventory(dst, inv)


def test_public_api_drift_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    api = dst / "src" / "eth_research" / "api" / "__init__.py"
    text = api.read_text().replace("__all__ = [", '__all__ = [\n    "_SneakyExport",', 1)
    api.write_text(text)
    with pytest.raises(Fable5InventoryError, match=r"public_api|surface_digest"):
        verify_system_inventory(dst, inv)


def test_duplicate_normalized_path_is_refused(tmp_path: Path) -> None:
    dst = _scratch_repo(tmp_path)
    inv = build_system_inventory(dst)
    # a case-only duplicate of an existing tracked module
    (dst / "src" / "eth_research" / "V2").mkdir(exist_ok=True)
    # create a path whose casefold collides with an existing one
    existing = "src/eth_research/v2/strict.py"
    dup = dst / "src/eth_research/v2/STRICT.py"
    if not dup.exists():
        dup.write_text((dst / existing).read_text())
        with pytest.raises(Fable5InventoryError, match=r"duplicate normalized|surface_digest"):
            verify_system_inventory(dst, inv)
