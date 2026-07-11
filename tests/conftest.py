"""Shared fixtures for the test suite."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eth_research.data.builder import BuildResult, build_canonical_dataset
from eth_research.data.coinbase import (
    AcquisitionEvidence,
    ChunkRequest,
    derive_daily_ohlcv,
    write_acquisition_evidence,
)
from eth_research.data.provenance import DatasetIdentity, sha256_file
from eth_research.data.synthetic import make_synthetic_ohlcv


@pytest.fixture
def synthetic_daily() -> pd.DataFrame:
    """400 daily bars of deterministic synthetic ETH-like data."""
    return make_synthetic_ohlcv(n_periods=400, seed=7)


def _build_frame(opens: Sequence[float], closes: Sequence[float]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(closes), freq="1D", tz="UTC", name="timestamp")
    open_array = np.asarray(list(opens), dtype=float)
    close_array = np.asarray(list(closes), dtype=float)
    high = np.maximum(open_array, close_array) * 1.01
    low = np.minimum(open_array, close_array) * 0.99
    return pd.DataFrame(
        {
            "open": open_array,
            "high": high,
            "low": low,
            "close": close_array,
            "volume": np.full(len(close_array), 1_000.0),
        },
        index=index,
    )


@pytest.fixture
def frame_from_bars() -> Callable[[Sequence[tuple[float, float]]], pd.DataFrame]:
    """Factory for a valid OHLCV frame with exactly the given (open, close) bars.

    Lets tests hand-compute expected fills and equity from known prices,
    including overnight gaps (open != previous close).
    """

    def build(bars: Sequence[tuple[float, float]]) -> pd.DataFrame:
        return _build_frame([bar[0] for bar in bars], [bar[1] for bar in bars])

    return build


@pytest.fixture
def frame_from_closes() -> Callable[[Sequence[float]], pd.DataFrame]:
    """Factory for a gapless frame with the given closes (open = previous close)."""

    def build(closes: Sequence[float]) -> pd.DataFrame:
        opens = [closes[0], *closes[:-1]]
        return _build_frame(opens, closes)

    return build


@dataclass(frozen=True)
class CoinbasePipeline:
    """A synthetic end-to-end fixture: chunks -> derived CSV -> canonical dataset.

    Everything here is deterministic synthetic data explicitly labelled as
    such in the dataset identity's ``source``; it exists so the Milestone 2B
    provenance/evaluation chain can be exercised without any real market
    data.
    """

    chunk_dir: Path
    derived_csv: Path
    evidence: AcquisitionEvidence
    evidence_path: Path
    build: BuildResult
    identity: DatasetIdentity

    @property
    def manifest_sha256(self) -> str:
        return sha256_file(self.build.manifest_path)

    @property
    def evidence_sha256(self) -> str:
        return sha256_file(self.evidence_path)


def _synthetic_coinbase_rows(
    start: pd.Timestamp,
    days: int,
    *,
    first_row_index: int,
    price_shift_from_row: int | None,
) -> list[list[float | int]]:
    """Deterministic plausible daily candles in Coinbase field order (ascending)."""
    rows: list[list[float | int]] = []
    for i in range(days):
        row_index = first_row_index + i
        shift = (
            5.0 if price_shift_from_row is not None and row_index >= price_shift_from_row else 0.0
        )
        open_ = 100.0 + (row_index % 17) - (row_index % 5) + shift
        close = open_ + ((row_index % 3) - 1) * 2.0
        high = max(open_, close) + 1.5
        low = min(open_, close) - 1.25
        volume = 10.0 + (row_index % 7)
        time_s = int(start.as_unit("ns").value) // 10**9 + i * 86_400
        rows.append([time_s, low, high, open_, close, volume])
    return rows


def build_coinbase_pipeline(
    root: Path, *, price_shift_from_row: int | None = None
) -> CoinbasePipeline:
    """120 synthetic days frozen through the full acquisition -> M2A chain.

    ``price_shift_from_row`` shifts prices from that row position onward —
    used to build a dataset that differs from the default *only* in later
    rows (e.g. only inside the test segment) for invariance proofs.
    """
    root.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp("2024-01-01", tz="UTC")
    total_days = 120
    chunk_days = 60
    chunk_dir = root / "raw"
    chunk_dir.mkdir()
    requests: list[ChunkRequest] = []
    for position in range(0, total_days, chunk_days):
        window_start = start + pd.Timedelta(days=position)
        window_end = window_start + pd.Timedelta(days=chunk_days)
        rows = _synthetic_coinbase_rows(
            window_start,
            chunk_days,
            first_row_index=position,
            price_shift_from_row=price_shift_from_row,
        )
        path = chunk_dir / f"chunk_{position:03d}.json"
        path.write_bytes(json.dumps(rows).encode("ascii"))
        requests.append(
            ChunkRequest(
                path=path,
                window_start=window_start,
                window_end=window_end,
                requested_start=window_start.isoformat(),
                requested_end=(window_end - pd.Timedelta(days=1)).isoformat(),
                retrieved_at=pd.Timestamp("2026-07-11T12:00:00+00:00"),
            )
        )
    derived_csv = root / "synthetic-eth-usd-daily.csv"
    evidence = derive_daily_ohlcv(
        requests,
        overall_start=start,
        overall_end=start + pd.Timedelta(days=total_days),
        output_csv=derived_csv,
    )
    evidence_path = root / "acquisition_evidence.json"
    write_acquisition_evidence(evidence, evidence_path)
    identity = DatasetIdentity(
        quote_asset="USD",
        symbol="ETH-USD",
        venue="coinbase-exchange",
        interval=pd.Timedelta(days=1),
        source="synthetic fixture — deterministic fake candles, not real market data",
    )
    build = build_canonical_dataset(derived_csv, identity, root / "datasets")
    return CoinbasePipeline(
        chunk_dir=chunk_dir,
        derived_csv=derived_csv,
        evidence=evidence,
        evidence_path=evidence_path,
        build=build,
        identity=identity,
    )


@pytest.fixture
def coinbase_pipeline(tmp_path: Path) -> CoinbasePipeline:
    return build_coinbase_pipeline(tmp_path)
