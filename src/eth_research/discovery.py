"""Machine-verified earliest-continuous-start decision.

The Milestone 2B dataset begins at 2016-05-23, not at Coinbase's first
listed ETH-USD candle (2016-05-18), because the daily candles for
2016-05-21 and 2016-05-22 are absent — a start there would not be gap-free.
This choice was previously only a Markdown assertion. This module makes it
a strict, immutable :class:`DiscoveryDecision` **re-derived from the raw
discovery response bytes**: the first available candle, the early-history
gap, and the chosen start are all recomputed and cross-checked, so a
hand-edited claim can never diverge from what the bytes actually show. No
candle is ever filled or synthesized — a start is chosen, never a repair.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.acquisition_plan import load_acquisition_plan, load_acquisition_receipt
from eth_research.data.coinbase import (
    COINBASE_GRANULARITY_SECONDS,
    COINBASE_PRODUCT,
    COINBASE_VENUE,
    DailyCandle,
    parse_candles_chunk,
)
from eth_research.data.provenance import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
    sha256_bytes,
)
from eth_research.data.validation import (
    parse_timestamp_field,
    require_commit_sha,
    require_day_aligned_utc,
    require_positive_int,
    require_utc_timestamp,
)

DISCOVERY_SCHEMA_VERSION: int = 1

_DISCOVERY_KEYS: frozenset[str] = frozenset(
    {
        "discovery_schema_version",
        "venue",
        "product",
        "candle_interval_seconds",
        "discovery_window_start",
        "discovery_window_end",
        "raw_response_sha256",
        "workflow_run_id",
        "source_commit",
        "retrieved_at",
        "discovery_candle_count",
        "first_available_open_time",
        "last_discovery_open_time",
        "missing_early_open_times",
        "chosen_start",
        "chosen_end",
    }
)


class DiscoveryDecisionError(RuntimeError):
    """A discovery decision is invalid or disagrees with the raw bytes."""


@dataclass(frozen=True)
class DiscoveryDecision:
    """A strict, immutable, machine-verifiable earliest-start decision."""

    discovery_schema_version: int
    venue: str
    product: str
    candle_interval_seconds: int
    discovery_window_start: pd.Timestamp
    discovery_window_end: pd.Timestamp
    raw_response_sha256: str
    workflow_run_id: str
    source_commit: str
    retrieved_at: pd.Timestamp
    discovery_candle_count: int
    first_available_open_time: pd.Timestamp
    last_discovery_open_time: pd.Timestamp
    missing_early_open_times: tuple[pd.Timestamp, ...]
    chosen_start: pd.Timestamp
    chosen_end: pd.Timestamp

    def __post_init__(self) -> None:
        version = require_int("discovery_schema_version", self.discovery_schema_version)
        if version != DISCOVERY_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported discovery schema version {version!r}; "
                f"this package reads version {DISCOVERY_SCHEMA_VERSION}"
            )
        if require_str("venue", self.venue) != COINBASE_VENUE:
            raise ValueError(f"venue must be {COINBASE_VENUE!r}, got {self.venue!r}")
        if require_str("product", self.product) != COINBASE_PRODUCT:
            raise ValueError(f"product must be {COINBASE_PRODUCT!r}, got {self.product!r}")
        if require_int("candle_interval_seconds", self.candle_interval_seconds) != (
            COINBASE_GRANULARITY_SECONDS
        ):
            raise ValueError(
                f"candle_interval_seconds must be {COINBASE_GRANULARITY_SECONDS}, "
                f"got {self.candle_interval_seconds}"
            )
        require_day_aligned_utc("discovery_window_start", self.discovery_window_start)
        require_day_aligned_utc("discovery_window_end", self.discovery_window_end)
        if self.discovery_window_start >= self.discovery_window_end:
            raise ValueError("discovery_window_start must precede discovery_window_end")
        require_hex64("raw_response_sha256", self.raw_response_sha256)
        require_nonempty_str("workflow_run_id", self.workflow_run_id)
        require_commit_sha("source_commit", self.source_commit)
        require_utc_timestamp("retrieved_at", self.retrieved_at)
        require_positive_int("discovery_candle_count", self.discovery_candle_count)
        for label in (
            "first_available_open_time",
            "last_discovery_open_time",
            "chosen_start",
            "chosen_end",
        ):
            require_day_aligned_utc(label, getattr(self, label))
        if not (
            self.first_available_open_time
            <= self.chosen_start
            <= self.last_discovery_open_time
            < self.discovery_window_end
        ):
            raise ValueError(
                "the chosen start must lie between the first available candle and the last "
                "discovery candle, which must precede the discovery window end"
            )
        if self.chosen_start >= self.chosen_end:
            raise ValueError("chosen_start must precede chosen_end")
        if not isinstance(self.missing_early_open_times, tuple):
            raise ValueError("missing_early_open_times must be a tuple")
        previous: pd.Timestamp | None = None
        for value in self.missing_early_open_times:
            require_day_aligned_utc("missing_early_open_times entry", value)
            if not self.first_available_open_time < value < self.chosen_start:
                raise ValueError(
                    "every missing early candle must lie strictly between the first available "
                    "candle and the chosen start (the gap is advanced past, never filled)"
                )
            if previous is not None and value <= previous:
                raise ValueError("missing_early_open_times must be strictly ascending")
            previous = value

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "discovery_schema_version": self.discovery_schema_version,
            "venue": self.venue,
            "product": self.product,
            "candle_interval_seconds": self.candle_interval_seconds,
            "discovery_window_start": self.discovery_window_start.isoformat(),
            "discovery_window_end": self.discovery_window_end.isoformat(),
            "raw_response_sha256": self.raw_response_sha256,
            "workflow_run_id": self.workflow_run_id,
            "source_commit": self.source_commit,
            "retrieved_at": self.retrieved_at.isoformat(),
            "discovery_candle_count": self.discovery_candle_count,
            "first_available_open_time": self.first_available_open_time.isoformat(),
            "last_discovery_open_time": self.last_discovery_open_time.isoformat(),
            "missing_early_open_times": [ts.isoformat() for ts in self.missing_early_open_times],
            "chosen_start": self.chosen_start.isoformat(),
            "chosen_end": self.chosen_end.isoformat(),
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> DiscoveryDecision:
        """Strict parse feeding the shared constructor validation."""
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"discovery decision is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("discovery decision JSON must be an object")
        keys = set(payload)
        if keys != _DISCOVERY_KEYS:
            unknown = sorted(keys - _DISCOVERY_KEYS)
            missing = sorted(_DISCOVERY_KEYS - keys)
            raise ValueError(
                f"discovery decision keys do not match schema: unknown={unknown}, missing={missing}"
            )
        missing_times = payload["missing_early_open_times"]
        if not isinstance(missing_times, list):
            raise ValueError("missing_early_open_times must be an array")
        return cls(
            discovery_schema_version=payload["discovery_schema_version"],
            venue=payload["venue"],
            product=payload["product"],
            candle_interval_seconds=payload["candle_interval_seconds"],
            discovery_window_start=parse_timestamp_field(
                "discovery_window_start", payload["discovery_window_start"]
            ),
            discovery_window_end=parse_timestamp_field(
                "discovery_window_end", payload["discovery_window_end"]
            ),
            raw_response_sha256=payload["raw_response_sha256"],
            workflow_run_id=payload["workflow_run_id"],
            source_commit=payload["source_commit"],
            retrieved_at=parse_timestamp_field("retrieved_at", payload["retrieved_at"]),
            discovery_candle_count=payload["discovery_candle_count"],
            first_available_open_time=parse_timestamp_field(
                "first_available_open_time", payload["first_available_open_time"]
            ),
            last_discovery_open_time=parse_timestamp_field(
                "last_discovery_open_time", payload["last_discovery_open_time"]
            ),
            missing_early_open_times=tuple(
                parse_timestamp_field("missing_early_open_times entry", value)
                for value in missing_times
            ),
            chosen_start=parse_timestamp_field("chosen_start", payload["chosen_start"]),
            chosen_end=parse_timestamp_field("chosen_end", payload["chosen_end"]),
        )


def _open_time(candle: DailyCandle) -> pd.Timestamp:
    return pd.Timestamp(candle.open_time_s, unit="s", tz="UTC")


def _missing_between(candles: tuple[DailyCandle, ...], interval_s: int) -> list[pd.Timestamp]:
    """Every absent daily open strictly between consecutive present candles."""
    missing: list[pd.Timestamp] = []
    for earlier, later in pairwise(candles):
        step = later.open_time_s - earlier.open_time_s
        if step % interval_s != 0:
            raise DiscoveryDecisionError(
                f"discovery candle at {later.open_time_s} is not a whole number of days after "
                f"the previous candle at {earlier.open_time_s}"
            )
        for k in range(1, step // interval_s):
            missing.append(pd.Timestamp(earlier.open_time_s + k * interval_s, unit="s", tz="UTC"))
    return missing


def verify_discovery_decision_from_raw(decision: DiscoveryDecision, raw_bytes: bytes) -> None:
    """Re-derive every candle fact from the raw bytes and cross-check it.

    Proves, from the exact discovery response body, that the first available
    candle, the early-history gap, and the chosen start are what the
    decision claims, and that the series is continuous from the chosen start
    to the end of the discovery window.
    """
    if sha256_bytes(raw_bytes) != decision.raw_response_sha256:
        raise DiscoveryDecisionError(
            "raw discovery bytes do not hash to the decision's raw_response_sha256"
        )
    try:
        parsed = parse_candles_chunk(
            raw_bytes,
            window_start=decision.discovery_window_start,
            window_end=decision.discovery_window_end,
        )
    except Exception as exc:
        raise DiscoveryDecisionError(f"discovery response failed to parse: {exc}") from exc
    candles = parsed.candles
    if len(candles) != decision.discovery_candle_count:
        raise DiscoveryDecisionError(
            f"discovery candle count {len(candles)} does not match the decision's "
            f"{decision.discovery_candle_count}"
        )
    if _open_time(candles[0]) != decision.first_available_open_time:
        raise DiscoveryDecisionError("first available candle disagrees with the raw bytes")
    if _open_time(candles[-1]) != decision.last_discovery_open_time:
        raise DiscoveryDecisionError("last discovery candle disagrees with the raw bytes")

    interval_s = decision.candle_interval_seconds
    missing = _missing_between(candles, interval_s)
    if tuple(missing) != decision.missing_early_open_times:
        raise DiscoveryDecisionError(
            "the missing daily candles derived from the raw bytes do not match the decision"
        )
    # The chosen start must be an actually-present candle, and the series
    # from it onward (within the discovery window) must be gap-free.
    present = {candle.open_time_s for candle in candles}
    if int(decision.chosen_start.timestamp()) not in present:
        raise DiscoveryDecisionError("the chosen start is not a present discovery candle")
    onward = tuple(c for c in candles if _open_time(c) >= decision.chosen_start)
    if _missing_between(onward, interval_s):
        raise DiscoveryDecisionError(
            "the series is not continuous from the chosen start through the discovery window"
        )


def build_discovery_decision(repo_root: str | Path) -> DiscoveryDecision:
    """Derive the decision from the committed discovery raw, receipt, and plan.

    The chosen start/end are taken from the frozen acquisition request plan
    (``overall_start``/``overall_end``); every candle fact is re-derived from
    the raw discovery bytes and the result is self-verified before return.
    """
    root = Path(repo_root)
    attempt = root / "research/m2b/raw/coinbase/discovery-001"
    receipt = load_acquisition_receipt(attempt / "acquisition_receipt.json")
    response = receipt.responses[0]
    raw_bytes = (attempt / response.filename).read_bytes()
    discovery_plan = load_acquisition_plan(root / "research/m2b/discovery_plan.json")
    acquisition_plan = load_acquisition_plan(root / "research/m2b/acquisition_request_plan.json")

    parsed = parse_candles_chunk(
        raw_bytes,
        window_start=discovery_plan.overall_start,
        window_end=discovery_plan.overall_end,
    )
    candles = parsed.candles
    interval_s = COINBASE_GRANULARITY_SECONDS
    missing = tuple(
        ts for ts in _missing_between(candles, interval_s) if ts < acquisition_plan.overall_start
    )
    decision = DiscoveryDecision(
        discovery_schema_version=DISCOVERY_SCHEMA_VERSION,
        venue=COINBASE_VENUE,
        product=COINBASE_PRODUCT,
        candle_interval_seconds=interval_s,
        discovery_window_start=discovery_plan.overall_start,
        discovery_window_end=discovery_plan.overall_end,
        raw_response_sha256=response.sha256,
        workflow_run_id=receipt.workflow_run_id,
        source_commit=receipt.source_commit,
        retrieved_at=response.retrieved_at,
        discovery_candle_count=len(candles),
        first_available_open_time=_open_time(candles[0]),
        last_discovery_open_time=_open_time(candles[-1]),
        missing_early_open_times=missing,
        chosen_start=acquisition_plan.overall_start,
        chosen_end=acquisition_plan.overall_end,
    )
    verify_discovery_decision_from_raw(decision, raw_bytes)
    return decision


def render_discovery_decision(decision: DiscoveryDecision) -> str:
    """Render the decision as Markdown, purely from the validated model."""
    missing = ", ".join(ts.date().isoformat() for ts in decision.missing_early_open_times)
    lines = [
        "# Earliest-continuous-series decision (Coinbase Exchange ETH-USD daily)",
        "",
        "This records the explicit, evidence-based choice of the frozen dataset's "
        "start, machine-verified from the raw discovery response. No candle was "
        "ever filled, interpolated, resampled, or synthesized; a start is chosen, "
        "never a repair.",
        "",
        "## Stage-A discovery evidence (re-derived from the raw bytes)",
        "",
        f"- Attempt `discovery-001`, workflow run `{decision.workflow_run_id}`, source "
        f"commit `{decision.source_commit}`.",
        f"- Discovery request window: [{decision.discovery_window_start.date()}, "
        f"{decision.discovery_window_end.date()}) (one request), retrieved "
        f"{decision.retrieved_at.isoformat()}.",
        f"- Raw response SHA-256: `{decision.raw_response_sha256}`.",
        f"- Parsed candles in the window: **{decision.discovery_candle_count}**. First "
        f"available daily candle: **{decision.first_available_open_time.date()}**. Last "
        f"candle in the discovery window: {decision.last_discovery_open_time.date()}.",
        f"- Absent early daily candles: **{missing}** (no trades/ticks published). The "
        f"series is contiguous after the chosen start through the discovery window.",
        "",
        "## Decision",
        "",
        f"- **Rejected start candidates:** every day up to and including the last absent "
        f"candle. Days before {decision.first_available_open_time.date()} precede the first "
        f"available candle; the isolated early candles are rejected because the absent "
        f"{missing} gap immediately follows, so a dataset beginning there would not be "
        f"gap-free. This gap lies wholly in the earliest listing era, so the start is "
        f"advanced past it — it is not a mid/recent-history gap (which would abort instead).",
        f"- **Chosen start = {decision.chosen_start.date()}** — the first daily candle after "
        f"the last early-history gap, from which the series is continuous in the discovery "
        f"window.",
        f"- **Chosen end = {decision.chosen_end.date()}** — the exclusive upper bound fixed "
        f"in the committed acquisition plan; the forming final-day candle is excluded and "
        f'this bound is never replaced with "now" during replay.',
        "",
        "Full-series daily continuity from the chosen start onward is proven by the "
        "Stage-B acquisition and offline replay; a gap anywhere after the early era "
        "aborts the freeze with the offending timestamp — it is never filled.",
        "",
    ]
    return "\n".join(lines)


def load_discovery_decision(path: str | Path) -> DiscoveryDecision:
    """Strictly parse a discovery-decision file."""
    file = Path(path)
    try:
        return DiscoveryDecision.from_json_bytes(file.read_bytes())
    except ValueError as exc:
        raise DiscoveryDecisionError(f"invalid discovery decision {file.name!r}: {exc}") from exc
