"""Strict decode + canonical-JSON helpers for the M3C governance layer.

Every M3C JSON artifact is *decoded, never repaired*: the reviewed Milestone 3B
``require_*`` surface (which rejects ``bool``-as-int, non-finite reals, coerced
types, unsafe paths, non-canonical order, and unexpected keys) is re-exported here,
alongside the shared strict JSON loader (dup-key / NaN / Infinity / overflow
rejecting) and a single canonical serializer so every artifact is byte-stable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eth_research._json import strict_json_loads
from eth_research.data.provenance import sha256_bytes
from eth_research.fractional.validation import (
    FractionalValidationError,
    require_bool,
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
)

__all__ = [
    "M3CValidationError",
    "canonical_json_bytes",
    "canonical_sha256",
    "load_canonical_json",
    "require_bool",
    "require_exact_keys",
    "require_exact_string",
    "require_hex64",
    "require_int",
    "require_mapping",
    "require_nonempty_str",
    "require_nonnegative_int",
    "require_nonnegative_real",
    "require_positive_int",
    "require_positive_real",
    "require_real",
    "require_safe_relative_path",
    "require_sha256_fingerprint",
    "require_str",
    "require_tuple",
    "require_unit_interval",
    "strict_json_loads",
]

# M3C validation failures are the same strict class the fractional layer raises so a
# single ``(ValueError, TypeError)`` catch covers every strict rejection.
M3CValidationError = FractionalValidationError


def require_mapping(label: str, value: object) -> dict[str, Any]:
    """A JSON object (never a list/scalar); keys already de-duplicated upstream."""
    if not isinstance(value, dict):
        raise M3CValidationError(f"{label} must be a JSON object, got {type(value).__name__}")
    return value


def canonical_json_bytes(payload: Any) -> bytes:
    """Deterministic canonical JSON: sorted keys, 2-space indent, trailing newline.

    ``allow_nan=False`` rejects NaN/Infinity at serialization time, so a non-finite
    value can never be written into an artifact.
    """
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    """SHA-256 of the canonical serialization of ``payload``."""
    return sha256_bytes(canonical_json_bytes(payload))


def load_canonical_json(path: str | Path) -> Any:
    """Read + strictly decode a committed JSON artifact (dup-key/NaN/Inf rejecting)."""
    return strict_json_loads(Path(path).read_bytes())
