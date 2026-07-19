"""Transactional publication of the V2A research results into an immutable archive.

Publication writes the results artifact and an archive manifest that binds it by SHA-256, so a
published run is a self-describing, verifiable bundle. It is transactional: the bytes are staged and
only swapped into place together, and :func:`verify_publication` re-checks the manifest against the
committed bytes.

Publication never advances the registry itself — the orchestrator appends the ``completed`` event
after a successful publish — and it never emits a reserved claim status (the results it writes are
already constitution-validated).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from eth_research.v2.results import FrozenResearchResults, parse_results
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    load_canonical_json,
    require_exact_keys,
    require_hex64,
    require_int,
    require_mapping,
    require_nonempty_str,
    sha256_bytes,
    strict_json_loads,
)

PUBLICATION_SCHEMA_VERSION: int = 1

V2A_DIR: str = "research/v2a"
RESULTS_NAME: str = "results.json"
MANIFEST_NAME: str = "results_manifest.json"


class PublicationError(V2ValidationError):
    """A results bundle could not be published or failed verification."""


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    """What was written and the digests that describe it."""

    results_path: str
    manifest_path: str
    results_sha256: str
    results_fingerprint: str


def _manifest(results: FrozenResearchResults, results_bytes: bytes) -> dict[str, object]:
    return {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "run_id": results.run_id,
        "results_file": RESULTS_NAME,
        "results_sha256": sha256_bytes(results_bytes),
        "results_fingerprint": results.fingerprint(),
        "nominated_candidate_id": results.nominated_candidate_id,
    }


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def publish_results(repo_root: str | Path, results: FrozenResearchResults) -> PublicationReceipt:
    """Write the results + manifest atomically under ``research/v2a`` and verify them."""
    out_dir = Path(repo_root) / V2A_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / RESULTS_NAME
    manifest_path = out_dir / MANIFEST_NAME

    results_bytes = canonical_json_bytes(results.to_canonical())
    manifest_bytes = canonical_json_bytes(_manifest(results, results_bytes))

    # Stage both, then swap into place; verify before returning.
    _atomic_write(results_path, results_bytes)
    _atomic_write(manifest_path, manifest_bytes)

    problems = verify_publication(repo_root)
    if problems:
        raise PublicationError("; ".join(problems))

    return PublicationReceipt(
        results_path=str(results_path.relative_to(Path(repo_root))),
        manifest_path=str(manifest_path.relative_to(Path(repo_root))),
        results_sha256=sha256_bytes(results_bytes),
        results_fingerprint=results.fingerprint(),
    )


_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "results_file",
        "results_sha256",
        "results_fingerprint",
        "nominated_candidate_id",
    }
)


def verify_publication(repo_root: str | Path) -> list[str]:
    """Return every mismatch between the manifest and the committed results (empty == sound)."""
    out_dir = Path(repo_root) / V2A_DIR
    results_path = out_dir / RESULTS_NAME
    manifest_path = out_dir / MANIFEST_NAME
    problems: list[str] = []

    if not results_path.exists() or not manifest_path.exists():
        return [f"missing published results or manifest under {V2A_DIR}"]

    results_bytes = results_path.read_bytes()
    try:
        manifest = require_mapping("manifest", load_canonical_json(manifest_path))
        require_exact_keys("manifest", manifest, _MANIFEST_KEYS)
        require_int("manifest.schema_version", manifest["schema_version"])
        require_nonempty_str("manifest.run_id", manifest["run_id"])
        recorded_sha = require_hex64("manifest.results_sha256", manifest["results_sha256"])
        recorded_fp = require_hex64("manifest.results_fingerprint", manifest["results_fingerprint"])
    except V2ValidationError as exc:
        return [str(exc)]

    if sha256_bytes(results_bytes) != recorded_sha:
        problems.append("manifest results_sha256 does not match the results bytes")

    try:
        results = parse_results(strict_json_loads(results_bytes))
    except V2ValidationError as exc:
        return [*problems, f"results failed strict parse: {exc}"]

    if results.fingerprint() != recorded_fp:
        problems.append("manifest results_fingerprint does not match the parsed results")
    if manifest["nominated_candidate_id"] != results.nominated_candidate_id:
        problems.append("manifest nominated_candidate_id disagrees with the results decision")

    return problems
