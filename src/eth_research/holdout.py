"""Durable identity of the one-time test holdout, and its conflict policy.

The one-time test evaluation is consumed **once and permanently**. What is
consumed is not a ``(dataset_lock, protocol)`` pair — those are mutable
metadata that a researcher under milestone pressure could change to launder
a fresh-looking access to the *same candles*. What is consumed is the
holdout *itself*: a specific instrument's specific test candles over a
specific window.

:class:`HoldoutIdentity` is a strict, immutable model of exactly that. Its
**test content fingerprint** is a domain-separated, integrity-only digest of
the validated test OHLCV bound to the instrument identity. Computing it may
read and hash the test candle values, but it must never generate a signal,
instantiate a test strategy, run the engine, compute a return, P&L, or
metric, plot, or otherwise expose a test value. The only permissible
pre-authorization test outputs are the opaque fingerprint, the row count,
the first/last timestamp, the interval, and the instrument identity.

:func:`find_holdout_conflicts` is the freshness gate: a proposed holdout is
rejected if any prior ledger event shares its holdout id, its dataset
content fingerprint, or its test content fingerprint, or if its test window
overlaps a prior one for the same instrument. Changing the protocol, the
lock, the package version, the schema, the evaluation id, the commit, the
runtime, or any wording therefore does **not** restore freshness, and a
grown or trimmed dataset cannot slip an overlapping test window past the
gate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from eth_research.data.builder import LoadedDataset
from eth_research.data.provenance import (
    DatasetIdentity,
    require_int,
    require_nonempty_str,
    require_str,
    sha256_bytes,
)
from eth_research.data.schema import OHLCV_COLUMNS
from eth_research.data.validation import (
    parse_timestamp_field,
    require_aware_timestamp,
    require_fingerprint,
    require_finite_float,
    require_positive_int,
)
from eth_research.ledger import LedgerEvent
from eth_research.protocol import (
    SPLIT_SEMANTICS,
    TRAIN_FRACTION,
    VALIDATION_FRACTION,
    BenchmarkProtocol,
)
from eth_research.splits import chronological_split

HOLDOUT_SCHEMA_VERSION: int = 1
HOLDOUT_FINGERPRINT_ALGORITHM: str = "holdout-fp-v1/sha256"
"""Domain-separated integrity digest of the validated test candles."""

_HOLDOUT_FP_HEADER: bytes = b"eth-research holdout-v1\n"

_HOLDOUT_KEYS: frozenset[str] = frozenset(
    {
        "holdout_schema_version",
        "base_asset",
        "quote_asset",
        "symbol",
        "venue",
        "market_type",
        "candle_interval",
        "dataset_content_fingerprint",
        "test_content_fingerprint",
        "test_first_open_time",
        "test_last_open_time",
        "test_row_count",
        "split_semantics",
        "train_fraction",
        "validation_fraction",
        "fingerprint_algorithm",
    }
)


def holdout_test_fingerprint(test_frame: pd.DataFrame, identity: DatasetIdentity) -> str:
    """``holdout-fp-v1/sha256`` digest of the validated test candles.

    An **integrity-only** operation: it reads and hashes the test OHLCV
    values but never runs a strategy or the engine. The digest binds the
    instrument identity (so the same numbers under a different claimed
    symbol produce a different fingerprint) and is domain-separated from the
    dataset content fingerprint, so the two can never be confused.
    """
    index = test_frame.index
    if not isinstance(index, pd.DatetimeIndex) or str(index.dtype) != "datetime64[ns, UTC]":
        raise ValueError("holdout fingerprint requires a validated canonical frame (ns UTC index)")
    if tuple(test_frame.columns) != OHLCV_COLUMNS:
        raise ValueError(f"holdout fingerprint requires exactly the columns {OHLCV_COLUMNS}")
    if len(test_frame) == 0:
        raise ValueError("holdout fingerprint requires at least one candle")

    hasher = hashlib.sha256()
    hasher.update(_HOLDOUT_FP_HEADER)
    identity_blob = json.dumps(
        {
            "base_asset": identity.base_asset,
            "quote_asset": identity.quote_asset,
            "symbol": identity.symbol,
            "venue": identity.venue,
            "market_type": identity.market_type,
            "interval_seconds": int(identity.interval.total_seconds()),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    hasher.update(identity_blob.encode("ascii") + b"\n")
    epoch_ns = index.astype("int64")
    columns = [test_frame[column].to_numpy(dtype=float) for column in OHLCV_COLUMNS]
    for position in range(len(test_frame)):
        values = "|".join((float(column[position]) + 0.0).hex() for column in columns)
        hasher.update(f"{int(epoch_ns[position])}|{values}\n".encode("ascii"))
    return "sha256:" + hasher.hexdigest()


@dataclass(frozen=True)
class HoldoutIdentity:
    """Strict, immutable identity of one one-time test holdout.

    Every field is validated in ``__post_init__`` — the single shared
    validation path for constructed and parsed identities alike. The
    non-dataset split fields are pinned to the frozen protocol's values in
    schema v1; a future split scheme bumps the schema version.
    """

    holdout_schema_version: int
    base_asset: str
    quote_asset: str
    symbol: str
    venue: str
    market_type: str
    candle_interval: pd.Timedelta
    dataset_content_fingerprint: str
    test_content_fingerprint: str
    test_first_open_time: pd.Timestamp
    test_last_open_time: pd.Timestamp
    test_row_count: int
    split_semantics: str
    train_fraction: float
    validation_fraction: float
    fingerprint_algorithm: str

    def __post_init__(self) -> None:
        version = require_int("holdout_schema_version", self.holdout_schema_version)
        if version != HOLDOUT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported holdout schema version {version!r}; "
                f"this package reads version {HOLDOUT_SCHEMA_VERSION}"
            )
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
        require_fingerprint("dataset_content_fingerprint", self.dataset_content_fingerprint)
        require_fingerprint("test_content_fingerprint", self.test_content_fingerprint)
        require_aware_timestamp("test_first_open_time", self.test_first_open_time)
        require_aware_timestamp("test_last_open_time", self.test_last_open_time)
        row_count = require_positive_int("test_row_count", self.test_row_count)
        if self.test_first_open_time > self.test_last_open_time:
            raise ValueError(
                f"test_first_open_time {self.test_first_open_time} must not be after "
                f"test_last_open_time {self.test_last_open_time}"
            )
        expected_last = self.test_first_open_time + (row_count - 1) * self.candle_interval
        if self.test_last_open_time != expected_last:
            raise ValueError(
                "test_last_open_time is inconsistent with test_first_open_time + "
                f"(test_row_count - 1) * candle_interval: expected {expected_last}, "
                f"got {self.test_last_open_time}"
            )
        if self.split_semantics != SPLIT_SEMANTICS:
            raise ValueError(
                f"split_semantics is pinned to {SPLIT_SEMANTICS!r} in schema v1, "
                f"got {self.split_semantics!r}"
            )
        train = require_finite_float("train_fraction", self.train_fraction)
        validation = require_finite_float("validation_fraction", self.validation_fraction)
        if train != TRAIN_FRACTION:
            raise ValueError(
                f"train_fraction is pinned to {TRAIN_FRACTION!r} in schema v1, got {train!r}"
            )
        if validation != VALIDATION_FRACTION:
            raise ValueError(
                f"validation_fraction is pinned to {VALIDATION_FRACTION!r} in schema v1, "
                f"got {validation!r}"
            )
        if self.fingerprint_algorithm != HOLDOUT_FINGERPRINT_ALGORITHM:
            raise ValueError(
                f"unsupported fingerprint algorithm {self.fingerprint_algorithm!r}; "
                f"this package computes {HOLDOUT_FINGERPRINT_ALGORITHM!r}"
            )

    @property
    def holdout_id(self) -> str:
        """Stable 64-hex identifier: SHA-256 of the canonical serialization."""
        return sha256_bytes(self.to_json_bytes())

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "holdout_schema_version": self.holdout_schema_version,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "symbol": self.symbol,
            "venue": self.venue,
            "market_type": self.market_type,
            "candle_interval": self.candle_interval.isoformat(),
            "dataset_content_fingerprint": self.dataset_content_fingerprint,
            "test_content_fingerprint": self.test_content_fingerprint,
            "test_first_open_time": self.test_first_open_time.isoformat(),
            "test_last_open_time": self.test_last_open_time.isoformat(),
            "test_row_count": self.test_row_count,
            "split_semantics": self.split_semantics,
            "train_fraction": self.train_fraction,
            "validation_fraction": self.validation_fraction,
            "fingerprint_algorithm": self.fingerprint_algorithm,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> HoldoutIdentity:
        """Strict parse feeding the shared constructor validation."""
        from eth_research._json import StrictJSONError, strict_json_loads

        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"holdout identity is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("holdout identity JSON must be an object")
        keys = set(payload)
        if keys != _HOLDOUT_KEYS:
            unknown = sorted(keys - _HOLDOUT_KEYS)
            missing = sorted(_HOLDOUT_KEYS - keys)
            raise ValueError(
                f"holdout identity keys do not match schema: unknown={unknown}, missing={missing}"
            )
        interval_text = require_str("candle_interval", payload["candle_interval"])
        try:
            interval = pd.Timedelta(interval_text)
        except ValueError as exc:
            raise ValueError(f"candle_interval is unparseable: {interval_text!r}") from exc
        return cls(
            holdout_schema_version=payload["holdout_schema_version"],
            base_asset=payload["base_asset"],
            quote_asset=payload["quote_asset"],
            symbol=payload["symbol"],
            venue=payload["venue"],
            market_type=payload["market_type"],
            candle_interval=interval,
            dataset_content_fingerprint=payload["dataset_content_fingerprint"],
            test_content_fingerprint=payload["test_content_fingerprint"],
            test_first_open_time=parse_timestamp_field(
                "test_first_open_time", payload["test_first_open_time"]
            ),
            test_last_open_time=parse_timestamp_field(
                "test_last_open_time", payload["test_last_open_time"]
            ),
            test_row_count=payload["test_row_count"],
            split_semantics=payload["split_semantics"],
            train_fraction=payload["train_fraction"],
            validation_fraction=payload["validation_fraction"],
            fingerprint_algorithm=payload["fingerprint_algorithm"],
        )


def build_holdout_identity(dataset: LoadedDataset, protocol: BenchmarkProtocol) -> HoldoutIdentity:
    """Derive the holdout identity from a verified dataset and protocol.

    Splits off the test segment mechanically and fingerprints it with the
    integrity-only :func:`holdout_test_fingerprint`. No strategy is
    instantiated, no backtest runs, and no test return or metric is
    computed — the only test-derived outputs are the opaque fingerprint,
    the row count, and the first/last timestamps.
    """
    splits = chronological_split(
        dataset.frame,
        train_fraction=protocol.train_fraction,
        validation_fraction=protocol.validation_fraction,
    )
    test = splits.test
    manifest = dataset.manifest
    identity = DatasetIdentity(
        quote_asset=manifest.quote_asset,
        symbol=manifest.symbol,
        venue=manifest.venue,
        interval=manifest.candle_interval,
        source=manifest.source,
        base_asset=manifest.base_asset,
        market_type=manifest.market_type,  # type: ignore[arg-type]
    )
    return HoldoutIdentity(
        holdout_schema_version=HOLDOUT_SCHEMA_VERSION,
        base_asset=manifest.base_asset,
        quote_asset=manifest.quote_asset,
        symbol=manifest.symbol,
        venue=manifest.venue,
        market_type=manifest.market_type,
        candle_interval=manifest.candle_interval,
        dataset_content_fingerprint=manifest.content_fingerprint,
        test_content_fingerprint=holdout_test_fingerprint(test, identity),
        test_first_open_time=test.index[0],
        test_last_open_time=test.index[-1],
        test_row_count=len(test),
        split_semantics=protocol.split_semantics,
        train_fraction=protocol.train_fraction,
        validation_fraction=protocol.validation_fraction,
        fingerprint_algorithm=HOLDOUT_FINGERPRINT_ALGORITHM,
    )


@dataclass(frozen=True)
class HoldoutConflict:
    """A prior ledger event that collides with a proposed holdout."""

    evaluation_id: str
    event: str
    reasons: tuple[str, ...]


def _windows_overlap(
    a_first: pd.Timestamp,
    a_last: pd.Timestamp,
    b_first: pd.Timestamp,
    b_last: pd.Timestamp,
) -> bool:
    """Two inclusive open-time ranges share at least one candle open."""
    return a_first <= b_last and b_first <= a_last


def find_holdout_conflicts(
    events: tuple[LedgerEvent, ...], proposed: HoldoutIdentity
) -> tuple[HoldoutConflict, ...]:
    """Every prior recorded access that consumes the proposed holdout.

    Any returned conflict — started, completed, or failed — means the
    one-time test evaluation of these candles has already been consumed.
    A holdout collides when a prior event shares its holdout id, its
    dataset content fingerprint, or its test content fingerprint, or when
    its test open-time window overlaps the proposed one for the *same
    instrument* (symbol, venue, and interval). The temporal check catches
    an overlapping or containing test window even when a grown or trimmed
    dataset changes both content fingerprints. None of these signals change
    when the protocol, lock, package version, schema, evaluation id,
    commit, runtime, or wording changes, so none of those edits can restore
    freshness.
    """
    conflicts: list[HoldoutConflict] = []
    for event in events:
        reasons: list[str] = []
        if event.holdout_id == proposed.holdout_id:
            reasons.append("same holdout identity")
        if event.dataset_content_fingerprint == proposed.dataset_content_fingerprint:
            reasons.append("same dataset content fingerprint")
        if event.test_content_fingerprint == proposed.test_content_fingerprint:
            reasons.append("same test content fingerprint")
        if (
            event.symbol == proposed.symbol
            and event.venue == proposed.venue
            and event.candle_interval == proposed.candle_interval
            and _windows_overlap(
                event.test_first_open_time,
                event.test_last_open_time,
                proposed.test_first_open_time,
                proposed.test_last_open_time,
            )
        ):
            reasons.append("overlapping test window for the same instrument")
        if reasons:
            conflicts.append(
                HoldoutConflict(
                    evaluation_id=event.evaluation_id,
                    event=event.event,
                    reasons=tuple(reasons),
                )
            )
    return tuple(conflicts)
