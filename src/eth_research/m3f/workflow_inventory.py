"""Workflow & action inventory for Milestone 3F.

Scans every ``.github/workflows/*.yml`` and ``*.yaml`` and binds path/hash/name/
triggers/permission facts + whether each can write contents, references secrets,
contacts a market host, uploads artifacts, is scheduled, or can publish/merge, plus
every pinned action ``uses:`` target. Fails closed on: any ``contents: write`` /
``write-all`` written as a block scalar (whitespace/tab/trailing-comment tolerant),
a flow mapping, or a YAML anchor; an unpinned (not full-SHA) action ref; a piped
installer (``curl|sh`` / ``wget|sh``) *or* a process substitution (``bash <(curl …)``);
a market-data host; a plain/force push; and a tag/release/PR-merge/undraft/retarget
or auto-merge verb, including the REST/GraphQL ref-mutation and auto-merge spellings
(``git/refs``, ``git/tags``, ``enablePullRequestAutoMerge``). The write and verb
detectors mirror the hardened M3E ``verify_m3e_program`` scanner. The M3E standing
probe may remain scheduled but read-only.

Residual (documented, not silently ignored): a regex scan cannot fully parse
arbitrary YAML or resolve a remote reusable workflow, and the market-host list names
known exchange hosts rather than proving no live egress — both are backstopped by the
``contents: read`` default token, branch protection, and mandatory human review.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
    sha256_bytes,
)

INVENTORY_RELPATH = "research/m3f/workflow_inventory.json"

# A write permission as a block scalar — any scope, any surrounding whitespace/tabs,
# quoted or not, with an optional trailing YAML comment (``contents: write # …``).
# The ``(?:#.*)?$`` clause and ``\s*`` spacing mirror the hardened M3E scanner so a
# multi-space / tab / trailing-comment grant cannot slip past.
_BLOCK_WRITE = re.compile(
    r"^\s*[A-Za-z_-]+\s*:\s*['\"]?write(?:-all)?['\"]?\s*(?:#.*)?$", re.MULTILINE
)
# A write permission as a YAML *flow* mapping — ``permissions: { contents: write }``.
_FLOW_WRITE = re.compile(r"permissions\s*:\s*\{[^}]*\bwrite(?:-all)?\b", re.IGNORECASE)
# A YAML anchor bound to a write value (``&w write``), aliased later to dodge the
# literal ``: write`` match.
_ANCHOR_WRITE = re.compile(r"&[\w-]+\s+['\"]?write(?:-all)?\b", re.IGNORECASE)
_REAL_PERMS = re.compile(r"^\s*permissions\s*:", re.MULTILINE)
_USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)
_SHA_PIN = re.compile(r"@[0-9a-f]{40}$")
# Live market-data hosts — a workflow that fetches any of these violates "all data
# frozen". Not exhaustive; the residual (arbitrary egress) is noted in the docstring.
_MARKET_HOST = re.compile(
    r"\b(?:[a-z0-9-]+\.)*(?:coinbase\.(?:com|pro)|binance\.com|kraken\.com|coingecko\.com"
    r"|coinmarketcap\.com|bitfinex\.com|kucoin\.com)\b",
    re.IGNORECASE,
)
# A remote script executed via a pipe (``curl … | sh``) OR process substitution
# (``bash <(curl …)``) — both run a downloaded script.
_PIPED_INSTALLER = re.compile(
    r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh"
    r"|<\(\s*(?:sudo\s+)?(?:curl|wget)\b",
    re.IGNORECASE,
)
# ``git push`` — tolerant of interposed ``-c <key>=<value>`` config tokens (quoted values
# included), the exact form used to push with an injected credential
# (``git -c http.extraheader="AUTHORIZATION: bearer <token>" push``).
_GIT_CONFIG_TOKENS = r"(?:-c\s+[^\s=]+(?:=(?:'[^']*'|\"[^\"]*\"|\S*))?\s+)*"
_PUSH = re.compile(rf"\bgit\s+{_GIT_CONFIG_TOKENS}push\b", re.IGNORECASE)
# Any verb that lands, tags, releases, moves a ref, or arms auto-merge — including the
# REST/GraphQL ref-mutation and auto-merge spellings the CLI forms alone would miss, and
# tolerant of interposed ``git -c`` tokens and ``gh pr`` flags (e.g. ``--repo o/r``).
_MERGE_VERBS = re.compile(
    r"gh\s+pr\s+(?:--?[A-Za-z0-9][\w-]*(?:[= ]\S+)?\s+)*(?:merge|ready|edit)\b"
    r"|gh\s+release\s+create\b"
    rf"|git\s+{_GIT_CONFIG_TOKENS}tag\b"
    r"|pulls/\d+/merge\b"
    r"|git/(?:refs|tags)\b|refs/tags/"
    r"|mergepullrequest\b|markpullrequestreadyforreview\b"
    r"|enablepullrequestautomerge|enable-pull-request-automerge|enable_pr_auto_merge|--auto\b",
    re.IGNORECASE,
)


def workflow_grants_write(text: str) -> bool:
    """True if the workflow text grants a ``contents``/``write-all`` permission in any
    block, flow, or anchored YAML form (whitespace/comment/tab tolerant)."""
    return bool(
        "write-all" in text
        or _FLOW_WRITE.search(text)
        or _BLOCK_WRITE.search(text)
        or _ANCHOR_WRITE.search(text)
    )


def _scan_one(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    name_m = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
    can_write = workflow_grants_write(text)
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


# The single authorized private-repo release-artifact channel. ``private-release-build.yml`` is a
# ``workflow_dispatch``-only, ``contents: read`` job that uploads the closed ``dist_private/``
# payload to the PRIVATE repository's own Actions artifact store — the one sanctioned way to hand a
# built private payload to an authorized maintainer (a private repo's artifacts are themselves
# access-controlled). The exemption is deliberately CONDITIONAL: it holds only while every *other*
# least-privilege protection on that same workflow entry still holds — it must not grant
# ``contents``/``write-all``, must reference no secret, and must have every action ``uses:`` pinned
# to a full commit SHA. If any of those regress the upload becomes a fail-closed violation again,
# and every *other* workflow that uploads an artifact still fails unconditionally. The exemption is
# keyed on the exact basename: a renamed copy (``evil.yml``) or a ``.yaml`` twin has a different
# basename and is NOT exempt. ``build_inventory`` globs only the top level of ``.github/workflows``
# (a non-recursive glob) and GitHub Actions never executes a nested-directory workflow, so the
# canonical top-level file is the only thing this predicate can ever see in practice. That lexical
# limit is honestly disclosed and backstopped by the adversarial evasion matrix and the closed-
# workflow-set pairing in ``tests/test_private_workflow_security.py`` and by the workflow's own
# runtime assertions (private repo, workflow_dispatch, contents:read).
_PRIVATE_RELEASE_UPLOAD_BASENAME = "private-release-build.yml"


def _artifact_upload_is_authorized(entry: dict[str, Any]) -> bool:
    """True only for the one allowlisted private-release workflow AND only while its other
    least-privilege protections still hold (no write-contents, no secret, fully SHA-pinned)."""
    return (
        Path(entry["path"]).name == _PRIVATE_RELEASE_UPLOAD_BASENAME
        and entry["can_write_contents"] is False
        and entry["references_secrets"] is False
        and entry["uses_all_sha_pinned"] is True
    )


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
        if e["uploads_artifact"] and not _artifact_upload_is_authorized(e):
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
    """Committed inventory reproduces from the FROZEN workflows AND passes the checks.

    Verifies against ``.github/workflows`` *at the M3F source-freeze commit* (immutable
    git blobs), not the live tree, so a later governed layer that adds a workflow (e.g.
    the M4A release-candidate CI) cannot invalidate this accepted, frozen artifact. Fails
    closed if the freeze commit is unreachable.
    """
    from eth_research.m3f.catalog import (
        blob_at_commit,
        frozen_source_sha,
        tracked_paths_at_commit,
    )

    root = Path(repo_root)
    committed = load_canonical_json((root / INVENTORY_RELPATH).read_bytes(), "workflow_inventory")
    freeze = frozen_source_sha(root)
    with tempfile.TemporaryDirectory() as td:
        frozen = Path(td)
        (frozen / ".github/workflows").mkdir(parents=True)
        for rel in tracked_paths_at_commit(root, freeze, ".github/workflows"):
            if rel.endswith((".yml", ".yaml")):
                (frozen / rel).write_bytes(blob_at_commit(root, freeze, rel))
        fresh = build_inventory(frozen)
        failures = check_inventory(fresh)
    if canonical_json_bytes(committed) != canonical_json_bytes(fresh):
        raise M3FValidationError("workflow inventory drifted from the frozen .github/workflows")
    if failures:
        raise M3FValidationError("workflow supply-chain check failed: " + "; ".join(failures[:6]))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    from eth_research.m3f.cli import emit, repo_root_parser

    args = repo_root_parser("M3F workflow inventory (read-only)").parse_args(argv)
    _inv, failures = build_and_check(args.repo_root)
    emit({"ok": not failures, "failures": failures}, as_json=True)
    return 0 if not failures else 1


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
