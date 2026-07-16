"""Append-only, hash-chained JSONL ledger primitives shared across M3D.

Every M3D ledger (research multiplicity, data use, prospective segments) is an
append-only JSONL file whose first line is a genesis sentinel and whose every
record commits to the previous line's exact bytes through a
``previous_line_sha256`` field. This module renders and verifies that chain; it
provides no repair, truncation, deletion, or in-place mutation — a ledger can
only be rebuilt in full and compared byte-for-byte to what is committed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_jsonl_line,
    require_mapping,
    require_sha256_hex,
    sha256_bytes,
    strict_json_loads,
)

PREVIOUS_FIELD = "previous_line_sha256"
# Genesis commits to the same all-zero-input empty SHA-256 the sealed ledgers use,
# so "nothing precedes the genesis line" is stated with a well-known constant.
GENESIS_PREVIOUS = up.EMPTY_SHA256


def chained_line_bytes(records: list[dict[str, Any]]) -> list[bytes]:
    """Render ordered records (genesis first) as canonical chained JSONL line-bytes.

    Each record must **not** already carry ``previous_line_sha256``; it is injected:
    the genesis line commits to :data:`GENESIS_PREVIOUS`, and every subsequent line
    commits to the SHA-256 of the previous line's exact bytes.
    """
    lines: list[bytes] = []
    previous = GENESIS_PREVIOUS
    for record in records:
        if PREVIOUS_FIELD in record:
            raise M3DValidationError(f"record must not pre-set {PREVIOUS_FIELD}")
        line = canonical_jsonl_line({**record, PREVIOUS_FIELD: previous})
        lines.append(line)
        previous = sha256_bytes(line)
    return lines


def render_ledger_bytes(lines: list[bytes]) -> bytes:
    """Join line-bytes into canonical JSONL file bytes (newline after every line)."""
    if not lines:
        return b""
    return b"\n".join(lines) + b"\n"


def split_ledger_lines(raw: bytes) -> list[bytes]:
    """Split a committed JSONL file into line-bytes, rejecting blank/garbage lines.

    Requires a trailing newline and no empty lines, so the file is an exact join of
    canonical records with nothing hidden between or after them.
    """
    if raw == b"":
        return []
    if not raw.endswith(b"\n"):
        raise M3DValidationError("ledger file must end with a trailing newline")
    body = raw[:-1]
    lines = body.split(b"\n")
    for line in lines:
        if line == b"":
            raise M3DValidationError("ledger file contains a blank line")
    return lines


def verify_chain(lines: list[bytes]) -> list[dict[str, Any]]:
    """Strictly decode + verify the genesis + previous-line hash chain.

    Each line must decode to a JSON object, re-serialize to exactly its own bytes
    (canonical), and carry ``previous_line_sha256`` equal to the SHA-256 of the
    prior line's bytes (genesis: :data:`GENESIS_PREVIOUS`). Returns the decoded
    records in order.
    """
    if not lines:
        raise M3DValidationError("chained ledger must have at least a genesis line")
    records: list[dict[str, Any]] = []
    previous = GENESIS_PREVIOUS
    for index, line in enumerate(lines):
        record = require_mapping(f"ledger line {index}", strict_json_loads(line))
        if canonical_jsonl_line(record) != line:
            raise M3DValidationError(f"ledger line {index} is not canonical")
        stated = require_sha256_hex(
            f"ledger line {index}.{PREVIOUS_FIELD}", record.get(PREVIOUS_FIELD)
        )
        if stated != previous:
            raise M3DValidationError(f"ledger line {index} breaks the hash chain")
        records.append(record)
        previous = sha256_bytes(line)
    return records


def load_and_verify_chain(
    repo_root: str | Path, relpath: str
) -> tuple[bytes, list[dict[str, Any]]]:
    """Read a committed ledger, split, and verify its chain; return raw + records."""
    raw = (Path(repo_root) / relpath).read_bytes()
    records = verify_chain(split_ledger_lines(raw))
    return raw, records
