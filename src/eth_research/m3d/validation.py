"""Shared strict-validation and canonicalization surface for Milestone 3D.

Milestone 3D is *data-only* and *governance-only*. This module is the one
invariant surface that every M3D model shares between construction and parsing,
so a value that would be rejected on load can never be produced on build.

It deliberately imports only the repository's low-level, **strategy-free**
utilities — the strict JSON decoder (:mod:`eth_research._json`), the SHA-256
helper and timestamp/provenance validators (:mod:`eth_research.data`) — and adds
the field validators, canonical serializer, and domain-separated fingerprint
helper the governance and prospective-data models need. It imports **no**
strategy, backtest, engine, accounting, metric, promotion-decision, or
experiment-executor module; ``tests/test_m3d_architecture.py`` enforces that with
an AST scan.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from eth_research._json import (
    StrictJSONError,
    require_canonical_file_bytes,
    strict_json_loads,
)
from eth_research.data.provenance import sha256_bytes
from eth_research.data.validation import (
    epoch_nanoseconds,
    require_aware_timestamp,
    require_commit_sha,
    require_day_aligned_utc,
    require_fingerprint,
    require_utc_timestamp,
)

__all__ = [
    "M3DValidationError",
    "StrictJSONError",
    "canonical_json_bytes",
    "canonical_sha256",
    "domain_sha256",
    "epoch_nanoseconds",
    "load_canonical_json",
    "load_canonical_json_bytes",
    "require_aware_timestamp",
    "require_bool",
    "require_commit_sha",
    "require_day_aligned_utc",
    "require_exact",
    "require_fingerprint",
    "require_finite_float",
    "require_int",
    "require_list",
    "require_mapping",
    "require_nonempty_str",
    "require_nonnegative_int",
    "require_positive_int",
    "require_sha256_hex",
    "require_str",
    "require_string_sequence",
    "require_utc_timestamp",
    "sha256_bytes",
    "strict_json_loads",
]

# A single strict error class, a ``ValueError`` subclass so ``except ValueError``
# at parse boundaries keeps working, and identical whether raised on build or load.
M3DValidationError = StrictJSONError

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


# --------------------------------------------------------------------------- #
# Canonical serialization                                                      #
# --------------------------------------------------------------------------- #
def canonical_json_bytes(payload: Any) -> bytes:
    """Deterministic canonical JSON: sorted keys, 2-space indent, one newline.

    ``allow_nan=False`` rejects NaN/Infinity at serialization time, so a
    non-finite float can never be written into an M3D artifact. The trailing
    newline matches :func:`eth_research._json.require_canonical_file_bytes`, so a
    file this function writes reloads cleanly through
    :func:`load_canonical_json_bytes`.
    """
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    """Bare lowercase-hex SHA-256 of the canonical serialization of ``payload``."""
    return sha256_bytes(canonical_json_bytes(payload))


def domain_sha256(domain: str, payload: Any) -> str:
    """Domain-separated SHA-256 over ``payload``'s canonical form.

    The domain label is folded into the digest input (as its own length-tagged
    prefix) so two structurally identical payloads under different domains can
    never collide, and a payload can never be replayed under a domain it was not
    computed for. Returns bare lowercase hex.
    """
    if not isinstance(domain, str) or not domain:
        raise M3DValidationError("domain must be a non-empty string")
    prefix = f"m3d/{domain}\n".encode()
    return hashlib.sha256(prefix + canonical_json_bytes(payload)).hexdigest()


def load_canonical_json_bytes(path: str | Path, label: str) -> tuple[bytes, Any]:
    """Read a committed artifact, require canonical file bytes, strictly decode.

    Returns the exact on-disk bytes and the decoded document. The canonical-file
    check (exactly one trailing newline) closes the gap where a re-serialization
    could differ from committed bytes only by trailing whitespace.
    """
    raw = Path(path).read_bytes()
    require_canonical_file_bytes(raw, label)
    return raw, strict_json_loads(raw)


def load_canonical_json(path: str | Path) -> Any:
    """Read + strictly decode a committed JSON artifact (dup-key/NaN/Inf rejecting)."""
    return strict_json_loads(Path(path).read_bytes())


# --------------------------------------------------------------------------- #
# Strict field validators (all raise M3DValidationError)                       #
# --------------------------------------------------------------------------- #
def require_mapping(label: str, value: object) -> dict[str, Any]:
    """A JSON object (never a list/scalar); keys already de-duplicated upstream."""
    if not isinstance(value, dict):
        raise M3DValidationError(f"{label} must be a JSON object, got {type(value).__name__}")
    return value


def require_list(label: str, value: object) -> list[Any]:
    """A JSON array (never a mapping/scalar)."""
    if not isinstance(value, list):
        raise M3DValidationError(f"{label} must be a JSON array, got {type(value).__name__}")
    return value


def require_str(label: str, value: object) -> str:
    """A JSON string (``bool``/``int`` are not strings)."""
    if not isinstance(value, str):
        raise M3DValidationError(f"{label} must be a string, got {type(value).__name__}")
    return value


def require_nonempty_str(label: str, value: object) -> str:
    text = require_str(label, value)
    if not text:
        raise M3DValidationError(f"{label} must be a non-empty string")
    return text


def require_int(label: str, value: object) -> int:
    """A JSON integer. ``bool`` is rejected even though ``bool`` subclasses ``int``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise M3DValidationError(f"{label} must be an integer, got {type(value).__name__}")
    return value


def require_nonnegative_int(label: str, value: object) -> int:
    number = require_int(label, value)
    if number < 0:
        raise M3DValidationError(f"{label} must be >= 0, got {number}")
    return number


def require_positive_int(label: str, value: object) -> int:
    number = require_int(label, value)
    if number <= 0:
        raise M3DValidationError(f"{label} must be > 0, got {number}")
    return number


def require_bool(label: str, value: object) -> bool:
    """Exactly a JSON boolean; ``0``/``1`` are rejected."""
    if not isinstance(value, bool):
        raise M3DValidationError(f"{label} must be a boolean, got {type(value).__name__}")
    return value


def require_finite_float(label: str, value: object) -> float:
    """A finite JSON number (``int`` accepted and widened; ``bool`` rejected)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise M3DValidationError(f"{label} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise M3DValidationError(f"{label} must be finite, got {value!r}")
    return number


def require_exact(label: str, value: object, expected: object) -> Any:
    """``value`` must equal a preregistered constant exactly (same type + value)."""
    if type(value) is not type(expected) or value != expected:
        raise M3DValidationError(f"{label} must be exactly {expected!r}, got {value!r}")
    return value


def require_sha256_hex(label: str, value: object) -> str:
    """A bare 64-character lowercase-hex SHA-256 (no ``sha256:`` prefix)."""
    text = require_str(label, value)
    if not _SHA256_HEX_RE.fullmatch(text):
        raise M3DValidationError(f"{label} must be 64 lowercase hex chars, got {text!r}")
    return text


def require_string_sequence(label: str, value: object) -> tuple[str, ...]:
    """A JSON array of strings, returned as an immutable tuple."""
    items = require_list(label, value)
    return tuple(require_str(f"{label}[{i}]", item) for i, item in enumerate(items))
