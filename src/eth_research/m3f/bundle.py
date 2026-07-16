"""Deterministic private recovery capsule for Milestone 3F.

A *capsule* is the minimal, byte-reproducible bundle needed to reconstruct and
replay the accepted M2B-M3E research state without the git history: every tracked
governed artifact under ``research/`` **except** the M3F verification layer, which
is itself derivable and would introduce a catalog-of-itself circularity.

The capsule bytes are private — they are never committed as a data publication
(that would merely duplicate the repository). What is committed is the *manifest*
that pins them: each file's path, SHA-256, and length, plus one ``capsule_digest``
over the whole sorted set. From the manifest the capsule can be rebuilt from the
working tree and verified byte-for-byte, and a disposable-clone recovery drill can
confirm the reconstruction re-derives the honest governance state.

The capsule carries no sealed-partition contents (the three access ledgers are
byte-empty), no secret, and no network credential — the manifest states this and
the drill enforces it.

Strictly read-only: building or verifying the manifest computes no strategy
signal, return, metric, or network call, and mutates no ledger.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from eth_research.m3f import M3F_PACKAGE_VERSION
from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
    require_int,
    require_mapping,
    require_str,
    sha256_bytes,
)

CAPSULE_MANIFEST_RELPATH = "research/m3f/recovery_capsule_manifest.json"
CAPSULE_NOTICE_RELPATH = "research/m3f/RECOVERY_CAPSULE_NOTICE.md"
CAPSULE_SCHEMA_VERSION = 1
CAPSULE_ALGORITHM = "sha256-over-sorted-path-sha256-length-lines-v1"
GOVERNED_ROOT = "research"
M3F_LAYER_PREFIX = "research/m3f/"
SEALED_LEDGERS = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class CapsuleError(M3FValidationError):
    """The recovery capsule manifest failed a strict invariant."""


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout


def capsule_files(repo_root: str | Path) -> list[str]:
    """The sorted set of tracked governed files carried by the capsule."""
    root = Path(repo_root)
    out = _git(root, "ls-files", "-z", "--", GOVERNED_ROOT + "/")
    files = [p for p in out.split("\0") if p and not p.startswith(M3F_LAYER_PREFIX)]
    return sorted(set(files))


def _digest_material(files: list[dict[str, Any]]) -> bytes:
    lines = [f"{f['path']}:{f['sha256']}:{f['byte_length']}" for f in files]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_manifest(repo_root: str | Path) -> dict[str, Any]:
    """Deterministically derive the capsule manifest from working-tree bytes."""
    root = Path(repo_root)
    files: list[dict[str, Any]] = []
    sealed_present = 0
    for rel in capsule_files(root):
        raw = (root / rel).read_bytes()
        digest = sha256_bytes(raw)
        if rel in SEALED_LEDGERS:
            sealed_present += 1
            if len(raw) != 0 or digest != EMPTY_SHA256:
                raise CapsuleError(f"sealed ledger {rel} is not byte-empty; refusing to bundle")
        files.append({"path": rel, "sha256": digest, "byte_length": len(raw)})
    files.sort(key=lambda f: f["path"])
    return {
        "schema_version": CAPSULE_SCHEMA_VERSION,
        "capsule_algorithm": CAPSULE_ALGORITHM,
        "package_version": M3F_PACKAGE_VERSION,
        "governed_root": GOVERNED_ROOT,
        "excludes": [M3F_LAYER_PREFIX, "data/", "reports/", ".github/"],
        "file_count": len(files),
        "files": files,
        "capsule_digest": sha256_bytes(_digest_material(files)),
        "sealed_ledgers_included_empty": sorted(SEALED_LEDGERS),
        "sealed_ledger_count": sealed_present,
        "contains_sealed_partition_contents": False,
        "contains_secrets_or_credentials": False,
        "reconstruction_note": (
            "private break-glass bundle; rebuild from these bytes and re-run the M3F "
            "verifiers — carries no sealed-partition contents, secret, or credential"
        ),
    }


def render_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return canonical_json_bytes(manifest)


def verify_materialized(manifest: dict[str, Any], root: str | Path) -> list[str]:
    """Re-hash every manifest file under ``root`` and re-derive the capsule digest.

    Uses only the manifest's own file list — no git — so it works against a
    disposable reconstruction that is not a repository.
    """
    base = Path(root)
    failures: list[str] = []
    files = require_mapping(manifest, "capsule_manifest").get("files", [])
    rebuilt: list[dict[str, Any]] = []
    for entry in files:
        record = require_mapping(entry, "capsule_file")
        rel = require_str(record.get("path"), "capsule_file.path")
        want = require_str(record.get("sha256"), "capsule_file.sha256")
        length = require_int(record.get("byte_length"), "capsule_file.byte_length")
        path = base / rel
        if not path.is_file():
            failures.append(f"missing {rel}")
            continue
        raw = path.read_bytes()
        got = sha256_bytes(raw)
        if got != want:
            failures.append(f"hash mismatch {rel}")
        if len(raw) != length:
            failures.append(f"length mismatch {rel}")
        rebuilt.append({"path": rel, "sha256": got, "byte_length": len(raw)})
    rebuilt.sort(key=lambda f: f["path"])
    if sha256_bytes(_digest_material(rebuilt)) != manifest.get("capsule_digest"):
        failures.append("capsule_digest does not reproduce from the materialized tree")
    return failures


def verify_manifest(repo_root: str | Path) -> None:
    """The committed manifest reproduces byte-for-byte from the working tree."""
    root = Path(repo_root)
    committed = load_canonical_json(
        (root / CAPSULE_MANIFEST_RELPATH).read_bytes(), "recovery_capsule_manifest"
    )
    fresh = build_manifest(root)
    if canonical_json_bytes(committed) != canonical_json_bytes(fresh):
        raise CapsuleError("recovery capsule manifest drifted from the working tree")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    from eth_research.m3f.cli import emit, repo_root_parser

    args = repo_root_parser("M3F recovery capsule manifest (read-only)").parse_args(argv)
    root = Path(args.repo_root)
    try:
        if (root / CAPSULE_MANIFEST_RELPATH).is_file():
            verify_manifest(root)
            emit({"ok": True, "mode": "verify_committed"}, as_json=True)
        else:
            manifest = build_manifest(root)
            emit(
                {
                    "ok": True,
                    "mode": "derive",
                    "file_count": manifest["file_count"],
                    "capsule_digest": manifest["capsule_digest"],
                },
                as_json=True,
            )
        return 0
    except (OSError, M3FValidationError) as exc:
        emit({"ok": False, "error": str(exc)}, as_json=True)
        return 1


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
