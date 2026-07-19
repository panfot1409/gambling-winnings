"""Strict, offline BTC-USD acquisition plan + response verifier for V2B.

The **only** new information source V2B is permitted is historical **BTC-USD daily** candles,
restricted to the exact half-open window matching the authorized ETH research-train:

    [2016-05-23T00:00:00Z, 2022-06-22T00:00:00Z)   →  2221 daily opens (2016-05-23 … 2022-06-21).

This module contains **no networking**. It (a) builds a fixed, immutable request plan — a small
number of non-overlapping half-open day windows of at most 299 daily buckets each, with canonical
per-window ``start``/``end`` request parameters that a hardened workflow ``curl`` step consumes, and
(b) strictly parses and verifies the downloaded response bodies offline into one canonical daily
OHLCV series, refusing anything outside the window, any duplicate/missing/forming bucket, any
non-finite field, or any OHLCV-identity violation.

The window is **hard-coded** here; there is no caller-supplied product, host, start, end, or
granularity. A caller cannot widen the request window through an input, environment variable, plan
edit, alternate file, or symlink — the plan a workflow runs is exactly
:func:`build_btc_acquisition_plan` and its ``plan_sha256`` is bound into every receipt. No BTC (or
ETH) observation at or after the
research cutoff may be acquired.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise

import pandas as pd

from eth_research.data.coinbase import canonical_utc_request
from eth_research.data.provenance import sha256_bytes
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    strict_json_loads,
)

ACQUISITION_SCHEMA_VERSION: int = 1

# One parsed daily candle: (open_epoch_seconds, low, high, open, close, volume).
Candle = tuple[int, float, float, float, float, float]

BTC_VENUE: str = "coinbase-exchange"
BTC_PRODUCT: str = "BTC-USD"
BTC_GRANULARITY_SECONDS: int = 86_400
BTC_CANDLES_ENDPOINT: str = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
BTC_DOCUMENTATION_URL: str = (
    "https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles"
)
BTC_ADAPTER_ALGORITHM: str = "coinbase-candles-v1"

# The authorized window — matched exactly to the ETH research-train. Hard-coded; not caller-set.
WINDOW_START: pd.Timestamp = pd.Timestamp("2016-05-23T00:00:00Z")
WINDOW_END_EXCLUSIVE: pd.Timestamp = pd.Timestamp("2022-06-22T00:00:00Z")  # half-open
RESEARCH_CUTOFF_LAST_OPEN: pd.Timestamp = pd.Timestamp("2022-06-21T00:00:00Z")
EXPECTED_DAILY_OPENS: int = 2221
MAX_BUCKETS_PER_REQUEST: int = 299  # margin below Coinbase's 300-candle response limit

# The two allowlisted acquisition attempts (genesis + independent audit).
GENESIS_ATTEMPT_ID: str = "coinbase-btc-usd-research-genesis-001"
AUDIT_ATTEMPT_ID: str = "coinbase-btc-usd-research-audit-002"
ATTEMPT_IDS: tuple[str, ...] = (GENESIS_ATTEMPT_ID, AUDIT_ATTEMPT_ID)

_DAY = pd.Timedelta(days=1)


class BtcAcquisitionError(V2ValidationError):
    """A BTC acquisition plan/response was malformed, out-of-window, or otherwise unacceptable."""


@dataclass(frozen=True, slots=True)
class BtcAcquisitionWindow:
    """One planned request: a half-open UTC day window and its canonical request parameters."""

    ordinal: int
    window_start: pd.Timestamp
    window_end: pd.Timestamp  # exclusive
    requested_start: str  # Coinbase 'start' param == window_start (inclusive bucket open)
    requested_end: str  # Coinbase 'end' param == window_end - 1 day (last inclusive bucket open)
    filename: str

    def expected_open_count(self) -> int:
        return int((self.window_end - self.window_start) / _DAY)

    def to_canonical(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "window_start": self.window_start.isoformat().replace("+00:00", "Z"),
            "window_end": self.window_end.isoformat().replace("+00:00", "Z"),
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "filename": self.filename,
            "expected_open_count": self.expected_open_count(),
        }


@dataclass(frozen=True, slots=True)
class BtcAcquisitionPlan:
    """The fixed, immutable BTC-USD request plan (hard-coded window; no caller inputs)."""

    schema_version: int
    venue: str
    product: str
    endpoint: str
    documentation_url: str
    granularity_seconds: int
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    expected_daily_opens: int
    max_buckets_per_request: int
    windows: tuple[BtcAcquisitionWindow, ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "venue": self.venue,
            "product": self.product,
            "endpoint": self.endpoint,
            "documentation_url": self.documentation_url,
            "granularity_seconds": self.granularity_seconds,
            "window_start": self.window_start.isoformat().replace("+00:00", "Z"),
            "window_end": self.window_end.isoformat().replace("+00:00", "Z"),
            "expected_daily_opens": self.expected_daily_opens,
            "max_buckets_per_request": self.max_buckets_per_request,
            "windows": [w.to_canonical() for w in self.windows],
        }

    def plan_sha256(self) -> str:
        return canonical_sha256(self.to_canonical())

    def expected_request_count(self) -> int:
        return len(self.windows)


def _filename(ordinal: int) -> str:
    return f"candles_{ordinal:03d}.json"


def build_btc_acquisition_plan() -> BtcAcquisitionPlan:
    """The one fixed BTC-USD acquisition plan for the authorized research-train window."""
    windows: list[BtcAcquisitionWindow] = []
    cursor = WINDOW_START
    ordinal = 0
    total_opens = 0
    while cursor < WINDOW_END_EXCLUSIVE:
        window_end = min(cursor + _DAY * MAX_BUCKETS_PER_REQUEST, WINDOW_END_EXCLUSIVE)
        window = BtcAcquisitionWindow(
            ordinal=ordinal,
            window_start=cursor,
            window_end=window_end,
            requested_start=canonical_utc_request(cursor),
            requested_end=canonical_utc_request(window_end - _DAY),
            filename=_filename(ordinal),
        )
        if window.expected_open_count() > MAX_BUCKETS_PER_REQUEST:
            raise BtcAcquisitionError("planned window exceeds the per-request bucket cap")
        windows.append(window)
        total_opens += window.expected_open_count()
        cursor = window_end
        ordinal += 1
    if total_opens != EXPECTED_DAILY_OPENS:
        raise BtcAcquisitionError(
            f"planned windows cover {total_opens} opens, expected {EXPECTED_DAILY_OPENS}"
        )
    return BtcAcquisitionPlan(
        schema_version=ACQUISITION_SCHEMA_VERSION,
        venue=BTC_VENUE,
        product=BTC_PRODUCT,
        endpoint=BTC_CANDLES_ENDPOINT,
        documentation_url=BTC_DOCUMENTATION_URL,
        granularity_seconds=BTC_GRANULARITY_SECONDS,
        window_start=WINDOW_START,
        window_end=WINDOW_END_EXCLUSIVE,
        expected_daily_opens=EXPECTED_DAILY_OPENS,
        max_buckets_per_request=MAX_BUCKETS_PER_REQUEST,
        windows=tuple(windows),
    )


def build_plan_bytes() -> bytes:
    return canonical_json_bytes(build_btc_acquisition_plan().to_canonical())


# --------------------------------------------------------------------------- #
# strict offline response parsing (no networking)                             #
# --------------------------------------------------------------------------- #
_EPOCH_START = int(WINDOW_START.timestamp())
_EPOCH_END = int(WINDOW_END_EXCLUSIVE.timestamp())


def parse_candles_body(body: bytes, window: BtcAcquisitionWindow) -> list[Candle]:
    """Strictly parse one Coinbase candles response body into in-window daily rows.

    Each row is ``[time, low, high, open, close, volume]`` (time = bucket-open epoch seconds).
    Rows before the window start are excluded and counted; rows at/after the window end (or at/after
    the research cutoff) are rejected; OHLCV identities and finiteness are enforced.
    """
    decoded = strict_json_loads(body)
    if not isinstance(decoded, list):
        raise BtcAcquisitionError("candles response is not a JSON array")
    rows: list[Candle] = []
    seen: set[int] = set()
    win_start = int(window.window_start.timestamp())
    win_end = int(window.window_end.timestamp())
    for raw in decoded:
        if not isinstance(raw, list) or len(raw) != 6:
            raise BtcAcquisitionError("candle row is not a 6-element array")
        t = raw[0]
        if not isinstance(t, int) or isinstance(t, bool):
            raise BtcAcquisitionError("candle time is not an integer epoch")
        if t % BTC_GRANULARITY_SECONDS != 0:
            raise BtcAcquisitionError(f"candle time {t} is not day-aligned")
        if t < win_start:
            continue  # a pre-window row: excluded (Coinbase may return earlier buckets)
        if t >= win_end or t >= _EPOCH_END or t > int(RESEARCH_CUTOFF_LAST_OPEN.timestamp()):
            raise BtcAcquisitionError(
                f"candle time {t} is at/after the window end or research cutoff"
            )
        low, high, open_, close, volume = (raw[1], raw[2], raw[3], raw[4], raw[5])
        for name, value in (("low", low), ("high", high), ("open", open_), ("close", close)):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise BtcAcquisitionError(f"candle {name} is not a real number")
            if not (value == value and value not in (float("inf"), float("-inf")) and value > 0):
                raise BtcAcquisitionError(f"candle {name} is not a finite positive price")
        if not isinstance(volume, (int, float)) or isinstance(volume, bool) or volume < 0:
            raise BtcAcquisitionError("candle volume is not a finite non-negative number")
        if not (low <= open_ <= high and low <= close <= high):
            raise BtcAcquisitionError(f"candle at {t} violates low<=open,close<=high")
        if t in seen:
            raise BtcAcquisitionError(f"duplicate candle open {t}")
        seen.add(t)
        rows.append((t, float(low), float(high), float(open_), float(close), float(volume)))
    rows.sort(key=lambda r: r[0])
    return rows


@dataclass(frozen=True, slots=True)
class BtcResponseReceipt:
    """A strict, byte-reproducible receipt for one fetched window body."""

    attempt_id: str
    ordinal: int
    filename: str
    plan_sha256: str
    body_sha256: str
    body_bytes: int
    parsed_open_count: int
    first_open_epoch: int
    last_open_epoch: int

    def to_canonical(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "ordinal": self.ordinal,
            "filename": self.filename,
            "plan_sha256": self.plan_sha256,
            "body_sha256": self.body_sha256,
            "body_bytes": self.body_bytes,
            "parsed_open_count": self.parsed_open_count,
            "first_open_epoch": self.first_open_epoch,
            "last_open_epoch": self.last_open_epoch,
        }


def build_window_receipt(
    attempt_id: str, window: BtcAcquisitionWindow, body: bytes, plan_sha256: str
) -> BtcResponseReceipt:
    if attempt_id not in ATTEMPT_IDS:
        raise BtcAcquisitionError(f"attempt_id {attempt_id!r} is not allowlisted")
    rows = parse_candles_body(body, window)
    if not rows:
        raise BtcAcquisitionError(f"window {window.ordinal} produced no in-window candles")
    return BtcResponseReceipt(
        attempt_id=attempt_id,
        ordinal=window.ordinal,
        filename=window.filename,
        plan_sha256=plan_sha256,
        body_sha256=sha256_bytes(body),
        body_bytes=len(body),
        parsed_open_count=len(rows),
        first_open_epoch=rows[0][0],
        last_open_epoch=rows[-1][0],
    )


def canonical_daily_frame(rows_by_window: list[list[Candle]]) -> pd.DataFrame:
    """Assemble the canonical BTC daily OHLCV frame from all windows' parsed rows (strict)."""
    merged: dict[int, Candle] = {}
    for rows in rows_by_window:
        for row in rows:
            t = row[0]
            if t in merged:
                raise BtcAcquisitionError(f"duplicate candle open {t} across windows")
            merged[t] = row
    if len(merged) != EXPECTED_DAILY_OPENS:
        raise BtcAcquisitionError(
            f"assembled {len(merged)} daily opens, expected {EXPECTED_DAILY_OPENS}"
        )
    times = sorted(merged)
    # Every consecutive open must be exactly one day apart (no missing bucket).
    for a, b in pairwise(times):
        if b - a != BTC_GRANULARITY_SECONDS:
            raise BtcAcquisitionError(f"gap between opens {a} and {b} (missing daily bucket)")
    index = pd.to_datetime([t * 1_000_000_000 for t in times], utc=True)
    frame = pd.DataFrame(
        {
            "open": [merged[t][3] for t in times],
            "high": [merged[t][2] for t in times],
            "low": [merged[t][1] for t in times],
            "close": [merged[t][4] for t in times],
            "volume": [merged[t][5] for t in times],
        },
        index=index,
    )
    frame.index.name = "timestamp"
    if frame.index[0] != WINDOW_START:
        raise BtcAcquisitionError("first open is not the window start")
    if frame.index[-1] != RESEARCH_CUTOFF_LAST_OPEN:
        raise BtcAcquisitionError("last open is not the research cutoff last open")
    return frame


def content_fingerprint(frame: pd.DataFrame) -> str:
    """A canonical content fingerprint over the assembled BTC daily frame."""
    cols = ("open", "high", "low", "close", "volume")
    lines = []
    for i, ts in enumerate(frame.index):
        stamp = pd.Timestamp(ts).isoformat().replace("+00:00", "Z")
        vals = ",".join(repr(frame[col].iloc[i]) for col in cols)
        lines.append(f"{stamp},{vals}")
    return sha256_bytes("\n".join(lines).encode("utf-8"))


def _utc_now_iso() -> str:  # pragma: no cover - only a default for tooling
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
