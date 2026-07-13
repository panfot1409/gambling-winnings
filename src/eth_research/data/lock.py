"""Tracked dataset lock: metadata and hashes only, never market rows.

A canonical dataset and its evidence live in the git-ignored ``data/``
tree; the lock is the compact, committable record that pins exactly which
dataset a benchmark ran on. It contains identity metadata and hashes only
— never candle values and never filesystem paths (verification takes the
local paths as arguments instead).

The lock chains the whole provenance stack together:

* ``content_fingerprint`` / ``manifest_sha256`` / ``quality_report_sha256``
  pin the canonical dataset and its audit evidence (Milestone 2A);
* ``raw_file_sha256`` pins the derived OHLCV file the dataset was built
  from, which must equal the acquisition evidence's ``derived_sha256``;
* ``acquisition_evidence_sha256`` pins the acquisition record itself.

``verify_dataset_lock`` re-hashes the local manifest and acquisition
evidence, strictly parses both, and cross-checks every shared field, so a
lock cannot silently describe a different dataset than the one on disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.coinbase import (
    AcquisitionError,
    AcquisitionEvidence,
    verify_acquisition_evidence,
)
from eth_research.data.provenance import (
    DatasetManifest,
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
    sha256_bytes,
)
from eth_research.data.validation import (
    parse_timestamp_field,
    require_aware_timestamp,
    require_fingerprint,
    require_positive_int,
)

LOCK_SCHEMA_VERSION: int = 1

_LOCK_KEYS: frozenset[str] = frozenset(
    {
        "lock_schema_version",
        "package_version",
        "base_asset",
        "quote_asset",
        "symbol",
        "venue",
        "market_type",
        "candle_interval",
        "content_fingerprint",
        "manifest_sha256",
        "quality_report_sha256",
        "raw_file_sha256",
        "acquisition_evidence_sha256",
        "row_count",
        "first_open_time",
        "last_open_time",
    }
)


class DatasetLockError(RuntimeError):
    """A dataset lock is invalid or disagrees with the artifacts it pins."""


@dataclass(frozen=True)
class DatasetLock:
    """Committable pin of one canonical dataset and its acquisition evidence.

    Every field is validated in ``__post_init__`` — the single shared
    validation path for constructed and parsed locks alike.
    """

    lock_schema_version: int
    package_version: str
    base_asset: str
    quote_asset: str
    symbol: str
    venue: str
    market_type: str
    candle_interval: pd.Timedelta
    content_fingerprint: str
    manifest_sha256: str
    quality_report_sha256: str
    raw_file_sha256: str
    acquisition_evidence_sha256: str
    row_count: int
    first_open_time: pd.Timestamp
    last_open_time: pd.Timestamp

    def __post_init__(self) -> None:
        version = require_int("lock_schema_version", self.lock_schema_version)
        if version != LOCK_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported lock schema version {version!r}; "
                f"this package reads version {LOCK_SCHEMA_VERSION}"
            )
        require_nonempty_str("package_version", self.package_version)
        if self.base_asset != "ETH":
            raise ValueError(f"base_asset must be 'ETH', got {self.base_asset!r}")
        if self.market_type != "spot":
            raise ValueError(f"market_type must be 'spot', got {self.market_type!r}")
        for label in ("quote_asset", "symbol", "venue"):
            require_nonempty_str(label, getattr(self, label))
        if (
            not isinstance(self.candle_interval, pd.Timedelta)
            or pd.isna(self.candle_interval)
            or self.candle_interval <= pd.Timedelta(0)
        ):
            raise ValueError(
                f"candle_interval must be a positive Timedelta, got {self.candle_interval!r}"
            )
        require_fingerprint("content_fingerprint", self.content_fingerprint)
        for label in (
            "manifest_sha256",
            "quality_report_sha256",
            "raw_file_sha256",
            "acquisition_evidence_sha256",
        ):
            require_hex64(label, getattr(self, label))
        row_count = require_positive_int("row_count", self.row_count)
        require_aware_timestamp("first_open_time", self.first_open_time)
        require_aware_timestamp("last_open_time", self.last_open_time)
        expected_last = self.first_open_time + (row_count - 1) * self.candle_interval
        if self.last_open_time != expected_last:
            raise ValueError(
                "last_open_time is inconsistent with first_open_time + "
                f"(row_count - 1) * candle_interval: expected {expected_last}, "
                f"got {self.last_open_time}"
            )

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "lock_schema_version": self.lock_schema_version,
            "package_version": self.package_version,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "symbol": self.symbol,
            "venue": self.venue,
            "market_type": self.market_type,
            "candle_interval": self.candle_interval.isoformat(),
            "content_fingerprint": self.content_fingerprint,
            "manifest_sha256": self.manifest_sha256,
            "quality_report_sha256": self.quality_report_sha256,
            "raw_file_sha256": self.raw_file_sha256,
            "acquisition_evidence_sha256": self.acquisition_evidence_sha256,
            "row_count": self.row_count,
            "first_open_time": self.first_open_time.isoformat(),
            "last_open_time": self.last_open_time.isoformat(),
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> DatasetLock:
        """Strict parse feeding the shared constructor validation."""
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"dataset lock is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("dataset lock JSON must be an object")
        keys = set(payload)
        if keys != _LOCK_KEYS:
            unknown = sorted(keys - _LOCK_KEYS)
            missing = sorted(_LOCK_KEYS - keys)
            raise ValueError(
                f"dataset lock keys do not match schema: unknown={unknown}, missing={missing}"
            )
        interval_text = require_str("candle_interval", payload["candle_interval"])
        try:
            interval = pd.Timedelta(interval_text)
        except ValueError as exc:
            raise ValueError(f"candle_interval is unparseable: {interval_text!r}") from exc
        return cls(
            lock_schema_version=payload["lock_schema_version"],
            package_version=payload["package_version"],
            base_asset=payload["base_asset"],
            quote_asset=payload["quote_asset"],
            symbol=payload["symbol"],
            venue=payload["venue"],
            market_type=payload["market_type"],
            candle_interval=interval,
            content_fingerprint=payload["content_fingerprint"],
            manifest_sha256=payload["manifest_sha256"],
            quality_report_sha256=payload["quality_report_sha256"],
            raw_file_sha256=payload["raw_file_sha256"],
            acquisition_evidence_sha256=payload["acquisition_evidence_sha256"],
            row_count=payload["row_count"],
            first_open_time=parse_timestamp_field("first_open_time", payload["first_open_time"]),
            last_open_time=parse_timestamp_field("last_open_time", payload["last_open_time"]),
        )


def build_dataset_lock(
    manifest: DatasetManifest,
    *,
    manifest_sha256: str,
    acquisition_evidence_sha256: str,
) -> DatasetLock:
    """Compose the lock for a built manifest plus its acquisition evidence."""
    return DatasetLock(
        lock_schema_version=LOCK_SCHEMA_VERSION,
        package_version=manifest.package_version,
        base_asset=manifest.base_asset,
        quote_asset=manifest.quote_asset,
        symbol=manifest.symbol,
        venue=manifest.venue,
        market_type=manifest.market_type,
        candle_interval=manifest.candle_interval,
        content_fingerprint=manifest.content_fingerprint,
        manifest_sha256=manifest_sha256,
        quality_report_sha256=manifest.quality_report_sha256,
        raw_file_sha256=manifest.raw_file_sha256,
        acquisition_evidence_sha256=acquisition_evidence_sha256,
        row_count=manifest.row_count,
        first_open_time=manifest.first_open_time,
        last_open_time=manifest.last_open_time,
    )


def load_dataset_lock(path: str | Path) -> DatasetLock:
    """Strictly parse a lock file."""
    try:
        return DatasetLock.from_json_bytes(Path(path).read_bytes())
    except ValueError as exc:
        raise DatasetLockError(f"invalid dataset lock {Path(path).name!r}: {exc}") from exc


def _require_match(label: str, lock_value: object, actual_value: object) -> None:
    if lock_value != actual_value:
        raise DatasetLockError(
            f"dataset lock mismatch on {label}: lock says {lock_value!r}, "
            f"artifacts say {actual_value!r}"
        )


def verify_dataset_lock(
    lock: DatasetLock,
    *,
    manifest_path: str | Path,
    acquisition_evidence_path: str | Path,
    raw_chunk_dir: str | Path | None = None,
    derived_csv: str | Path | None = None,
) -> tuple[DatasetManifest, AcquisitionEvidence]:
    """Re-hash and cross-check the lock against the local artifacts it pins.

    Verifies the manifest bytes, the acquisition-evidence bytes, every
    shared identity/hash/bound field, and the chain link between them
    (the manifest's raw file must be exactly the evidence's derived file).
    Returns the parsed manifest and evidence on success.

    Acquisition arguments are all-or-nothing: supplying **both**
    ``raw_chunk_dir`` and ``derived_csv`` additionally runs the full
    semantic acquisition verification — proving the derived CSV re-derives
    byte-for-byte from the raw chunks
    (:func:`eth_research.data.coinbase.verify_acquisition_evidence`).
    Supplying exactly one is a hard error, never a silent downgrade;
    supplying neither performs only the metadata/hash cross-check. The
    one-time evaluator always supplies both.
    """
    if (raw_chunk_dir is None) != (derived_csv is None):
        raise DatasetLockError(
            "raw_chunk_dir and derived_csv must be supplied together (or both omitted); "
            "supplying exactly one would silently skip semantic acquisition verification"
        )
    manifest_file = Path(manifest_path)
    if not manifest_file.exists():
        raise DatasetLockError(f"manifest {manifest_file} does not exist")
    manifest_bytes = manifest_file.read_bytes()
    _require_match("manifest_sha256", lock.manifest_sha256, sha256_bytes(manifest_bytes))
    try:
        manifest = DatasetManifest.from_json_bytes(manifest_bytes)
    except ValueError as exc:
        raise DatasetLockError(f"invalid manifest {manifest_file.name!r}: {exc}") from exc

    evidence_file = Path(acquisition_evidence_path)
    if not evidence_file.exists():
        raise DatasetLockError(f"acquisition evidence {evidence_file} does not exist")
    evidence_bytes = evidence_file.read_bytes()
    _require_match(
        "acquisition_evidence_sha256",
        lock.acquisition_evidence_sha256,
        sha256_bytes(evidence_bytes),
    )
    try:
        evidence = AcquisitionEvidence.from_json_bytes(evidence_bytes)
    except ValueError as exc:
        raise DatasetLockError(
            f"invalid acquisition evidence {evidence_file.name!r}: {exc}"
        ) from exc

    _require_match("package_version", lock.package_version, manifest.package_version)
    # Software-version chain: the acquisition evidence must report the same
    # version as the manifest and lock that pin it.
    _require_match("package_version (evidence)", evidence.package_version, manifest.package_version)
    _require_match("base_asset", lock.base_asset, manifest.base_asset)
    _require_match("quote_asset", lock.quote_asset, manifest.quote_asset)
    _require_match("symbol", lock.symbol, manifest.symbol)
    _require_match("venue", lock.venue, manifest.venue)
    _require_match("market_type", lock.market_type, manifest.market_type)
    _require_match("candle_interval", lock.candle_interval, manifest.candle_interval)
    _require_match("content_fingerprint", lock.content_fingerprint, manifest.content_fingerprint)
    _require_match(
        "quality_report_sha256", lock.quality_report_sha256, manifest.quality_report_sha256
    )
    _require_match("raw_file_sha256", lock.raw_file_sha256, manifest.raw_file_sha256)
    _require_match("row_count", lock.row_count, manifest.row_count)
    _require_match("first_open_time", lock.first_open_time, manifest.first_open_time)
    _require_match("last_open_time", lock.last_open_time, manifest.last_open_time)

    # Chain link: the manifest's raw input must be exactly the evidence's
    # derived output — same bytes, same name, same shape.
    _require_match(
        "derived sha256 (evidence vs manifest raw)",
        evidence.derived_sha256,
        manifest.raw_file_sha256,
    )
    _require_match(
        "derived filename (evidence vs manifest raw)",
        evidence.derived_filename,
        manifest.raw_filename,
    )
    _require_match("derived row count", evidence.derived_row_count, manifest.row_count)
    _require_match("first open time (evidence)", evidence.first_open_time, manifest.first_open_time)
    _require_match("last open time (evidence)", evidence.last_open_time, manifest.last_open_time)
    _require_match("venue (evidence)", evidence.venue, lock.venue)
    _require_match("product (evidence vs symbol)", evidence.product, lock.symbol)
    _require_match(
        "granularity (evidence vs interval seconds)",
        float(evidence.granularity_seconds),
        lock.candle_interval.total_seconds(),
    )

    if raw_chunk_dir is not None and derived_csv is not None:
        try:
            verify_acquisition_evidence(evidence, chunk_dir=raw_chunk_dir, derived_csv=derived_csv)
        except AcquisitionError as exc:
            raise DatasetLockError(f"semantic acquisition verification failed: {exc}") from exc

    return manifest, evidence
