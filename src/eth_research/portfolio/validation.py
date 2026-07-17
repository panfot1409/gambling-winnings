"""Shared strict validation and domain-separated hashing for the portfolio layer.

Every portfolio model parses and serializes through this one surface, which extends the accepted
canonical-serialization helpers (:mod:`eth_research.api.serialization`) with the numeric and
string constraints M4B needs — positive/non-negative finite floats, safe normalized tokens, exact
key sets — and a single domain-separated content hash so two structurally different objects can
never collide even if their payloads happen to serialize alike.

Nothing here coerces: a ``bool`` is never an ``int`` or a ``float``, a numeric string is never a
number, and a non-finite value is always rejected. All violations raise
:class:`~eth_research.api.serialization.CanonicalError`, which the public portfolio error taxonomy
translates at its parse boundary.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from eth_research.api.serialization import (
    CanonicalError,
    canonical_json_bytes,
    require_finite_float,
    require_str,
    sha256_hex,
)

__all__ = [
    "domain_hash",
    "exact_keys",
    "require_non_negative_finite_float",
    "require_positive_finite_float",
    "require_safe_token",
]

# The domain-separation prefix binds every portfolio content hash to both the milestone and the
# specific object kind, so a bar hash can never equal a calendar hash of coincidentally equal
# bytes. The NUL byte cannot appear in the domain label (an ASCII identifier), so the boundary
# between the label and the canonical payload is unambiguous.
_DOMAIN_PREFIX = "eth_research.portfolio.v1"


def exact_keys(data: dict[str, Any], allowed: set[str], label: str) -> None:
    """Reject a mapping that carries any key outside ``allowed`` (fail closed on unknown input)."""
    extra = set(data) - allowed
    if extra:
        raise CanonicalError(f"{label}: unexpected key(s) {sorted(extra)}")
    missing = allowed - set(data)
    if missing:
        raise CanonicalError(f"{label}: missing required key(s) {sorted(missing)}")


def require_positive_finite_float(value: Any, field: str) -> float:
    """A finite float strictly greater than zero (a price, an FX rate, a positive quantity)."""
    number = require_finite_float(value, field)
    if number <= 0.0:
        raise CanonicalError(f"{field}: must be a positive finite number")
    return number


def require_non_negative_finite_float(value: Any, field: str) -> float:
    """A finite float greater than or equal to zero (a volume, a cost, a weight)."""
    number = require_finite_float(value, field)
    if number < 0.0:
        raise CanonicalError(f"{field}: must be a non-negative finite number")
    return number


def require_safe_token(value: Any, field: str, *, max_length: int = 128) -> str:
    """A safe, normalized, non-empty identifier token.

    Used for symbols, venues, asset codes, and object ids: NFC-normalized, no leading/trailing
    whitespace, no path separators (``/`` or ``\\``), no ``..`` traversal, no control or
    zero-width characters, and bounded in length. This never asserts that the token names a real
    instrument or a real venue — it only guarantees the string is safe to place in a canonical
    identity and on a filesystem path without ambiguity.
    """
    text = require_str(value, field)
    if unicodedata.normalize("NFC", text) != text:
        raise CanonicalError(f"{field}: must be Unicode NFC-normalized")
    if text != text.strip():
        raise CanonicalError(f"{field}: must not have leading or trailing whitespace")
    if len(text) > max_length:
        raise CanonicalError(f"{field}: exceeds the {max_length}-character limit")
    if "/" in text or "\\" in text:
        raise CanonicalError(f"{field}: must not contain a path separator")
    if ".." in text:
        raise CanonicalError(f"{field}: must not contain '..'")
    for ch in text:
        category = unicodedata.category(ch)
        if category.startswith("C") or (category == "Zs" and ch != " "):
            raise CanonicalError(f"{field}: must not contain control or zero-width characters")
    return text


def domain_hash(kind: str, payload: Any) -> str:
    """A domain-separated lowercase-hex SHA-256 over the canonical serialization of ``payload``.

    The digest binds the milestone prefix and the object ``kind`` ahead of the canonical bytes, so
    identity is stable across runtimes (canonical JSON is byte-identical) yet distinct per object
    kind. ``payload`` must be canonically serializable (finite floats only); a non-finite value
    raises :class:`CanonicalError` before any digest is produced.
    """
    require_str(kind, "domain_hash.kind")
    tag = f"{_DOMAIN_PREFIX}:{kind}\x00".encode()
    return sha256_hex(tag + canonical_json_bytes(payload))
