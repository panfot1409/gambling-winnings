"""One strict JSON decoder shared by every provenance-bearing format.

Python's ``json.loads`` is permissive in ways that break a strict-schema
claim: it silently keeps the last of duplicate object keys, and it decodes
``NaN``/``Infinity``/``-Infinity`` and exponent-overflow tokens like
``1e999`` into non-finite floats. Every Milestone 2A/2B format is parsed
through :func:`strict_json_loads` so those ambiguities are rejected
identically everywhere, before any field validator runs.

The rules:

* **duplicate keys** at any nesting level are rejected (``object_pairs_hook``
  sees every pair, including repeats);
* the bare constants ``NaN``, ``Infinity`` and ``-Infinity`` are rejected
  (``parse_constant``);
* any float token that decodes to a non-finite value — exponent overflow
  such as ``1e999`` — is rejected (``parse_float``);
* normal JSON integers and finite floats are returned unchanged, so field
  validators keep their exact type checks.

:class:`StrictJSONError` subclasses :class:`ValueError`, so the existing
``except ValueError`` sites in every ``from_json_bytes`` keep working.
"""

from __future__ import annotations

import json
import math
from typing import Any


class StrictJSONError(ValueError):
    """A JSON document violated the strict decoding rules."""


def _reject_constant(token: str) -> float:
    raise StrictJSONError(f"non-finite JSON constant {token!r} is rejected")


def _checked_float(token: str) -> float:
    number = float(token)
    if not math.isfinite(number):
        raise StrictJSONError(f"non-finite JSON number {token!r} is rejected (exponent overflow)")
    return number


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError(f"duplicate JSON object key {key!r} is rejected")
        result[key] = value
    return result


def require_canonical_file_bytes(raw: bytes, label: str) -> bytes:
    """A serialized artifact *file* must end with exactly one trailing newline.

    Every model's ``to_json_bytes`` appends ``"\\n"``, so the canonical on-disk
    form ends with a newline. Enforcing that at the file-load boundary makes a
    committed artifact a true serialize fixed point (``load(dump(x)) == file``),
    rather than silently accepting a de-newlined file. ``from_json_bytes`` itself
    stays a lenient parser — registry/errata *lines* carry no trailing newline —
    and every committed artifact is additionally SHA-256-bound downstream.
    """
    if not raw.endswith(b"\n"):
        raise StrictJSONError(f"{label} must end with a trailing newline")
    return raw


def strict_json_loads(raw: bytes | str) -> Any:
    """Parse JSON with the strict rules above; raise :class:`StrictJSONError`.

    Accepts ``bytes`` (decoded as UTF-8) or ``str``. The return value is a
    plain Python object graph with no duplicate keys and no non-finite
    numbers anywhere.
    """
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StrictJSONError(f"not valid UTF-8: {exc}") from exc
    else:
        text = raw
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
            parse_float=_checked_float,
        )
    except StrictJSONError:
        raise
    except json.JSONDecodeError as exc:
        raise StrictJSONError(f"not valid JSON: {exc}") from exc
