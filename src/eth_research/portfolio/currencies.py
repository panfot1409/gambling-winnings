"""Structural validation of currency codes — without claiming any ISO authority.

A base accounting currency and an instrument's quote currency are named by short uppercase codes
(``USD``, ``EUR``, ``USDT``). This module validates that a code is *structurally* well-formed —
uppercase ASCII letters, a bounded length — so it can be placed in a canonical identity and used
as a settlement label without ambiguity. It deliberately does **not** assert that a code is a real,
registered ISO-4217 currency: M4B is an offline research simulator over caller-supplied or
synthetic evidence, and a spurious authority claim would be dishonest. The one guarantee is
structural well-formedness and case-exactness, so ``usd`` and ``USD`` never both pass.
"""

from __future__ import annotations

from typing import Any

from eth_research.api.serialization import CanonicalError, require_str

__all__ = ["require_currency_code", "same_currency"]

_MIN_CODE_LEN = 3
_MAX_CODE_LEN = 12


def require_currency_code(value: Any, field: str) -> str:
    """A structurally valid currency code: 3-12 uppercase ASCII letters, no coercion.

    Rejects lowercase, digits, whitespace, and punctuation so the code is unambiguous and
    case-exact. This is a *structural* check only — it makes no claim that the code is a
    registered ISO-4217 currency.
    """
    text = require_str(value, field)
    if not (_MIN_CODE_LEN <= len(text) <= _MAX_CODE_LEN):
        raise CanonicalError(
            f"{field}: currency code must be {_MIN_CODE_LEN}-{_MAX_CODE_LEN} characters"
        )
    if not text.isascii() or not text.isalpha() or not text.isupper():
        raise CanonicalError(f"{field}: currency code must be uppercase ASCII letters")
    return text


def same_currency(left: str, right: str) -> bool:
    """Whether two validated currency codes name the same currency (exact, case-sensitive)."""
    return left == right
