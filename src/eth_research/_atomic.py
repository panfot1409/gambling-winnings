"""Atomic file publication for provenance-bearing artifacts.

Same write discipline as the canonical dataset builder (kept deliberately
self-contained so the reviewed Milestone 2A builder stays untouched):
artifact bytes are precomputed by the caller, each file is written to a
temporary sibling, fsynced, and renamed into place, and a multi-artifact
publication rolls back to the exact previous bytes on any failure —
leaving no temporary, partial, or backup files either way.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    """Write bytes to ``path`` atomically (temp file + fsync + rename)."""
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise


def publish_atomically(
    artifacts: Sequence[tuple[Path, bytes]],
    *,
    error: Callable[[str], Exception],
) -> None:
    """All-or-nothing publication of precomputed artifact bytes.

    Artifacts are written atomically in the given order (put the
    completeness marker last). If any write fails, artifacts already
    published in this batch are rolled back — restored to their previous
    bytes when overwriting, removed when newly created — and ``error`` is
    raised with a description, chained to the original failure.
    """
    previous: dict[Path, bytes | None] = {
        path: (path.read_bytes() if path.exists() else None) for path, _ in artifacts
    }
    published: list[Path] = []
    try:
        for path, data in artifacts:
            write_atomic(path, data)
            published.append(path)
    except BaseException as exc:
        for path in reversed(published):
            original = previous[path]
            with contextlib.suppress(OSError):
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    write_atomic(path, original)
        raise error(
            f"publication failed and was rolled back; no partial artifacts remain ({exc})"
        ) from exc
