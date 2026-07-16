"""Shared strict-validation and canonicalization surface for Milestone 3E.

M3E reuses, unmodified, the single strict-validation surface the completed
Milestone 3D already established (canonical JSON, domain-separated hashing,
hash-chained JSONL line rendering, strict field validators, canonical-file
loading). Re-exporting it here — rather than importing scattered symbols across
the package — keeps one invariant surface shared between construction and parsing,
so a value that would be rejected on load can never be produced on build, and
keeps the reviewed M3D validators as the single source of truth.

This module adds no new validation behaviour; it only re-exports. The M3E import
allow-list (``tests/test_m3e_architecture.py``) permits ``eth_research.m3d.validation``
exactly because it is strategy-free and already reviewed.
"""

from __future__ import annotations

from eth_research.m3d.validation import (
    M3DValidationError,
    StrictJSONError,
    canonical_json_bytes,
    canonical_jsonl_line,
    canonical_sha256,
    domain_sha256,
    epoch_nanoseconds,
    jsonl_line_sha256,
    load_canonical_json,
    load_canonical_json_bytes,
    require_aware_timestamp,
    require_bool,
    require_commit_sha,
    require_day_aligned_utc,
    require_exact,
    require_fingerprint,
    require_finite_float,
    require_int,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_nonnegative_int,
    require_positive_int,
    require_sha256_hex,
    require_str,
    require_string_sequence,
    require_utc_timestamp,
    sha256_bytes,
    strict_json_loads,
)

# A single strict error class for M3E, identical to the M3D one so ``except
# ValueError`` at parse boundaries keeps working and the two milestones share one
# error taxonomy.
M3EValidationError = M3DValidationError

__all__ = [
    "M3DValidationError",
    "M3EValidationError",
    "StrictJSONError",
    "canonical_json_bytes",
    "canonical_jsonl_line",
    "canonical_sha256",
    "domain_sha256",
    "epoch_nanoseconds",
    "jsonl_line_sha256",
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
