"""Prospective raw-bundle and transformation evidence.

For each acquired window, a ``ProspectiveRawBundle`` binds the retained raw
response bytes (filename, byte length, SHA-256) to the canonical OHLCV rows they
transform into, under an exact, non-repairing rule:

1. Decode strict JSON.
2. Map Coinbase ``[time, low, high, open, close, volume]`` to
   ``(timestamp, open, high, low, close, volume)``.
3. Reverse only a strictly descending response; reject any other ordering.
4. Include every row inside the declared half-open window; reject any row outside.
5. Serialize canonical UTC timestamps and round-trip floats.
6. Never interpolate, resample, deduplicate, arbitrarily sort, or gap-fill.

The transformation is delegated to the already-reviewed M2B Coinbase adapter
(:func:`eth_research.data.coinbase.parse_candles_chunk`), which enforces exactly
these rules. The canonical rows re-derive byte-for-byte from the retained raw
bytes, so :func:`build_raw_bundles` is a deterministic function of committed
evidence and the segment/cohort canonical content is fully replayable offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.data.coinbase import parse_candles_chunk
from eth_research.m3d import _upstream as up
from eth_research.m3d.acquisition_plan import load_prospective_acquisition_plan
from eth_research.m3d.receipt import load_prospective_attempt_receipt
from eth_research.m3d.validation import (
    M3DValidationError,
    domain_sha256,
    require_positive_int,
    require_str,
    sha256_bytes,
)

RAW_BUNDLE_DOMAIN = "prospective_raw_bundle"
_INTERVAL_SECONDS = 86400


def _z(open_time_s: int) -> str:
    return pd.Timestamp(open_time_s, unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ProspectiveRawBundle:
    ordinal: int
    raw_filename: str
    start_param: str
    end_param: str
    byte_length: int
    raw_sha256: str
    row_count: int
    first_open: str
    last_open: str
    canonical_rows: list[list[Any]]
    canonical_content_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "raw_filename": self.raw_filename,
            "start_param": self.start_param,
            "end_param": self.end_param,
            "byte_length": self.byte_length,
            "raw_sha256": self.raw_sha256,
            "row_count": self.row_count,
            "first_open": self.first_open,
            "last_open": self.last_open,
            "canonical_content_fingerprint": self.canonical_content_fingerprint,
        }


def _bundle_from_raw(
    ordinal: int,
    raw_filename: str,
    window_start: str,
    window_end: str,
    start_param: str,
    end_param: str,
    raw_bytes: bytes,
) -> ProspectiveRawBundle:
    # Hash before and after parsing to catch any in-flight mutation. Parse against
    # the half-open plan window [window_start, window_end); start_param/end_param
    # are the inclusive Coinbase request opens (end_param == window_end - 1 day),
    # recorded as provenance, not used as parse bounds.
    before = sha256_bytes(raw_bytes)
    parsed = parse_candles_chunk(
        raw_bytes,
        window_start=pd.Timestamp(window_start),
        window_end=pd.Timestamp(window_end),
    )
    after = sha256_bytes(raw_bytes)
    if before != after:  # pragma: no cover - defensive
        raise M3DValidationError("raw bytes mutated during parsing")
    if not parsed.candles:
        raise M3DValidationError(f"window {ordinal}: no candle in the declared window")
    rows: list[list[Any]] = [
        [_z(c.open_time_s), c.open, c.high, c.low, c.close, c.volume] for c in parsed.candles
    ]
    # Contiguity: exactly one-day spacing, no gap or duplicate.
    times = [c.open_time_s for c in parsed.candles]
    for earlier, later in pairwise(times):
        if later - earlier != _INTERVAL_SECONDS:
            raise M3DValidationError(f"window {ordinal}: candles are not contiguous daily")
    fingerprint = domain_sha256(
        RAW_BUNDLE_DOMAIN,
        {
            "ordinal": ordinal,
            "raw_filename": raw_filename,
            "start_param": start_param,
            "end_param": end_param,
            "byte_length": len(raw_bytes),
            "raw_sha256": before,
            "row_count": len(rows),
            "first_open": rows[0][0],
            "last_open": rows[-1][0],
            "rows": rows,
        },
    )
    return ProspectiveRawBundle(
        ordinal=ordinal,
        raw_filename=raw_filename,
        start_param=start_param,
        end_param=end_param,
        byte_length=len(raw_bytes),
        raw_sha256=before,
        row_count=len(rows),
        first_open=rows[0][0],
        last_open=rows[-1][0],
        canonical_rows=rows,
        canonical_content_fingerprint=fingerprint,
    )


def build_raw_bundles(repo_root: str | Path, attempt_id: str) -> list[ProspectiveRawBundle]:
    """Deterministically rebuild every raw bundle for ``attempt_id`` from committed bytes.

    Reads the committed plan + receipt, verifies each retained raw file's SHA-256
    against the receipt, and transforms it into canonical OHLCV rows.
    """
    raw_dir = f"research/m3d/raw/coinbase/{attempt_id}"
    plan = load_prospective_acquisition_plan(Path(repo_root) / raw_dir / "acquisition_plan.json")
    receipt = load_prospective_attempt_receipt(
        Path(repo_root) / raw_dir / "acquisition_receipt.json"
    )
    if receipt.plan_sha256 != plan.plan_sha256:
        raise M3DValidationError("receipt plan hash does not match the committed plan")

    by_ordinal = {int(w["ordinal"]): w for w in plan.windows}
    # The receipt must cover exactly the plan windows — no unknown ordinal (which would
    # otherwise raise a bare KeyError, breaking the M3DValidationError contract) and no
    # missing window (a strict subset would rebuild a truncated cohort). This mirrors the
    # m3e runner boundary's full-coverage requirement (m3e.acquisition).
    receipt_ordinals = [int(r["ordinal"]) for r in receipt.responses]
    if len(set(receipt_ordinals)) != len(receipt_ordinals):
        raise M3DValidationError("receipt has duplicate window ordinals")
    if set(receipt_ordinals) != set(by_ordinal):
        raise M3DValidationError(
            "receipt windows do not exactly cover the plan windows "
            f"(receipt {sorted(set(receipt_ordinals))}, plan {sorted(by_ordinal)})"
        )
    bundles: list[ProspectiveRawBundle] = []
    for response in receipt.responses:
        ordinal = int(response["ordinal"])
        window = by_ordinal[ordinal]
        raw_name = require_str("raw_filename", response["raw_filename"])
        if raw_name != window["raw_filename"]:
            raise M3DValidationError(
                f"receipt raw filename does not match the plan for ordinal {ordinal}"
            )
        raw_bytes = up.read_bytes(repo_root, f"{raw_dir}/{raw_name}")
        if sha256_bytes(raw_bytes) != response["response_sha256"]:
            raise M3DValidationError(f"raw file {raw_name} SHA-256 does not match the receipt")
        if len(raw_bytes) != int(response["response_byte_length"]):
            raise M3DValidationError(
                f"raw file {raw_name} byte length {len(raw_bytes)} does not match the "
                f"receipt {int(response['response_byte_length'])}"
            )
        bundle = _bundle_from_raw(
            ordinal,
            raw_name,
            str(window["window_start"]),
            str(window["window_end"]),
            str(window["start_param"]),
            str(window["end_param"]),
            raw_bytes,
        )
        # Bind the delivered cohort to the pre-registered plan window: exactly the
        # planned number of buckets, and the last open must reach the final
        # completed bucket (window_end - 1 day). This rejects a truncated tail that
        # would otherwise pass as an internally-contiguous shorter cohort.
        expected = require_positive_int("expected_bucket_count", window["expected_bucket_count"])
        if bundle.row_count != expected:
            raise M3DValidationError(
                f"window {ordinal}: {bundle.row_count} rows does not equal the planned {expected}"
            )
        planned_last = pd.Timestamp(str(window["window_end"])) - pd.Timedelta(days=1)
        if pd.Timestamp(bundle.last_open) != planned_last:
            raise M3DValidationError(
                f"window {ordinal}: last open {bundle.last_open} does not reach the plan window end"
            )
        bundles.append(bundle)

    bundles.sort(key=lambda b: b.ordinal)
    _check_bundle_continuity(bundles)
    return bundles


def _check_bundle_continuity(bundles: list[ProspectiveRawBundle]) -> None:
    if not bundles:
        raise M3DValidationError("no raw bundles were produced")
    previous_last: int | None = None
    for bundle in bundles:
        first = int(pd.Timestamp(bundle.first_open).timestamp())
        if previous_last is not None and first - previous_last != _INTERVAL_SECONDS:
            raise M3DValidationError("raw bundles are not contiguous across windows")
        previous_last = int(pd.Timestamp(bundle.last_open).timestamp())


def combined_canonical_rows(bundles: list[ProspectiveRawBundle]) -> list[list[Any]]:
    """All canonical OHLCV rows across bundles, in chronological order."""
    rows: list[list[Any]] = []
    for bundle in bundles:
        rows.extend(bundle.canonical_rows)
    return rows


def cohort_canonical_fingerprint(bundles: list[ProspectiveRawBundle]) -> str:
    """Domain-separated fingerprint over the full ordered canonical cohort rows."""
    rows = combined_canonical_rows(bundles)
    return domain_sha256(
        "prospective_cohort_canonical",
        {
            "interval_seconds": _INTERVAL_SECONDS,
            "row_count": len(rows),
            "first_open": rows[0][0],
            "last_open": rows[-1][0],
            "rows": rows,
        },
    )
