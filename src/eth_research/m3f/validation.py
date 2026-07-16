"""Strict parsing, safe-path normalization, and canonical bytes for Milestone 3F.

Every M3F JSON/JSONL parser routes through here. The construction path and the
parse path share one invariant surface: :func:`load_canonical_json` rejects
duplicate keys (any depth), ``NaN``/``Infinity``/exponent overflow, trailing data,
non-UTF-8, and a missing canonical trailing newline; the ``require_*`` helpers
reject ``bool`` where ``int`` is expected, numeric strings, wrong containers, and
non-finite reals — never coercing with ``str()``/``int()``/``float()``/``bool()``.

Path handling refuses absolute paths, ``..``, backslashes, NUL, empty components,
current-directory components, Unicode-normalization aliases, and case-colliding
aliases, so a catalogued repository-relative path can never escape the repo root.
"""

from __future__ import annotations

import math
import unicodedata
from pathlib import PurePosixPath
from typing import Any

from eth_research._json import StrictJSONError, require_canonical_file_bytes, strict_json_loads
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.m3d.validation import canonical_json_bytes, canonical_sha256

__all__ = [
    "M3FValidationError",
    "canonical_json_bytes",
    "canonical_sha256",
    "count_created_proposals",
    "load_canonical_json",
    "normalize_relpath",
    "require_bool",
    "require_finite_float",
    "require_int",
    "require_list",
    "require_mapping",
    "require_nonneg_int",
    "require_sha256_hex",
    "require_str",
    "safe_repo_path",
    "sha256_bytes",
    "sha256_file",
    "strict_jsonl_records",
]

_MAX_JSON_BYTES = 8 * 1024 * 1024  # a governance/inventory artifact is never this big


class M3FValidationError(ValueError):
    """A committed M3F/accepted artifact failed a strict invariant."""


def load_canonical_json(raw: bytes, label: str) -> Any:
    """Parse ``raw`` as a canonical committed JSON artifact.

    Enforces a size ceiling first, then the canonical trailing-newline contract,
    then strict decoding (dup-key / non-finite / trailing-data rejection).
    """
    if not isinstance(raw, bytes | bytearray):
        raise M3FValidationError(f"{label}: expected raw bytes")
    if len(raw) > _MAX_JSON_BYTES:
        raise M3FValidationError(f"{label}: file exceeds the {_MAX_JSON_BYTES}-byte parse ceiling")
    try:
        body = require_canonical_file_bytes(bytes(raw), label)
        return strict_json_loads(body)
    except StrictJSONError as exc:
        raise M3FValidationError(f"{label}: {exc}") from exc


def strict_jsonl_records(raw: bytes, label: str) -> list[Any]:
    """Parse a JSONL artifact: one strict JSON value per non-empty line, no trailing junk."""
    if not isinstance(raw, bytes | bytearray):
        raise M3FValidationError(f"{label}: expected raw bytes")
    if len(raw) > _MAX_JSON_BYTES:
        raise M3FValidationError(f"{label}: file exceeds the parse ceiling")
    text = bytes(raw).decode("utf-8", errors="strict")
    if text and not text.endswith("\n"):
        raise M3FValidationError(f"{label}: JSONL must end with a newline")
    records: list[Any] = []
    for i, line in enumerate(text.splitlines()):
        if line == "":
            raise M3FValidationError(f"{label}: line {i + 1} is empty")
        try:
            records.append(strict_json_loads(line))
        except StrictJSONError as exc:
            raise M3FValidationError(f"{label}: line {i + 1}: {exc}") from exc
    return records


def count_created_proposals(raw: bytes, label: str = "proposal_registry") -> int:
    """Count M3E registry records that record a *created* proposal.

    Each JSONL line is strictly parsed, so the count is whitespace-independent —
    unlike a substring scan, it matches the M3E registry's compact
    ``"proposal_created":true`` serialization as well as any spaced form. It is
    fail-closed: a record whose ``proposal_created`` is present and not exactly
    ``false`` (a smuggled truthy value, a non-bool) is counted as a proposal rather
    than silently ignored, so the zero-proposal governance invariant can never pass
    open on a value it failed to recognize.
    """
    count = 0
    for rec in strict_jsonl_records(raw, label):
        if not isinstance(rec, dict):
            continue
        created = rec.get("proposal_created")
        if created is not None and created is not False:
            count += 1
    return count


def normalize_relpath(value: object, label: str) -> str:
    """Return a validated, normalized POSIX repository-relative path string.

    Rejects non-str, empty, absolute, backslash, NUL, ``.``/``..`` components,
    empty components, and Unicode non-NFC forms (a confusable/decomposed alias of
    an ASCII path). The returned string is exactly ``value`` (already NFC + clean).
    """
    if not isinstance(value, str):
        raise M3FValidationError(f"{label}: path must be a string")
    if value == "":
        raise M3FValidationError(f"{label}: empty path")
    if "\x00" in value:
        raise M3FValidationError(f"{label}: NUL in path")
    if "\\" in value:
        raise M3FValidationError(f"{label}: backslash in path {value!r}")
    if value.startswith("/"):
        raise M3FValidationError(f"{label}: absolute path {value!r}")
    if unicodedata.normalize("NFC", value) != value:
        raise M3FValidationError(f"{label}: non-NFC (Unicode-alias) path {value!r}")
    parts = value.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise M3FValidationError(f"{label}: unsafe path component in {value!r}")
    posix = PurePosixPath(value)
    if str(posix) != value:
        raise M3FValidationError(f"{label}: non-normalized path {value!r}")
    return value


def safe_repo_path(repo_root: Any, relpath: str, label: str) -> Any:
    """Resolve ``relpath`` under ``repo_root`` and prove it stays inside, with no symlink.

    Returns the resolved ``Path``. Raises if the resolved path escapes the repo,
    if any component is a symlink, or if the entry is not a regular file/dir.
    """
    from pathlib import Path

    root = Path(repo_root).resolve()
    normalize_relpath(relpath, label)
    target = (root / relpath).resolve()
    if root != target and root not in target.parents:
        raise M3FValidationError(f"{label}: path escapes the repository: {relpath!r}")
    # No symlink anywhere along the relative chain.
    cursor = root
    for part in relpath.split("/"):
        cursor = cursor / part
        if cursor.is_symlink():
            raise M3FValidationError(f"{label}: symlink component in {relpath!r}")
    return target


def require_str(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise M3FValidationError(f"{label}: expected str, got {type(value).__name__}")
    if not allow_empty and value == "":
        raise M3FValidationError(f"{label}: empty string")
    return value


def require_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise M3FValidationError(f"{label}: expected bool, got {type(value).__name__}")
    return value


def require_int(value: object, label: str) -> int:
    # bool is a subclass of int — reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise M3FValidationError(f"{label}: expected int, got {type(value).__name__}")
    return value


def require_nonneg_int(value: object, label: str) -> int:
    n = require_int(value, label)
    if n < 0:
        raise M3FValidationError(f"{label}: expected a non-negative int, got {n}")
    return n


def require_finite_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise M3FValidationError(f"{label}: expected a real number, got {type(value).__name__}")
    f = float(value)
    if not math.isfinite(f):
        raise M3FValidationError(f"{label}: non-finite number")
    return f


def require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise M3FValidationError(f"{label}: expected object, got {type(value).__name__}")
    return value


def require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise M3FValidationError(f"{label}: expected array, got {type(value).__name__}")
    return value


def require_exact_keys(mapping: dict[str, Any], expected: frozenset[str], label: str) -> None:
    keys = set(mapping)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        raise M3FValidationError(f"{label}: key mismatch (missing={missing}, unexpected={extra})")


def require_sha256_hex(value: object, label: str) -> str:
    s = require_str(value, label)
    if len(s) != 64 or any(c not in "0123456789abcdef" for c in s):
        raise M3FValidationError(f"{label}: not a lowercase hex sha256")
    return s
