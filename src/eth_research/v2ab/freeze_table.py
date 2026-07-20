"""The complete immutable freeze table over the accepted stacked milestones (section 4).

The freeze table is one strict, machine-readable manifest of every governed artifact of the accepted
milestones (V1 private GA through V2B). Each entry binds the artifact's repo-relative path,
milestone, role, byte count, and SHA-256, plus an immutable/mutable classification and its relation
to the sealed partitions. The whole table is bound by a domain-separated digest, so a single changed
byte, a changed classification, a missing artifact, an unexpected new governed artifact, or a
reordered duplicate identity is detected.

Scope: the table freezes the accepted artifacts under ``research/m*``, ``research/v2a``,
``research/v2b`` and ``release/``. The V2A-V2B acceptance tooling this package adds
(``research/v2ab/`` and the new ``research/v2/`` governance artifacts) is deliberately excluded --
that layer is the verifier side, not the frozen side, and is checked by its own verifiers. Building
the table never modifies any artifact; it only reads bytes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    require_choice,
    require_exact_keys,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_nonnegative_int,
    require_sha256_fingerprint,
    sha256_bytes,
    strict_json_loads,
)

FREEZE_TABLE_SCHEMA_VERSION: int = 1
FREEZE_TABLE_RELPATH: str = "research/v2ab/stack_freeze_table.json"

#: Domain separation tag for the table's self-binding digest (never reused by another artifact).
_DIGEST_DOMAIN: bytes = b"eth_research.v2ab.stack_freeze_table.v1\n"

#: Governed roots the table enumerates.
_FROZEN_ROOTS: tuple[str, ...] = ("research", "release")

#: Subtrees that are acceptance tooling (verifier side), not part of the frozen table.
_EXCLUDED_PREFIXES: tuple[str, ...] = ("research/v2ab/", "research/v2/")

#: The three sealed access ledgers (must be byte-empty; classified specially).
_SEALED_LEDGERS: frozenset[str] = frozenset(
    {
        "research/m3a/development_gate_access.jsonl",
        "research/m2b/test_evaluations.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    }
)

_EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

_MILESTONES: frozenset[str] = frozenset(
    {"m2b", "m3a", "m3b", "m3c", "m3d", "m3e", "m3f", "m4a", "m4b", "v2a", "v2b", "release"}
)

_ROLES: frozenset[str] = frozenset(
    {
        "sealed_access_ledger",
        "registry",
        "results",
        "manifest",
        "decision",
        "report",
        "archive",
        "budget",
        "protocol",
        "lock",
        "receipt",
        "raw_candles",
        "dataset",
        "ledger",
        "catalog",
        "policy",
        "evidence",
        "state",
        "plan",
        "other",
    }
)

_ENTRY_KEYS: frozenset[str] = frozenset(
    {"path", "milestone", "role", "byte_count", "sha256", "immutability", "sealed_relationship"}
)

_TABLE_KEYS: frozenset[str] = frozenset(
    {"schema_version", "roots", "excluded_prefixes", "entry_count", "entries", "table_digest"}
)


class FreezeTableError(V2ValidationError):
    """The freeze table was malformed, or the live tree diverged from it."""


@dataclass(frozen=True, slots=True)
class FreezeEntry:
    """One governed artifact's frozen identity."""

    path: str
    milestone: str
    role: str
    byte_count: int
    sha256: str
    immutability: str
    sealed_relationship: str

    def to_canonical(self) -> dict[str, object]:
        return {
            "path": self.path,
            "milestone": self.milestone,
            "role": self.role,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "immutability": self.immutability,
            "sealed_relationship": self.sealed_relationship,
        }


def _milestone_of(relpath: str) -> str:
    parts = relpath.split("/")
    if parts[0] == "release":
        return "release"
    if parts[0] == "research" and len(parts) > 1 and parts[1] in _MILESTONES:
        return parts[1]
    raise FreezeTableError(f"cannot classify milestone for {relpath!r}")


def _role_of(relpath: str, name: str) -> str:
    if relpath in _SEALED_LEDGERS:
        return "sealed_access_ledger"
    low = name.lower()
    # order matters: most specific first
    if low.startswith("candles_"):
        return "raw_candles"
    if "registry" in low:
        return "registry"
    if "manifest" in low:
        return "manifest"
    if "results" in low or low == "result.json":
        return "results"
    if "decision" in low:
        return "decision"
    if "report" in low:
        return "report"
    if "archive" in low:
        return "archive"
    if "budget" in low:
        return "budget"
    if "protocol" in low or "pre_registration" in low or "preregistration" in low:
        return "protocol"
    if "lock" in low:
        return "lock"
    if "receipt" in low:
        return "receipt"
    if "dataset" in low or "candles" in low or "partition" in low:
        return "dataset"
    if low.endswith(".jsonl") or "ledger" in low:
        return "ledger"
    if "catalog" in low or "index" in low:
        return "catalog"
    if "policy" in low or "constitution" in low:
        return "policy"
    if "evidence" in low or "claims" in low or "scorecard" in low or "factsheet" in low:
        return "evidence"
    if "state" in low or "readiness" in low or "memory" in low or "debt" in low:
        return "state"
    if low.endswith(".md"):
        return "plan"
    return "other"


def _immutability_of(relpath: str, role: str) -> str:
    if role == "sealed_access_ledger":
        return "sealed_empty"
    return "immutable"


def _sealed_relationship_of(relpath: str) -> str:
    if relpath in _SEALED_LEDGERS:
        return "is_sealed_access_ledger"
    return "none"


def _is_excluded(relpath: str) -> bool:
    return any(relpath.startswith(prefix) for prefix in _EXCLUDED_PREFIXES)


def _enumerate(repo_root: Path) -> list[str]:
    """Repo-relative POSIX paths of all frozen governed files (sorted, symlinks rejected)."""
    root = repo_root.resolve()
    found: list[str] = []
    for top in _FROZEN_ROOTS:
        base = root / top
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            for fn in sorted(filenames):
                abspath = Path(dirpath) / fn
                if abspath.is_symlink():
                    raise FreezeTableError(
                        f"symlink is not permitted under a governed root: {abspath}"
                    )
                relpath = abspath.relative_to(root).as_posix()
                if _is_excluded(relpath):
                    continue
                found.append(relpath)
    found.sort()
    return found


def _entry_for(repo_root: Path, relpath: str) -> FreezeEntry:
    abspath = (repo_root.resolve() / relpath).resolve()
    root = repo_root.resolve()
    if root not in abspath.parents and abspath != root:
        raise FreezeTableError(f"path escapes the repository root: {relpath!r}")
    data = abspath.read_bytes()
    milestone = _milestone_of(relpath)
    role = _role_of(relpath, abspath.name)
    return FreezeEntry(
        path=relpath,
        milestone=milestone,
        role=role,
        byte_count=len(data),
        sha256=sha256_bytes(data),
        immutability=_immutability_of(relpath, role),
        sealed_relationship=_sealed_relationship_of(relpath),
    )


def _table_body(entries: list[FreezeEntry]) -> dict[str, object]:
    return {
        "schema_version": FREEZE_TABLE_SCHEMA_VERSION,
        "roots": list(_FROZEN_ROOTS),
        "excluded_prefixes": list(_EXCLUDED_PREFIXES),
        "entry_count": len(entries),
        "entries": [e.to_canonical() for e in entries],
    }


def _digest_of_body(body: dict[str, object]) -> str:
    return sha256_bytes(_DIGEST_DOMAIN + canonical_json_bytes(body))


def build_freeze_table(repo_root: str | Path) -> dict[str, object]:
    """Enumerate every frozen governed artifact and produce the canonical, self-bound table."""
    root = Path(repo_root)
    entries = [_entry_for(root, rp) for rp in _enumerate(root)]
    # Reject duplicate identities defensively (os.walk cannot; a caller-built list could).
    seen: set[str] = set()
    for e in entries:
        if e.path in seen:
            raise FreezeTableError(f"duplicate path in freeze table: {e.path!r}")
        seen.add(e.path)
    body = _table_body(entries)
    table = dict(body)
    table["table_digest"] = _digest_of_body(body)
    return table


def _parse_entry(label: str, raw: object) -> FreezeEntry:
    obj = require_mapping(label, raw)
    require_exact_keys(label, obj, _ENTRY_KEYS)
    return FreezeEntry(
        path=require_nonempty_str(f"{label}.path", obj["path"]),
        milestone=require_choice(f"{label}.milestone", obj["milestone"], _MILESTONES),
        role=require_choice(f"{label}.role", obj["role"], _ROLES),
        byte_count=require_nonnegative_int(f"{label}.byte_count", obj["byte_count"]),
        sha256=require_sha256_fingerprint(f"{label}.sha256", obj["sha256"]),
        immutability=require_choice(
            f"{label}.immutability",
            obj["immutability"],
            frozenset({"immutable", "sealed_empty"}),
        ),
        sealed_relationship=require_choice(
            f"{label}.sealed_relationship",
            obj["sealed_relationship"],
            frozenset({"none", "is_sealed_access_ledger"}),
        ),
    )


def parse_freeze_table(raw_bytes: bytes) -> tuple[list[FreezeEntry], str]:
    """Strictly parse committed freeze-table bytes; re-verify the self-binding digest.

    Returns the parsed entries (in committed order) and the recomputed table digest.
    """
    obj = require_mapping("freeze_table", strict_json_loads(raw_bytes))
    require_exact_keys("freeze_table", obj, _TABLE_KEYS)
    if obj["schema_version"] != FREEZE_TABLE_SCHEMA_VERSION:
        raise FreezeTableError("unexpected freeze-table schema_version")
    entries = require_list("freeze_table.entries", obj["entries"], _parse_entry)
    count = require_nonnegative_int("freeze_table.entry_count", obj["entry_count"])
    if count != len(entries):
        raise FreezeTableError("entry_count does not match the number of entries")
    # Reject reordered duplicate identities and out-of-order entries (canonical order is strict).
    paths = [e.path for e in entries]
    if len(set(paths)) != len(paths):
        raise FreezeTableError("duplicate path identity in committed freeze table")
    if paths != sorted(paths):
        raise FreezeTableError("freeze-table entries are not in canonical (sorted) path order")
    body = _table_body(entries)
    recomputed = _digest_of_body(body)
    committed = require_sha256_fingerprint("freeze_table.table_digest", obj["table_digest"])
    if recomputed != committed:
        raise FreezeTableError("freeze-table self digest does not bind the committed entries")
    return entries, recomputed


def verify_freeze_table(repo_root: str | Path) -> list[str]:
    """Compare the committed freeze table against the live tree; return problems (empty list = OK).

    Detects: a missing committed artifact, an unlisted governed artifact, a symlink, a traversal
    escape, a duplicate/reordered path identity, changed bytes, a changed role/milestone/class, and
    a broken self digest. Never mutates anything.
    """
    root = Path(repo_root).resolve()
    problems: list[str] = []

    table_path = root / FREEZE_TABLE_RELPATH
    if not table_path.exists():
        return [f"freeze table is missing at {FREEZE_TABLE_RELPATH}"]
    try:
        committed_entries, _ = parse_freeze_table(table_path.read_bytes())
    except V2ValidationError as exc:
        return [f"freeze table failed strict parse: {exc}"]

    committed_by_path = {e.path: e for e in committed_entries}

    try:
        live_paths = _enumerate(root)
    except FreezeTableError as exc:
        return [f"live enumeration failed: {exc}"]

    live_set = set(live_paths)
    committed_set = set(committed_by_path)

    for missing in sorted(committed_set - live_set):
        problems.append(f"committed artifact is missing from the tree: {missing}")
    for extra in sorted(live_set - committed_set):
        problems.append(f"unlisted governed artifact present in the tree: {extra}")

    for relpath in sorted(committed_set & live_set):
        want = committed_by_path[relpath]
        try:
            have = _entry_for(root, relpath)
        except V2ValidationError as exc:
            problems.append(f"{relpath}: could not re-derive entry: {exc}")
            continue
        if have.sha256 != want.sha256 or have.byte_count != want.byte_count:
            problems.append(f"{relpath}: bytes changed (sha/byte-count mismatch)")
        if have.role != want.role:
            problems.append(f"{relpath}: role changed ({want.role} -> {have.role})")
        if have.milestone != want.milestone:
            problems.append(f"{relpath}: milestone changed ({want.milestone} -> {have.milestone})")
        if have.immutability != want.immutability:
            problems.append(f"{relpath}: immutability classification changed")
        if relpath in _SEALED_LEDGERS and want.sha256 != _EMPTY_SHA256:
            problems.append(f"{relpath}: sealed ledger is not byte-empty in the freeze table")

    return problems


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Build or verify the V2A-V2B stack freeze table.")
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--build", action="store_true", help="Print the canonical freeze table to stdout."
    )
    group.add_argument(
        "--check", action="store_true", help="Verify the committed table against the tree."
    )
    args = parser.parse_args(argv)

    if args.build:
        table = build_freeze_table(args.repo_root)
        os.write(1, canonical_json_bytes(table))
        return 0
    problems = verify_freeze_table(args.repo_root)
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "FREEZE_TABLE_RELPATH",
    "FREEZE_TABLE_SCHEMA_VERSION",
    "FreezeEntry",
    "FreezeTableError",
    "build_freeze_table",
    "parse_freeze_table",
    "verify_freeze_table",
]
