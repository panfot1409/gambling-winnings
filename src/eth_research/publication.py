"""Durable, rollback-safe batch publication of committed artifacts.

Publication is an explicit transaction with a verify-before-commit phase, so
read-back, strict-parse, reconciliation failures roll the whole tree back
instead of leaving finished-looking artifacts behind (closure defects N2-N5,
originally R2)::

    with prepare_batch(root, artifacts) as txn:
        txn.replace_all()
        txn.verify(callback)   # runs while rollback is still possible
        txn.commit()

Guarantees:

* every artifact path is a canonical safe repository-relative path — no ``..``,
  ``.`` or empty segment, no absolute/drive/backslash/NUL, no symlink in any
  parent component, and the resolved target stays inside the canonical root
  (enforced by the primitive itself, N2);
* all bytes are precomputed; each is written to a unique ``O_EXCL`` temp in its
  destination directory and ``fsync``-ed, never clobbering a pre-existing file
  (N3);
* immutable per-run paths are refused if they already exist; only declared
  compatibility aliases may be replaced;
* the completeness marker (manifest/bundle) is replaced last;
* the caller's ``verify`` callback runs after ``replace_all`` but before
  ``commit`` — a failure there rolls back to the exact prior bytes (N4);
* on rollback every replaced final is restored (or removed if new) through a
  unique fsynced temp, created directories are removed, and every touched
  directory is ``fsync``-ed; if rollback itself fails a distinct
  :class:`PublicationCatastrophe` is raised rather than a false "restored"
  claim (N5);
* a repository-level lock refuses two concurrent publications rather than
  interleaving them.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType


class PublicationError(RuntimeError):
    """A batch publication failed; the tree was restored to its prior state."""


class PublicationCatastrophe(RuntimeError):
    """Rollback itself failed; the tree is in an unknown, un-restored state."""


@dataclass(frozen=True)
class Artifact:
    """One file to publish: a repo-relative path, its bytes, and its policy."""

    relpath: str
    data: bytes
    immutable: bool = False  # True: refuse if the final already exists
    is_completeness_marker: bool = False  # replaced last (the manifest/bundle)


@dataclass
class _Prepared:
    final: Path
    temp: Path
    prior: bytes | None
    created_dirs: tuple[Path, ...]


@dataclass
class _Txn:
    prepared: list[_Prepared] = field(default_factory=list)
    replaced: list[_Prepared] = field(default_factory=list)


_LOCK_RELNAME = ".m3a_publish.lock"
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _require_safe_relpath(relpath: object) -> list[str]:
    """Validate a canonical safe POSIX repository-relative path; return its parts."""
    if not isinstance(relpath, str) or not relpath:
        raise PublicationError("artifact path must be a non-empty string")
    if relpath != relpath.strip() or "\x00" in relpath or "\\" in relpath:
        raise PublicationError(f"artifact path {relpath!r} has whitespace/backslash/NUL")
    if relpath.startswith("/") or (len(relpath) >= 2 and relpath[1] == ":"):
        raise PublicationError(f"artifact path {relpath!r} must be relative (no root/drive)")
    parts = relpath.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PublicationError(f"artifact path {relpath!r} has empty/dot/dotdot segments")
    if any(not _SAFE_SEGMENT.match(part) for part in parts):
        raise PublicationError(f"artifact path {relpath!r} has an unsafe segment")
    if os.path.normpath(relpath) != relpath:
        raise PublicationError(f"artifact path {relpath!r} is not in normalized form")
    return parts


def _resolve_within_root(root: Path, relpath: str) -> tuple[Path, tuple[Path, ...]]:
    """Return the safe final path and the list of parent dirs that must be created.

    Rejects any symlinked parent component and any target that resolves outside
    the canonical root.
    """
    parts = _require_safe_relpath(relpath)
    root_resolved = root.resolve()
    final = root / relpath
    to_create: list[Path] = []
    cur = root
    for part in parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            raise PublicationError(f"parent component {cur} of {relpath!r} is a symlink")
        if not cur.exists():
            to_create.append(cur)
        elif not cur.is_dir():
            raise PublicationError(f"parent component {cur} of {relpath!r} is not a directory")
    if final.is_symlink():
        raise PublicationError(f"target {relpath} is a symlink")
    if final.exists() and not final.is_file():
        raise PublicationError(f"target {relpath} is not a regular file")
    # The existing portion of the destination must resolve inside the root.
    existing_parent = final.parent
    while not existing_parent.exists():
        existing_parent = existing_parent.parent
    resolved = existing_parent.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise PublicationError(f"target {relpath} resolves outside the repository root")
    return final, tuple(to_create)


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_temp(final: Path, data: bytes) -> Path:
    """Write ``data`` to a unique O_EXCL temp beside ``final``; never clobber."""
    fd, name = tempfile.mkstemp(prefix=f".{final.name}.", suffix=".tmp", dir=str(final.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise
    return Path(name)


def _replace(temp: Path, final: Path) -> None:
    os.replace(temp, final)


class _Transaction:
    """A durable, rollback-safe batch publication with a verify-before-commit phase."""

    def __init__(self, repo_root: str | Path, artifacts: list[Artifact]) -> None:
        self.root = Path(repo_root)
        if not self.root.is_dir():
            raise PublicationError(f"publication root {self.root} is not a directory")
        if not artifacts:
            raise PublicationError("no artifacts to publish")
        ordered = [a for a in artifacts if not a.is_completeness_marker]
        ordered += [a for a in artifacts if a.is_completeness_marker]
        seen: set[str] = set()
        for artifact in ordered:
            if artifact.relpath in seen:
                raise PublicationError(f"duplicate artifact path {artifact.relpath!r}")
            seen.add(artifact.relpath)
        self._artifacts = ordered
        self._txn = _Txn()
        self._committed = False
        self._lock_fd: int | None = None

    def __enter__(self) -> _Transaction:
        lock = self.root / _LOCK_RELNAME
        try:
            self._lock_fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise PublicationError(
                "another publication is in progress (lock present); refusing to interleave"
            ) from exc
        try:
            self._prepare()
        except BaseException:
            self._release_lock()
            raise
        return self

    def _prepare(self) -> None:
        for artifact in self._artifacts:
            final, to_create = _resolve_within_root(self.root, artifact.relpath)
            if artifact.immutable and final.exists():
                raise PublicationError(
                    f"immutable artifact {artifact.relpath} already exists; never overwritten"
                )
            for directory in to_create:
                directory.mkdir()
            prior = final.read_bytes() if final.exists() else None
            temp = _write_temp(final, artifact.data)
            self._txn.prepared.append(
                _Prepared(final=final, temp=temp, prior=prior, created_dirs=to_create)
            )

    def replace_all(self) -> None:
        for prep in self._txn.prepared:
            _replace(prep.temp, prep.final)
            self._txn.replaced.append(prep)

    def verify(self, callback: Callable[[Path], None]) -> None:
        """Run ``callback(root)`` while rollback is still possible."""
        callback(self.root)

    def commit(self) -> None:
        for directory in {prep.final.parent for prep in self._txn.prepared}:
            _fsync_dir(directory)
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if not self._committed:
                self._rollback()
        finally:
            self._release_lock()

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            with contextlib.suppress(OSError):  # pragma: no cover - best effort
                (self.root / _LOCK_RELNAME).unlink()
            self._lock_fd = None

    def _rollback(self) -> None:
        # Content restoration is what defines success: if a replaced final cannot
        # be restored (or a new final removed), the tree is genuinely unknown and
        # a catastrophe is raised. A failure to fsync an already-restored
        # directory only degrades durability and must not mask a good restore.
        try:
            for prep in reversed(self._txn.replaced):
                if prep.prior is None:
                    if prep.final.exists():
                        prep.final.unlink()
                else:
                    restore = _write_temp(prep.final, prep.prior)
                    _replace(restore, prep.final)
            for prep in self._txn.prepared:
                if prep.temp.exists():
                    prep.temp.unlink()
                for directory in reversed(prep.created_dirs):
                    if directory.is_dir() and not any(directory.iterdir()):
                        directory.rmdir()
        except OSError as exc:
            raise PublicationCatastrophe(
                f"rollback failed; the tree may be partially published: {exc}"
            ) from exc
        for prep in self._txn.replaced:
            with contextlib.suppress(OSError):  # pragma: no cover - degraded durability only
                _fsync_dir(prep.final.parent)


def prepare_batch(repo_root: str | Path, artifacts: list[Artifact]) -> _Transaction:
    """Open a publication transaction (prepares temps on ``__enter__``)."""
    return _Transaction(repo_root, artifacts)


def publish_batch(
    repo_root: str | Path,
    artifacts: list[Artifact],
    verify: Callable[[Path], None] | None = None,
) -> None:
    """Publish ``artifacts`` as one durable, rollback-safe transaction.

    ``verify``, if given, runs after all finals are replaced but before commit,
    so a verification failure restores the exact prior bytes. On any failure the
    prior tree state is restored and :class:`PublicationError` is raised.
    """
    try:
        with prepare_batch(repo_root, artifacts) as txn:
            txn.replace_all()
            if verify is not None:
                txn.verify(verify)
            txn.commit()
    except PublicationCatastrophe:
        raise
    except PublicationError:
        raise
    except Exception as exc:
        raise PublicationError(f"batch publication failed and was rolled back: {exc}") from exc
