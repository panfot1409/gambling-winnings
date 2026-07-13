"""Durable, rollback-safe batch publication of committed artifacts (M3A closure R2).

The previous publisher wrote each artifact with an independent ``os.replace`` and
no ``fsync``, so a failure between the results and report writes left a mixed
pair (``results=NEW, report=OLD``) and nothing was flushed to disk. This module
publishes a whole batch as one durable transaction:

* all artifact bytes are precomputed by the caller before any final path is
  touched;
* each artifact is written to a unique temp file in its destination directory
  and ``fsync``-ed; non-regular / symlink targets are refused;
* the prior bytes of every final that will be replaced are held in memory;
* the finals are ``os.replace``-d in a deterministic order, the completeness
  marker (the manifest/bundle) last;
* the containing directories are ``fsync``-ed;
* on **any** exception the transaction rolls back in reverse — every replaced
  final is atomically restored to its prior bytes (or removed if it was new) and
  every temp file is deleted — so a failed fresh publication leaves no finals and
  a failed correction leaves every prior byte intact.

Immutable per-run paths are refused if they already exist (they are never
overwritten); only explicitly-declared compatibility aliases may be replaced.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class PublicationError(RuntimeError):
    """A batch publication failed; the tree was restored to its prior state."""


@dataclass(frozen=True)
class Artifact:
    """One file to publish: a repo-relative path, its bytes, and its policy."""

    relpath: str
    data: bytes
    immutable: bool  # True: refuse if the final already exists (per-run archive)
    is_completeness_marker: bool = False  # written last (the manifest/bundle)


@dataclass
class _Prepared:
    final: Path
    temp: Path
    prior: bytes | None


@dataclass
class _Txn:
    prepared: list[_Prepared] = field(default_factory=list)
    replaced: list[_Prepared] = field(default_factory=list)


def _fsync_file(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_temp(final: Path, data: bytes) -> Path:
    temp = final.with_name(f".{final.name}.{os.getpid()}.tmp")
    if temp.is_symlink() or (temp.exists() and not temp.is_file()):
        raise PublicationError(f"temp path {temp} is not a regular file")
    with open(temp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return temp


def _replace(temp: Path, final: Path) -> None:
    os.replace(temp, final)


def publish_batch(repo_root: str | Path, artifacts: list[Artifact]) -> None:
    """Publish ``artifacts`` as one durable, rollback-safe transaction.

    Completeness-marker artifacts are written after all others. On any failure
    the prior tree state is restored exactly and :class:`PublicationError` is
    raised.
    """
    root = Path(repo_root)
    if not artifacts:
        raise PublicationError("no artifacts to publish")
    ordered = [a for a in artifacts if not a.is_completeness_marker]
    ordered += [a for a in artifacts if a.is_completeness_marker]
    seen: set[str] = set()
    for artifact in ordered:
        if artifact.relpath in seen:
            raise PublicationError(f"duplicate artifact path {artifact.relpath!r}")
        seen.add(artifact.relpath)

    txn = _Txn()
    try:
        # Phase 1 — prepare every temp (no final touched yet).
        for artifact in ordered:
            final = root / artifact.relpath
            if final.is_symlink() or (final.exists() and not final.is_file()):
                raise PublicationError(f"target {artifact.relpath} is not a regular file")
            if artifact.immutable and final.exists():
                raise PublicationError(
                    f"immutable artifact {artifact.relpath} already exists; it is never overwritten"
                )
            final.parent.mkdir(parents=True, exist_ok=True)
            prior = final.read_bytes() if final.exists() else None
            temp = _write_temp(final, artifact.data)
            txn.prepared.append(_Prepared(final=final, temp=temp, prior=prior))

        # Phase 2 — commit every final in order, marker last.
        for prep in txn.prepared:
            _replace(prep.temp, prep.final)
            txn.replaced.append(prep)

        # Phase 3 — durability: fsync every touched directory.
        for directory in {prep.final.parent for prep in txn.prepared}:
            _fsync_dir(directory)
    except Exception as exc:
        _rollback(txn)
        raise PublicationError(f"batch publication failed and was rolled back: {exc}") from exc


def _rollback(txn: _Txn) -> None:
    """Restore every replaced final to its prior bytes and remove all temps."""
    for prep in reversed(txn.replaced):
        if prep.prior is None:
            if prep.final.exists():
                prep.final.unlink()
        else:
            restore = prep.final.with_name(f".{prep.final.name}.rollback.tmp")
            with open(restore, "wb") as handle:
                handle.write(prep.prior)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(restore, prep.final)
    for prep in txn.prepared:
        if prep.temp.exists():
            prep.temp.unlink()
