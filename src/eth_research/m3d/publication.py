"""Transactional publication of the prospective evidence bundle.

The prospective cohort's derived artifacts are published all-or-nothing: every
blob is precomputed and validated first, each is written atomically (temp file,
fsync, rename) in a fixed order with the completeness marker last, and every
written file is immediately read back, reparsed strictly, and rehashed. Any
failure at any write / readback / reparse / rehash position rolls the whole batch
back — newly created files are removed and overwritten files are restored to
their exact previous bytes — so a failed publication never leaves a partial
bundle, temporary debris, or a completeness marker without its bundle.

This module is data-only: it moves and verifies bytes; it computes no strategy,
metric, ranking, or decision.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eth_research._atomic import write_atomic
from eth_research.m3d import _upstream as up
from eth_research.m3d.chain import split_ledger_lines
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_json_bytes,
    canonical_sha256,
    domain_sha256,
    load_canonical_json_bytes,
    require_list,
    require_mapping,
    require_positive_int,
    require_sha256_hex,
    require_str,
    sha256_bytes,
    strict_json_loads,
)

PUBLICATION_MANIFEST_PATH = "research/m3d/publication_manifest.json"
PUBLICATION_MANIFEST_SCHEMA_VERSION = 1
PUBLICATION_MANIFEST_KIND = "prospective_publication_manifest"
PUBLICATION_ROOT_DOMAIN = "prospective_publication_root"


class ProspectivePublicationError(M3DValidationError):
    """A transactional publication failed and was rolled back."""


def _reparse(relpath: str, data: bytes) -> None:
    """Strictly reparse published bytes (JSONL line-by-line, else strict JSON)."""
    if relpath.endswith(".jsonl"):
        for line in split_ledger_lines(data):
            strict_json_loads(line)
    else:
        strict_json_loads(data)


def publish_bundle(
    repo_root: str | Path, blobs: Sequence[tuple[str, bytes]]
) -> list[tuple[str, str]]:
    """Atomically publish precomputed ``(relpath, bytes)`` blobs with rollback.

    Each blob is written atomically, then read back, reparsed strictly, and
    rehashed before the next is written. Any failure rolls the whole batch back
    to its exact previous state. Returns ``(relpath, sha256)`` for each published
    artifact on success.
    """
    root = Path(repo_root)
    targets = [(rel, root / rel, data) for rel, data in blobs]
    if len({rel for rel, _, _ in targets}) != len(targets):
        raise ProspectivePublicationError("duplicate relpath in publication bundle")
    previous: dict[Path, bytes | None] = {
        path: (path.read_bytes() if path.exists() else None) for _, path, _ in targets
    }
    published: list[Path] = []
    try:
        digests: list[tuple[str, str]] = []
        for relpath, path, data in targets:
            write_atomic(path, data)
            published.append(path)
            readback = path.read_bytes()
            if readback != data:
                raise ProspectivePublicationError(f"readback mismatch for {relpath}")
            _reparse(relpath, readback)
            digest = sha256_bytes(readback)
            if digest != sha256_bytes(data):
                raise ProspectivePublicationError(f"rehash mismatch for {relpath}")
            digests.append((relpath, digest))
    except BaseException as exc:
        for path in reversed(published):
            original = previous[path]
            with contextlib.suppress(OSError):
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    write_atomic(path, original)
        if isinstance(exc, ProspectivePublicationError):
            raise
        raise ProspectivePublicationError(
            f"publication failed and was rolled back; no partial bundle remains ({exc})"
        ) from exc
    return digests


def build_publication_manifest_bytes(bundle_blobs: Sequence[tuple[str, bytes]]) -> bytes:
    """Render the completeness marker binding every non-marker artifact by hash.

    ``bundle_blobs`` are the precomputed ``(relpath, bytes)`` for every artifact
    except the manifest itself, so the marker is a pure function of the batch.
    """
    from eth_research.m3d import M3D_PACKAGE_VERSION

    artifacts = [
        {"path": relpath, "sha256": sha256_bytes(data)}
        for relpath, data in sorted(bundle_blobs, key=lambda item: item[0])
    ]
    document: dict[str, Any] = {
        "schema_version": PUBLICATION_MANIFEST_SCHEMA_VERSION,
        "kind": PUBLICATION_MANIFEST_KIND,
        "package_version": M3D_PACKAGE_VERSION,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
    document["publication_root_sha256"] = domain_sha256(
        PUBLICATION_ROOT_DOMAIN, {"artifacts": artifacts}
    )
    return canonical_json_bytes(document)


def publication_manifest_sha256(bundle_blobs: Sequence[tuple[str, bytes]]) -> str:
    return canonical_sha256(strict_json_loads(build_publication_manifest_bytes(bundle_blobs)))


def verify_publication_manifest(
    repo_root: str | Path, bundle_blobs: Sequence[tuple[str, bytes]]
) -> dict[str, Any]:
    """Verify the committed marker matches the batch and every artifact's bytes."""
    raw, doc = load_canonical_json_bytes(
        Path(repo_root) / PUBLICATION_MANIFEST_PATH, "publication_manifest"
    )
    mapping = require_mapping("publication_manifest", doc)
    if raw != build_publication_manifest_bytes(bundle_blobs):
        raise ProspectivePublicationError("committed publication manifest does not match the batch")
    artifacts = require_list("artifacts", mapping["artifacts"])
    require_positive_int("artifact_count", mapping["artifact_count"])
    for entry in artifacts:
        item = require_mapping("artifact", entry)
        relpath = require_str("path", item["path"])
        expected = require_sha256_hex("sha256", item["sha256"])
        if up.hash_file(repo_root, relpath) != expected:
            raise ProspectivePublicationError(f"published artifact {relpath} bytes drifted")
    return mapping
