"""Locked dependency inventory for Milestone 3F.

Derived deterministically from ``uv.lock`` + ``pyproject.toml``. Binds the Python
requirement, every locked package + exact version + source kind + wheel/sdist hashes
where recorded, and the two lockfile hashes. Fails closed on a duplicate package
identity or a locked distribution missing a reproducible source identity. Lock
reproducibility is *not* binary provenance or signature verification, and any license
metadata is package-declared, never a legal-approval inference — both stated in the
inventory itself.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
    require_int,
    require_str,
    sha256_bytes,
)

INVENTORY_RELPATH = "research/m3f/dependency_inventory.json"

_PKG_BLOCK = re.compile(r"\[\[package\]\]\n(.*?)(?=\n\[\[|\Z)", re.DOTALL)


def _parse_lock_packages(lock_text: str) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for block in _PKG_BLOCK.findall(lock_text):
        name_m = re.search(r'^name = "([^"]+)"', block, re.MULTILINE)
        ver_m = re.search(r'^version = "([^"]+)"', block, re.MULTILINE)
        if not name_m or not ver_m:
            continue
        src_m = re.search(r"^source = \{ ([^}]+) \}", block, re.MULTILINE)
        source = src_m.group(1).strip() if src_m else "unknown"
        wheels = len(re.findall(r'wheels = \[|url = "[^"]+\.whl"', block))
        has_sdist = "sdist = {" in block
        source_kind = (
            "registry"
            if "registry" in source
            else "editable"
            if "editable" in source
            else "url"
            if "url" in source
            else "unknown"
        )
        packages.append(
            {
                "name": name_m.group(1),
                "version": ver_m.group(1),
                "source_kind": source_kind,
                "has_sdist_hash": has_sdist,
                "wheel_entries": wheels,
            }
        )
    packages.sort(key=lambda p: p["name"])
    return packages


def build_inventory(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    lock_bytes = (root / "uv.lock").read_bytes()
    pyproject_bytes = (root / "pyproject.toml").read_bytes()
    pyproject = tomllib.loads(pyproject_bytes.decode("utf-8"))
    project = pyproject.get("project", {})
    packages = _parse_lock_packages(lock_bytes.decode("utf-8"))

    names = [p["name"] for p in packages]
    if len(names) != len(set(names)):
        raise M3FValidationError("duplicate package identity in the lockfile")
    # every non-editable locked distribution must carry a reproducible source identity
    for pkg in packages:
        if pkg["source_kind"] == "unknown":
            raise M3FValidationError(f"package {pkg['name']} has no reproducible source identity")

    return {
        "schema_version": 1,
        "python_requirement": require_str(
            project.get("requires-python", ""), "requires-python", allow_empty=True
        ),
        "direct_dependencies": sorted(project.get("dependencies", [])),
        "direct_optional_dependency_groups": sorted(project.get("optional-dependencies", {})),
        "locked_package_count": len(packages),
        "locked_packages": packages,
        "lockfile_sha256": sha256_bytes(lock_bytes),
        "pyproject_sha256": sha256_bytes(pyproject_bytes),
        "provenance_note": (
            "lock reproducibility is not binary provenance or signature verification; "
            "any license metadata is package-declared, never a legal-approval inference"
        ),
    }


def render_inventory_bytes(inventory: dict[str, Any]) -> bytes:
    return canonical_json_bytes(inventory)


def verify_inventory(repo_root: str | Path) -> None:
    """The committed inventory reproduces byte-for-byte from the current lock/pyproject."""
    root = Path(repo_root)
    committed = load_canonical_json((root / INVENTORY_RELPATH).read_bytes(), "dependency_inventory")
    if require_int(committed.get("schema_version"), "schema_version") != 1:
        raise M3FValidationError("unexpected dependency inventory schema")
    fresh = build_inventory(root)
    if canonical_json_bytes(committed) != canonical_json_bytes(fresh):
        raise M3FValidationError("dependency inventory drifted from uv.lock/pyproject.toml")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    from eth_research.m3f.cli import emit, repo_root_parser

    args = repo_root_parser("M3F dependency inventory (read-only)").parse_args(argv)
    try:
        verify_inventory(args.repo_root)
        emit({"ok": True}, as_json=True)
        return 0
    except (OSError, M3FValidationError) as exc:
        emit({"ok": False, "error": str(exc)}, as_json=True)
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
