"""Fable 5 machine-readable system inventory — builder and fail-closed verifier.

The inventory is a deterministic enumeration of the merged V2 platform's surfaces, computed from the
committed bytes under a repository root. It is stored canonically at
``governance/v2/fable5_system_inventory.json`` and re-derived by the verifier, which:

1. rebuilds the inventory from live bytes and compares it category-by-category against the committed
   snapshot (any addition, removal, or drift fails closed), and
2. runs structural checks that fail closed on symlinks, path traversal / duplicate normalized paths,
   unexpected executable files, workflow write-permission escalation (``contents: write`` /
   ``id-token: write``), unregistered CLI ``__main__`` surfaces, and public-API
   (``eth_research.api``) drift.

No enumeration executes research, opens a sealed ledger's *values*, or mutates governed
state; sealed ledgers are only *stat*-ed (byte length) and hashed, never interpreted.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from eth_research.v2.strict import canonical_json_bytes

FABLE5_INVENTORY_RELPATH = "governance/v2/fable5_system_inventory.json"
INVENTORY_SCHEMA_VERSION = 1

#: Roots whose *tracked* files the inventory enumerates and structurally checks.
_SCANNED_ROOTS = ("src", "tests", "docs", ".github", "governance", "research", "release", "tools")

#: The three sealed research access ledgers. They must remain byte-empty; the inventory records
#: their length and hash but never parses their contents (there are none to parse).
SEALED_LEDGER_RELPATHS = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)

_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: Workflows are the only place a write permission could legitimately be requested; none currently
#: do, and the Fable 5 posture forbids it. There is no allowlist: any ``contents: write`` /
#: ``id-token: write`` in any workflow fails closed.
_WRITE_PERMISSION_RE = re.compile(
    r"^\s*(contents|id-token|packages|deployments|pull-requests|issues)\s*:\s*write\b",
    re.MULTILINE,
)


class Fable5InventoryError(RuntimeError):
    """A structural red flag or a drift from the committed system inventory."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _require_confined(root: Path, path: Path) -> None:
    """Refuse a symlink or a path that escapes ``root`` (traversal / absolute)."""
    if path.is_symlink():
        raise Fable5InventoryError(f"symlink is not permitted in the audited tree: {path}")
    resolved = path.resolve()
    root_resolved = root.resolve()
    if root_resolved != resolved and root_resolved not in resolved.parents:
        raise Fable5InventoryError(f"path escapes the repository root: {path}")


def _iter_files(root: Path, rel: str) -> Iterable[Path]:
    base = root / rel
    if not base.exists():
        return
    for path in sorted(base.rglob("*")):
        # rglob does not descend into a symlinked dir target, but a symlink entry still appears; the
        # confinement check below refuses it explicitly.
        if any(part == ".git" or part == "__pycache__" for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            raise Fable5InventoryError(f"symlink is not permitted in the audited tree: {path}")
        if path.is_file():
            yield path


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _structural_scan(root: Path) -> dict[str, Any]:
    """Walk every scanned root once, failing closed on symlink/traversal/dup/unexpected-exec, and
    return the flat file map {relpath: sha256} used as the drift baseline."""
    seen_normalized: dict[str, str] = {}
    file_hashes: dict[str, str] = {}
    executables: list[str] = []
    for rel_root in _SCANNED_ROOTS:
        for path in _iter_files(root, rel_root):
            _require_confined(root, path)
            relpath = _rel(root, path)
            if relpath == FABLE5_INVENTORY_RELPATH:
                # The inventory cannot contain its own hash; it is excluded from the drift baseline
                # so that build-then-verify is stable. It is still structurally confined above.
                continue
            norm = relpath.casefold()
            if norm in seen_normalized and seen_normalized[norm] != relpath:
                raise Fable5InventoryError(
                    f"duplicate normalized path collision: {relpath} vs {seen_normalized[norm]}"
                )
            seen_normalized[norm] = relpath
            file_hashes[relpath] = _sha256_file(path)
            mode = path.stat().st_mode
            if mode & 0o111:  # any execute bit set
                executables.append(relpath)
    if executables:
        raise Fable5InventoryError(
            "unexpected executable file(s) in the audited tree: " + ", ".join(sorted(executables))
        )
    return file_hashes


def _enumerate_modules(root: Path) -> list[str]:
    return sorted(_rel(root, p) for p in _iter_files(root, "src/eth_research") if p.suffix == ".py")


def _enumerate_cli_mains(root: Path) -> list[str]:
    """Modules that expose a ``__main__`` entrypoint (``if __name__ == "__main__"``)."""
    mains: list[str] = []
    for p in _iter_files(root, "src/eth_research"):
        if p.suffix != ".py":
            continue
        text = p.read_text(encoding="utf-8", errors="strict")
        if '__name__ == "__main__"' in text or "__name__ == '__main__'" in text:
            mains.append(_rel(root, p))
    return sorted(mains)


def _enumerate_console_scripts(root: Path) -> list[str]:
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    scripts: list[str] = []
    in_scripts = False
    for line in pyproject.splitlines():
        stripped = line.strip()
        if stripped.startswith("[project.scripts]"):
            in_scripts = True
            continue
        if in_scripts:
            if stripped.startswith("["):
                break
            if "=" in stripped and stripped:
                scripts.append(stripped.split("=", 1)[0].strip())
    return sorted(scripts)


def _enumerate_workflows(root: Path) -> dict[str, dict[str, Any]]:
    wf: dict[str, dict[str, Any]] = {}
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.exists():
        return wf
    for path in sorted(wf_dir.iterdir()):
        if path.suffix not in (".yml", ".yaml") or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        wf[path.name] = {
            "sha256": _sha256_file(path),
            "declares_write_permission": bool(_WRITE_PERMISSION_RE.search(text)),
            "uses_secrets": ("secrets." in text),
            "has_unpinned_uses": _has_unpinned_uses(text),
        }
    return wf


_USES_RE = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)
_SHA_PIN_RE = re.compile(r"@[0-9a-f]{40}$")


def _has_unpinned_uses(text: str) -> bool:
    for m in _USES_RE.finditer(text):
        ref = m.group(1).strip().strip("'\"")
        if ref.startswith("./"):
            continue  # local composite action
        if not _SHA_PIN_RE.search(ref):
            return True
    return False


def _enumerate_governed(root: Path) -> dict[str, str]:
    governed: dict[str, str] = {}
    for rel_root in ("governance", "release"):
        for path in _iter_files(root, rel_root):
            relpath = _rel(root, path)
            if relpath == FABLE5_INVENTORY_RELPATH:
                continue  # the inventory cannot record its own hash
            governed[relpath] = _sha256_file(path)
    return governed


def _enumerate_sealed_ledgers(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rel in SEALED_LEDGER_RELPATHS:
        p = root / rel
        size = p.stat().st_size if p.exists() else None
        out[rel] = {
            "exists": p.exists(),
            "bytes": size,
            "sha256": _sha256_file(p) if p.exists() else None,
        }
    return out


def _enumerate_inactive_templates(root: Path) -> list[str]:
    return sorted(
        _rel(root, p)
        for r in _SCANNED_ROOTS
        for p in _iter_files(root, r)
        if p.suffix == ".inactive"
    )


def _public_api(root: Path) -> list[str]:
    """The declared public API surface, read from ``eth_research/api/__init__.py``'s ``__all__``
    literal (parsed statically — no import, so the inventory needs no installed package)."""
    text = (root / "src/eth_research/api/__init__.py").read_text(encoding="utf-8")
    m = re.search(r"__all__\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if not m:
        raise Fable5InventoryError("could not locate __all__ in eth_research.api")
    names = re.findall(r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", m.group(1))
    return sorted(set(names))


def _classify(root: Path, governed: dict[str, str]) -> dict[str, list[str]]:
    """Group governed paths into audit categories (registry/ledger/archive/freeze/contract)."""

    def match(pred: Any) -> list[str]:
        return sorted(p for p in governed if pred(p))

    return {
        "registries": match(lambda p: p.endswith("registry.jsonl") or "_registry" in Path(p).name),
        "source_freezes": match(lambda p: "source_freeze" in p or p.endswith("freeze.json")),
        "activation_anchors": match(lambda p: "activation" in Path(p).name),
        "supersessions": match(lambda p: "supersession" in p),
        "archives": match(lambda p: "/qualifications/" in p or "/archive" in p),
        "runtime_contracts": match(lambda p: "runtime_contract" in p),
    }


def build_system_inventory(repo_root: str | Path) -> dict[str, Any]:
    """Deterministically enumerate the platform surface from committed bytes under ``repo_root``.

    Runs the structural fail-closed scan as a side effect; raises :class:`Fable5InventoryError` on a
    symlink, traversal, duplicate normalized path, or unexpected executable.
    """
    root = Path(repo_root)
    file_hashes = _structural_scan(root)  # fail-closed structural gate
    governed = _enumerate_governed(root)
    inventory: dict[str, Any] = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "scanned_roots": list(_SCANNED_ROOTS),
        "package_modules": _enumerate_modules(root),
        "public_api": _public_api(root),
        "console_scripts": _enumerate_console_scripts(root),
        "cli_module_mains": _enumerate_cli_mains(root),
        "workflows": _enumerate_workflows(root),
        "governed_artifacts": governed,
        "sealed_ledgers": _enumerate_sealed_ledgers(root),
        "inactive_templates": _enumerate_inactive_templates(root),
        "categories": _classify(root, governed),
        "tracked_file_count": len(file_hashes),
    }
    # The surface digest covers only the enumerated *classified* surface (modules, public API, CLIs,
    # workflows, governed artifacts, sealed ledgers, inactive templates, categories). It
    # deliberately excludes ``tracked_file_count`` and ``scanned_roots`` so that adding a test or a
    # doc — neither of which is a classified surface — does not spuriously trip drift; a
    # symlink/exec/traversal in any scanned root is still caught by the structural scan, which
    # raises before this point.
    _digest_keys = (
        "package_modules",
        "public_api",
        "console_scripts",
        "cli_module_mains",
        "workflows",
        "governed_artifacts",
        "sealed_ledgers",
        "inactive_templates",
        "categories",
    )
    inventory["surface_digest"] = hashlib.sha256(
        canonical_json_bytes({k: inventory[k] for k in _digest_keys})
    ).hexdigest()
    return inventory


def _diff_keys(name: str, live: Iterable[str], stored: Iterable[str]) -> list[str]:
    live_set, stored_set = set(live), set(stored)
    problems: list[str] = []
    added = sorted(live_set - stored_set)
    removed = sorted(stored_set - live_set)
    if added:
        problems.append(f"{name}: unclassified/added: {added}")
    if removed:
        problems.append(f"{name}: missing: {removed}")
    return problems


def verify_system_inventory(repo_root: str | Path, committed: dict[str, Any]) -> list[str]:
    """Rebuild the inventory and prove it matches the committed snapshot, failing closed.

    Returns the ordered list of check names that passed; raises :class:`Fable5InventoryError` with
    an aggregated message on any drift or structural red flag.
    """
    live = build_system_inventory(repo_root)
    problems: list[str] = []

    problems += _diff_keys("package_modules", live["package_modules"], committed["package_modules"])
    problems += _diff_keys("public_api", live["public_api"], committed["public_api"])
    problems += _diff_keys("console_scripts", live["console_scripts"], committed["console_scripts"])
    problems += _diff_keys(
        "cli_module_mains", live["cli_module_mains"], committed["cli_module_mains"]
    )
    problems += _diff_keys("workflows", live["workflows"], committed["workflows"])
    problems += _diff_keys(
        "governed_artifacts", live["governed_artifacts"], committed["governed_artifacts"]
    )
    problems += _diff_keys(
        "inactive_templates", live["inactive_templates"], committed["inactive_templates"]
    )

    # Governed-artifact byte neutrality: every governed path present in both must be byte-identical.
    for path, digest in committed["governed_artifacts"].items():
        if path in live["governed_artifacts"] and live["governed_artifacts"][path] != digest:
            problems.append(f"governed_artifacts: byte drift at {path}")

    # Workflow write-permission escalation is forbidden regardless of drift.
    for name, meta in live["workflows"].items():
        if meta["declares_write_permission"]:
            problems.append(f"workflow {name}: declares a write permission (forbidden)")
        if meta["uses_secrets"]:
            problems.append(f"workflow {name}: references a secret (forbidden)")
        if meta["has_unpinned_uses"]:
            problems.append(f"workflow {name}: has an unpinned action ref (forbidden)")

    # Sealed ledgers must be byte-empty.
    for rel, meta in live["sealed_ledgers"].items():
        if not meta["exists"] or meta["bytes"] != 0 or meta["sha256"] != _EMPTY_SHA256:
            problems.append(f"sealed ledger {rel}: not byte-empty ({meta})")

    if live["surface_digest"] != committed.get("surface_digest"):
        problems.append(
            "surface_digest drift: live "
            f"{live['surface_digest']} != committed {committed.get('surface_digest')}"
        )

    if problems:
        raise Fable5InventoryError(
            "system inventory verification failed:\n  - " + "\n  - ".join(problems)
        )

    return [
        "modules_match",
        "public_api_match",
        "console_scripts_match",
        "cli_mains_match",
        "workflows_match",
        "governed_artifacts_match",
        "governed_byte_neutral",
        "inactive_templates_match",
        "no_workflow_write_permission",
        "no_workflow_secret",
        "no_unpinned_action",
        "sealed_ledgers_byte_empty",
        "surface_digest_match",
    ]
