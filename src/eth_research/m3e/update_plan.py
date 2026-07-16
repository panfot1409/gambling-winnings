"""Deterministic, append-only prospective update plan + idempotency key.

A ``ProspectiveUpdatePlan`` pins exactly which newly-completed public Coinbase
daily candles an update proposal may fetch: a contiguous half-open tiling of the
due window ``[first_missing_open, completed_day_exclusive_end)`` (from
:func:`eth_research.m3e.cutoff.plan_update_window`) into windows of at most 299
daily buckets. It is a **deterministic function of the verified accepted base and
the explicit cutoff** — the same base and the same due window always yield the same
plan bytes and the same idempotency key, so two scheduled runs for the same due
window converge on one proposal rather than duplicating it.

The per-window schema and the Coinbase inclusive-``start``/``end`` convention are
the reviewed Milestone 3D machinery, reused unmodified. The plan carries no
secret, no command string, and no URL other than the pinned public endpoint; it is
computed offline before any network access, and each runner replays it exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.data.coinbase import canonical_utc_request
from eth_research.m3d.acquisition_plan import (
    DOCUMENTATION_URL,
    ENDPOINT,
    GRANULARITY_SECONDS,
    MAX_BUCKETS_PER_REQUEST,
    USER_AGENT,
    ProspectiveAcquisitionWindow,
    require_safe_json_filename,
)
from eth_research.m3e import M3E_PACKAGE_VERSION
from eth_research.m3e.accepted_base import AcceptedProspectiveBase
from eth_research.m3e.cutoff import UpdateWindowDecision
from eth_research.m3e.validation import (
    M3EValidationError,
    canonical_json_bytes,
    canonical_sha256,
    domain_sha256,
    load_canonical_json_bytes,
    require_exact,
    require_list,
    require_mapping,
    require_positive_int,
    require_sha256_hex,
    require_str,
)

UPDATE_PLAN_SCHEMA_VERSION = 1
UPDATE_PLAN_KIND = "prospective_update_plan"
UPDATE_PLAN_DOMAIN = "m3e_prospective_update_plan"
IDEMPOTENCY_DOMAIN = "m3e_update_idempotency"
_DAY = pd.Timedelta(days=1)


def _z(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_idempotency_key(
    *,
    base_fingerprint: str,
    accepted_last_open: str,
    first_missing_open: str,
    completed_day_exclusive_end: str,
    expected_total_buckets: int,
) -> str:
    """Deterministic key for a due window over a specific accepted base."""
    return domain_sha256(
        IDEMPOTENCY_DOMAIN,
        {
            "base_fingerprint": base_fingerprint,
            "accepted_last_open": accepted_last_open,
            "first_missing_open": first_missing_open,
            "completed_day_exclusive_end": completed_day_exclusive_end,
            "expected_total_buckets": expected_total_buckets,
        },
    )


@dataclass(frozen=True)
class ProspectiveUpdatePlan:
    document: dict[str, Any]

    @property
    def idempotency_key(self) -> str:
        return str(self.document["idempotency_key"])

    @property
    def plan_sha256(self) -> str:
        return str(self.document["plan_sha256"])

    @property
    def windows(self) -> list[dict[str, Any]]:
        return list(self.document["windows"])

    @property
    def expected_total_buckets(self) -> int:
        return int(self.document["expected_total_buckets"])

    @property
    def first_missing_open(self) -> str:
        return str(self.document["first_missing_open"])

    @property
    def completed_day_exclusive_end(self) -> str:
        return str(self.document["completed_day_exclusive_end"])

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.document)

    @classmethod
    def from_mapping(cls, doc: object) -> ProspectiveUpdatePlan:
        mapping = require_mapping("update_plan", doc)
        _require_exact_keys(
            "update_plan",
            mapping,
            {
                "schema_version",
                "kind",
                "package_version",
                "endpoint",
                "documentation_url",
                "granularity_seconds",
                "user_agent",
                "max_buckets_per_request",
                "base_fingerprint",
                "accepted_last_open",
                "first_missing_open",
                "completed_day_exclusive_end",
                "expected_total_buckets",
                "windows",
                "idempotency_key",
                "plan_sha256",
            },
        )
        require_exact(
            "schema_version",
            require_positive_int("schema_version", mapping["schema_version"]),
            UPDATE_PLAN_SCHEMA_VERSION,
        )
        require_exact("kind", require_str("kind", mapping["kind"]), UPDATE_PLAN_KIND)
        require_exact("endpoint", require_str("endpoint", mapping["endpoint"]), ENDPOINT)
        require_exact(
            "granularity_seconds",
            require_positive_int("granularity_seconds", mapping["granularity_seconds"]),
            GRANULARITY_SECONDS,
        )
        require_exact("user_agent", require_str("user_agent", mapping["user_agent"]), USER_AGENT)
        require_exact(
            "max_buckets_per_request",
            require_positive_int("max_buckets_per_request", mapping["max_buckets_per_request"]),
            MAX_BUCKETS_PER_REQUEST,
        )
        base_fingerprint = require_sha256_hex("base_fingerprint", mapping["base_fingerprint"])
        first_missing = _require_utc_midnight("first_missing_open", mapping["first_missing_open"])
        end = _require_utc_midnight(
            "completed_day_exclusive_end", mapping["completed_day_exclusive_end"]
        )
        last_open = _require_utc_midnight("accepted_last_open", mapping["accepted_last_open"])
        if first_missing != last_open + _DAY:
            raise M3EValidationError("first_missing_open must be accepted_last_open + 1 day")
        if not end > first_missing:
            raise M3EValidationError("completed_day_exclusive_end must be after first_missing_open")

        windows = [
            ProspectiveAcquisitionWindow.from_mapping(w)
            for w in require_list("windows", mapping["windows"])
        ]
        _check_tiling(first_missing, end, windows)
        total = sum(w.expected_bucket_count for w in windows)
        if total != require_positive_int(
            "expected_total_buckets", mapping["expected_total_buckets"]
        ):
            raise M3EValidationError("expected_total_buckets must equal the summed window buckets")

        expected_key = compute_idempotency_key(
            base_fingerprint=base_fingerprint,
            accepted_last_open=_z(last_open),
            first_missing_open=_z(first_missing),
            completed_day_exclusive_end=_z(end),
            expected_total_buckets=total,
        )
        if require_sha256_hex("idempotency_key", mapping["idempotency_key"]) != expected_key:
            raise M3EValidationError("idempotency_key does not match the base + due window")

        document = {
            "schema_version": UPDATE_PLAN_SCHEMA_VERSION,
            "kind": UPDATE_PLAN_KIND,
            "package_version": require_str("package_version", mapping["package_version"]),
            "endpoint": ENDPOINT,
            "documentation_url": require_str("documentation_url", mapping["documentation_url"]),
            "granularity_seconds": GRANULARITY_SECONDS,
            "user_agent": USER_AGENT,
            "max_buckets_per_request": MAX_BUCKETS_PER_REQUEST,
            "base_fingerprint": base_fingerprint,
            "accepted_last_open": _z(last_open),
            "first_missing_open": _z(first_missing),
            "completed_day_exclusive_end": _z(end),
            "expected_total_buckets": total,
            "windows": [w.to_dict() for w in windows],
            "idempotency_key": expected_key,
        }
        expected_hash = canonical_sha256(document)
        if require_str("plan_sha256", mapping["plan_sha256"]) != expected_hash:
            raise M3EValidationError("plan_sha256 does not match the canonical plan hash")
        document["plan_sha256"] = expected_hash
        return cls(document=document)


def build_update_plan(
    base: AcceptedProspectiveBase, decision: UpdateWindowDecision
) -> ProspectiveUpdatePlan:
    """Tile the due window into <=299-bucket windows; bind base + idempotency.

    Raises on a NO-OP decision — there is no plan when nothing is due.
    """
    if decision.is_noop:
        raise M3EValidationError("cannot build an update plan for a no-op (nothing is due)")
    if decision.window_start is None or decision.window_end is None:
        raise M3EValidationError("non-noop decision must carry a window")
    if decision.accepted_last_open != base.last_open:
        raise M3EValidationError("decision was computed against a different accepted base")

    first_missing = _require_utc_midnight("first_missing_open", decision.first_missing_open)
    end = _require_utc_midnight("completed_day_exclusive_end", decision.completed_day_exclusive_end)
    last_open = _require_utc_midnight("accepted_last_open", base.last_open)
    if first_missing != last_open + _DAY:
        raise M3EValidationError("first_missing_open must be accepted_last_open + 1 day")

    windows: list[ProspectiveAcquisitionWindow] = []
    cursor = first_missing
    ordinal = 0
    while cursor < end:
        span_days = min(MAX_BUCKETS_PER_REQUEST, int((end - cursor) / _DAY))
        window_end = cursor + span_days * _DAY
        filename = (
            f"coinbase-eth-usd-1d-update_{ordinal:04d}_"
            f"{cursor.strftime('%Y%m%d')}_{window_end.strftime('%Y%m%d')}.json"
        )
        windows.append(
            ProspectiveAcquisitionWindow(
                ordinal=ordinal,
                window_start=canonical_utc_request(cursor),
                window_end=canonical_utc_request(window_end),
                start_param=canonical_utc_request(cursor),
                end_param=canonical_utc_request(window_end - _DAY),
                expected_bucket_count=span_days,
                raw_filename=require_safe_json_filename("raw_filename", filename),
            )
        )
        cursor = window_end
        ordinal += 1

    total = sum(w.expected_bucket_count for w in windows)
    idempotency_key = compute_idempotency_key(
        base_fingerprint=base.canonical_content_fingerprint,
        accepted_last_open=_z(last_open),
        first_missing_open=_z(first_missing),
        completed_day_exclusive_end=_z(end),
        expected_total_buckets=total,
    )
    document = {
        "schema_version": UPDATE_PLAN_SCHEMA_VERSION,
        "kind": UPDATE_PLAN_KIND,
        "package_version": M3E_PACKAGE_VERSION,
        "endpoint": ENDPOINT,
        "documentation_url": DOCUMENTATION_URL,
        "granularity_seconds": GRANULARITY_SECONDS,
        "user_agent": USER_AGENT,
        "max_buckets_per_request": MAX_BUCKETS_PER_REQUEST,
        "base_fingerprint": base.canonical_content_fingerprint,
        "accepted_last_open": _z(last_open),
        "first_missing_open": _z(first_missing),
        "completed_day_exclusive_end": _z(end),
        "expected_total_buckets": total,
        "windows": [w.to_dict() for w in windows],
        "idempotency_key": idempotency_key,
    }
    document["plan_sha256"] = canonical_sha256(document)
    return ProspectiveUpdatePlan.from_mapping(document)


def load_update_plan(path: str | Path) -> ProspectiveUpdatePlan:
    _raw, doc = load_canonical_json_bytes(Path(path), "prospective_update_plan")
    return ProspectiveUpdatePlan.from_mapping(doc)


def _require_utc_midnight(label: str, value: object) -> pd.Timestamp:
    from eth_research.m3e.validation import require_utc_timestamp

    ts = require_utc_timestamp(
        label, value if isinstance(value, pd.Timestamp) else pd.Timestamp(str(value))
    )
    if ts != ts.floor("D"):
        raise M3EValidationError(f"{label} must be a UTC midnight, got {ts}")
    return ts


def _require_exact_keys(label: str, mapping: dict[str, Any], keys: set[str]) -> None:
    present = set(mapping)
    if missing := keys - present:
        raise M3EValidationError(f"{label} missing keys: {sorted(missing)}")
    if unknown := present - keys:
        raise M3EValidationError(f"{label} has unknown keys: {sorted(unknown)}")


def _check_tiling(
    first_missing: pd.Timestamp,
    end: pd.Timestamp,
    windows: list[ProspectiveAcquisitionWindow],
) -> None:
    if not windows:
        raise M3EValidationError("update plan must have at least one window")
    cursor = first_missing
    for index, window in enumerate(windows):
        if window.ordinal != index:
            raise M3EValidationError(f"window ordinal must be {index}, got {window.ordinal}")
        if pd.Timestamp(window.window_start) != cursor:
            raise M3EValidationError("windows must tile contiguously with no gap or overlap")
        cursor = pd.Timestamp(window.window_end)
    if cursor != end:
        raise M3EValidationError("windows must tile exactly up to the completed-day cutoff")
    filenames = [w.raw_filename for w in windows]
    if len(filenames) != len(set(filenames)):
        raise M3EValidationError("duplicate raw filename in update plan")
