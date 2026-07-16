"""Workflow & action inventory for Milestone 3F.

Scans every ``.github/workflows/*.yml`` and ``*.yaml`` and binds path/hash/name/
triggers/permission facts + whether each can write contents, references secrets,
contacts a market host, uploads artifacts, is scheduled, or can publish/merge, plus
every pinned action ``uses:`` target. Fails closed on: any ``contents: write`` /
``write-all`` (block or flow or comment-decoy), an unpinned (not full-SHA) action ref,
a piped installer (``curl|sh`` / ``wget|sh``), a market-data host, a plain/force push,
a tag/release/PR-merge/undraft/retarget verb, or a ``.yaml`` that would escape a
``.yml``-only scanner. The M3E standing probe may remain scheduled but read-only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
    sha256_bytes,
)

INVENTORY_RELPATH = "research/m3f/workflow_inventory.json"

_FLOW_WRITE = re.compile(r"permissions\s*:\s*\{[^}]*\bwrite(?:-all)?\b", re.IGNORECASE)
_BLOCK_WRITE = re.compile(r"^\s*[A-Za-z_-]+\s*:\s*['\"]?write(?:-all)?['\"]?\s*$", re.MULTILINE)
_REAL_PERMS = re.compile(r"^\s*permissions\s*:", re.MULTILINE)
_USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)
_SHA_PIN = re.compile(r"@[0-9a-f]{40}$")
_MARKET_HOST = re.compile(r"coinbase\.(?:com|pro)\b", re.IGNORECASE)
_PIPED_INSTALLER = re.compile(r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh", re.IGNORECASE)
_PUSH = re.compile(r"git\s+push\b", re.IGNORECASE)
_MERGE_VERBS = re.compile(
    r"gh\s+pr\s+(?:merge|ready|edit)\b|gh\s+release\s+create\b|git\s+tag\b|pulls/\d+/merge\b",
    re.IGNORECASE,
)


def _scan_one(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    name_m = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
    can_write = bool(
        "write-all" in text
        or "contents: write" in text
        or "contents:write" in text
        or _FLOW_WRITE.search(text)
        or _BLOCK_WRITE.search(text)
    )
    uses = _USES.findall(text)
    return {
        "path": path.relative_to(path.parents[2]).as_posix(),
        "sha256": sha256_bytes(text.encode("utf-8")),
        "name": (name_m.group(1).strip() if name_m else "").strip("'\""),
        "has_real_permissions_block": bool(_REAL_PERMS.search(text)),
        "can_write_contents": can_write,
        "references_secrets": "secrets." in text or "secrets:" in text,
        "contacts_market_host": bool(_MARKET_HOST.search(text)),
        "uploads_artifact": "upload-artifact" in text or "upload-pages-artifact" in text,
        "scheduled": "schedule:" in text and "cron:" in text,
        "piped_installer": bool(_PIPED_INSTALLER.search(text)),
        "can_push": bool(_PUSH.search(text)),
        "can_merge_or_release_or_tag": bool(_MERGE_VERBS.search(text)),
        "uses_targets": sorted(set(uses)),
        "uses_all_sha_pinned": all(_SHA_PIN.search(u) for u in uses),
    }


def build_inventory(repo_root: str | Path) -> dict[str, Any]:
    wf = Path(repo_root) / ".github/workflows"
    files = sorted([*wf.glob("*.yml"), *wf.glob("*.yaml")]) if wf.is_dir() else []
    entries = [_scan_one(p) for p in files]
    entries.sort(key=lambda e: e["path"])
    return {
        "schema_version": 1,
        "workflow_count": len(entries),
        "extensions_scanned": [".yml", ".yaml"],
        "workflows": entries,
    }


def check_inventory(inventory: dict[str, Any]) -> list[str]:
    """Return the list of fail-closed violations (empty == all clear)."""
    failures: list[str] = []
    for e in inventory["workflows"]:
        p = e["path"]
        if not e["has_real_permissions_block"]:
            failures.append(f"{p}: no explicit permissions block")
        if e["can_write_contents"]:
            failures.append(f"{p}: grants write contents")
        if e["contacts_market_host"]:
            failures.append(f"{p}: contacts a market host")
        if e["uploads_artifact"]:
            failures.append(f"{p}: uploads an artifact")
        if e["piped_installer"]:
            failures.append(f"{p}: uses a piped installer")
        if e["can_push"]:
            failures.append(f"{p}: contains git push")
        if e["can_merge_or_release_or_tag"]:
            failures.append(f"{p}: contains a merge/release/tag verb")
        if not e["uses_all_sha_pinned"]:
            failures.append(f"{p}: an action ref is not pinned to a full commit SHA")
    return failures


def build_and_check(repo_root: str | Path) -> tuple[dict[str, Any], list[str]]:
    inv = build_inventory(repo_root)
    return inv, check_inventory(inv)


def render_inventory_bytes(inventory: dict[str, Any]) -> bytes:
    return canonical_json_bytes(inventory)


def verify_inventory(repo_root: str | Path) -> None:
    """Committed inventory reproduces from the live workflows AND passes the checks."""
    root = Path(repo_root)
    committed = load_canonical_json((root / INVENTORY_RELPATH).read_bytes(), "workflow_inventory")
    fresh = build_inventory(root)
    if canonical_json_bytes(committed) != canonical_json_bytes(fresh):
        raise M3FValidationError("workflow inventory drifted from .github/workflows")
    failures = check_inventory(fresh)
    if failures:
        raise M3FValidationError("workflow supply-chain check failed: " + "; ".join(failures[:6]))
