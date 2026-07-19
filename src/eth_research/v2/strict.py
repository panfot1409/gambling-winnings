"""Strict decode + canonical-JSON helpers for the V2A commercial-evidence layer.

Every V2 JSON artifact is *decoded, never repaired*: the reviewed fractional/M3B
``require_*`` surface (which rejects ``bool``-as-int, non-finite reals, coerced types,
unsafe paths, and unexpected keys) is re-exported here alongside the shared strict JSON
loader (dup-key / NaN / Infinity / overflow rejecting) and a single canonical serializer,
so every V2 artifact is byte-stable and no accepted engine is modified to serve V2.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eth_research._json import strict_json_loads
from eth_research.data.provenance import sha256_bytes
from eth_research.fractional.validation import (
    FractionalValidationError,
    require_bool,
    require_canonical_order,
    require_exact_keys,
    require_exact_string,
    require_hex64,
    require_int,
    require_nonempty_str,
    require_nonnegative_int,
    require_nonnegative_real,
    require_positive_int,
    require_positive_real,
    require_real,
    require_safe_relative_path,
    require_sha256_fingerprint,
    require_str,
    require_tuple,
    require_unit_interval,
    require_utc_timestamp,
)

__all__ = [
    "V2ValidationError",
    "canonical_json_bytes",
    "canonical_sha256",
    "load_canonical_json",
    "require_bool",
    "require_canonical_order",
    "require_choice",
    "require_exact_keys",
    "require_exact_string",
    "require_hex64",
    "require_int",
    "require_list",
    "require_mapping",
    "require_nonempty_str",
    "require_nonnegative_int",
    "require_nonnegative_real",
    "require_positive_int",
    "require_positive_real",
    "require_real",
    "require_safe_relative_path",
    "require_sha256_fingerprint",
    "require_slug",
    "require_str",
    "require_tuple",
    "require_unit_interval",
    "require_utc_timestamp",
    "strict_json_loads",
]

# V2 validation failures are the same strict class the fractional layer raises so a single
# ``(ValueError, TypeError)`` catch covers every strict rejection across V2 and its dependencies.
V2ValidationError = FractionalValidationError


def require_mapping(label: str, value: object) -> dict[str, Any]:
    """A JSON object (never a list/scalar); keys already de-duplicated by the strict loader."""
    if not isinstance(value, dict):
        raise V2ValidationError(f"{label} must be a JSON object, got {type(value).__name__}")
    return value


def require_list[T](label: str, value: object, item: Callable[[str, object], T]) -> list[T]:
    """A JSON array decoded element-by-element through ``item`` (order preserved)."""
    if not isinstance(value, list):
        raise V2ValidationError(f"{label} must be a JSON array, got {type(value).__name__}")
    return [item(f"{label}[{i}]", element) for i, element in enumerate(value)]


def require_choice(label: str, value: object, allowed: frozenset[str]) -> str:
    """A string that must be one of ``allowed`` (fail-closed on anything else)."""
    text = require_str(label, value)
    if text not in allowed:
        raise V2ValidationError(f"{label} must be one of {sorted(allowed)!r}, got {text!r}")
    return text


def require_slug(label: str, value: object) -> str:
    """A lowercase ``[a-z0-9_]+`` identifier (stable, filesystem- and JSON-safe)."""
    text = require_nonempty_str(label, value)
    if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in text):
        raise V2ValidationError(f"{label} must be a lowercase [a-z0-9_] slug, got {text!r}")
    return text


def canonical_json_bytes(payload: Any) -> bytes:
    """Deterministic canonical JSON: sorted keys, 2-space indent, trailing newline.

    ``allow_nan=False`` rejects NaN/Infinity at serialization time, so a non-finite value can
    never be written into a V2 artifact.
    """
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    """SHA-256 of the canonical serialization of ``payload``."""
    return sha256_bytes(canonical_json_bytes(payload))


def load_canonical_json(path: str | Path) -> Any:
    """Read + strictly decode a committed V2 JSON artifact (dup-key/NaN/Inf rejecting)."""
    return strict_json_loads(Path(path).read_bytes())
