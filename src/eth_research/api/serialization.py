"""Strict, canonical JSON serialization shared by the public result/receipt/config schemas.

The canonical on-disk form matches the accepted stack exactly: sorted keys, two-space
indent, UTF-8 (no ASCII escaping), ``NaN``/``Infinity`` refused at serialize time, and
exactly one trailing newline. ``load(dump(x))`` is therefore a fixed point and every
artifact has a stable SHA-256.

Parsing routes through the one strict decoder shared by the whole repository
(:func:`eth_research._json.strict_json_loads`): duplicate keys, non-finite numbers,
exponent overflow, trailing data, and non-UTF-8 are rejected before any field validator
runs, so the construct-path and the parse-path enforce a single invariant surface.

The ``require_*`` helpers never coerce — a ``bool`` is not an ``int``, a numeric string is
not a number, and a non-finite float is rejected. They raise :class:`CanonicalError`,
which every public model catches at its parse boundary and re-raises as the appropriate
public error (result / receipt / configuration), preserving ``__cause__``.
``CanonicalError`` is an internal implementation detail and is not part of the public
error taxonomy; a caller never sees it.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from eth_research._json import StrictJSONError, require_canonical_file_bytes, strict_json_loads

__all__ = [
    "CanonicalError",
    "canonical_json_bytes",
    "canonical_sha256",
    "require_bool",
    "require_finite_float",
    "require_int",
    "require_list",
    "require_mapping",
    "require_sha256_hex",
    "require_str",
    "sha256_hex",
    "strict_load_canonical",
]

# A public artifact (result, receipt, config) is a small structured document, never a
# bulk data payload; this ceiling bounds the parse cost of untrusted input.
_MAX_JSON_BYTES = 4 * 1024 * 1024


class CanonicalError(ValueError):
    """A value failed strict canonical serialization or validation.

    Internal to the API layer: every public model translates it into the appropriate
    public error at its parse boundary, so it never reaches a caller. Subclasses
    :class:`ValueError`, so a translate site can narrowly catch it without masking an
    unrelated bug.
    """


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize ``payload`` to the canonical on-disk form.

    Sorted keys, two-space indent, UTF-8, ``NaN``/``Infinity`` refused, exactly one
    trailing newline. Raises :class:`CanonicalError` if a non-finite float reaches
    serialization.
    """
    try:
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    except ValueError as exc:  # a non-finite float reached serialization
        raise CanonicalError(f"value is not canonically serializable: {exc}") from exc
    return (text + "\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Lowercase hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(payload: Any) -> str:
    """Lowercase hex SHA-256 of the canonical serialization of ``payload``."""
    return sha256_hex(canonical_json_bytes(payload))


def strict_load_canonical(raw: bytes, label: str) -> Any:
    """Parse ``raw`` as a canonical committed artifact (size ceiling, trailing newline,
    strict decoding). Raises :class:`CanonicalError` on any violation."""
    if not isinstance(raw, bytes | bytearray):
        raise CanonicalError(f"{label}: expected raw bytes")
    if len(raw) > _MAX_JSON_BYTES:
        raise CanonicalError(f"{label}: exceeds the {_MAX_JSON_BYTES}-byte parse ceiling")
    try:
        body = require_canonical_file_bytes(bytes(raw), label)
        return strict_json_loads(body)
    except StrictJSONError as exc:
        raise CanonicalError(f"{label}: {exc}") from exc


def require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CanonicalError(f"{field}: expected an object")
    return value


def require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise CanonicalError(f"{field}: expected an array")
    return value


def require_str(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CanonicalError(f"{field}: expected a string")
    if not allow_empty and value == "":
        raise CanonicalError(f"{field}: must not be empty")
    return value


def require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise CanonicalError(f"{field}: expected a boolean")
    return value


def require_int(value: Any, field: str) -> int:
    # ``bool`` is a subclass of ``int`` — reject it so ``true`` is never read as ``1``.
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanonicalError(f"{field}: expected an integer")
    return value


def require_finite_float(value: Any, field: str) -> float:
    # Strict: an ``int`` (or ``bool``) is not a float. Canonical round-trip preserves the
    # float literal form, so a float field always reloads as a float.
    if isinstance(value, bool) or not isinstance(value, float):
        raise CanonicalError(f"{field}: expected a finite number")
    if not math.isfinite(value):
        raise CanonicalError(f"{field}: number must be finite")
    return value


def require_sha256_hex(value: Any, field: str) -> str:
    text = require_str(value, field)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CanonicalError(f"{field}: expected a lowercase hex SHA-256 digest")
    return text
