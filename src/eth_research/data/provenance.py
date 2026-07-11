"""Dataset identity, manifest, and content fingerprinting.

A canonical dataset carries two complementary hashes:

* ``raw_file_sha256`` — SHA-256 of the exact source bytes that were parsed,
  tying the dataset to the file it was built from;
* ``content_fingerprint`` — SHA-256 over a canonical serialization of the
  validated candle values, independent of the container format: equivalent
  CSV and Parquet sources produce the same fingerprint.

The manifest also binds the audit evidence: the quality report's filename
and exact SHA-256, plus the two build flags (``assume_utc``,
``allow_extra_columns``) that shaped the audit and validation.

Fingerprint algorithm ``ohlcv-fp-v1/sha256``: the SHA-256 digest of the
header line ``b"eth-research ohlcv-fp-v1\\n"`` followed, for every candle in
chronological order, by one ASCII line::

    <open time, integer epoch nanoseconds>|<open>|<high>|<low>|<close>|<volume>\\n

where each float is rendered with ``float.hex()`` after normalizing negative
zero to zero — a bit-exact, locale-independent encoding of IEEE-754 doubles.

Manifests serialize deterministically (sorted keys, two-space indent,
trailing newline, no build timestamp), so rebuilding the same input yields
byte-identical manifest files. Validation is a single shared path: the
``DatasetManifest`` constructor validates every field, and strict JSON
parsing feeds it raw values without ever repairing types — a manifest that
constructs is a manifest that parses, and vice versa.
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
from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.schema import OHLCV_COLUMNS

MANIFEST_SCHEMA_VERSION: int = 1
FINGERPRINT_ALGORITHM: str = "ohlcv-fp-v1/sha256"
TIMESTAMP_CONVENTION: str = "candle open time, UTC"

_FINGERPRINT_HEADER: bytes = b"eth-research ohlcv-fp-v1\n"
_HASH_CHUNK_BYTES: int = 1 << 20
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
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
        "quality_report_filename",
        "quality_report_sha256",
        "assume_utc",
        "allow_extra_columns",
    }
)


def require_str(label: str, value: object) -> str:
    """The value must be exactly a JSON/Python string — no type repair."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string, got {type(value).__name__}")
    return value


def require_nonempty_str(label: str, value: object) -> str:
    text = require_str(label, value)
    if not text.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return text


def require_int(label: str, value: object) -> int:
    """The value must be an integer; bool is explicitly rejected."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer (bool is rejected), got {value!r}")
    return value


def require_bool(label: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean, got {type(value).__name__}")
    return value


def require_hex64(label: str, value: object) -> str:
    text = require_str(label, value)
    if not _HEX64_RE.match(text):
        raise ValueError(f"{label} must be exactly 64 lowercase hex characters, got {text!r}")
    return text


def require_safe_basename(label: str, value: object) -> str:
    """A bare file name: no separators, traversal, absolute paths, or NULs."""
    text = require_nonempty_str(label, value)
    if (
        "/" in text
        or "\\" in text
        or ".." in text
        or "\x00" in text
        or text != Path(text).name
        or Path(text).is_absolute()
    ):
        raise ValueError(f"{label} must be a safe file basename, got {text!r}")
    return text


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
            require_nonempty_str(label, getattr(self, label))
        if (
            not isinstance(self.interval, pd.Timedelta)
            or pd.isna(self.interval)
            or self.interval <= pd.Timedelta(0)
        ):
            raise ValueError(f"interval must be a positive Timedelta, got {self.interval!r}")

    @property
    def slug(self) -> str:
        """Filesystem-safe dataset name, e.g. ``kraken-ethusd-86400s``."""
        seconds = int(self.interval.total_seconds())
        raw = f"{self.venue}-{self.symbol}-{seconds}s".lower()
        return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")


@dataclass(frozen=True)
class DatasetManifest:
    """Versioned provenance record for one canonical dataset.

    Every field is validated in ``__post_init__`` — the single shared
    validation path for constructed and parsed manifests alike.
    """

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
    quality_report_filename: str
    quality_report_sha256: str
    assume_utc: bool
    allow_extra_columns: bool

    def __post_init__(self) -> None:
        version = require_int("manifest_schema_version", self.manifest_schema_version)
        if version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported manifest schema version {version!r}; "
                f"this package reads version {MANIFEST_SCHEMA_VERSION}"
            )
        require_nonempty_str("package_version", self.package_version)
        if self.base_asset != "ETH":
            raise ValueError(f"base_asset must be 'ETH', got {self.base_asset!r}")
        if self.market_type != "spot":
            raise ValueError(f"market_type must be 'spot', got {self.market_type!r}")
        if self.timestamp_convention != TIMESTAMP_CONVENTION:
            raise ValueError(
                f"timestamp_convention must be {TIMESTAMP_CONVENTION!r}, "
                f"got {self.timestamp_convention!r}"
            )
        for label in ("quote_asset", "symbol", "venue", "source"):
            require_nonempty_str(label, getattr(self, label))
        if (
            not isinstance(self.candle_interval, pd.Timedelta)
            or pd.isna(self.candle_interval)
            or self.candle_interval <= pd.Timedelta(0)
        ):
            raise ValueError(
                f"candle_interval must be a positive Timedelta, got {self.candle_interval!r}"
            )
        row_count = require_int("row_count", self.row_count)
        if row_count < 1:
            raise ValueError(f"row_count must be a positive integer, got {row_count}")
        for label, value in (
            ("first_open_time", self.first_open_time),
            ("last_open_time", self.last_open_time),
        ):
            if not isinstance(value, pd.Timestamp) or pd.isna(value):
                raise ValueError(f"{label} must be a valid timestamp, got {value!r}")
            if value.tz is None:
                raise ValueError(f"{label} must be timezone-aware")
        if self.first_open_time > self.last_open_time:
            raise ValueError(
                f"first_open_time {self.first_open_time} must not be after "
                f"last_open_time {self.last_open_time}"
            )
        expected_last = self.first_open_time + (row_count - 1) * self.candle_interval
        if self.last_open_time != expected_last:
            raise ValueError(
                "last_open_time is inconsistent with first_open_time + "
                f"(row_count - 1) * candle_interval: expected {expected_last}, "
                f"got {self.last_open_time}"
            )
        require_hex64("raw_file_sha256", self.raw_file_sha256)
        require_hex64("quality_report_sha256", self.quality_report_sha256)
        fingerprint = require_str("content_fingerprint", self.content_fingerprint)
        if not _FINGERPRINT_RE.match(fingerprint):
            raise ValueError(
                f"content_fingerprint must match sha256:<64 lowercase hex>, got {fingerprint!r}"
            )
        if self.fingerprint_algorithm != FINGERPRINT_ALGORITHM:
            raise ValueError(
                f"unsupported fingerprint algorithm {self.fingerprint_algorithm!r}; "
                f"this package computes {FINGERPRINT_ALGORITHM!r}"
            )
        require_safe_basename("raw_filename", self.raw_filename)
        require_safe_basename("canonical_filename", self.canonical_filename)
        require_safe_basename("quality_report_filename", self.quality_report_filename)
        require_bool("assume_utc", self.assume_utc)
        require_bool("allow_extra_columns", self.allow_extra_columns)

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
            "quality_report_filename": self.quality_report_filename,
            "quality_report_sha256": self.quality_report_sha256,
            "assume_utc": self.assume_utc,
            "allow_extra_columns": self.allow_extra_columns,
        }
        return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> DatasetManifest:
        """Strict parse feeding the shared constructor validation.

        JSON types are required exactly as serialized — nothing is repaired
        with ``str(...)`` or numeric coercion. Unknown keys, missing keys,
        and every invalid field are rejected.
        """
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"manifest is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("manifest JSON must be an object")

        keys = set(payload)
        if keys != _MANIFEST_KEYS:
            unknown = sorted(keys - _MANIFEST_KEYS)
            missing = sorted(_MANIFEST_KEYS - keys)
            raise ValueError(
                f"manifest keys do not match schema: unknown={unknown}, missing={missing}"
            )

        interval_text = require_str("candle_interval", payload["candle_interval"])
        try:
            interval = pd.Timedelta(interval_text)
        except ValueError as exc:
            raise ValueError(f"candle_interval is unparseable: {interval_text!r}") from exc

        timestamps: dict[str, pd.Timestamp] = {}
        for label in ("first_open_time", "last_open_time"):
            text = require_str(label, payload[label])
            try:
                timestamps[label] = pd.Timestamp(text)
            except ValueError as exc:
                raise ValueError(f"{label} is unparseable: {text!r}") from exc

        return cls(
            manifest_schema_version=payload["manifest_schema_version"],
            package_version=payload["package_version"],
            base_asset=payload["base_asset"],
            quote_asset=payload["quote_asset"],
            symbol=payload["symbol"],
            venue=payload["venue"],
            market_type=payload["market_type"],
            candle_interval=interval,
            timestamp_convention=payload["timestamp_convention"],
            source=payload["source"],
            raw_filename=payload["raw_filename"],
            raw_file_sha256=payload["raw_file_sha256"],
            fingerprint_algorithm=payload["fingerprint_algorithm"],
            content_fingerprint=payload["content_fingerprint"],
            row_count=payload["row_count"],
            first_open_time=timestamps["first_open_time"],
            last_open_time=timestamps["last_open_time"],
            canonical_filename=payload["canonical_filename"],
            quality_report_filename=payload["quality_report_filename"],
            quality_report_sha256=payload["quality_report_sha256"],
            assume_utc=payload["assume_utc"],
            allow_extra_columns=payload["allow_extra_columns"],
        )


def build_manifest(
    canonical: pd.DataFrame,
    identity: DatasetIdentity,
    *,
    raw_filename: str,
    raw_file_sha256: str,
    canonical_filename: str,
    quality_report_filename: str,
    quality_report_sha256: str,
    assume_utc: bool,
    allow_extra_columns: bool,
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
        quality_report_filename=quality_report_filename,
        quality_report_sha256=quality_report_sha256,
        assume_utc=assume_utc,
        allow_extra_columns=allow_extra_columns,
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


def sha256_bytes(data: bytes) -> str:
    """SHA-256 hex digest of an in-memory byte snapshot."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Streaming SHA-256 of a file's exact bytes (hex digest)."""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            hasher.update(chunk)
    return hasher.hexdigest()
