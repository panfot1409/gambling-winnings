"""Machine-readable acquisition request plan and workflow receipts.

Real-data acquisition (Milestone 2B Part B) replaces hand-edited ``curl``
commands with a strict, deterministic **request plan**: the exact set of
public Coinbase Exchange candle windows to fetch, each as a fixed
half-open UTC day range with its canonical request parameters and the raw
output filename. The plan is generated offline from explicit start/end
values, parsed through the shared strict JSON decoder, and validated to
tile ``[overall_start, overall_end)`` exactly — no gaps, overlaps,
reordering, off-by-one windows, unsafe filenames, or arbitrary
host/scheme/product/query injection. **No free-form shell command is ever
stored here.**

The acquisition workflow additionally records a signed-off **receipt** per
attempt: the plan it fulfilled, the workflow run id, the source commit,
the curl version, and — per response — the HTTP status, byte length,
SHA-256, and retrieval time. Receipts never carry authorization headers,
cookies, tokens, or environment dumps.

This module performs **no networking**. It is the offline contract the
clean-room workflow consumes and the offline replay verifies against.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import pandas as pd

from eth_research import __version__
from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.coinbase import (
    COINBASE_CANDLES_ENDPOINT,
    COINBASE_DOCUMENTATION_URL,
    COINBASE_GRANULARITY_SECONDS,
    COINBASE_PRODUCT,
    COINBASE_VENUE,
    MAX_WINDOW_DAYS,
    canonical_utc_request,
)
from eth_research.data.provenance import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_safe_basename,
    require_str,
    sha256_bytes,
)
from eth_research.data.validation import (
    parse_timestamp_field,
    require_commit_sha,
    require_day_aligned_utc,
    require_nonnegative_int,
    require_positive_int,
    require_utc_timestamp,
)

ACQUISITION_PLAN_SCHEMA_VERSION: int = 1
ACQUISITION_RECEIPT_SCHEMA_VERSION: int = 1

MAX_CANDLES_PER_REQUEST: int = 300
"""Coinbase serves at most 300 candles per response."""

COINBASE_RATE_LIMIT_URL: str = "https://docs.cdp.coinbase.com/exchange/rest-api/rate-limits"

ACQUISITION_USER_AGENT: str = "eth-research-m2b-acquisition/1 (offline research; public candles)"
"""Fixed, descriptive user-agent; carries no account or contact identity."""

TIMESTAMP_CONVENTION: str = (
    "UTC candle open times; half-open [window_start, window_end); Coinbase start/end "
    "request params are inclusive bucket opens (start == window_start, "
    "end == window_end - 1 day)"
)

_DAY: pd.Timedelta = pd.Timedelta(days=1)

_SAFE_JSON_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.json$")
"""Raw filenames are a strict charset: no spaces or shell metacharacters, so
a plan value can never be smuggled into a shell command."""


def _require_safe_json_filename(label: str, value: object) -> str:
    text = require_safe_basename(label, value)
    if not _SAFE_JSON_FILENAME_RE.match(text):
        raise ValueError(
            f"{label} must match [A-Za-z0-9._-]+.json with no spaces or shell metacharacters, "
            f"got {text!r}"
        )
    return text


_WINDOW_KEYS: frozenset[str] = frozenset(
    {"ordinal", "window_start", "window_end", "requested_start", "requested_end", "filename"}
)

_PLAN_KEYS: frozenset[str] = frozenset(
    {
        "plan_schema_version",
        "package_version",
        "venue",
        "product",
        "endpoint",
        "granularity_seconds",
        "documentation_url",
        "rate_limit_url",
        "timestamp_convention",
        "user_agent",
        "max_candles_per_request",
        "max_window_days",
        "overall_start",
        "overall_end",
        "no_repair",
        "windows",
    }
)

_RESPONSE_RECEIPT_KEYS: frozenset[str] = frozenset(
    {"ordinal", "filename", "http_status", "byte_length", "sha256", "retrieved_at", "content_type"}
)

_ATTEMPT_RECEIPT_KEYS: frozenset[str] = frozenset(
    {
        "receipt_schema_version",
        "package_version",
        "plan_sha256",
        "attempt_id",
        "workflow_run_id",
        "source_commit",
        "curl_version",
        "runner",
        "user_agent",
        "responses",
    }
)


class AcquisitionPlanError(RuntimeError):
    """A request plan or acquisition receipt is invalid or inconsistent."""


def _require_window(window_start: pd.Timestamp, window_end: pd.Timestamp) -> None:
    require_day_aligned_utc("window_start", window_start)
    require_day_aligned_utc("window_end", window_end)
    if window_start >= window_end:
        raise ValueError(f"window_start {window_start} must precede window_end {window_end}")
    if window_end - window_start > _DAY * MAX_WINDOW_DAYS:
        raise ValueError(
            f"window {window_start} .. {window_end} spans more than {MAX_WINDOW_DAYS} daily "
            f"buckets; Coinbase serves at most {MAX_CANDLES_PER_REQUEST} candles per response"
        )


@dataclass(frozen=True)
class AcquisitionWindow:
    """One planned request: a half-open UTC day window and its raw filename."""

    ordinal: int
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    requested_start: str
    requested_end: str
    filename: str

    def __post_init__(self) -> None:
        require_nonnegative_int("ordinal", self.ordinal)
        _require_window(self.window_start, self.window_end)
        expected_start = canonical_utc_request(self.window_start)
        expected_end = canonical_utc_request(self.window_end - _DAY)
        if require_str("requested_start", self.requested_start) != expected_start:
            raise ValueError(
                f"requested_start must be the canonical UTC open {expected_start!r} for "
                f"window_start, got {self.requested_start!r}"
            )
        if require_str("requested_end", self.requested_end) != expected_end:
            raise ValueError(
                f"requested_end must be the canonical UTC open {expected_end!r} (window_end - "
                f"1 day), got {self.requested_end!r}"
            )
        _require_safe_json_filename("filename", self.filename)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "filename": self.filename,
        }

    @classmethod
    def from_json_dict(cls, payload: object) -> AcquisitionWindow:
        if not isinstance(payload, dict):
            raise ValueError(f"window entry must be an object, got {type(payload).__name__}")
        keys = set(payload)
        if keys != _WINDOW_KEYS:
            unknown = sorted(keys - _WINDOW_KEYS)
            missing = sorted(_WINDOW_KEYS - keys)
            raise ValueError(
                f"window keys do not match schema: unknown={unknown}, missing={missing}"
            )
        return cls(
            ordinal=payload["ordinal"],
            window_start=parse_timestamp_field("window_start", payload["window_start"]),
            window_end=parse_timestamp_field("window_end", payload["window_end"]),
            requested_start=payload["requested_start"],
            requested_end=payload["requested_end"],
            filename=payload["filename"],
        )


@dataclass(frozen=True)
class AcquisitionRequestPlan:
    """The complete, deterministic set of public candle requests to make."""

    plan_schema_version: int
    package_version: str
    venue: str
    product: str
    endpoint: str
    granularity_seconds: int
    documentation_url: str
    rate_limit_url: str
    timestamp_convention: str
    user_agent: str
    max_candles_per_request: int
    max_window_days: int
    overall_start: pd.Timestamp
    overall_end: pd.Timestamp
    no_repair: bool
    windows: tuple[AcquisitionWindow, ...]

    def __post_init__(self) -> None:
        version = require_int("plan_schema_version", self.plan_schema_version)
        if version != ACQUISITION_PLAN_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported acquisition plan schema version {version!r}; "
                f"this package reads version {ACQUISITION_PLAN_SCHEMA_VERSION}"
            )
        require_nonempty_str("package_version", self.package_version)
        for label, value, expected in (
            ("venue", self.venue, COINBASE_VENUE),
            ("product", self.product, COINBASE_PRODUCT),
            ("endpoint", self.endpoint, COINBASE_CANDLES_ENDPOINT),
            ("documentation_url", self.documentation_url, COINBASE_DOCUMENTATION_URL),
            ("rate_limit_url", self.rate_limit_url, COINBASE_RATE_LIMIT_URL),
        ):
            require_str(label, value)
            if value != expected:
                raise ValueError(f"{label} must be {expected!r}, got {value!r}")
        if require_int("granularity_seconds", self.granularity_seconds) != (
            COINBASE_GRANULARITY_SECONDS
        ):
            raise ValueError(
                f"granularity_seconds must be {COINBASE_GRANULARITY_SECONDS}, got "
                f"{self.granularity_seconds}"
            )
        require_nonempty_str("timestamp_convention", self.timestamp_convention)
        require_nonempty_str("user_agent", self.user_agent)
        if require_int("max_candles_per_request", self.max_candles_per_request) != (
            MAX_CANDLES_PER_REQUEST
        ):
            raise ValueError(
                f"max_candles_per_request must be {MAX_CANDLES_PER_REQUEST}, got "
                f"{self.max_candles_per_request}"
            )
        window_days = require_positive_int("max_window_days", self.max_window_days)
        if window_days > MAX_WINDOW_DAYS:
            raise ValueError(
                f"max_window_days {window_days} exceeds the cautious cap {MAX_WINDOW_DAYS}"
            )
        require_day_aligned_utc("overall_start", self.overall_start)
        require_day_aligned_utc("overall_end", self.overall_end)
        if self.overall_start >= self.overall_end:
            raise ValueError(
                f"overall_start {self.overall_start} must precede overall_end {self.overall_end}"
            )
        if not isinstance(self.no_repair, bool) or self.no_repair is not True:
            raise ValueError("no_repair must be true: acquisition never fills or repairs candles")
        if not isinstance(self.windows, tuple) or not self.windows:
            raise ValueError("windows must be a non-empty tuple of AcquisitionWindow")
        for position, window in enumerate(self.windows):
            if not isinstance(window, AcquisitionWindow):
                raise ValueError(f"windows[{position}] must be an AcquisitionWindow")
            if window.window_end - window.window_start > _DAY * window_days:
                raise ValueError(
                    f"window {window.ordinal} spans more than the plan's max_window_days "
                    f"{window_days}"
                )
        self._check_ordinals_and_filenames()
        self._check_tiling()

    def _check_ordinals_and_filenames(self) -> None:
        ordinals = [window.ordinal for window in self.windows]
        if ordinals != list(range(len(self.windows))):
            raise ValueError(f"window ordinals must be contiguous 0..n-1, got {ordinals}")
        filenames = [window.filename for window in self.windows]
        if len(set(filenames)) != len(filenames):
            raise ValueError("window filenames must be unique")

    def _check_tiling(self) -> None:
        if self.windows[0].window_start != self.overall_start:
            raise ValueError(
                f"first window starts at {self.windows[0].window_start}, expected overall_start "
                f"{self.overall_start}"
            )
        for position, (earlier, later) in enumerate(pairwise(self.windows)):
            if later.window_start != earlier.window_end:
                raise ValueError(
                    "windows must tile the overall range without gaps, overlaps, or reordering: "
                    f"window {position} ends at {earlier.window_end} but window {position + 1} "
                    f"starts at {later.window_start}"
                )
        if self.windows[-1].window_end != self.overall_end:
            raise ValueError(
                f"last window ends at {self.windows[-1].window_end}, expected overall_end "
                f"{self.overall_end}"
            )

    @property
    def expected_request_count(self) -> int:
        return len(self.windows)

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "plan_schema_version": self.plan_schema_version,
            "package_version": self.package_version,
            "venue": self.venue,
            "product": self.product,
            "endpoint": self.endpoint,
            "granularity_seconds": self.granularity_seconds,
            "documentation_url": self.documentation_url,
            "rate_limit_url": self.rate_limit_url,
            "timestamp_convention": self.timestamp_convention,
            "user_agent": self.user_agent,
            "max_candles_per_request": self.max_candles_per_request,
            "max_window_days": self.max_window_days,
            "overall_start": self.overall_start.isoformat(),
            "overall_end": self.overall_end.isoformat(),
            "no_repair": self.no_repair,
            "windows": [window.to_json_dict() for window in self.windows],
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    def plan_sha256(self) -> str:
        """The SHA-256 of the deterministic plan bytes (its stable identity)."""
        return sha256_bytes(self.to_json_bytes())

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> AcquisitionRequestPlan:
        """Strict parse feeding the shared constructor validation."""
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"acquisition plan is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("acquisition plan JSON must be an object")
        keys = set(payload)
        if keys != _PLAN_KEYS:
            unknown = sorted(keys - _PLAN_KEYS)
            missing = sorted(_PLAN_KEYS - keys)
            raise ValueError(
                f"acquisition plan keys do not match schema: unknown={unknown}, missing={missing}"
            )
        windows = payload["windows"]
        if not isinstance(windows, list):
            raise ValueError("windows must be an array")
        return cls(
            plan_schema_version=payload["plan_schema_version"],
            package_version=payload["package_version"],
            venue=payload["venue"],
            product=payload["product"],
            endpoint=payload["endpoint"],
            granularity_seconds=payload["granularity_seconds"],
            documentation_url=payload["documentation_url"],
            rate_limit_url=payload["rate_limit_url"],
            timestamp_convention=payload["timestamp_convention"],
            user_agent=payload["user_agent"],
            max_candles_per_request=payload["max_candles_per_request"],
            max_window_days=payload["max_window_days"],
            overall_start=parse_timestamp_field("overall_start", payload["overall_start"]),
            overall_end=parse_timestamp_field("overall_end", payload["overall_end"]),
            no_repair=payload["no_repair"],
            windows=tuple(AcquisitionWindow.from_json_dict(entry) for entry in windows),
        )


def build_acquisition_plan(
    *,
    overall_start: pd.Timestamp,
    overall_end: pd.Timestamp,
    package_version: str = __version__,
    max_window_days: int = MAX_WINDOW_DAYS,
    filename_prefix: str = "coinbase-eth-usd-1d",
) -> AcquisitionRequestPlan:
    """Offline: tile ``[overall_start, overall_end)`` into request windows.

    No networking, no "now", no guessing: the caller supplies exact
    day-aligned UTC bounds and this produces the canonical, contiguous
    window list at most ``max_window_days`` daily buckets each.
    """
    require_day_aligned_utc("overall_start", overall_start)
    require_day_aligned_utc("overall_end", overall_end)
    if overall_start >= overall_end:
        raise AcquisitionPlanError(
            f"overall_start {overall_start} must precede overall_end {overall_end}"
        )
    if not 1 <= max_window_days <= MAX_WINDOW_DAYS:
        raise AcquisitionPlanError(
            f"max_window_days must be in 1..{MAX_WINDOW_DAYS}, got {max_window_days}"
        )
    windows: list[AcquisitionWindow] = []
    cursor = overall_start
    ordinal = 0
    step = _DAY * max_window_days
    while cursor < overall_end:
        window_end = min(cursor + step, overall_end)
        filename = (
            f"{filename_prefix}_{ordinal:04d}_"
            f"{cursor.strftime('%Y%m%d')}_{window_end.strftime('%Y%m%d')}.json"
        )
        windows.append(
            AcquisitionWindow(
                ordinal=ordinal,
                window_start=cursor,
                window_end=window_end,
                requested_start=canonical_utc_request(cursor),
                requested_end=canonical_utc_request(window_end - _DAY),
                filename=filename,
            )
        )
        cursor = window_end
        ordinal += 1
    return AcquisitionRequestPlan(
        plan_schema_version=ACQUISITION_PLAN_SCHEMA_VERSION,
        package_version=package_version,
        venue=COINBASE_VENUE,
        product=COINBASE_PRODUCT,
        endpoint=COINBASE_CANDLES_ENDPOINT,
        granularity_seconds=COINBASE_GRANULARITY_SECONDS,
        documentation_url=COINBASE_DOCUMENTATION_URL,
        rate_limit_url=COINBASE_RATE_LIMIT_URL,
        timestamp_convention=TIMESTAMP_CONVENTION,
        user_agent=ACQUISITION_USER_AGENT,
        max_candles_per_request=MAX_CANDLES_PER_REQUEST,
        max_window_days=max_window_days,
        overall_start=overall_start,
        overall_end=overall_end,
        no_repair=True,
        windows=tuple(windows),
    )


@dataclass(frozen=True)
class AcquisitionResponseReceipt:
    """Provenance for one captured response: status, size, hash, retrieval."""

    ordinal: int
    filename: str
    http_status: int
    byte_length: int
    sha256: str
    retrieved_at: pd.Timestamp
    content_type: str

    def __post_init__(self) -> None:
        require_nonnegative_int("ordinal", self.ordinal)
        _require_safe_json_filename("filename", self.filename)
        if require_int("http_status", self.http_status) != 200:
            raise ValueError(
                f"http_status must be 200 for a captured response, got {self.http_status}"
            )
        require_positive_int("byte_length", self.byte_length)
        require_hex64("sha256", self.sha256)
        require_utc_timestamp("retrieved_at", self.retrieved_at)
        require_nonempty_str("content_type", self.content_type)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "filename": self.filename,
            "http_status": self.http_status,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "retrieved_at": self.retrieved_at.isoformat(),
            "content_type": self.content_type,
        }

    @classmethod
    def from_json_dict(cls, payload: object) -> AcquisitionResponseReceipt:
        if not isinstance(payload, dict):
            raise ValueError(f"response receipt must be an object, got {type(payload).__name__}")
        keys = set(payload)
        if keys != _RESPONSE_RECEIPT_KEYS:
            unknown = sorted(keys - _RESPONSE_RECEIPT_KEYS)
            missing = sorted(_RESPONSE_RECEIPT_KEYS - keys)
            raise ValueError(
                f"response receipt keys do not match schema: unknown={unknown}, missing={missing}"
            )
        return cls(
            ordinal=payload["ordinal"],
            filename=payload["filename"],
            http_status=payload["http_status"],
            byte_length=payload["byte_length"],
            sha256=payload["sha256"],
            retrieved_at=parse_timestamp_field("retrieved_at", payload["retrieved_at"]),
            content_type=payload["content_type"],
        )


@dataclass(frozen=True)
class AcquisitionAttemptReceipt:
    """Provenance for one acquisition attempt binding a plan to its responses."""

    receipt_schema_version: int
    package_version: str
    plan_sha256: str
    attempt_id: str
    workflow_run_id: str
    source_commit: str
    curl_version: str
    runner: str
    user_agent: str
    responses: tuple[AcquisitionResponseReceipt, ...]

    def __post_init__(self) -> None:
        version = require_int("receipt_schema_version", self.receipt_schema_version)
        if version != ACQUISITION_RECEIPT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported acquisition receipt schema version {version!r}; "
                f"this package reads version {ACQUISITION_RECEIPT_SCHEMA_VERSION}"
            )
        require_nonempty_str("package_version", self.package_version)
        require_hex64("plan_sha256", self.plan_sha256)
        require_nonempty_str("attempt_id", self.attempt_id)
        require_nonempty_str("workflow_run_id", self.workflow_run_id)
        require_commit_sha("source_commit", self.source_commit)
        require_nonempty_str("curl_version", self.curl_version)
        require_nonempty_str("runner", self.runner)
        require_nonempty_str("user_agent", self.user_agent)
        if not isinstance(self.responses, tuple) or not self.responses:
            raise ValueError("responses must be a non-empty tuple of AcquisitionResponseReceipt")
        for position, response in enumerate(self.responses):
            if not isinstance(response, AcquisitionResponseReceipt):
                raise ValueError(f"responses[{position}] must be an AcquisitionResponseReceipt")
        ordinals = [response.ordinal for response in self.responses]
        if ordinals != list(range(len(self.responses))):
            raise ValueError(f"response ordinals must be contiguous 0..n-1, got {ordinals}")
        filenames = [response.filename for response in self.responses]
        if len(set(filenames)) != len(filenames):
            raise ValueError("response filenames must be unique")

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "receipt_schema_version": self.receipt_schema_version,
            "package_version": self.package_version,
            "plan_sha256": self.plan_sha256,
            "attempt_id": self.attempt_id,
            "workflow_run_id": self.workflow_run_id,
            "source_commit": self.source_commit,
            "curl_version": self.curl_version,
            "runner": self.runner,
            "user_agent": self.user_agent,
            "responses": [response.to_json_dict() for response in self.responses],
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> AcquisitionAttemptReceipt:
        """Strict parse feeding the shared constructor validation."""
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"acquisition receipt is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("acquisition receipt JSON must be an object")
        keys = set(payload)
        if keys != _ATTEMPT_RECEIPT_KEYS:
            unknown = sorted(keys - _ATTEMPT_RECEIPT_KEYS)
            missing = sorted(_ATTEMPT_RECEIPT_KEYS - keys)
            raise ValueError(
                f"acquisition receipt keys do not match schema: unknown={unknown}, missing={missing}"
            )
        responses = payload["responses"]
        if not isinstance(responses, list):
            raise ValueError("responses must be an array")
        return cls(
            receipt_schema_version=payload["receipt_schema_version"],
            package_version=payload["package_version"],
            plan_sha256=payload["plan_sha256"],
            attempt_id=payload["attempt_id"],
            workflow_run_id=payload["workflow_run_id"],
            source_commit=payload["source_commit"],
            curl_version=payload["curl_version"],
            runner=payload["runner"],
            user_agent=payload["user_agent"],
            responses=tuple(
                AcquisitionResponseReceipt.from_json_dict(entry) for entry in responses
            ),
        )
