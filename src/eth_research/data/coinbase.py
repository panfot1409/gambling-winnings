"""Strict offline adapter for saved Coinbase Exchange candle responses.

This module contains **no networking**. It parses response bodies that
were downloaded separately (one-time, unauthenticated ``curl`` requests
outside the package — see ``docs/M2B_ACQUISITION.md``) and turns them into
one deterministic daily OHLCV CSV suitable for the Milestone 2A canonical
dataset builder, together with a strict, byte-reproducible acquisition
evidence record.

Coinbase Exchange ``GET /products/<product>/candles`` facts honoured here
(documented at the URL in :data:`COINBASE_DOCUMENTATION_URL`):

* each response row is an array ``[time, low, high, open, close, volume]``
  with ``time`` = bucket start in epoch seconds;
* at most 300 candles per response — acquisition uses fixed,
  non-overlapping half-open windows of at most 299 daily buckets;
* responses are usually newest-first; a strictly descending response is
  reversed to chronological order as an explicit, documented
  source-format transformation (anything not strictly monotonic is
  rejected);
* responses may include candles *preceding* the requested start — such
  rows are excluded and counted, never silently dropped; rows at or after
  the declared window end are rejected outright;
* no candle is published for a bucket with no trades — every missing
  daily candle is therefore a hard error here; nothing is ever
  synthesized, forward-filled, interpolated, clipped, or repaired.

The raw response files are never modified: each is read once into an
immutable byte snapshot that is both hashed and parsed, and every file is
re-hashed immediately before anything is written — a source mutated
mid-derivation aborts with nothing published.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, NamedTuple

import pandas as pd

from eth_research import __version__
from eth_research._atomic import publish_atomically, write_atomic
from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.provenance import (
    require_bool,
    require_hex64,
    require_int,
    require_nonempty_str,
    require_safe_basename,
    require_str,
    sha256_bytes,
    sha256_file,
)
from eth_research.data.validation import (
    epoch_nanoseconds,
    parse_timestamp_field,
    require_day_aligned_utc,
    require_nonnegative_int,
    require_positive_int,
    require_utc_timestamp,
)

ACQUISITION_SCHEMA_VERSION: int = 1
COINBASE_VENUE: str = "coinbase-exchange"
COINBASE_PRODUCT: str = "ETH-USD"
COINBASE_GRANULARITY_SECONDS: int = 86_400
COINBASE_DOCUMENTATION_URL: str = (
    "https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles"
)
COINBASE_CANDLES_ENDPOINT: str = "https://api.exchange.coinbase.com/products/ETH-USD/candles"
ADAPTER_ALGORITHM: str = "coinbase-candles-v1"
ADAPTER_TRANSFORMATIONS: tuple[str, ...] = (
    "map Coinbase candle arrays [time, low, high, open, close, volume] to"
    " columns timestamp, open, high, low, close, volume",
    "reverse a strictly descending response to chronological order",
    "exclude response rows before the request's declared window start (counted per chunk)",
    "serialize to CSV with ISO-8601 UTC open times and round-trip float formatting",
)
MAX_WINDOW_DAYS: int = 299
"""Coinbase serves at most 300 candles per response; windows stay strictly below that."""

_DAY = pd.Timedelta(days=1)
_DAY_SECONDS: int = 86_400
_CANDLE_FIELDS: int = 6
# Scheme prefixes only (no slashes): pathlib collapses "//" so "https://x"
# arrives as "https:/x" when a URL is smuggled in as a Path.
_URL_SCHEMES: tuple[str, ...] = ("http:", "https:", "ftp:", "s3:", "gs:")
_CSV_HEADER: str = "timestamp,open,high,low,close,volume"

_CHUNK_KEYS: frozenset[str] = frozenset(
    {
        "filename",
        "sha256",
        "window_start",
        "window_end",
        "requested_start",
        "requested_end",
        "retrieved_at",
        "row_count",
        "rows_before_window",
    }
)

_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {
        "acquisition_schema_version",
        "package_version",
        "venue",
        "product",
        "granularity_seconds",
        "documentation_url",
        "endpoint",
        "adapter_algorithm",
        "transformations",
        "no_repair",
        "overall_start",
        "overall_end",
        "chunks",
        "total_rows_before_window",
        "derived_filename",
        "derived_sha256",
        "derived_row_count",
        "first_open_time",
        "last_open_time",
    }
)


class AcquisitionError(RuntimeError):
    """A saved response, request declaration, or evidence record is unacceptable."""


class DailyCandle(NamedTuple):
    """One parsed daily candle, already mapped to OHLCV field order."""

    open_time_s: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class ParsedChunk:
    """Candles contributed by one response, chronological and window-filtered."""

    candles: tuple[DailyCandle, ...]
    rows_before_window: int
    """Response rows excluded because they precede the declared window start."""
    row_count: int
    """Total rows in the raw response body, before any filtering."""


_REQUEST_TIME_FORMAT: str = "%Y-%m-%dT%H:%M:%SZ"


def canonical_utc_request(ts: pd.Timestamp) -> str:
    """The canonical Coinbase request string for a UTC timestamp.

    The Coinbase ``start``/``end`` query parameters are inclusive bucket
    opens formatted as ``YYYY-MM-DDTHH:MM:SSZ``.
    """
    return require_utc_timestamp("request timestamp", ts).strftime(_REQUEST_TIME_FORMAT)


def _require_request_param(label: str, text: object, expected: pd.Timestamp) -> str:
    """The request string must be exactly the canonical UTC form of ``expected``."""
    value = require_nonempty_str(label, text)
    canonical = canonical_utc_request(expected)
    if value != canonical:
        raise ValueError(
            f"{label} must be the canonical UTC request string {canonical!r} for the "
            f"declared window, got {value!r}"
        )
    return value


def _bind_request_metadata(
    *,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    requested_start: object,
    requested_end: object,
    retrieved_at: object,
) -> None:
    """Coinbase request params are inclusive opens: start == window_start,
    end == window_end - 1 day (the last bucket in the half-open window)."""
    _require_request_param("requested_start", requested_start, window_start)
    _require_request_param("requested_end", requested_end, window_end - _DAY)
    require_utc_timestamp("retrieved_at", retrieved_at)


def _check_window(window_start: pd.Timestamp, window_end: pd.Timestamp) -> None:
    require_day_aligned_utc("window_start", window_start)
    require_day_aligned_utc("window_end", window_end)
    if window_start >= window_end:
        raise ValueError(f"window_start {window_start} must precede window_end {window_end}")
    if window_end - window_start > _DAY * MAX_WINDOW_DAYS:
        raise ValueError(
            f"window {window_start} .. {window_end} spans more than {MAX_WINDOW_DAYS} daily "
            f"buckets; Coinbase serves at most {MAX_WINDOW_DAYS + 1} candles per response"
        )


@dataclass(frozen=True)
class ChunkRequest:
    """One saved response file plus the exact request that produced it."""

    path: Path
    window_start: pd.Timestamp
    """Inclusive UTC day boundary; candles before it are excluded and counted."""
    window_end: pd.Timestamp
    """Exclusive UTC day boundary; candles at or after it are rejected."""
    requested_start: str
    """The exact ``start`` parameter sent to the endpoint."""
    requested_end: str
    """The exact ``end`` parameter sent to the endpoint."""
    retrieved_at: pd.Timestamp

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise ValueError(f"path must be a pathlib.Path, got {type(self.path).__name__}")
        if str(self.path).lower().startswith(_URL_SCHEMES):
            raise ValueError(
                f"network sources are not supported ({self.path}); "
                "this adapter reads already-downloaded local files only"
            )
        _check_window(self.window_start, self.window_end)
        _bind_request_metadata(
            window_start=self.window_start,
            window_end=self.window_end,
            requested_start=self.requested_start,
            requested_end=self.requested_end,
            retrieved_at=self.retrieved_at,
        )


@dataclass(frozen=True)
class AcquisitionChunk:
    """Evidence for one response: request window, raw hash, and exact counts."""

    filename: str
    sha256: str
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    requested_start: str
    requested_end: str
    retrieved_at: pd.Timestamp
    row_count: int
    rows_before_window: int

    def __post_init__(self) -> None:
        require_safe_basename("filename", self.filename)
        require_hex64("sha256", self.sha256)
        _check_window(self.window_start, self.window_end)
        _bind_request_metadata(
            window_start=self.window_start,
            window_end=self.window_end,
            requested_start=self.requested_start,
            requested_end=self.requested_end,
            retrieved_at=self.retrieved_at,
        )
        row_count = require_positive_int("row_count", self.row_count)
        before = require_nonnegative_int("rows_before_window", self.rows_before_window)
        contributed = row_count - before
        if contributed < 1:
            raise ValueError(
                f"chunk {self.filename!r} contributes no candles inside its window "
                f"(row_count {row_count}, rows_before_window {before})"
            )
        window_days = (self.window_end - self.window_start) // _DAY
        if contributed > window_days:
            raise ValueError(
                f"chunk {self.filename!r} claims {contributed} candles inside a "
                f"{window_days}-day window"
            )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "sha256": self.sha256,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "retrieved_at": self.retrieved_at.isoformat(),
            "row_count": self.row_count,
            "rows_before_window": self.rows_before_window,
        }

    @classmethod
    def from_json_dict(cls, payload: object) -> AcquisitionChunk:
        if not isinstance(payload, dict):
            raise ValueError(f"chunk entry must be an object, got {type(payload).__name__}")
        keys = set(payload)
        if keys != _CHUNK_KEYS:
            unknown = sorted(keys - _CHUNK_KEYS)
            missing = sorted(_CHUNK_KEYS - keys)
            raise ValueError(
                f"chunk keys do not match schema: unknown={unknown}, missing={missing}"
            )
        return cls(
            filename=payload["filename"],
            sha256=payload["sha256"],
            window_start=parse_timestamp_field("window_start", payload["window_start"]),
            window_end=parse_timestamp_field("window_end", payload["window_end"]),
            requested_start=payload["requested_start"],
            requested_end=payload["requested_end"],
            retrieved_at=parse_timestamp_field("retrieved_at", payload["retrieved_at"]),
            row_count=payload["row_count"],
            rows_before_window=payload["rows_before_window"],
        )


@dataclass(frozen=True)
class AcquisitionEvidence:
    """Deterministic record binding raw responses to the derived OHLCV file.

    Every field is validated in ``__post_init__`` — the single shared
    validation path for constructed and parsed evidence alike.
    """

    acquisition_schema_version: int
    package_version: str
    venue: str
    product: str
    granularity_seconds: int
    documentation_url: str
    endpoint: str
    adapter_algorithm: str
    transformations: tuple[str, ...]
    no_repair: bool
    overall_start: pd.Timestamp
    overall_end: pd.Timestamp
    chunks: tuple[AcquisitionChunk, ...]
    total_rows_before_window: int
    derived_filename: str
    derived_sha256: str
    derived_row_count: int
    first_open_time: pd.Timestamp
    last_open_time: pd.Timestamp

    def __post_init__(self) -> None:
        version = require_int("acquisition_schema_version", self.acquisition_schema_version)
        if version != ACQUISITION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported acquisition schema version {version!r}; "
                f"this package reads version {ACQUISITION_SCHEMA_VERSION}"
            )
        require_nonempty_str("package_version", self.package_version)
        for label, value, expected in (
            ("venue", self.venue, COINBASE_VENUE),
            ("product", self.product, COINBASE_PRODUCT),
            ("documentation_url", self.documentation_url, COINBASE_DOCUMENTATION_URL),
            ("endpoint", self.endpoint, COINBASE_CANDLES_ENDPOINT),
            ("adapter_algorithm", self.adapter_algorithm, ADAPTER_ALGORITHM),
        ):
            require_str(label, value)
            if value != expected:
                raise ValueError(f"{label} must be {expected!r}, got {value!r}")
        granularity = require_int("granularity_seconds", self.granularity_seconds)
        if granularity != COINBASE_GRANULARITY_SECONDS:
            raise ValueError(
                f"granularity_seconds must be {COINBASE_GRANULARITY_SECONDS}, got {granularity}"
            )
        if (
            not isinstance(self.transformations, tuple)
            or self.transformations != ADAPTER_TRANSFORMATIONS
        ):
            raise ValueError(
                "transformations must record exactly the documented "
                f"{ADAPTER_ALGORITHM!r} transformation list"
            )
        if require_bool("no_repair", self.no_repair) is not True:
            raise ValueError(
                "no_repair must be true: this adapter never fills, interpolates, "
                "clips, or repairs candles"
            )
        require_day_aligned_utc("overall_start", self.overall_start)
        require_day_aligned_utc("overall_end", self.overall_end)
        if self.overall_start >= self.overall_end:
            raise ValueError(
                f"overall_start {self.overall_start} must precede overall_end {self.overall_end}"
            )
        if not isinstance(self.chunks, tuple) or not self.chunks:
            raise ValueError("chunks must be a non-empty tuple of AcquisitionChunk")
        for position, chunk in enumerate(self.chunks):
            if not isinstance(chunk, AcquisitionChunk):
                raise ValueError(f"chunks[{position}] must be an AcquisitionChunk")
        _check_tiling(
            [(chunk.window_start, chunk.window_end) for chunk in self.chunks],
            overall_start=self.overall_start,
            overall_end=self.overall_end,
        )
        filenames = [chunk.filename for chunk in self.chunks]
        if len(set(filenames)) != len(filenames):
            raise ValueError("chunk filenames must be unique")
        require_safe_basename("derived_filename", self.derived_filename)
        if self.derived_filename in filenames:
            raise ValueError("derived_filename must differ from every chunk filename")
        require_hex64("derived_sha256", self.derived_sha256)
        derived_rows = require_positive_int("derived_row_count", self.derived_row_count)
        expected_rows = (self.overall_end - self.overall_start) // _DAY
        if derived_rows != expected_rows:
            raise ValueError(
                f"derived_row_count {derived_rows} does not equal the {expected_rows} daily "
                "buckets in [overall_start, overall_end) — a gap-free daily series is required"
            )
        total_before = require_nonnegative_int(
            "total_rows_before_window", self.total_rows_before_window
        )
        if total_before != sum(chunk.rows_before_window for chunk in self.chunks):
            raise ValueError(
                "total_rows_before_window does not equal the sum over chunks "
                f"({total_before} declared)"
            )
        contributed = sum(chunk.row_count - chunk.rows_before_window for chunk in self.chunks)
        if contributed != derived_rows:
            raise ValueError(
                f"chunks contribute {contributed} candles but derived_row_count is {derived_rows}"
            )
        require_day_aligned_utc("first_open_time", self.first_open_time)
        require_day_aligned_utc("last_open_time", self.last_open_time)
        if self.first_open_time != self.overall_start:
            raise ValueError(
                f"first_open_time {self.first_open_time} must equal overall_start "
                f"{self.overall_start}; choose overall_start at the first available candle"
            )
        if self.last_open_time != self.overall_end - _DAY:
            raise ValueError(
                f"last_open_time {self.last_open_time} must equal overall_end - 1 day "
                f"({self.overall_end - _DAY}); the final day must be a completed candle"
            )

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "acquisition_schema_version": self.acquisition_schema_version,
            "package_version": self.package_version,
            "venue": self.venue,
            "product": self.product,
            "granularity_seconds": self.granularity_seconds,
            "documentation_url": self.documentation_url,
            "endpoint": self.endpoint,
            "adapter_algorithm": self.adapter_algorithm,
            "transformations": list(self.transformations),
            "no_repair": self.no_repair,
            "overall_start": self.overall_start.isoformat(),
            "overall_end": self.overall_end.isoformat(),
            "chunks": [chunk.to_json_dict() for chunk in self.chunks],
            "total_rows_before_window": self.total_rows_before_window,
            "derived_filename": self.derived_filename,
            "derived_sha256": self.derived_sha256,
            "derived_row_count": self.derived_row_count,
            "first_open_time": self.first_open_time.isoformat(),
            "last_open_time": self.last_open_time.isoformat(),
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> AcquisitionEvidence:
        """Strict parse feeding the shared constructor validation."""
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"acquisition evidence is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("acquisition evidence JSON must be an object")
        keys = set(payload)
        if keys != _EVIDENCE_KEYS:
            unknown = sorted(keys - _EVIDENCE_KEYS)
            missing = sorted(_EVIDENCE_KEYS - keys)
            raise ValueError(
                f"acquisition evidence keys do not match schema: "
                f"unknown={unknown}, missing={missing}"
            )
        transformations = payload["transformations"]
        if not isinstance(transformations, list) or not all(
            isinstance(item, str) for item in transformations
        ):
            raise ValueError("transformations must be an array of strings")
        chunk_entries = payload["chunks"]
        if not isinstance(chunk_entries, list):
            raise ValueError("chunks must be an array")
        return cls(
            acquisition_schema_version=payload["acquisition_schema_version"],
            package_version=payload["package_version"],
            venue=payload["venue"],
            product=payload["product"],
            granularity_seconds=payload["granularity_seconds"],
            documentation_url=payload["documentation_url"],
            endpoint=payload["endpoint"],
            adapter_algorithm=payload["adapter_algorithm"],
            transformations=tuple(transformations),
            no_repair=payload["no_repair"],
            overall_start=parse_timestamp_field("overall_start", payload["overall_start"]),
            overall_end=parse_timestamp_field("overall_end", payload["overall_end"]),
            chunks=tuple(AcquisitionChunk.from_json_dict(entry) for entry in chunk_entries),
            total_rows_before_window=payload["total_rows_before_window"],
            derived_filename=payload["derived_filename"],
            derived_sha256=payload["derived_sha256"],
            derived_row_count=payload["derived_row_count"],
            first_open_time=parse_timestamp_field("first_open_time", payload["first_open_time"]),
            last_open_time=parse_timestamp_field("last_open_time", payload["last_open_time"]),
        )


def _check_tiling(
    windows: list[tuple[pd.Timestamp, pd.Timestamp]],
    *,
    overall_start: pd.Timestamp,
    overall_end: pd.Timestamp,
) -> None:
    """Windows must tile [overall_start, overall_end) exactly, in declared order."""
    if windows[0][0] != overall_start:
        raise ValueError(
            f"first window starts at {windows[0][0]}, expected overall_start {overall_start}"
        )
    for position, ((_, previous_end), (next_start, _)) in enumerate(pairwise(windows)):
        if next_start != previous_end:
            raise ValueError(
                f"windows must tile the overall range without gaps, overlaps, or reordering: "
                f"window {position} ends at {previous_end} but window {position + 1} starts "
                f"at {next_start}"
            )
    if windows[-1][1] != overall_end:
        raise ValueError(
            f"last window ends at {windows[-1][1]}, expected overall_end {overall_end}"
        )


def _require_json_int(label: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be a JSON integer (bool is rejected), got {value!r}")
    return value


def _require_json_number(label: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a JSON number (bool is rejected), got {value!r}")
    number = float(value)
    # json.loads("1e999") overflows to infinity without hitting the
    # NaN/Infinity literal hook, so finiteness must be checked here.
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite, got {number!r}")
    return number


def parse_candles_chunk(
    raw: bytes,
    *,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> ParsedChunk:
    """Strictly parse one saved candles response against its declared window.

    Returns the chronological candles inside ``[window_start, window_end)``
    plus the exact count of excluded pre-window rows. Everything else —
    malformed JSON, error objects, wrong row width, non-number values,
    booleans, non-finite numbers, unaligned or duplicate timestamps,
    shuffled ordering, rows at/after the window end — is rejected with
    :class:`AcquisitionError`.
    """
    _check_window(window_start, window_end)
    try:
        payload: Any = strict_json_loads(raw)
    except StrictJSONError as exc:
        raise AcquisitionError(f"chunk is not valid JSON: {exc}") from exc

    if isinstance(payload, dict):
        message = payload.get("message")
        detail = f" (API error object with message {message!r})" if message is not None else ""
        raise AcquisitionError(f"chunk JSON must be a top-level array, got an object{detail}")
    if not isinstance(payload, list):
        raise AcquisitionError(
            f"chunk JSON must be a top-level array, got {type(payload).__name__}"
        )
    if not payload:
        raise AcquisitionError(
            "chunk contains no candles; an empty response always implies missing daily "
            "candles under the tiling rule"
        )

    candles: list[DailyCandle] = []
    for position, row in enumerate(payload):
        label = f"row {position}"
        if not isinstance(row, list):
            raise AcquisitionError(f"{label} must be an array, got {type(row).__name__}")
        if len(row) != _CANDLE_FIELDS:
            raise AcquisitionError(
                f"{label} has {len(row)} fields, expected exactly {_CANDLE_FIELDS} "
                "([time, low, high, open, close, volume])"
            )
        try:
            time_s = _require_json_int(f"{label} time", row[0])
            low = _require_json_number(f"{label} low", row[1])
            high = _require_json_number(f"{label} high", row[2])
            open_ = _require_json_number(f"{label} open", row[3])
            close = _require_json_number(f"{label} close", row[4])
            volume = _require_json_number(f"{label} volume", row[5])
        except ValueError as exc:
            raise AcquisitionError(str(exc)) from exc
        if time_s % _DAY_SECONDS != 0:
            raise AcquisitionError(
                f"{label} time {time_s} is not aligned to a 86400-second UTC day boundary"
            )
        for field_label, price in (("low", low), ("high", high), ("open", open_), ("close", close)):
            if price <= 0.0:
                raise AcquisitionError(f"{label} {field_label} must be positive, got {price!r}")
        if volume < 0.0:
            raise AcquisitionError(f"{label} volume must be non-negative, got {volume!r}")
        if high < low:
            raise AcquisitionError(
                f"{label} has high {high!r} < low {low!r}; the response does not match the "
                "documented [time, low, high, open, close, volume] field order"
            )
        candles.append(
            DailyCandle(
                open_time_s=time_s, open=open_, high=high, low=low, close=close, volume=volume
            )
        )

    times = [candle.open_time_s for candle in candles]
    if len(times) > 1:
        ascending = all(later > earlier for earlier, later in pairwise(times))
        descending = all(later < earlier for earlier, later in pairwise(times))
        if descending:
            # Documented source-format transformation: Coinbase responds newest-first.
            candles.reverse()
        elif not ascending:
            raise AcquisitionError(
                "rows are neither strictly ascending nor strictly descending by time; "
                "shuffled or duplicated candles are rejected, never reordered"
            )

    start_s = epoch_nanoseconds(window_start) // 10**9
    end_s = epoch_nanoseconds(window_end) // 10**9
    after_end = [candle.open_time_s for candle in candles if candle.open_time_s >= end_s]
    if after_end:
        raise AcquisitionError(
            f"{len(after_end)} row(s) at or after the declared window end "
            f"(first offending epoch {after_end[0]}); the request window and response disagree"
        )
    rows_before = sum(1 for candle in candles if candle.open_time_s < start_s)
    contributed = tuple(candle for candle in candles if candle.open_time_s >= start_s)
    if not contributed:
        raise AcquisitionError(
            "no candles inside the declared window; the response covers only pre-window time"
        )
    return ParsedChunk(candles=contributed, rows_before_window=rows_before, row_count=len(payload))


def _check_daily_continuity(candles: list[DailyCandle], *, start_s: int, end_s: int) -> None:
    """The combined series must cover every daily bucket of [start, end) exactly."""
    expected = range(start_s, end_s, _DAY_SECONDS)
    actual = [candle.open_time_s for candle in candles]
    if actual == list(expected):
        return
    actual_set = set(actual)
    missing = [time_s for time_s in expected if time_s not in actual_set]
    if missing:
        examples = ", ".join(
            pd.Timestamp(time_s, unit="s", tz="UTC").isoformat() for time_s in missing[:3]
        )
        raise AcquisitionError(
            f"{len(missing)} missing daily candle(s) in [{_iso(start_s)}, {_iso(end_s)}): "
            f"first {examples}. Missing candles are never synthesized or filled — choose an "
            "overall window with continuous history or stop"
        )
    raise AcquisitionError(
        "combined candles do not form the expected strictly ascending daily series"
    )


def _iso(time_s: int) -> str:
    return str(pd.Timestamp(time_s, unit="s", tz="UTC").isoformat())


def _derived_csv_bytes(candles: list[DailyCandle]) -> bytes:
    """Deterministic CSV: ISO-8601 UTC open times, shortest round-trip floats."""
    lines = [_CSV_HEADER]
    lines.extend(
        f"{_iso(candle.open_time_s)},{candle.open!r},{candle.high!r},"
        f"{candle.low!r},{candle.close!r},{candle.volume!r}"
        for candle in candles
    )
    return ("\n".join(lines) + "\n").encode("ascii")


def _compute_derivation(
    requests: list[ChunkRequest],
    *,
    overall_start: pd.Timestamp,
    overall_end: pd.Timestamp,
    derived_filename: str,
) -> tuple[bytes, AcquisitionEvidence]:
    """Pure computation: read/parse/combine raw chunks into (CSV bytes, evidence).

    Reads and re-hashes the raw files but writes **nothing**. A raw file
    that changes between its snapshot hash and the final re-hash aborts.
    """
    require_day_aligned_utc("overall_start", overall_start)
    require_day_aligned_utc("overall_end", overall_end)
    if overall_start >= overall_end:
        raise AcquisitionError(
            f"overall_start {overall_start} must precede overall_end {overall_end}"
        )
    if not requests:
        raise AcquisitionError("at least one chunk request is required")
    for position, request in enumerate(requests):
        if not isinstance(request, ChunkRequest):
            raise AcquisitionError(f"requests[{position}] must be a ChunkRequest")
    try:
        _check_tiling(
            [(request.window_start, request.window_end) for request in requests],
            overall_start=overall_start,
            overall_end=overall_end,
        )
    except ValueError as exc:
        raise AcquisitionError(str(exc)) from exc

    snapshots: list[tuple[ChunkRequest, bytes, str]] = []
    for request in requests:
        # One immutable snapshot per file: the bytes hashed ARE the bytes parsed.
        raw = request.path.read_bytes()
        snapshots.append((request, raw, sha256_bytes(raw)))

    chunks: list[AcquisitionChunk] = []
    combined: list[DailyCandle] = []
    for request, raw, digest in snapshots:
        try:
            parsed = parse_candles_chunk(
                raw, window_start=request.window_start, window_end=request.window_end
            )
        except AcquisitionError as exc:
            raise AcquisitionError(f"chunk {request.path.name!r}: {exc}") from exc
        combined.extend(parsed.candles)
        chunks.append(
            AcquisitionChunk(
                filename=request.path.name,
                sha256=digest,
                window_start=request.window_start,
                window_end=request.window_end,
                requested_start=request.requested_start,
                requested_end=request.requested_end,
                retrieved_at=request.retrieved_at,
                row_count=parsed.row_count,
                rows_before_window=parsed.rows_before_window,
            )
        )

    start_s = epoch_nanoseconds(overall_start) // 10**9
    end_s = epoch_nanoseconds(overall_end) // 10**9
    _check_daily_continuity(combined, start_s=start_s, end_s=end_s)

    csv_bytes = _derived_csv_bytes(combined)
    evidence = AcquisitionEvidence(
        acquisition_schema_version=ACQUISITION_SCHEMA_VERSION,
        package_version=__version__,
        venue=COINBASE_VENUE,
        product=COINBASE_PRODUCT,
        granularity_seconds=COINBASE_GRANULARITY_SECONDS,
        documentation_url=COINBASE_DOCUMENTATION_URL,
        endpoint=COINBASE_CANDLES_ENDPOINT,
        adapter_algorithm=ADAPTER_ALGORITHM,
        transformations=ADAPTER_TRANSFORMATIONS,
        no_repair=True,
        overall_start=overall_start,
        overall_end=overall_end,
        chunks=tuple(chunks),
        total_rows_before_window=sum(chunk.rows_before_window for chunk in chunks),
        derived_filename=derived_filename,
        derived_sha256=sha256_bytes(csv_bytes),
        derived_row_count=len(combined),
        first_open_time=pd.Timestamp(combined[0].open_time_s, unit="s", tz="UTC"),
        last_open_time=pd.Timestamp(combined[-1].open_time_s, unit="s", tz="UTC"),
    )

    # Belt and braces: refuse if any raw file changed between snapshot and now.
    for request, _, digest in snapshots:
        if sha256_file(request.path) != digest:
            raise AcquisitionError(
                f"raw response {request.path.name!r} changed during derivation; "
                "nothing was written — re-run against settled files"
            )
    return csv_bytes, evidence


def derive_daily_ohlcv(
    requests: list[ChunkRequest],
    *,
    overall_start: pd.Timestamp,
    overall_end: pd.Timestamp,
    output_csv: str | Path,
    overwrite: bool = False,
) -> AcquisitionEvidence:
    """Combine saved responses into one gap-free daily OHLCV CSV plus evidence.

    Lower-level helper: writes only the CSV and returns the evidence object
    (the caller persists it separately). For a crash-safe single operation
    that publishes the CSV and its evidence together, use
    :func:`publish_acquisition`.

    The request windows must exactly tile ``[overall_start, overall_end)``
    half-open, in declared order, each at most :data:`MAX_WINDOW_DAYS`
    daily buckets. The combined series must start exactly at
    ``overall_start``, end exactly at ``overall_end - 1 day``, and contain
    every day in between — any missing candle aborts with nothing written.
    The CSV is written atomically; existing output is never overwritten
    without ``overwrite=True``. Raw response files are never modified, and
    a file that changes between hashing and publication aborts the run.
    """
    output_path = Path(output_csv)
    if str(output_path).lower().startswith(_URL_SCHEMES):
        raise AcquisitionError(f"output must be a local file, got {output_path}")
    if output_path.suffix.lower() != ".csv":
        raise AcquisitionError(f"output must be a .csv file, got {output_path.name!r}")
    if output_path.exists() and not overwrite:
        raise AcquisitionError(
            f"refusing to overwrite existing {output_path}; pass overwrite=True explicitly"
        )

    csv_bytes, evidence = _compute_derivation(
        requests,
        overall_start=overall_start,
        overall_end=overall_end,
        derived_filename=output_path.name,
    )

    # Assemble and validate the evidence record *before* touching the
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(output_path, csv_bytes)
    return evidence


def acquisition_is_complete(derived_csv: str | Path, evidence_path: str | Path) -> bool:
    """True only when both artifacts exist and the evidence describes the CSV.

    Distinguishes a completed acquisition from an incomplete orphan (a CSV
    without its evidence, or an evidence file without its CSV, or a pair
    that do not describe each other).
    """
    csv_path = Path(derived_csv)
    ev_path = Path(evidence_path)
    if not (csv_path.exists() and ev_path.exists()):
        return False
    try:
        evidence = load_acquisition_evidence(ev_path)
    except AcquisitionError:
        return False
    return evidence.derived_filename == csv_path.name and evidence.derived_sha256 == sha256_file(
        csv_path
    )


def publish_acquisition(
    requests: list[ChunkRequest],
    *,
    overall_start: pd.Timestamp,
    overall_end: pd.Timestamp,
    derived_csv: str | Path,
    evidence_path: str | Path,
    overwrite: bool = False,
) -> AcquisitionEvidence:
    """Transactionally publish the derived CSV and its evidence together.

    Both artifact byte blobs are precomputed and validated first; then they
    are published atomically with the evidence JSON written **last** as the
    completeness marker. If either write fails, the batch is rolled back —
    a fresh publication leaves nothing behind and an overwrite leaves the
    previous bytes intact — so a reader never sees a CSV without its
    evidence. Pre-existing state at either target is refused unless
    ``overwrite=True``, and no temporary files remain either way.

    This is the operation the documented real acquisition procedure uses;
    :func:`derive_daily_ohlcv` remains available as a lower-level helper.
    """
    csv_path = Path(derived_csv)
    ev_path = Path(evidence_path)
    if str(csv_path).lower().startswith(_URL_SCHEMES) or str(ev_path).lower().startswith(
        _URL_SCHEMES
    ):
        raise AcquisitionError("outputs must be local files")
    if csv_path.suffix.lower() != ".csv":
        raise AcquisitionError(f"derived output must be a .csv file, got {csv_path.name!r}")
    if ev_path.suffix.lower() != ".json":
        raise AcquisitionError(f"evidence output must be a .json file, got {ev_path.name!r}")

    existing = [path for path in (csv_path, ev_path) if path.exists()]
    if existing and not overwrite:
        state = (
            "a completed acquisition"
            if acquisition_is_complete(csv_path, ev_path)
            else "an incomplete orphan"
        )
        names = ", ".join(path.name for path in existing)
        raise AcquisitionError(
            f"refusing to overwrite existing artifact(s) ({names}) — {state}. "
            "Pass overwrite=True to replace them explicitly."
        )

    csv_bytes, evidence = _compute_derivation(
        requests,
        overall_start=overall_start,
        overall_end=overall_end,
        derived_filename=csv_path.name,
    )
    evidence_bytes = evidence.to_json_bytes()

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    ev_path.parent.mkdir(parents=True, exist_ok=True)
    publish_atomically(
        [
            (csv_path, csv_bytes),
            (ev_path, evidence_bytes),  # evidence last: the completeness marker
        ],
        error=AcquisitionError,
    )
    return evidence


def write_acquisition_evidence(
    evidence: AcquisitionEvidence, path: str | Path, *, overwrite: bool = False
) -> None:
    """Atomically write the evidence JSON; never overwrites without opt-in."""
    target = Path(path)
    if target.suffix.lower() != ".json":
        raise AcquisitionError(f"evidence must be a .json file, got {target.name!r}")
    if target.exists() and not overwrite:
        raise AcquisitionError(
            f"refusing to overwrite existing {target}; pass overwrite=True explicitly"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(target, evidence.to_json_bytes())


def load_acquisition_evidence(path: str | Path) -> AcquisitionEvidence:
    """Strictly parse an evidence file."""
    try:
        return AcquisitionEvidence.from_json_bytes(Path(path).read_bytes())
    except ValueError as exc:
        raise AcquisitionError(f"invalid acquisition evidence {Path(path).name!r}: {exc}") from exc


def verify_acquisition_evidence(
    evidence: AcquisitionEvidence,
    *,
    chunk_dir: str | Path,
    derived_csv: str | Path,
) -> None:
    """Prove the derived CSV was actually derived from the raw chunks.

    This is a *semantic* verification, not independent per-file hashing:
    every raw chunk is re-read into an immutable snapshot, its recorded
    SHA-256 is checked, it is re-parsed against the evidence-declared
    window (with ``row_count`` and ``rows_before_window`` cross-checked
    exactly), the chunks are recombined in declared order, daily
    continuity is re-run, and the deterministic CSV bytes are
    reconstructed and required to equal the supplied derived CSV
    **byte for byte** — so a raw candle cannot be changed (even with its
    recorded SHA updated) while leaving the CSV untouched. Raw sources are
    finally re-hashed to detect mutation during verification. Raises
    :class:`AcquisitionError` on any mismatch.
    """
    directory = Path(chunk_dir)
    snapshots: list[tuple[AcquisitionChunk, bytes]] = []
    for chunk in evidence.chunks:
        path = directory / chunk.filename
        if not path.exists():
            raise AcquisitionError(f"raw response {chunk.filename!r} not found in {directory}")
        # One immutable snapshot: the bytes hashed ARE the bytes re-parsed.
        raw = path.read_bytes()
        if sha256_bytes(raw) != chunk.sha256:
            raise AcquisitionError(
                f"raw response {chunk.filename!r} does not match its recorded SHA-256 — "
                "the file was modified after evidence creation"
            )
        snapshots.append((chunk, raw))

    combined: list[DailyCandle] = []
    for chunk, raw in snapshots:
        try:
            parsed = parse_candles_chunk(
                raw, window_start=chunk.window_start, window_end=chunk.window_end
            )
        except AcquisitionError as exc:
            raise AcquisitionError(f"chunk {chunk.filename!r} no longer parses: {exc}") from exc
        if parsed.row_count != chunk.row_count:
            raise AcquisitionError(
                f"chunk {chunk.filename!r} re-parses to {parsed.row_count} rows but evidence "
                f"records {chunk.row_count}"
            )
        if parsed.rows_before_window != chunk.rows_before_window:
            raise AcquisitionError(
                f"chunk {chunk.filename!r} re-parses to {parsed.rows_before_window} pre-window "
                f"rows but evidence records {chunk.rows_before_window}"
            )
        combined.extend(parsed.candles)

    start_s = epoch_nanoseconds(evidence.overall_start) // 10**9
    end_s = epoch_nanoseconds(evidence.overall_end) // 10**9
    _check_daily_continuity(combined, start_s=start_s, end_s=end_s)

    reconstructed = _derived_csv_bytes(combined)

    derived_path = Path(derived_csv)
    if derived_path.name != evidence.derived_filename:
        raise AcquisitionError(
            f"derived file is named {derived_path.name!r} but evidence records "
            f"{evidence.derived_filename!r}"
        )
    if not derived_path.exists():
        raise AcquisitionError(f"derived OHLCV file {derived_path} does not exist")
    derived_bytes = derived_path.read_bytes()
    if sha256_bytes(derived_bytes) != evidence.derived_sha256:
        raise AcquisitionError(
            f"derived OHLCV file {derived_path.name!r} does not match its recorded SHA-256 — "
            "the file was modified after evidence creation"
        )
    if reconstructed != derived_bytes:
        raise AcquisitionError(
            f"derived OHLCV file {derived_path.name!r} does not re-derive byte-for-byte from "
            "the raw chunks — the CSV and the raw responses disagree"
        )
    # The reconstructed bytes prove content; the recorded scalars must agree.
    if len(combined) != evidence.derived_row_count:
        raise AcquisitionError(
            f"re-derived row count {len(combined)} disagrees with evidence "
            f"{evidence.derived_row_count}"
        )
    if pd.Timestamp(combined[0].open_time_s, unit="s", tz="UTC") != evidence.first_open_time:
        raise AcquisitionError("re-derived first open time disagrees with evidence")
    if pd.Timestamp(combined[-1].open_time_s, unit="s", tz="UTC") != evidence.last_open_time:
        raise AcquisitionError("re-derived last open time disagrees with evidence")

    # Detect a raw source mutated during verification (between snapshot and now).
    for chunk, _ in snapshots:
        if sha256_file(directory / chunk.filename) != chunk.sha256:
            raise AcquisitionError(
                f"raw response {chunk.filename!r} changed during verification; "
                "re-run against settled files"
            )
