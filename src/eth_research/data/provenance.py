"""Dataset identity, manifest, and content fingerprinting.

A canonical dataset carries two complementary hashes:

* ``raw_file_sha256`` — SHA-256 of the exact source file bytes, tying the
  dataset to the file it was built from;
* ``content_fingerprint`` — SHA-256 over a canonical serialization of the
  validated candle values, independent of the container format: equivalent
  CSV and Parquet sources produce the same fingerprint.

Fingerprint algorithm ``ohlcv-fp-v1/sha256``: the SHA-256 digest of the
header line ``b"eth-research ohlcv-fp-v1\\n"`` followed, for every candle in
chronological order, by one ASCII line::

    <open time, integer epoch nanoseconds>|<open>|<high>|<low>|<close>|<volume>\\n

where each float is rendered with ``float.hex()`` after normalizing negative
zero to zero — a bit-exact, locale-independent encoding of IEEE-754 doubles.

Manifests serialize deterministically (sorted keys, two-space indent,
trailing newline, no build timestamp), so rebuilding the same input yields
byte-identical manifest files. Parsing is strict: unknown or missing keys
and unsupported schema versions are rejected.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from eth_research import __version__
from eth_research.data.schema import OHLCV_COLUMNS

MANIFEST_SCHEMA_VERSION: int = 1
FINGERPRINT_ALGORITHM: str = "ohlcv-fp-v1/sha256"
TIMESTAMP_CONVENTION: str = "candle open time, UTC"

_FINGERPRINT_HEADER: bytes = b"eth-research ohlcv-fp-v1\n"
_HASH_CHUNK_BYTES: int = 1 << 20


@dataclass(frozen=True)
class DatasetIdentity:
    """What the candles claim to be. Milestone 2A scope: ETH spot only."""

    quote_asset: str
    symbol: str
    """The exact venue symbol, e.g. ``"ETHUSD"`` or ``"ETH/USD"``."""
    venue: str
    interval: pd.Timedelta
    """Candle interval; timestamps are candle open times in UTC."""
    source: str
    """Free-text description of where the raw file came from."""
    base_asset: str = "ETH"
    market_type: Literal["spot"] = "spot"

    def __post_init__(self) -> None:
        if self.base_asset != "ETH":
            raise ValueError(
                f"base_asset must be 'ETH' (this project studies ETH only), got {self.base_asset!r}"
            )
        if self.market_type != "spot":
            raise ValueError(f"market_type must be 'spot', got {self.market_type!r}")
        for label in ("quote_asset", "symbol", "venue", "source"):
            if not str(getattr(self, label)).strip():
                raise ValueError(f"{label} must be a non-empty string")
        if not isinstance(self.interval, pd.Timedelta) or self.interval <= pd.Timedelta(0):
            raise ValueError(f"interval must be a positive Timedelta, got {self.interval!r}")

    @property
    def slug(self) -> str:
        """Filesystem-safe dataset name, e.g. ``kraken-ethusd-86400s``."""
        seconds = int(self.interval.total_seconds())
        raw = f"{self.venue}-{self.symbol}-{seconds}s".lower()
        return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")


@dataclass(frozen=True)
class DatasetManifest:
    """Versioned provenance record for one canonical dataset."""

    manifest_schema_version: int
    package_version: str
    base_asset: str
    quote_asset: str
    symbol: str
    venue: str
    market_type: str
    candle_interval: pd.Timedelta
    timestamp_convention: str
    source: str
    raw_filename: str
    raw_file_sha256: str
    fingerprint_algorithm: str
    content_fingerprint: str
    row_count: int
    first_open_time: pd.Timestamp
    last_open_time: pd.Timestamp
    canonical_filename: str

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "manifest_schema_version": self.manifest_schema_version,
            "package_version": self.package_version,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "symbol": self.symbol,
            "venue": self.venue,
            "market_type": self.market_type,
            "candle_interval": self.candle_interval.isoformat(),
            "timestamp_convention": self.timestamp_convention,
            "source": self.source,
            "raw_filename": self.raw_filename,
            "raw_file_sha256": self.raw_file_sha256,
            "fingerprint_algorithm": self.fingerprint_algorithm,
            "content_fingerprint": self.content_fingerprint,
            "row_count": self.row_count,
            "first_open_time": self.first_open_time.isoformat(),
            "last_open_time": self.last_open_time.isoformat(),
            "canonical_filename": self.canonical_filename,
        }
        return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> DatasetManifest:
        """Strict parse: unknown/missing keys or a wrong schema version fail."""
        try:
            payload: Any = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"manifest is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("manifest JSON must be an object")

        expected_keys = {
            "manifest_schema_version",
            "package_version",
            "base_asset",
            "quote_asset",
            "symbol",
            "venue",
            "market_type",
            "candle_interval",
            "timestamp_convention",
            "source",
            "raw_filename",
            "raw_file_sha256",
            "fingerprint_algorithm",
            "content_fingerprint",
            "row_count",
            "first_open_time",
            "last_open_time",
            "canonical_filename",
        }
        keys = set(payload)
        if keys != expected_keys:
            unknown = sorted(keys - expected_keys)
            missing = sorted(expected_keys - keys)
            raise ValueError(
                f"manifest keys do not match schema: unknown={unknown}, missing={missing}"
            )

        version = payload["manifest_schema_version"]
        if version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported manifest schema version {version!r}; "
                f"this package reads version {MANIFEST_SCHEMA_VERSION}"
            )
        row_count = payload["row_count"]
        if not isinstance(row_count, int) or row_count < 1:
            raise ValueError(f"row_count must be a positive integer, got {row_count!r}")
        try:
            interval = pd.Timedelta(str(payload["candle_interval"]))
            first = pd.Timestamp(str(payload["first_open_time"]))
            last = pd.Timestamp(str(payload["last_open_time"]))
        except ValueError as exc:
            raise ValueError(f"manifest has unparseable interval or timestamps: {exc}") from exc
        if first.tz is None or last.tz is None:
            raise ValueError("manifest open times must be timezone-aware")

        return cls(
            manifest_schema_version=MANIFEST_SCHEMA_VERSION,
            package_version=str(payload["package_version"]),
            base_asset=str(payload["base_asset"]),
            quote_asset=str(payload["quote_asset"]),
            symbol=str(payload["symbol"]),
            venue=str(payload["venue"]),
            market_type=str(payload["market_type"]),
            candle_interval=interval,
            timestamp_convention=str(payload["timestamp_convention"]),
            source=str(payload["source"]),
            raw_filename=str(payload["raw_filename"]),
            raw_file_sha256=str(payload["raw_file_sha256"]),
            fingerprint_algorithm=str(payload["fingerprint_algorithm"]),
            content_fingerprint=str(payload["content_fingerprint"]),
            row_count=row_count,
            first_open_time=first.tz_convert("UTC"),
            last_open_time=last.tz_convert("UTC"),
            canonical_filename=str(payload["canonical_filename"]),
        )


def build_manifest(
    canonical: pd.DataFrame,
    identity: DatasetIdentity,
    *,
    raw_filename: str,
    raw_file_sha256: str,
    canonical_filename: str,
) -> DatasetManifest:
    """Compose the manifest for a validated canonical frame."""
    return DatasetManifest(
        manifest_schema_version=MANIFEST_SCHEMA_VERSION,
        package_version=__version__,
        base_asset=identity.base_asset,
        quote_asset=identity.quote_asset,
        symbol=identity.symbol,
        venue=identity.venue,
        market_type=identity.market_type,
        candle_interval=identity.interval,
        timestamp_convention=TIMESTAMP_CONVENTION,
        source=identity.source,
        raw_filename=raw_filename,
        raw_file_sha256=raw_file_sha256,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        content_fingerprint=content_fingerprint(canonical),
        row_count=len(canonical),
        first_open_time=canonical.index[0],
        last_open_time=canonical.index[-1],
        canonical_filename=canonical_filename,
    )


def content_fingerprint(canonical: pd.DataFrame) -> str:
    """``ohlcv-fp-v1/sha256`` fingerprint of a validated canonical frame.

    Bit-exact over the candle values and open times; independent of the
    container the data came from. Requires the canonical form produced by
    :func:`eth_research.data.schema.validate_ohlcv`.
    """
    index = canonical.index
    if not isinstance(index, pd.DatetimeIndex) or str(index.dtype) != "datetime64[ns, UTC]":
        raise ValueError("fingerprint requires a validated canonical frame (ns UTC index)")
    if tuple(canonical.columns) != OHLCV_COLUMNS:
        raise ValueError(f"fingerprint requires exactly the columns {OHLCV_COLUMNS}")
    if len(canonical) == 0:
        raise ValueError("fingerprint requires at least one candle")

    hasher = hashlib.sha256()
    hasher.update(_FINGERPRINT_HEADER)
    epoch_ns = index.astype("int64")
    columns = [canonical[column].to_numpy(dtype=float) for column in OHLCV_COLUMNS]
    for position in range(len(canonical)):
        values = "|".join((float(column[position]) + 0.0).hex() for column in columns)
        hasher.update(f"{int(epoch_ns[position])}|{values}\n".encode("ascii"))
    return "sha256:" + hasher.hexdigest()


def sha256_file(path: str | Path) -> str:
    """Streaming SHA-256 of a file's exact bytes (hex digest)."""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            hasher.update(chunk)
    return hasher.hexdigest()
