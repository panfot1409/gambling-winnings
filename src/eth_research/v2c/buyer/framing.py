"""V2C section 24: bounded, length-prefixed JSON framing for the buyer boundary.

Every message on the buyer boundary is a canonical-JSON object preceded by a 4-byte big-endian
unsigned length. Reads and writes are size-bounded on both sides, so a hostile or buggy peer can
neither overrun memory nor smuggle a partial/oversized frame. Frames are decoded with the strict
loader (duplicate-key / NaN / Infinity / overflow rejecting); there is **no pickle and no eval**.
"""

from __future__ import annotations

from typing import BinaryIO

from eth_research._json import strict_json_loads
from eth_research.v2.strict import V2ValidationError, canonical_json_bytes, require_mapping

_LENGTH_PREFIX_BYTES: int = 4
#: Hard ceiling on a single frame's JSON body (256 KiB). Requests are far smaller; responses carry
#: at most one redacted artifact.
MAX_FRAME_BYTES: int = 256 * 1024


class FramingError(V2ValidationError):
    """A frame was malformed, truncated, or exceeded the size bound."""


def _read_exactly(stream: BinaryIO, count: int) -> bytes | None:
    """Read exactly ``count`` bytes. Return ``None`` on a clean EOF at a frame boundary; raise on a
    partial read (a truncated frame)."""
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            if not chunks and remaining == count:
                return None  # clean EOF between frames
            raise FramingError("truncated frame (stream closed mid-frame)")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def write_frame(stream: BinaryIO, payload: object, *, max_bytes: int = MAX_FRAME_BYTES) -> int:
    """Serialize ``payload`` to canonical JSON and write it as a length-prefixed frame.

    Returns the number of body bytes written. Raises :class:`FramingError` if the body exceeds
    ``max_bytes`` (nothing is written in that case).
    """
    body = canonical_json_bytes(payload)
    if len(body) > max_bytes:
        raise FramingError(f"frame body {len(body)} exceeds the {max_bytes}-byte bound")
    stream.write(len(body).to_bytes(_LENGTH_PREFIX_BYTES, "big"))
    stream.write(body)
    stream.flush()
    return len(body)


def read_frame(stream: BinaryIO, *, max_bytes: int = MAX_FRAME_BYTES) -> dict[str, object] | None:
    """Read one length-prefixed frame and strictly decode it to a JSON object.

    Returns ``None`` on a clean EOF (no more frames). Raises :class:`FramingError` on a truncated
    frame or one whose declared length exceeds ``max_bytes``.
    """
    header = _read_exactly(stream, _LENGTH_PREFIX_BYTES)
    if header is None:
        return None
    length = int.from_bytes(header, "big")
    if length > max_bytes:
        raise FramingError(f"declared frame length {length} exceeds the {max_bytes}-byte bound")
    if length == 0:
        raise FramingError("empty frame is not allowed")
    body = _read_exactly(stream, length)
    if body is None:
        raise FramingError("frame header present but body is missing")
    try:
        decoded = strict_json_loads(body)
    except (ValueError, TypeError) as exc:
        raise FramingError(f"frame body is not strict JSON: {exc}") from exc
    return require_mapping("frame", decoded)


__all__ = [
    "MAX_FRAME_BYTES",
    "FramingError",
    "read_frame",
    "write_frame",
]
