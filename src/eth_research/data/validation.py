"""Shared strict validators for Milestone 2B JSON models.

Extends the Milestone 2A validator family
(:mod:`eth_research.data.provenance`) with the numeric and timestamp
checks the acquisition-evidence, dataset-lock, protocol, result, and
ledger models need. Everything here rejects rather than repairs:
booleans are never accepted where numbers are required, non-finite
numbers are never accepted, and timezone-naive timestamps are never
assumed to be UTC.
"""

from __future__ import annotations

import math
import re

import pandas as pd

from eth_research.data.provenance import require_int, require_str

NANOSECONDS_PER_DAY: int = 86_400 * 10**9

_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_EVALUATION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")


def require_fingerprint(label: str, value: object) -> str:
    """A content fingerprint of the form ``sha256:<64 lowercase hex>``."""
    text = require_str(label, value)
    if not _FINGERPRINT_RE.match(text):
        raise ValueError(f"{label} must match sha256:<64 lowercase hex>, got {text!r}")
    return text


def require_commit_sha(label: str, value: object) -> str:
    """A full 40-character lowercase-hex git commit SHA."""
    text = require_str(label, value)
    if not _COMMIT_SHA_RE.match(text):
        raise ValueError(f"{label} must be 40 lowercase hex characters, got {text!r}")
    return text


def require_evaluation_id(label: str, value: object) -> str:
    """A safe test-evaluation identifier: ``^[a-z0-9][a-z0-9-]{7,63}$``."""
    text = require_str(label, value)
    if not _EVALUATION_ID_RE.match(text):
        raise ValueError(f"{label} must match ^[a-z0-9][a-z0-9-]{{7,63}}$, got {text!r}")
    return text


def require_finite_float(label: str, value: object) -> float:
    """A real, finite JSON number; bool is rejected, integers are accepted."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a finite number (bool is rejected), got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite, got {number!r}")
    return number


def require_nonnegative_int(label: str, value: object) -> int:
    number = require_int(label, value)
    if number < 0:
        raise ValueError(f"{label} must be >= 0, got {number}")
    return number


def require_positive_int(label: str, value: object) -> int:
    number = require_int(label, value)
    if number < 1:
        raise ValueError(f"{label} must be >= 1, got {number}")
    return number


def require_aware_timestamp(label: str, value: object) -> pd.Timestamp:
    """A valid, timezone-aware timestamp; naive values are rejected, never assumed UTC."""
    if not isinstance(value, pd.Timestamp) or pd.isna(value):
        raise ValueError(f"{label} must be a valid timestamp, got {value!r}")
    if value.tz is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def require_utc_timestamp(label: str, value: object) -> pd.Timestamp:
    """A timezone-aware timestamp whose offset is exactly UTC (zero).

    A merely timezone-aware value in some other zone (e.g. ``-05:00``) is
    rejected — acquisition times must be recorded in UTC, not an arbitrary
    local zone that happens to carry an offset.
    """
    ts = require_aware_timestamp(label, value)
    offset = ts.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{label} must be in UTC (zero offset), got {ts}")
    return ts


def epoch_nanoseconds(value: pd.Timestamp) -> int:
    """Exact epoch nanoseconds of a timezone-aware timestamp."""
    return int(value.as_unit("ns").value)


def require_day_aligned_utc(label: str, value: object) -> pd.Timestamp:
    """A timezone-aware timestamp aligned exactly to a 86,400-second UTC day."""
    ts = require_aware_timestamp(label, value)
    if epoch_nanoseconds(ts) % NANOSECONDS_PER_DAY != 0:
        raise ValueError(f"{label} must align to a 86400-second UTC day boundary, got {ts}")
    return ts


def parse_timestamp_field(label: str, value: object) -> pd.Timestamp:
    """Strictly parse a JSON string field into a timestamp (string input only)."""
    text = require_str(label, value)
    try:
        return pd.Timestamp(text)
    except ValueError as exc:
        raise ValueError(f"{label} is unparseable: {text!r}") from exc
