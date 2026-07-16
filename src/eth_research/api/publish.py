"""Transactional, all-or-nothing publication of a research output bundle.

One reviewed publisher writes a multi-file CLI output bundle (``result.json``,
``report.md``, ``receipt.json``, ``manifest.json``) into a target directory with a strict
contract: every file's bytes are precomputed up front; unsafe filenames, symlinks, and
path traversal are refused; an existing file is a collision unless ``overwrite`` is set;
each file is written atomically (temp + fsync + rename); the directory is fsynced; every
written file is read back and byte-verified; and on **any** failure the whole bundle is
rolled back to its previous bytes, leaving no temporary, partial, or backup residue. A
designated completeness marker is always written last.
"""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Mapping
from pathlib import Path

from eth_research._atomic import write_atomic
from eth_research.api.errors import EthResearchError, OutputCollisionError
from eth_research.api.serialization import sha256_hex

__all__ = ["publish_bundle"]

# A publishable filename is a single flat component: alphanumeric start, then
# alphanumerics / dot / dash / underscore. No separators, no ``..``, no leading dot.
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _require_safe_filename(name: str) -> None:
    if (
        not _SAFE_FILENAME.match(name)
        or ".." in name
        or "/" in name
        or "\\" in name
        or "\x00" in name
    ):
        raise OutputCollisionError(f"unsafe output filename: {name!r}")


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_bundle(
    output_dir: str | Path,
    files: Mapping[str, bytes],
    *,
    overwrite: bool = False,
    completeness_marker: str | None = None,
) -> dict[str, str]:
    """Publish ``files`` into ``output_dir`` transactionally; return ``{name: sha256}``.

    Raises :class:`OutputCollisionError` on an unsafe name, a symlink, an existing file
    (without ``overwrite``), or a read-back mismatch. Never leaves a partial bundle.
    """
    if not files:
        raise OutputCollisionError("nothing to publish: the bundle is empty")

    out = Path(output_dir)
    if out.is_symlink():
        raise OutputCollisionError(f"output directory is a symlink: {out}")
    out.mkdir(parents=True, exist_ok=True)
    if not out.is_dir():
        raise OutputCollisionError(f"output path is not a directory: {out}")

    names = sorted(files)
    if completeness_marker is not None:
        if completeness_marker not in files:
            raise OutputCollisionError(f"completeness marker {completeness_marker!r} not in bundle")
        names = [n for n in names if n != completeness_marker] + [completeness_marker]

    targets: list[tuple[str, Path, bytes]] = []
    for name in names:
        _require_safe_filename(name)
        path = out / name
        if path.is_symlink():
            raise OutputCollisionError(f"refusing to write through a symlink: {name}")
        if path.exists() and not overwrite:
            raise OutputCollisionError(f"output file already exists: {name}")
        targets.append((name, path, files[name]))

    previous: dict[Path, bytes | None] = {
        path: (path.read_bytes() if path.exists() else None) for _, path, _ in targets
    }
    written: list[Path] = []
    try:
        for _name, path, data in targets:
            write_atomic(path, data)
            written.append(path)
        _fsync_dir(out)
        for name, path, data in targets:
            if path.read_bytes() != data:
                raise OutputCollisionError(f"read-back verification failed for {name}")
    except BaseException as exc:
        for path in reversed(written):
            original = previous[path]
            with contextlib.suppress(OSError):
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    write_atomic(path, original)
        with contextlib.suppress(OSError):
            _fsync_dir(out)
        if isinstance(exc, EthResearchError):
            raise
        raise OutputCollisionError(
            f"publication failed and was rolled back; no partial artifacts remain ({exc})"
        ) from exc

    return {name: sha256_hex(data) for name, path, data in targets}
