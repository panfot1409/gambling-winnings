"""Per-runner strict acquisition validators for the update window.

Each of the two isolated runners independently fetches the same new window and
this module turns its retained raw bytes + receipt into *verified* canonical OHLCV
rows, under the same exact, non-repairing rule the reviewed Milestone 3D adapter
enforces:

1. bind the receipt's plan hash to the committed update plan;
2. for each window, verify the retained raw file's SHA-256 against the receipt;
3. transform via the reviewed M2B Coinbase adapter (strict JSON; Coinbase
   ``[time,low,high,open,close,volume]`` → ``(timestamp,open,high,low,close,
   volume)``; reverse a strictly-descending response; reject any other ordering;
   include exactly the rows inside the half-open window; never interpolate,
   resample, dedup, sort, or gap-fill);
4. bind the delivered rows to the pre-registered plan window — exactly the planned
   bucket count, last open reaching ``window_end - 1 day``, one-day contiguity.

The result is a deterministic function of the runner's committed evidence, so two
runners that fetched the same public candles produce byte-identical canonical rows
and an identical new-window fingerprint (checked in :mod:`eth_research.m3e.comparison`).
This module opens no socket; the network boundary is the workflow ``curl`` step.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.data.coinbase import parse_candles_chunk
from eth_research.m3d.receipt import ProspectiveAttemptReceipt
from eth_research.m3e.update_plan import ProspectiveUpdatePlan
from eth_research.m3e.validation import (
    M3EValidationError,
    domain_sha256,
    require_positive_int,
    require_str,
    sha256_bytes,
)

RUNNER_BUNDLE_DOMAIN = "m3e_runner_window_bundle"
NEW_WINDOW_CANONICAL_DOMAIN = "m3e_update_new_window_canonical"
_INTERVAL_SECONDS = 86400


def _z(open_time_s: int) -> str:
    return pd.Timestamp(open_time_s, unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class RunnerWindowBundle:
    ordinal: int
    raw_filename: str
    byte_length: int
    raw_sha256: str
    row_count: int
    first_open: str
    last_open: str
    canonical_rows: list[list[Any]]
    canonical_content_fingerprint: str


def _bundle_from_raw(
    *,
    ordinal: int,
    raw_filename: str,
    window_start: str,
    window_end: str,
    raw_bytes: bytes,
    expected_bucket_count: int,
) -> RunnerWindowBundle:
    before = sha256_bytes(raw_bytes)
    parsed = parse_candles_chunk(
        raw_bytes,
        window_start=pd.Timestamp(window_start),
        window_end=pd.Timestamp(window_end),
    )
    if sha256_bytes(raw_bytes) != before:  # pragma: no cover - defensive
        raise M3EValidationError("raw bytes mutated during parsing")
    if not parsed.candles:
        raise M3EValidationError(f"window {ordinal}: no candle in the declared window")
    rows: list[list[Any]] = [
        [_z(c.open_time_s), c.open, c.high, c.low, c.close, c.volume] for c in parsed.candles
    ]
    times = [c.open_time_s for c in parsed.candles]
    for earlier, later in pairwise(times):
        if later - earlier != _INTERVAL_SECONDS:
            raise M3EValidationError(f"window {ordinal}: candles are not contiguous daily")
    if len(rows) != expected_bucket_count:
        raise M3EValidationError(
            f"window {ordinal}: {len(rows)} rows does not equal the planned {expected_bucket_count}"
        )
    planned_last = pd.Timestamp(window_end) - pd.Timedelta(days=1)
    if pd.Timestamp(rows[-1][0]) != planned_last:
        raise M3EValidationError(
            f"window {ordinal}: last open {rows[-1][0]} does not reach the plan window end"
        )
    fingerprint = domain_sha256(
        RUNNER_BUNDLE_DOMAIN,
        {
            "ordinal": ordinal,
            "raw_filename": raw_filename,
            "byte_length": len(raw_bytes),
            "raw_sha256": before,
            "row_count": len(rows),
            "first_open": rows[0][0],
            "last_open": rows[-1][0],
            "rows": rows,
        },
    )
    return RunnerWindowBundle(
        ordinal=ordinal,
        raw_filename=raw_filename,
        byte_length=len(raw_bytes),
        raw_sha256=before,
        row_count=len(rows),
        first_open=rows[0][0],
        last_open=rows[-1][0],
        canonical_rows=rows,
        canonical_content_fingerprint=fingerprint,
    )


def build_runner_bundles(
    *, raw_dir: str | Path, update_plan: ProspectiveUpdatePlan, receipt: ProspectiveAttemptReceipt
) -> list[RunnerWindowBundle]:
    """Rebuild + verify a runner's canonical window bundles from committed evidence.

    ``raw_dir`` holds the runner's retained raw JSON files. Raises on any receipt /
    plan / SHA-256 / window / contiguity / truncation mismatch.
    """
    if receipt.plan_sha256 != update_plan.plan_sha256:
        raise M3EValidationError("runner receipt plan hash does not match the update plan")
    directory = Path(raw_dir)
    by_ordinal = {int(w["ordinal"]): w for w in update_plan.windows}
    if len(by_ordinal) != len(update_plan.windows):  # pragma: no cover - defensive
        raise M3EValidationError("duplicate window ordinal in update plan")

    bundles: list[RunnerWindowBundle] = []
    for response in receipt.responses:
        ordinal = int(response["ordinal"])
        if ordinal not in by_ordinal:
            raise M3EValidationError(f"receipt names an ordinal {ordinal} absent from the plan")
        window = by_ordinal[ordinal]
        raw_name = require_str("raw_filename", response["raw_filename"])
        if raw_name != window["raw_filename"]:
            raise M3EValidationError(
                f"receipt raw filename does not match the plan for ordinal {ordinal}"
            )
        raw_path = directory / raw_name
        if raw_path.is_symlink() or not raw_path.is_file():
            raise M3EValidationError(f"raw file {raw_name} is not a regular file")
        raw_bytes = raw_path.read_bytes()
        if sha256_bytes(raw_bytes) != response["response_sha256"]:
            raise M3EValidationError(f"raw file {raw_name} SHA-256 does not match the receipt")
        if len(raw_bytes) != int(response["response_byte_length"]):
            raise M3EValidationError(
                f"raw file {raw_name} byte length {len(raw_bytes)} does not match the "
                f"receipt {int(response['response_byte_length'])}"
            )
        bundles.append(
            _bundle_from_raw(
                ordinal=ordinal,
                raw_filename=raw_name,
                window_start=str(window["window_start"]),
                window_end=str(window["window_end"]),
                raw_bytes=raw_bytes,
                expected_bucket_count=require_positive_int(
                    "expected_bucket_count", window["expected_bucket_count"]
                ),
            )
        )

    if {b.ordinal for b in bundles} != set(by_ordinal):
        raise M3EValidationError("runner did not cover every planned window exactly once")
    bundles.sort(key=lambda b: b.ordinal)
    _check_continuity(bundles)
    return bundles


def _check_continuity(bundles: list[RunnerWindowBundle]) -> None:
    if not bundles:
        raise M3EValidationError("no runner bundles were produced")
    previous_last: int | None = None
    for bundle in bundles:
        first = int(pd.Timestamp(bundle.first_open).timestamp())
        if previous_last is not None and first - previous_last != _INTERVAL_SECONDS:
            raise M3EValidationError("runner bundles are not contiguous across windows")
        previous_last = int(pd.Timestamp(bundle.last_open).timestamp())


def new_window_canonical_rows(bundles: list[RunnerWindowBundle]) -> list[list[Any]]:
    """All new-window canonical OHLCV rows across bundles, in chronological order."""
    rows: list[list[Any]] = []
    for bundle in bundles:
        rows.extend(bundle.canonical_rows)
    return rows


def fingerprint_new_window_rows(rows: list[list[Any]]) -> str:
    """Domain-separated fingerprint over ordered new-window canonical rows."""
    if not rows:
        raise M3EValidationError("new window has no rows")
    return domain_sha256(
        NEW_WINDOW_CANONICAL_DOMAIN,
        {
            "interval_seconds": _INTERVAL_SECONDS,
            "row_count": len(rows),
            "first_open": rows[0][0],
            "last_open": rows[-1][0],
            "rows": rows,
        },
    )


def new_window_fingerprint(bundles: list[RunnerWindowBundle]) -> str:
    """Domain-separated fingerprint over the full ordered new-window canonical rows."""
    return fingerprint_new_window_rows(new_window_canonical_rows(bundles))
