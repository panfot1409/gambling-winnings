"""Transactional publication of the V2B one-shot results into an immutable archive.

Publication writes the results artifact and an archive manifest that binds it by SHA-256, so a
published run is a self-describing, verifiable bundle. It is transactional: both files are staged
durably and swapped into place together, and :func:`verify_publication` re-checks the manifest
against the committed bytes. Publication never advances the registry — the experiment driver appends
the ``completed`` event after a successful publish.
"""

from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

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
)
from eth_research.v2b import V2B_DIR
from eth_research.v2b.results import FrozenV2BResults, summarize_committed

PUBLICATION_SCHEMA_VERSION: int = 1

RESULTS_NAME: str = "v2b_results.json"
MANIFEST_NAME: str = "v2b_results_manifest.json"


class V2BPublicationError(V2ValidationError):
    """A results bundle could not be published or failed verification."""


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    """What was written and the digests that describe it."""

    results_path: str
    manifest_path: str
    results_sha256: str
    results_fingerprint: str


def _manifest(results: FrozenV2BResults, results_bytes: bytes) -> dict[str, object]:
    return {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "run_id": results.run_id,
        "results_file": RESULTS_NAME,
        "results_sha256": sha256_bytes(results_bytes),
        "results_fingerprint": results.fingerprint(),
        "nominated_candidate_id": results.nominated_candidate_id,
        "verdict": results.verdict,
    }


def _stage(path: Path, data: bytes) -> Path:
    """Write ``data`` to an fsync'd tmp file beside ``path`` and return the tmp path."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    return tmp


def _fsync_dir(path: Path) -> None:
    with suppress(OSError):  # pragma: no cover - best-effort directory durability
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def publish_results(repo_root: str | Path, results: FrozenV2BResults) -> PublicationReceipt:
    """Write the results + manifest atomically under ``research/v2b`` and verify them."""
    out_dir = Path(repo_root) / V2B_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / RESULTS_NAME
    manifest_path = out_dir / MANIFEST_NAME

    results_bytes = canonical_json_bytes(results.to_canonical())
    manifest_bytes = canonical_json_bytes(_manifest(results, results_bytes))

    # Stage BOTH durable tmp files first, then swap both into place, then fsync the directory.
    # A crash between the two swaps still leaves a state that verify_publication detects.
    results_tmp = _stage(results_path, results_bytes)
    manifest_tmp = _stage(manifest_path, manifest_bytes)
    os.replace(results_tmp, results_path)
    os.replace(manifest_tmp, manifest_path)
    _fsync_dir(out_dir)

    problems = verify_publication(repo_root)
    if problems:
        raise V2BPublicationError("; ".join(problems))

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
        "verdict",
    }
)


def verify_publication(repo_root: str | Path) -> list[str]:
    """Return every mismatch between the manifest and the committed results (empty == sound)."""
    out_dir = Path(repo_root) / V2B_DIR
    results_path = out_dir / RESULTS_NAME
    manifest_path = out_dir / MANIFEST_NAME

    if not results_path.exists() or not manifest_path.exists():
        return [f"missing published results or manifest under {V2B_DIR}"]

    results_bytes = results_path.read_bytes()
    try:
        manifest = require_mapping("manifest", load_canonical_json(manifest_path))
        require_exact_keys("manifest", manifest, _MANIFEST_KEYS)
        require_int("manifest.schema_version", manifest["schema_version"])
        require_nonempty_str("manifest.run_id", manifest["run_id"])
        require_nonempty_str("manifest.verdict", manifest["verdict"])
        recorded_sha = require_hex64("manifest.results_sha256", manifest["results_sha256"])
        recorded_fp = require_hex64("manifest.results_fingerprint", manifest["results_fingerprint"])
        summary = summarize_committed(results_bytes)
    except V2ValidationError as exc:
        return [str(exc)]

    problems: list[str] = []
    if sha256_bytes(results_bytes) != recorded_sha:
        problems.append("manifest results_sha256 does not match the results bytes")
    if summary.fingerprint != recorded_fp:
        problems.append("manifest results_fingerprint does not match the committed results")
    if manifest["run_id"] != summary.run_id:
        problems.append("manifest run_id disagrees with the results")
    if manifest["nominated_candidate_id"] != summary.nominated_candidate_id:
        problems.append("manifest nominated_candidate_id disagrees with the results decision")
    if manifest["verdict"] != summary.verdict:
        problems.append("manifest verdict disagrees with the results")
    return problems


__all__ = [
    "MANIFEST_NAME",
    "PUBLICATION_SCHEMA_VERSION",
    "RESULTS_NAME",
    "PublicationReceipt",
    "V2BPublicationError",
    "publish_results",
    "verify_publication",
]
