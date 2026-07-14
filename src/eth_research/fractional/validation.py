"""Shared strict validation for the M3B fractional domain (closure Section 3).

One import surface for every fractional model and serialized format. It
consolidates the existing strict helpers (which already reject ``bool`` where an
int/real is required and are backed by the shared duplicate-key / non-finite JSON
decoder) and adds the real / unit-interval / path / tuple / key-set helpers the
fractional domain needs.

Hard rules (enforced by these helpers, never by ``str()/int()/float()`` repair):

* a parsed value is **decoded**, never coerced — a JSON string is not a number,
  a number is not a string, and ``bool`` is neither an int nor a real;
* every financial value must be **finite**;
* integer acceptance is explicit; reals accept an integer JSON number only when
  the field is genuinely real-valued;
* constructors and parsers share exactly this surface, so ``construct == parse``.

All failures raise :class:`FractionalValidationError` (a ``ValueError``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping

import pandas as pd

from eth_research.data.provenance import require_bool as _require_bool
from eth_research.data.provenance import require_hex64 as _require_hex64
from eth_research.data.provenance import require_int as _require_int
from eth_research.data.provenance import require_nonempty_str as _require_nonempty_str
from eth_research.data.provenance import require_str as _require_str
from eth_research.data.validation import require_finite_float as _require_finite_float
from eth_research.data.validation import require_nonnegative_int as _require_nonnegative_int
from eth_research.data.validation import require_positive_int as _require_positive_int
from eth_research.data.validation import require_utc_timestamp as _require_utc_timestamp

_FINGERPRINT_RE = re.compile(r"^([a-z0-9][a-z0-9._-]*/)?sha256:[0-9a-f]{64}$")
_SAFE_PATH_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class FractionalValidationError(ValueError):
    """A fractional-domain value or serialized field failed strict validation."""


def _fail(label: str, detail: str) -> FractionalValidationError:
    return FractionalValidationError(f"{label}: {detail}")


# --- re-exported strict primitives (single fractional import surface) -------
def require_bool(label: str, value: object) -> bool:
    try:
        return _require_bool(label, value)
    except ValueError as exc:
        raise FractionalValidationError(str(exc)) from exc


def require_int(label: str, value: object) -> int:
    try:
        return _require_int(label, value)
    except ValueError as exc:
        raise FractionalValidationError(str(exc)) from exc


def require_nonnegative_int(label: str, value: object) -> int:
    try:
        return _require_nonnegative_int(label, value)
    except ValueError as exc:
        raise FractionalValidationError(str(exc)) from exc


def require_positive_int(label: str, value: object) -> int:
    try:
        return _require_positive_int(label, value)
    except ValueError as exc:
        raise FractionalValidationError(str(exc)) from exc


def require_str(label: str, value: object) -> str:
    try:
        return _require_str(label, value)
    except ValueError as exc:
        raise FractionalValidationError(str(exc)) from exc


def require_nonempty_str(label: str, value: object) -> str:
    try:
        return _require_nonempty_str(label, value)
    except ValueError as exc:
        raise FractionalValidationError(str(exc)) from exc


def require_hex64(label: str, value: object) -> str:
    try:
        return _require_hex64(label, value)
    except ValueError as exc:
        raise FractionalValidationError(str(exc)) from exc


def require_utc_timestamp(label: str, value: object) -> pd.Timestamp:
    try:
        return _require_utc_timestamp(label, value)
    except (ValueError, TypeError) as exc:
        raise FractionalValidationError(str(exc)) from exc


# --- reals ------------------------------------------------------------------
def require_real(label: str, value: object) -> float:
    """A finite real (int or float JSON number); ``bool`` is rejected."""
    try:
        return _require_finite_float(label, value)
    except ValueError as exc:
        raise FractionalValidationError(str(exc)) from exc


#: A finite real (``bool`` rejected). The fractional domain treats every real as
#: finite, so this is the same contract as :func:`require_real`, named for the
#: places that want to stress finiteness explicitly.
require_finite_real = require_real


def require_nonnegative_real(label: str, value: object, *, tolerance: float = 0.0) -> float:
    number = require_real(label, value)
    if number < -tolerance:
        raise _fail(label, f"must be >= {-tolerance!r}, got {number!r}")
    return number


def require_positive_real(label: str, value: object) -> float:
    number = require_real(label, value)
    if number <= 0.0:
        raise _fail(label, f"must be > 0, got {number!r}")
    return number


def require_unit_interval(label: str, value: object, *, tolerance: float = 0.0) -> float:
    """A finite real within ``[-tolerance, 1 + tolerance]`` (a long-only weight)."""
    number = require_real(label, value)
    if number < -tolerance or number > 1.0 + tolerance:
        raise _fail(label, f"must be within [0, 1] (tol {tolerance!r}), got {number!r}")
    return number


# --- strings / paths / fingerprints -----------------------------------------
def require_exact_string(label: str, value: object, expected: str) -> str:
    text = require_str(label, value)
    if text != expected:
        raise _fail(label, f"must be exactly {expected!r}, got {text!r}")
    return text


def require_sha256_fingerprint(label: str, value: object) -> str:
    """A ``[algo/]sha256:<64 hex>`` content fingerprint (or a bare 64-hex digest)."""
    text = require_nonempty_str(label, value)
    if _FINGERPRINT_RE.match(text) or re.fullmatch(r"[0-9a-f]{64}", text):
        return text
    raise _fail(label, f"must be a sha256 fingerprint, got {text!r}")


def require_safe_relative_path(label: str, value: object, *, prefix: str | None = None) -> str:
    """A clean repo-relative path (no absolute, backslash, NUL, ``.``/``..``,
    or unsafe component), optionally required to live under ``prefix``."""
    text = require_nonempty_str(label, value)
    if text != text.strip() or text.startswith("/") or "\\" in text or "\x00" in text:
        raise _fail(label, f"must be a clean relative path, got {text!r}")
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise _fail(label, f"must have no empty or dot components, got {text!r}")
    if any(not _SAFE_PATH_COMPONENT_RE.match(part) for part in parts):
        raise _fail(label, f"has an unsafe path component, got {text!r}")
    if prefix is not None and not text.startswith(prefix):
        raise _fail(label, f"must live under {prefix!r}, got {text!r}")
    return text


# --- containers -------------------------------------------------------------
def require_tuple[T](label: str, value: object, item: Callable[[str, object], T]) -> tuple[T, ...]:
    """``value`` must be a tuple/list; each element is validated by ``item``."""
    if not isinstance(value, tuple | list):
        raise _fail(label, f"must be a sequence, got {type(value).__name__}")
    return tuple(item(f"{label}[{i}]", element) for i, element in enumerate(value))


def require_exact_keys(
    label: str, mapping: object, expected: Iterable[str]
) -> Mapping[str, object]:
    """``mapping`` must be a dict whose key set is exactly ``expected``."""
    if not isinstance(mapping, Mapping):
        raise _fail(label, f"must be an object, got {type(mapping).__name__}")
    keys = set(mapping)
    want = set(expected)
    if keys != want:
        unknown = sorted(keys - want)
        missing = sorted(want - keys)
        raise _fail(label, f"keys do not match: unknown={unknown}, missing={missing}")
    return mapping


def require_canonical_order(
    label: str, value: object, expected: tuple[str, ...]
) -> tuple[str, ...]:
    """``value`` must equal ``expected`` element-for-element and in order."""
    got = require_tuple(label, value, require_str)
    if got != expected:
        raise _fail(label, f"must be exactly {expected!r} in order, got {got!r}")
    return got
