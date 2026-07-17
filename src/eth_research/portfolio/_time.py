"""The single UTC-timestamp convention for the portfolio layer.

Every portfolio timestamp is a timezone-aware UTC :class:`pandas.Timestamp` whose canonical string
form is ``ts.tz_convert("UTC").isoformat()`` (for example ``"2026-07-14T00:00:00+00:00"``). This
module is the one place that convention lives: :func:`iso_utc` serializes a timestamp to that
string, and :func:`require_utc_timestamp` parses an untrusted string back, accepting only the
canonical UTC spelling so the two functions round-trip exactly. A naive (timezone-less) timestamp,
a non-canonical spelling (a trailing ``Z`` or a non-zero offset), an unparseable string, or a
non-string input is rejected with :class:`~eth_research.api.serialization.CanonicalError`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from eth_research.api.serialization import CanonicalError

__all__ = ["iso_utc", "require_utc_timestamp"]


def iso_utc(ts: pd.Timestamp) -> str:
    """The canonical UTC ISO-8601 string for a timezone-aware timestamp.

    Raises :class:`CanonicalError` if ``ts`` is naive (has no timezone), so the caller can never
    silently serialize an ambiguous local time.
    """
    if ts.tz is None:
        raise CanonicalError("iso_utc: timestamp must be timezone-aware")
    return ts.tz_convert("UTC").isoformat()


def require_utc_timestamp(value: Any, field: str) -> pd.Timestamp:
    """Parse an untrusted canonical UTC ISO-8601 string into a tz-aware UTC :class:`Timestamp`.

    Only the canonical spelling passes: the string must be timezone-aware, and re-serializing the
    parsed timestamp via :func:`iso_utc` must reproduce ``value`` byte for byte. A trailing ``Z``,
    a non-zero UTC offset, sub-second noise, or a naive spelling therefore all fail, guaranteeing
    ``require_utc_timestamp(iso_utc(ts)) == ts`` for any canonical timestamp.
    """
    if not isinstance(value, str):
        raise CanonicalError(f"{field}: expected an ISO-8601 UTC timestamp string")
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise CanonicalError(f"{field}: not a parseable timestamp ({value!r})") from exc
    if pd.isna(ts):
        raise CanonicalError(f"{field}: not a valid timestamp ({value!r})")
    if ts.tz is None:
        raise CanonicalError(f"{field}: timestamp must be timezone-aware UTC ({value!r})")
    ts_utc = ts.tz_convert("UTC")
    if ts_utc.isoformat() != value:
        raise CanonicalError(f"{field}: must be a canonical ISO-8601 UTC timestamp ({value!r})")
    return ts_utc
