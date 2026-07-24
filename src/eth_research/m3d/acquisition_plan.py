"""Preregistered, offline-computed prospective acquisition plan.

A ``ProspectiveAcquisitionPlan`` pins exactly which public Coinbase daily candles
the one-shot acquisition may fetch: a contiguous half-open tiling of
``[2026-07-12T00:00:00Z, overall_end)`` into windows of at most 299 daily buckets,
where ``overall_end`` is the first UTC midnight after the most recent fully
completed day (computed from an explicit ``as_of``, never a wall clock). The plan
stores canonical ISO-8601 UTC request strings, safe-charset raw filenames, an
explicit user agent, the pinned public host/path, and a reproducible plan hash.
It carries no secrets, no command strings, and no URL other than the pinned
endpoint. The plan is committed before any network access; the runner replays it
exactly rather than recomputing windows that could diverge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.data.coinbase import canonical_utc_request
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_json_bytes,
    canonical_sha256,
    load_canonical_json_bytes,
    require_bool,
    require_exact,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_nonnegative_int,
    require_positive_int,
    require_str,
    require_utc_timestamp,
)

PLAN_SCHEMA_VERSION = 1
PLAN_KIND = "prospective_acquisition_plan"
ENDPOINT = "https://api.exchange.coinbase.com/products/ETH-USD/candles"
DOCUMENTATION_URL = (
    "https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles"
)
GRANULARITY_SECONDS = 86400
MAX_BUCKETS_PER_REQUEST = 299
USER_AGENT = "eth-research-m3d-prospective-acquisition/1 (offline research; public candles)"
COHORT_START = "2026-07-12T00:00:00Z"

GENESIS_ATTEMPT_ID = "coinbase-eth-usd-prospective-genesis-001"
AUDIT_ATTEMPT_ID = "coinbase-eth-usd-prospective-audit-002"
_ATTEMPT_ID_RE = re.compile(r"^coinbase-eth-usd-prospective-[a-z0-9-]+$")
_SAFE_JSON_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.json$")
_DAY = pd.Timedelta(days=1)


def _require_utc_midnight(label: str, value: object) -> pd.Timestamp:
    ts = require_utc_timestamp(
        label, value if isinstance(value, pd.Timestamp) else pd.Timestamp(str(value))
    )
    if ts != ts.floor("D"):
        raise M3DValidationError(f"{label} must be a UTC midnight, got {ts}")
    return ts


def require_safe_json_filename(label: str, value: object) -> str:
    text = require_nonempty_str(label, value)
    if not _SAFE_JSON_FILENAME_RE.fullmatch(text) or "/" in text or ".." in text:
        raise M3DValidationError(f"{label} is not a safe .json filename: {text!r}")
    return text


@dataclass(frozen=True)
class ProspectiveAcquisitionWindow:
    ordinal: int
    window_start: str
    window_end: str
    start_param: str
    end_param: str
    expected_bucket_count: int
    raw_filename: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "start_param": self.start_param,
            "end_param": self.end_param,
            "expected_bucket_count": self.expected_bucket_count,
            "raw_filename": self.raw_filename,
        }

    @classmethod
    def from_mapping(cls, doc: object) -> ProspectiveAcquisitionWindow:
        mapping = require_mapping("window", doc)
        expected = {
            "ordinal",
            "window_start",
            "window_end",
            "start_param",
            "end_param",
            "expected_bucket_count",
            "raw_filename",
        }
        if set(mapping) != expected:
            raise M3DValidationError(f"window keys must be {sorted(expected)}")
        start = _require_utc_midnight("window_start", mapping["window_start"])
        end = _require_utc_midnight("window_end", mapping["window_end"])
        if not end > start:
            raise M3DValidationError("window_end must be after window_start")
        buckets = int((end - start) / _DAY)
        if buckets != require_positive_int(
            "expected_bucket_count", mapping["expected_bucket_count"]
        ):
            raise M3DValidationError("expected_bucket_count must equal the window's day span")
        if buckets > MAX_BUCKETS_PER_REQUEST:
            raise M3DValidationError(f"window exceeds {MAX_BUCKETS_PER_REQUEST} buckets")
        # Coinbase start/end query params are INCLUSIVE bucket opens, so the
        # request covers [start_param, end_param] inclusive while the plan window
        # is the half-open [window_start, window_end). The last bucket in the
        # half-open window opens at window_end - 1 day, so end_param must be that
        # open (never window_end itself, which would pull the forming candle).
        if require_str("start_param", mapping["start_param"]) != canonical_utc_request(start):
            raise M3DValidationError(
                "start_param must be the canonical request string for window_start"
            )
        if require_str("end_param", mapping["end_param"]) != canonical_utc_request(end - _DAY):
            raise M3DValidationError(
                "end_param must be the canonical request string for window_end - 1 day"
            )
        return cls(
            ordinal=require_nonnegative_int("ordinal", mapping["ordinal"]),
            window_start=require_str("window_start", mapping["window_start"]),
            window_end=require_str("window_end", mapping["window_end"]),
            start_param=mapping["start_param"],
            end_param=mapping["end_param"],
            expected_bucket_count=buckets,
            raw_filename=require_safe_json_filename("raw_filename", mapping["raw_filename"]),
        )


@dataclass(frozen=True)
class ProspectiveAcquisitionPlan:
    document: dict[str, Any]

    @classmethod
    def from_mapping(cls, doc: object) -> ProspectiveAcquisitionPlan:
        mapping = require_mapping("plan", doc)
        _require_exact_keys(
            "plan",
            mapping,
            {
                "schema_version",
                "kind",
                "package_version",
                "attempt_id",
                "endpoint",
                "documentation_url",
                "docs_recheck",
                "granularity_seconds",
                "user_agent",
                "overall_start",
                "overall_end",
                "max_buckets_per_request",
                "expected_total_buckets",
                "windows",
                "plan_sha256",
            },
        )
        require_exact(
            "schema_version",
            require_positive_int("schema_version", mapping["schema_version"]),
            PLAN_SCHEMA_VERSION,
        )
        require_exact("kind", require_str("kind", mapping["kind"]), PLAN_KIND)
        attempt_id = require_str("attempt_id", mapping["attempt_id"])
        if not _ATTEMPT_ID_RE.fullmatch(attempt_id):
            raise M3DValidationError(
                f"attempt_id {attempt_id!r} is not a valid prospective attempt id"
            )
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

        overall_start = _require_utc_midnight("overall_start", mapping["overall_start"])
        overall_end = _require_utc_midnight("overall_end", mapping["overall_end"])
        if require_str("overall_start", mapping["overall_start"]) != COHORT_START:
            raise M3DValidationError("overall_start must be the fixed cohort start")
        if not overall_end > overall_start:
            raise M3DValidationError("overall_end must be after overall_start")

        docs_recheck = _validate_docs_recheck("docs_recheck", mapping["docs_recheck"])

        windows = [
            ProspectiveAcquisitionWindow.from_mapping(w)
            for w in require_list("windows", mapping["windows"])
        ]
        _check_tiling(overall_start, overall_end, windows)
        total = sum(w.expected_bucket_count for w in windows)
        if total != require_positive_int(
            "expected_total_buckets", mapping["expected_total_buckets"]
        ):
            raise M3DValidationError("expected_total_buckets must equal the summed window buckets")

        document = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "kind": PLAN_KIND,
            "package_version": require_str("package_version", mapping["package_version"]),
            "attempt_id": attempt_id,
            "endpoint": ENDPOINT,
            "documentation_url": require_str("documentation_url", mapping["documentation_url"]),
            "docs_recheck": docs_recheck,
            "granularity_seconds": GRANULARITY_SECONDS,
            "user_agent": USER_AGENT,
            "overall_start": mapping["overall_start"],
            "overall_end": mapping["overall_end"],
            "max_buckets_per_request": MAX_BUCKETS_PER_REQUEST,
            "expected_total_buckets": total,
            "windows": [w.to_dict() for w in windows],
        }
        expected_hash = canonical_sha256(document)
        if require_str("plan_sha256", mapping["plan_sha256"]) != expected_hash:
            raise M3DValidationError("plan_sha256 does not match the canonical plan hash")
        document["plan_sha256"] = expected_hash
        return cls(document=document)

    @property
    def attempt_id(self) -> str:
        return str(self.document["attempt_id"])

    @property
    def plan_sha256(self) -> str:
        return str(self.document["plan_sha256"])

    @property
    def windows(self) -> list[dict[str, Any]]:
        return list(self.document["windows"])

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.document)


def _require_exact_keys(label: str, mapping: dict[str, Any], keys: set[str]) -> None:
    present = set(mapping)
    if missing := keys - present:
        raise M3DValidationError(f"{label} missing keys: {sorted(missing)}")
    if unknown := present - keys:
        raise M3DValidationError(f"{label} has unknown keys: {sorted(unknown)}")


def _validate_docs_recheck(label: str, value: object) -> dict[str, Any]:
    mapping = require_mapping(label, value)
    _require_exact_keys(
        label, mapping, {"access_date", "http_status", "accessible", "source_of_truth"}
    )
    return {
        "access_date": require_str(f"{label}.access_date", mapping["access_date"]),
        "http_status": require_positive_int(f"{label}.http_status", mapping["http_status"]),
        "accessible": require_bool(f"{label}.accessible", mapping["accessible"]),
        "source_of_truth": require_str(f"{label}.source_of_truth", mapping["source_of_truth"]),
    }


def _check_tiling(
    overall_start: pd.Timestamp,
    overall_end: pd.Timestamp,
    windows: list[ProspectiveAcquisitionWindow],
) -> None:
    if not windows:
        raise M3DValidationError("plan must have at least one window")
    cursor = overall_start
    for index, window in enumerate(windows):
        if window.ordinal != index:
            raise M3DValidationError(f"window ordinal must be {index}, got {window.ordinal}")
        if pd.Timestamp(window.window_start) != cursor:
            raise M3DValidationError("windows must tile contiguously with no gap or overlap")
        cursor = pd.Timestamp(window.window_end)
    if cursor != overall_end:
        raise M3DValidationError("windows must tile exactly up to overall_end")
    filenames = [w.raw_filename for w in windows]
    if len(filenames) != len(set(filenames)):
        raise M3DValidationError("duplicate raw filename in plan")


def build_prospective_acquisition_plan(
    *, attempt_id: str, as_of_utc: pd.Timestamp, docs_recheck: dict[str, Any]
) -> ProspectiveAcquisitionPlan:
    """Compute the plan for ``[cohort_start, first_midnight_after_completed_day)``.

    ``overall_end`` is derived from ``as_of_utc`` (floored to its UTC midnight), so
    the window covers only fully completed days and never a forming candle.
    """
    from eth_research.m3d import M3D_PACKAGE_VERSION

    if not _ATTEMPT_ID_RE.fullmatch(attempt_id):
        raise M3DValidationError(f"attempt_id {attempt_id!r} is not a valid prospective attempt id")
    overall_start = pd.Timestamp(COHORT_START)
    as_of = require_utc_timestamp("as_of_utc", as_of_utc)
    overall_end = as_of.floor("D")
    if not overall_end > overall_start:
        raise M3DValidationError("no completed prospective day is available yet (HARD STOP)")

    windows: list[ProspectiveAcquisitionWindow] = []
    cursor = overall_start
    ordinal = 0
    while cursor < overall_end:
        span_days = min(MAX_BUCKETS_PER_REQUEST, int((overall_end - cursor) / _DAY))
        window_end = cursor + span_days * _DAY
        filename = (
            f"coinbase-eth-usd-1d_{ordinal:04d}_"
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

    document = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "package_version": M3D_PACKAGE_VERSION,
        "attempt_id": attempt_id,
        "endpoint": ENDPOINT,
        "documentation_url": DOCUMENTATION_URL,
        "docs_recheck": docs_recheck,
        "granularity_seconds": GRANULARITY_SECONDS,
        "user_agent": USER_AGENT,
        "overall_start": canonical_utc_request(overall_start),
        "overall_end": canonical_utc_request(overall_end),
        "max_buckets_per_request": MAX_BUCKETS_PER_REQUEST,
        "expected_total_buckets": sum(w.expected_bucket_count for w in windows),
        "windows": [w.to_dict() for w in windows],
    }
    document["plan_sha256"] = canonical_sha256(document)
    return ProspectiveAcquisitionPlan.from_mapping(document)


# ------------------------------------------------------------------------------------
# Update-attempt plans (V2D growth): an update attempt directory carries, verbatim, the
# M3E update plan its runner receipts bind (``receipt.plan_sha256`` is the M3E plan
# hash). This m3d-native validator accepts exactly that document kind so
# ``build_raw_bundles`` can replay a landed update attempt from committed bytes without
# importing m3e (layering: m3e imports m3d, never the reverse). It validates only what
# the raw-bundle replay needs — constants, window tiling, totals, and the plan's
# self-hash; the idempotency/base-fingerprint *semantics* stay M3E's job
# (``verify_m3e_program``), while the hash covers their bytes here.
# ------------------------------------------------------------------------------------

UPDATE_PLAN_KIND = "prospective_update_plan"
_UPDATE_PLAN_KEYS = {
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
}


@dataclass(frozen=True)
class ProspectiveUpdatePlanView:
    """A strictly-validated m3d view of a committed M3E update plan."""

    document: dict[str, Any]

    @property
    def plan_sha256(self) -> str:
        return str(self.document["plan_sha256"])

    @property
    def windows(self) -> list[dict[str, Any]]:
        return list(self.document["windows"])

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.document)

    @classmethod
    def from_mapping(cls, doc: object) -> ProspectiveUpdatePlanView:
        mapping = require_mapping("update_plan", doc)
        _require_exact_keys("update_plan", mapping, _UPDATE_PLAN_KEYS)
        require_exact(
            "schema_version",
            require_positive_int("schema_version", mapping["schema_version"]),
            1,
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
        base_fingerprint = require_str("base_fingerprint", mapping["base_fingerprint"])
        if len(base_fingerprint) != 64 or any(
            c not in "0123456789abcdef" for c in base_fingerprint
        ):
            raise M3DValidationError("base_fingerprint is not a sha256 hex digest")
        last_open = _require_utc_midnight("accepted_last_open", mapping["accepted_last_open"])
        first_missing = _require_utc_midnight("first_missing_open", mapping["first_missing_open"])
        end = _require_utc_midnight(
            "completed_day_exclusive_end", mapping["completed_day_exclusive_end"]
        )
        if first_missing != last_open + _DAY:
            raise M3DValidationError("first_missing_open must be accepted_last_open + 1 day")
        if not end > first_missing:
            raise M3DValidationError("completed_day_exclusive_end must be after first_missing_open")
        key = require_str("idempotency_key", mapping["idempotency_key"])
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise M3DValidationError("idempotency_key is not a sha256 hex digest")

        windows = [
            ProspectiveAcquisitionWindow.from_mapping(w)
            for w in require_list("windows", mapping["windows"])
        ]
        _check_tiling(first_missing, end, windows)
        total = sum(w.expected_bucket_count for w in windows)
        if total != require_positive_int(
            "expected_total_buckets", mapping["expected_total_buckets"]
        ):
            raise M3DValidationError("expected_total_buckets must equal the summed window buckets")

        document = {
            "schema_version": 1,
            "kind": UPDATE_PLAN_KIND,
            "package_version": require_str("package_version", mapping["package_version"]),
            "endpoint": ENDPOINT,
            "documentation_url": require_str("documentation_url", mapping["documentation_url"]),
            "granularity_seconds": GRANULARITY_SECONDS,
            "user_agent": USER_AGENT,
            "max_buckets_per_request": MAX_BUCKETS_PER_REQUEST,
            "base_fingerprint": base_fingerprint,
            "accepted_last_open": require_str("accepted_last_open", mapping["accepted_last_open"]),
            "first_missing_open": require_str("first_missing_open", mapping["first_missing_open"]),
            "completed_day_exclusive_end": require_str(
                "completed_day_exclusive_end", mapping["completed_day_exclusive_end"]
            ),
            "expected_total_buckets": total,
            "windows": [w.to_dict() for w in windows],
            "idempotency_key": key,
        }
        expected_hash = canonical_sha256(document)
        if require_str("plan_sha256", mapping["plan_sha256"]) != expected_hash:
            raise M3DValidationError("update plan_sha256 does not match the canonical plan hash")
        document["plan_sha256"] = expected_hash
        return cls(document=document)


def load_prospective_acquisition_plan(
    path: str | Path,
) -> ProspectiveAcquisitionPlan | ProspectiveUpdatePlanView:
    """Load a committed attempt plan, dispatching strictly on its declared kind.

    A genesis/audit attempt carries a ``prospective_acquisition_plan``; a landed
    update attempt carries, verbatim, the M3E ``prospective_update_plan`` its runner
    receipt binds. Both paths are strict; any other kind is refused.
    """
    _raw, doc = load_canonical_json_bytes(Path(path), "prospective_acquisition_plan")
    mapping = require_mapping("plan", doc)
    kind = require_str("kind", mapping.get("kind"))
    if kind == UPDATE_PLAN_KIND:
        return ProspectiveUpdatePlanView.from_mapping(mapping)
    return ProspectiveAcquisitionPlan.from_mapping(mapping)
