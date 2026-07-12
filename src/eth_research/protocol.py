"""Frozen benchmark protocol and deterministic result models.

Protocol schema version 1 **is** the frozen Milestone 2B protocol: every
non-dataset choice — split fractions and semantics, the two strategies and
their exact parameters, costs, context bars, accounting, metrics, and
annualization — is pinned by the validator to a single allowed value. The
JSON file exists to bind those pinned choices to one exact dataset
(content fingerprint, manifest hash, dataset-lock hash, and
acquisition-evidence hash) *before* any strategy touches the test
segment; there is deliberately nothing to tune.

Result models are equally strict: every number must be finite (genuinely
undefined Sharpe/Sortino are ``None`` and serialize as JSON ``null``,
never NaN or Infinity), segment rows must agree with the declared split
boundaries, and serialization is deterministic (sorted keys, two-space
indent, trailing newline, ``allow_nan=False``) so identical results are
byte-identical.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research import __version__
from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.lock import DatasetLock
from eth_research.data.provenance import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
    sha256_bytes,
)
from eth_research.data.validation import (
    parse_timestamp_field,
    require_aware_timestamp,
    require_commit_sha,
    require_evaluation_id,
    require_fingerprint,
    require_finite_float,
    require_nonnegative_int,
    require_positive_int,
)
from eth_research.metrics import SECONDS_PER_YEAR

PROTOCOL_SCHEMA_VERSION: int = 1
RESULTS_SCHEMA_VERSION: int = 2

TRAIN_FRACTION: float = 0.6
VALIDATION_FRACTION: float = 0.2
SPLIT_SEMANTICS: str = "positional-floor-v1"
"""``chronological_split`` boundaries: ``int(n * fraction)`` row positions."""

INITIAL_CASH: float = 10_000.0
FEE_RATE: float = 0.001
"""10 basis points of fill notional per fill."""
SLIPPAGE_RATE: float = 0.0005
"""5 basis points of directional slippage per fill."""
SMA_CONTEXT_BARS: int = 50
BUY_AND_HOLD_CONTEXT_BARS: int = 0
ACCOUNTING: str = "independent-segments-v1"
"""Each segment starts with the same initial cash and pays its own entry
costs; segment equity curves are never stitched together."""
ANNUALIZATION: str = "365.25-day-year-from-interval"
RISK_FREE_RATE: float = 0.0

BUY_AND_HOLD_STRATEGY: str = "buy_and_hold"
SMA_STRATEGY: str = "moving_average_crossover"
SMA_FAST_WINDOW: int = 20
SMA_SLOW_WINDOW: int = 50

REQUIRED_METRICS: tuple[str, ...] = (
    "total_return",
    "cagr",
    "sharpe",
    "sortino",
    "max_drawdown",
    "total_traded_notional",
    "turnover",
    "num_fills",
    "terminal_equity",
    "terminal_liquidation_equity",
)

SEGMENT_NAMES: tuple[str, ...] = ("train", "validation", "test")
RESULT_STRATEGY_NAMES: tuple[str, ...] = ("buy_and_hold", "sma_20_50")
"""Engine-reported strategy names, in canonical result order."""

_PROTOCOL_KEYS: frozenset[str] = frozenset(
    {
        "protocol_schema_version",
        "package_version",
        "dataset_content_fingerprint",
        "dataset_manifest_sha256",
        "dataset_lock_sha256",
        "acquisition_evidence_sha256",
        "train_fraction",
        "validation_fraction",
        "split_semantics",
        "strategies",
        "initial_cash",
        "fee_rate",
        "slippage_rate",
        "sma_context_bars",
        "buy_and_hold_context_bars",
        "accounting",
        "metrics",
        "annualization",
        "risk_free_rate",
    }
)

_BUY_AND_HOLD_SPEC_KEYS: frozenset[str] = frozenset({"name"})
_SMA_SPEC_KEYS: frozenset[str] = frozenset({"name", "fast_window", "slow_window"})

_SEGMENT_KEYS: frozenset[str] = frozenset(
    {
        "strategy",
        "segment",
        "n_bars",
        "start_time",
        "end_time",
        "context_bars",
        "initial_cash",
        "terminal_equity",
        "terminal_liquidation_equity",
        "total_return",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "total_traded_notional",
        "turnover",
        "num_fills",
    }
)

_SPLIT_KEYS: frozenset[str] = frozenset({"segment", "first_open_time", "last_open_time", "n_bars"})

_WARNING_KEYS: frozenset[str] = frozenset({"code", "count", "first_examples"})

_RESULTS_KEYS: frozenset[str] = frozenset(
    {
        "results_schema_version",
        "package_version",
        "base_asset",
        "quote_asset",
        "symbol",
        "venue",
        "market_type",
        "candle_interval",
        "dataset_content_fingerprint",
        "dataset_manifest_sha256",
        "dataset_lock_sha256",
        "quality_report_sha256",
        "acquisition_evidence_sha256",
        "protocol_sha256",
        "protocol_registration_commit_sha",
        "authorized_evaluation_code_commit_sha",
        "dataset_row_count",
        "dataset_first_open_time",
        "dataset_last_open_time",
        "quality_warnings",
        "splits",
        "segments",
        "accounting",
        "test_evaluation_id",
    }
)


class ProtocolError(RuntimeError):
    """A protocol or result record is invalid or disagrees with its dataset."""


def _loads_strict(raw: bytes, what: str) -> Any:
    try:
        return strict_json_loads(raw)
    except StrictJSONError as exc:
        raise ValueError(f"{what} is not valid JSON: {exc}") from exc


def _require_exact_float(label: str, value: object, expected: float) -> float:
    number = require_finite_float(label, value)
    if number != expected:
        raise ValueError(f"{label} is pinned to {expected!r} in schema v1, got {number!r}")
    return number


def _require_exact_int(label: str, value: object, expected: int) -> int:
    number = require_int(label, value)
    if number != expected:
        raise ValueError(f"{label} is pinned to {expected!r} in schema v1, got {number!r}")
    return number


def _require_exact_str(label: str, value: object, expected: str) -> str:
    text = require_str(label, value)
    if text != expected:
        raise ValueError(f"{label} is pinned to {expected!r} in schema v1, got {text!r}")
    return text


@dataclass(frozen=True)
class StrategySpec:
    """One pinned strategy entry; schema v1 allows exactly two shapes."""

    name: str
    fast_window: int | None = None
    slow_window: int | None = None

    def __post_init__(self) -> None:
        name = require_str("strategy name", self.name)
        if name == BUY_AND_HOLD_STRATEGY:
            if self.fast_window is not None or self.slow_window is not None:
                raise ValueError("buy_and_hold takes no parameters")
        elif name == SMA_STRATEGY:
            _require_exact_int("fast_window", self.fast_window, SMA_FAST_WINDOW)
            _require_exact_int("slow_window", self.slow_window, SMA_SLOW_WINDOW)
        else:
            raise ValueError(
                f"unsupported strategy {name!r}; schema v1 allows exactly "
                f"{BUY_AND_HOLD_STRATEGY!r} and {SMA_STRATEGY!r}"
            )

    def to_json_dict(self) -> dict[str, Any]:
        if self.name == BUY_AND_HOLD_STRATEGY:
            return {"name": self.name}
        return {"name": self.name, "fast_window": self.fast_window, "slow_window": self.slow_window}

    @classmethod
    def from_json_dict(cls, payload: object) -> StrategySpec:
        if not isinstance(payload, dict):
            raise ValueError(f"strategy entry must be an object, got {type(payload).__name__}")
        name = require_str("strategy name", payload.get("name"))
        keys = set(payload)
        if name == BUY_AND_HOLD_STRATEGY:
            expected_keys = _BUY_AND_HOLD_SPEC_KEYS
        elif name == SMA_STRATEGY:
            expected_keys = _SMA_SPEC_KEYS
        else:
            raise ValueError(
                f"unsupported strategy {name!r}; schema v1 allows exactly "
                f"{BUY_AND_HOLD_STRATEGY!r} and {SMA_STRATEGY!r}"
            )
        if keys != expected_keys:
            unknown = sorted(keys - expected_keys)
            missing = sorted(expected_keys - keys)
            raise ValueError(
                f"strategy {name!r} keys do not match schema: unknown={unknown}, missing={missing}"
            )
        if name == BUY_AND_HOLD_STRATEGY:
            return cls(name=name)
        return cls(
            name=name, fast_window=payload["fast_window"], slow_window=payload["slow_window"]
        )


PINNED_STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec(name=BUY_AND_HOLD_STRATEGY),
    StrategySpec(name=SMA_STRATEGY, fast_window=SMA_FAST_WINDOW, slow_window=SMA_SLOW_WINDOW),
)


@dataclass(frozen=True)
class BenchmarkProtocol:
    """The pre-registered benchmark: pinned choices bound to one dataset.

    Every field is validated in ``__post_init__`` — the single shared
    validation path for constructed and parsed protocols alike. All
    non-dataset fields must equal the module constants exactly.
    """

    protocol_schema_version: int
    package_version: str
    dataset_content_fingerprint: str
    dataset_manifest_sha256: str
    dataset_lock_sha256: str
    acquisition_evidence_sha256: str
    train_fraction: float
    validation_fraction: float
    split_semantics: str
    strategies: tuple[StrategySpec, ...]
    initial_cash: float
    fee_rate: float
    slippage_rate: float
    sma_context_bars: int
    buy_and_hold_context_bars: int
    accounting: str
    metrics: tuple[str, ...]
    annualization: str
    risk_free_rate: float

    def __post_init__(self) -> None:
        version = require_int("protocol_schema_version", self.protocol_schema_version)
        if version != PROTOCOL_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported protocol schema version {version!r}; "
                f"this package reads version {PROTOCOL_SCHEMA_VERSION}"
            )
        require_nonempty_str("package_version", self.package_version)
        require_fingerprint("dataset_content_fingerprint", self.dataset_content_fingerprint)
        require_hex64("dataset_manifest_sha256", self.dataset_manifest_sha256)
        require_hex64("dataset_lock_sha256", self.dataset_lock_sha256)
        require_hex64("acquisition_evidence_sha256", self.acquisition_evidence_sha256)
        _require_exact_float("train_fraction", self.train_fraction, TRAIN_FRACTION)
        _require_exact_float("validation_fraction", self.validation_fraction, VALIDATION_FRACTION)
        _require_exact_str("split_semantics", self.split_semantics, SPLIT_SEMANTICS)
        if not isinstance(self.strategies, tuple) or self.strategies != PINNED_STRATEGIES:
            raise ValueError(
                "strategies are pinned in schema v1 to exactly buy_and_hold and "
                f"moving_average_crossover({SMA_FAST_WINDOW}, {SMA_SLOW_WINDOW}), in that order — "
                "no alternatives, duplicates, reordering, or parameter changes"
            )
        _require_exact_float("initial_cash", self.initial_cash, INITIAL_CASH)
        _require_exact_float("fee_rate", self.fee_rate, FEE_RATE)
        _require_exact_float("slippage_rate", self.slippage_rate, SLIPPAGE_RATE)
        _require_exact_int("sma_context_bars", self.sma_context_bars, SMA_CONTEXT_BARS)
        _require_exact_int(
            "buy_and_hold_context_bars",
            self.buy_and_hold_context_bars,
            BUY_AND_HOLD_CONTEXT_BARS,
        )
        _require_exact_str("accounting", self.accounting, ACCOUNTING)
        if not isinstance(self.metrics, tuple) or self.metrics != REQUIRED_METRICS:
            raise ValueError(
                "metrics are pinned in schema v1 to exactly the required metric list, in order"
            )
        _require_exact_str("annualization", self.annualization, ANNUALIZATION)
        _require_exact_float("risk_free_rate", self.risk_free_rate, RISK_FREE_RATE)

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "protocol_schema_version": self.protocol_schema_version,
            "package_version": self.package_version,
            "dataset_content_fingerprint": self.dataset_content_fingerprint,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "dataset_lock_sha256": self.dataset_lock_sha256,
            "acquisition_evidence_sha256": self.acquisition_evidence_sha256,
            "train_fraction": self.train_fraction,
            "validation_fraction": self.validation_fraction,
            "split_semantics": self.split_semantics,
            "strategies": [spec.to_json_dict() for spec in self.strategies],
            "initial_cash": self.initial_cash,
            "fee_rate": self.fee_rate,
            "slippage_rate": self.slippage_rate,
            "sma_context_bars": self.sma_context_bars,
            "buy_and_hold_context_bars": self.buy_and_hold_context_bars,
            "accounting": self.accounting,
            "metrics": list(self.metrics),
            "annualization": self.annualization,
            "risk_free_rate": self.risk_free_rate,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> BenchmarkProtocol:
        """Strict parse feeding the shared constructor validation."""
        payload = _loads_strict(raw, "benchmark protocol")
        if not isinstance(payload, dict):
            raise ValueError("benchmark protocol JSON must be an object")
        keys = set(payload)
        if keys != _PROTOCOL_KEYS:
            unknown = sorted(keys - _PROTOCOL_KEYS)
            missing = sorted(_PROTOCOL_KEYS - keys)
            raise ValueError(
                f"benchmark protocol keys do not match schema: unknown={unknown}, missing={missing}"
            )
        strategies = payload["strategies"]
        if not isinstance(strategies, list):
            raise ValueError("strategies must be an array")
        metrics = payload["metrics"]
        if not isinstance(metrics, list) or not all(isinstance(item, str) for item in metrics):
            raise ValueError("metrics must be an array of strings")
        return cls(
            protocol_schema_version=payload["protocol_schema_version"],
            package_version=payload["package_version"],
            dataset_content_fingerprint=payload["dataset_content_fingerprint"],
            dataset_manifest_sha256=payload["dataset_manifest_sha256"],
            dataset_lock_sha256=payload["dataset_lock_sha256"],
            acquisition_evidence_sha256=payload["acquisition_evidence_sha256"],
            train_fraction=payload["train_fraction"],
            validation_fraction=payload["validation_fraction"],
            split_semantics=payload["split_semantics"],
            strategies=tuple(StrategySpec.from_json_dict(entry) for entry in strategies),
            initial_cash=payload["initial_cash"],
            fee_rate=payload["fee_rate"],
            slippage_rate=payload["slippage_rate"],
            sma_context_bars=payload["sma_context_bars"],
            buy_and_hold_context_bars=payload["buy_and_hold_context_bars"],
            accounting=payload["accounting"],
            metrics=tuple(metrics),
            annualization=payload["annualization"],
            risk_free_rate=payload["risk_free_rate"],
        )


def build_benchmark_protocol(lock: DatasetLock, *, package_version: str) -> BenchmarkProtocol:
    """Compose the pinned protocol bound to one dataset lock."""
    return BenchmarkProtocol(
        protocol_schema_version=PROTOCOL_SCHEMA_VERSION,
        package_version=package_version,
        dataset_content_fingerprint=lock.content_fingerprint,
        dataset_manifest_sha256=lock.manifest_sha256,
        dataset_lock_sha256=sha256_bytes(lock.to_json_bytes()),
        acquisition_evidence_sha256=lock.acquisition_evidence_sha256,
        train_fraction=TRAIN_FRACTION,
        validation_fraction=VALIDATION_FRACTION,
        split_semantics=SPLIT_SEMANTICS,
        strategies=PINNED_STRATEGIES,
        initial_cash=INITIAL_CASH,
        fee_rate=FEE_RATE,
        slippage_rate=SLIPPAGE_RATE,
        sma_context_bars=SMA_CONTEXT_BARS,
        buy_and_hold_context_bars=BUY_AND_HOLD_CONTEXT_BARS,
        accounting=ACCOUNTING,
        metrics=REQUIRED_METRICS,
        annualization=ANNUALIZATION,
        risk_free_rate=RISK_FREE_RATE,
    )


def verify_protocol(protocol: BenchmarkProtocol, lock: DatasetLock) -> None:
    """The protocol must pin exactly this dataset lock and its artifacts.

    For the frozen Milestone 2B protocol the software-version chain is
    validated too: the protocol, the dataset lock, and the running package
    must all report the same version.
    """
    if protocol.package_version != lock.package_version:
        raise ProtocolError(
            f"protocol/dataset-lock package version mismatch: protocol says "
            f"{protocol.package_version!r}, lock says {lock.package_version!r}"
        )
    if protocol.package_version != __version__:
        raise ProtocolError(
            f"protocol package version {protocol.package_version!r} is not the running "
            f"package version {__version__!r}; the frozen 2B protocol must be run by the "
            "version that pre-registered it"
        )
    checks: list[tuple[str, str, str]] = [
        (
            "dataset_content_fingerprint",
            protocol.dataset_content_fingerprint,
            lock.content_fingerprint,
        ),
        ("dataset_manifest_sha256", protocol.dataset_manifest_sha256, lock.manifest_sha256),
        ("dataset_lock_sha256", protocol.dataset_lock_sha256, sha256_bytes(lock.to_json_bytes())),
        (
            "acquisition_evidence_sha256",
            protocol.acquisition_evidence_sha256,
            lock.acquisition_evidence_sha256,
        ),
    ]
    for label, protocol_value, lock_value in checks:
        if protocol_value != lock_value:
            raise ProtocolError(
                f"protocol/dataset-lock mismatch on {label}: protocol says {protocol_value!r}, "
                f"lock says {lock_value!r}"
            )


def load_benchmark_protocol(path: str | Path) -> BenchmarkProtocol:
    """Strictly parse a protocol file."""
    file = Path(path)
    try:
        return BenchmarkProtocol.from_json_bytes(file.read_bytes())
    except ValueError as exc:
        raise ProtocolError(f"invalid benchmark protocol {file.name!r}: {exc}") from exc


def _optional_finite_float(label: str, value: object) -> float | None:
    if value is None:
        return None
    return require_finite_float(label, value)


@dataclass(frozen=True)
class SegmentMetrics:
    """The pinned metric set for one strategy on one segment."""

    strategy: str
    segment: str
    n_bars: int
    start_time: pd.Timestamp
    """Open time of the first evaluated bar (capital committed here)."""
    end_time: pd.Timestamp
    """Close time of the last evaluated bar: last open + interval."""
    context_bars: int
    initial_cash: float
    terminal_equity: float
    terminal_liquidation_equity: float
    total_return: float
    cagr: float
    sharpe: float | None
    """``None`` when genuinely undefined (zero volatility); JSON ``null``."""
    sortino: float | None
    """``None`` when genuinely undefined (no downside); JSON ``null``."""
    max_drawdown: float
    total_traded_notional: float
    turnover: float
    num_fills: int

    def __post_init__(self) -> None:
        strategy = require_str("strategy", self.strategy)
        if strategy not in RESULT_STRATEGY_NAMES:
            raise ValueError(f"strategy must be one of {RESULT_STRATEGY_NAMES}, got {strategy!r}")
        segment = require_str("segment", self.segment)
        if segment not in SEGMENT_NAMES:
            raise ValueError(f"segment must be one of {SEGMENT_NAMES}, got {segment!r}")
        require_positive_int("n_bars", self.n_bars)
        require_aware_timestamp("start_time", self.start_time)
        require_aware_timestamp("end_time", self.end_time)
        if self.start_time >= self.end_time:
            raise ValueError(f"start_time {self.start_time} must precede end_time {self.end_time}")
        context = require_nonnegative_int("context_bars", self.context_bars)
        if strategy == "buy_and_hold":
            expected_context = BUY_AND_HOLD_CONTEXT_BARS
        else:
            expected_context = 0 if segment == "train" else SMA_CONTEXT_BARS
        if context != expected_context:
            raise ValueError(
                f"context_bars for {strategy!r} on {segment!r} is pinned to "
                f"{expected_context}, got {context}"
            )
        _require_exact_float("initial_cash", self.initial_cash, INITIAL_CASH)
        for label in ("terminal_equity", "terminal_liquidation_equity"):
            value = require_finite_float(label, getattr(self, label))
            if value <= 0:
                raise ValueError(f"{label} must be positive, got {value!r}")
        # Liquidating (sell at the last close with slippage + fee) can never
        # exceed marking to market; equality holds only for a flat/cash
        # terminal position. The exact value needs the equity/fill path, so
        # only this stable bound is enforceable from the serialized scalars.
        if self.terminal_liquidation_equity > self.terminal_equity:
            raise ValueError(
                f"terminal_liquidation_equity {self.terminal_liquidation_equity!r} must not "
                f"exceed terminal_equity {self.terminal_equity!r}"
            )
        total_return = require_finite_float("total_return", self.total_return)
        cagr = require_finite_float("cagr", self.cagr)
        _optional_finite_float("sharpe", self.sharpe)
        _optional_finite_float("sortino", self.sortino)
        drawdown = require_finite_float("max_drawdown", self.max_drawdown)
        if not -1.0 <= drawdown <= 0.0:
            raise ValueError(f"max_drawdown must be in [-1, 0], got {drawdown!r}")
        notional = require_finite_float("total_traded_notional", self.total_traded_notional)
        turnover = require_finite_float("turnover", self.turnover)
        for label, value in (("total_traded_notional", notional), ("turnover", turnover)):
            if value < 0:
                raise ValueError(f"{label} must be >= 0, got {value!r}")
        num_fills = require_nonnegative_int("num_fills", self.num_fills)

        # Identities reconstructable from the serialized scalars alone.
        expected_return = self.terminal_equity / self.initial_cash - 1.0
        if total_return != expected_return:
            raise ValueError(
                f"total_return {total_return!r} does not equal terminal_equity / initial_cash "
                f"- 1 ({expected_return!r})"
            )
        if total_return <= -1.0:
            raise ValueError(f"total_return must be > -1 for positive equity, got {total_return!r}")
        expected_turnover = notional / self.initial_cash
        if turnover != expected_turnover:
            raise ValueError(
                f"turnover {turnover!r} does not equal total_traded_notional / initial_cash "
                f"({expected_turnover!r})"
            )
        if cagr <= -1.0:
            raise ValueError(f"cagr must be > -1, got {cagr!r}")
        years = (self.end_time - self.start_time).total_seconds() / SECONDS_PER_YEAR
        expected_cagr = (self.terminal_equity / self.initial_cash) ** (1.0 / years) - 1.0
        if not math.isclose(cagr, expected_cagr, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(
                f"cagr {cagr!r} is inconsistent with total return over the segment duration "
                f"(expected ~{expected_cagr!r})"
            )

        # Fill / notional coherence: num_fills == 0 if and only if traded
        # notional == 0 (and, via the turnover identity, turnover == 0).
        if num_fills == 0:
            if notional != 0.0 or turnover != 0.0:
                raise ValueError("zero fills must imply zero traded notional and zero turnover")
        elif notional <= 0.0 or turnover <= 0.0:
            raise ValueError(
                f"num_fills {num_fills} > 0 requires strictly positive traded notional and "
                f"turnover, got notional {notional!r}, turnover {turnover!r}"
            )
        if strategy == "buy_and_hold" and num_fills != 1:
            raise ValueError(
                f"buy_and_hold enters once at the first open, so num_fills must be 1, "
                f"got {num_fills}"
            )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "segment": self.segment,
            "n_bars": self.n_bars,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "context_bars": self.context_bars,
            "initial_cash": self.initial_cash,
            "terminal_equity": self.terminal_equity,
            "terminal_liquidation_equity": self.terminal_liquidation_equity,
            "total_return": self.total_return,
            "cagr": self.cagr,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "max_drawdown": self.max_drawdown,
            "total_traded_notional": self.total_traded_notional,
            "turnover": self.turnover,
            "num_fills": self.num_fills,
        }

    @classmethod
    def from_json_dict(cls, payload: object) -> SegmentMetrics:
        if not isinstance(payload, dict):
            raise ValueError(f"segment entry must be an object, got {type(payload).__name__}")
        keys = set(payload)
        if keys != _SEGMENT_KEYS:
            unknown = sorted(keys - _SEGMENT_KEYS)
            missing = sorted(_SEGMENT_KEYS - keys)
            raise ValueError(
                f"segment keys do not match schema: unknown={unknown}, missing={missing}"
            )
        return cls(
            strategy=payload["strategy"],
            segment=payload["segment"],
            n_bars=payload["n_bars"],
            start_time=parse_timestamp_field("start_time", payload["start_time"]),
            end_time=parse_timestamp_field("end_time", payload["end_time"]),
            context_bars=payload["context_bars"],
            initial_cash=payload["initial_cash"],
            terminal_equity=payload["terminal_equity"],
            terminal_liquidation_equity=payload["terminal_liquidation_equity"],
            total_return=payload["total_return"],
            cagr=payload["cagr"],
            sharpe=payload["sharpe"],
            sortino=payload["sortino"],
            max_drawdown=payload["max_drawdown"],
            total_traded_notional=payload["total_traded_notional"],
            turnover=payload["turnover"],
            num_fills=payload["num_fills"],
        )


@dataclass(frozen=True)
class SplitBoundary:
    """Exact bounds of one chronological segment of the dataset."""

    segment: str
    first_open_time: pd.Timestamp
    last_open_time: pd.Timestamp
    n_bars: int

    def __post_init__(self) -> None:
        segment = require_str("segment", self.segment)
        if segment not in SEGMENT_NAMES:
            raise ValueError(f"segment must be one of {SEGMENT_NAMES}, got {segment!r}")
        require_aware_timestamp("first_open_time", self.first_open_time)
        require_aware_timestamp("last_open_time", self.last_open_time)
        if self.first_open_time > self.last_open_time:
            raise ValueError(
                f"first_open_time {self.first_open_time} must not be after "
                f"last_open_time {self.last_open_time}"
            )
        require_positive_int("n_bars", self.n_bars)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "first_open_time": self.first_open_time.isoformat(),
            "last_open_time": self.last_open_time.isoformat(),
            "n_bars": self.n_bars,
        }

    @classmethod
    def from_json_dict(cls, payload: object) -> SplitBoundary:
        if not isinstance(payload, dict):
            raise ValueError(f"split entry must be an object, got {type(payload).__name__}")
        keys = set(payload)
        if keys != _SPLIT_KEYS:
            unknown = sorted(keys - _SPLIT_KEYS)
            missing = sorted(_SPLIT_KEYS - keys)
            raise ValueError(
                f"split keys do not match schema: unknown={unknown}, missing={missing}"
            )
        return cls(
            segment=payload["segment"],
            first_open_time=parse_timestamp_field("first_open_time", payload["first_open_time"]),
            last_open_time=parse_timestamp_field("last_open_time", payload["last_open_time"]),
            n_bars=payload["n_bars"],
        )


@dataclass(frozen=True)
class QualityWarningSummary:
    """One warning-severity audit finding echoed into the results."""

    code: str
    count: int
    first_examples: tuple[str, ...]

    def __post_init__(self) -> None:
        require_nonempty_str("code", self.code)
        require_positive_int("count", self.count)
        if not isinstance(self.first_examples, tuple) or len(self.first_examples) > 3:
            raise ValueError("first_examples must be a tuple of at most 3 strings")
        for example in self.first_examples:
            require_str("first_examples entry", example)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "count": self.count,
            "first_examples": list(self.first_examples),
        }

    @classmethod
    def from_json_dict(cls, payload: object) -> QualityWarningSummary:
        if not isinstance(payload, dict):
            raise ValueError(f"warning entry must be an object, got {type(payload).__name__}")
        keys = set(payload)
        if keys != _WARNING_KEYS:
            unknown = sorted(keys - _WARNING_KEYS)
            missing = sorted(_WARNING_KEYS - keys)
            raise ValueError(
                f"warning keys do not match schema: unknown={unknown}, missing={missing}"
            )
        examples = payload["first_examples"]
        if not isinstance(examples, list):
            raise ValueError("first_examples must be an array")
        return cls(code=payload["code"], count=payload["count"], first_examples=tuple(examples))


@dataclass(frozen=True)
class BenchmarkResults:
    """The complete, self-describing benchmark result record.

    Validated in ``__post_init__`` — one shared path for constructed and
    parsed results. Segment rows must agree exactly with the declared
    split boundaries; the splits must partition the dataset contiguously;
    a test evaluation id is present if and only if test segments are.
    """

    results_schema_version: int
    package_version: str
    base_asset: str
    quote_asset: str
    symbol: str
    venue: str
    market_type: str
    candle_interval: pd.Timedelta
    dataset_content_fingerprint: str
    dataset_manifest_sha256: str
    dataset_lock_sha256: str
    quality_report_sha256: str
    acquisition_evidence_sha256: str
    protocol_sha256: str
    protocol_registration_commit_sha: str
    """The commit that registered the frozen protocol — an immutable
    pre-registration fact, never a commit chosen at execution time."""
    authorized_evaluation_code_commit_sha: str | None
    """The reviewed code revision authorized for the one-time test; present
    if and only if test segments are. Never conflated with registration."""
    dataset_row_count: int
    dataset_first_open_time: pd.Timestamp
    dataset_last_open_time: pd.Timestamp
    quality_warnings: tuple[QualityWarningSummary, ...]
    splits: tuple[SplitBoundary, ...]
    segments: tuple[SegmentMetrics, ...]
    accounting: str
    test_evaluation_id: str | None

    def __post_init__(self) -> None:
        version = require_int("results_schema_version", self.results_schema_version)
        if version != RESULTS_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported results schema version {version!r}; "
                f"this package reads version {RESULTS_SCHEMA_VERSION}"
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
        require_fingerprint("dataset_content_fingerprint", self.dataset_content_fingerprint)
        for label in (
            "dataset_manifest_sha256",
            "dataset_lock_sha256",
            "quality_report_sha256",
            "acquisition_evidence_sha256",
            "protocol_sha256",
        ):
            require_hex64(label, getattr(self, label))
        require_commit_sha(
            "protocol_registration_commit_sha", self.protocol_registration_commit_sha
        )
        row_count = require_positive_int("dataset_row_count", self.dataset_row_count)
        require_aware_timestamp("dataset_first_open_time", self.dataset_first_open_time)
        require_aware_timestamp("dataset_last_open_time", self.dataset_last_open_time)
        _require_exact_str("accounting", self.accounting, ACCOUNTING)

        if not isinstance(self.quality_warnings, tuple):
            raise ValueError("quality_warnings must be a tuple")
        for warning in self.quality_warnings:
            if not isinstance(warning, QualityWarningSummary):
                raise ValueError("quality_warnings entries must be QualityWarningSummary")
        codes = [warning.code for warning in self.quality_warnings]
        if codes != sorted(codes) or len(set(codes)) != len(codes):
            raise ValueError("quality_warnings must be sorted by code without duplicates")

        if not isinstance(self.splits, tuple) or [split.segment for split in self.splits] != list(
            SEGMENT_NAMES
        ):
            raise ValueError("splits must declare train, validation, and test, in order")
        for split in self.splits:
            expected_last = split.first_open_time + (split.n_bars - 1) * self.candle_interval
            if split.last_open_time != expected_last:
                raise ValueError(
                    f"split {split.segment!r} bounds are inconsistent with its n_bars and "
                    f"the candle interval: expected last open {expected_last}, "
                    f"got {split.last_open_time}"
                )
        if self.splits[0].first_open_time != self.dataset_first_open_time:
            raise ValueError("train must start at the dataset's first open time")
        if self.splits[-1].last_open_time != self.dataset_last_open_time:
            raise ValueError("test must end at the dataset's last open time")
        for previous, following in zip(self.splits, self.splits[1:], strict=False):
            if following.first_open_time != previous.last_open_time + self.candle_interval:
                raise ValueError(
                    f"splits must be contiguous: {following.segment!r} does not start one "
                    f"interval after {previous.segment!r} ends"
                )
        if sum(split.n_bars for split in self.splits) != row_count:
            raise ValueError("split bar counts must sum to the dataset row count")

        if not isinstance(self.segments, tuple) or not self.segments:
            raise ValueError("segments must be a non-empty tuple")
        for entry in self.segments:
            if not isinstance(entry, SegmentMetrics):
                raise ValueError("segments entries must be SegmentMetrics")
        segment_sets: dict[str, list[str]] = {}
        for entry in self.segments:
            segment_sets.setdefault(entry.strategy, []).append(entry.segment)
        if sorted(segment_sets) != sorted(RESULT_STRATEGY_NAMES):
            raise ValueError(f"segments must cover exactly the strategies {RESULT_STRATEGY_NAMES}")
        evaluated = segment_sets[RESULT_STRATEGY_NAMES[0]]
        if any(names != evaluated for names in segment_sets.values()):
            raise ValueError("every strategy must cover the same segments")
        if evaluated not in (["train", "validation"], ["train", "validation", "test"]):
            raise ValueError(
                "segments must cover train+validation, plus test only after the "
                "authorized one-time evaluation"
            )
        expected_order = [
            (strategy, segment) for strategy in RESULT_STRATEGY_NAMES for segment in evaluated
        ]
        actual_order = [(entry.strategy, entry.segment) for entry in self.segments]
        if actual_order != expected_order:
            raise ValueError("segments must be in canonical strategy-major order")
        boundaries = {split.segment: split for split in self.splits}
        for entry in self.segments:
            split = boundaries[entry.segment]
            if entry.n_bars != split.n_bars:
                raise ValueError(
                    f"segment {entry.strategy}/{entry.segment} n_bars {entry.n_bars} disagrees "
                    f"with the declared split ({split.n_bars})"
                )
            if entry.start_time != split.first_open_time:
                raise ValueError(
                    f"segment {entry.strategy}/{entry.segment} starts at {entry.start_time}, "
                    f"expected the split's first open {split.first_open_time}"
                )
            expected_end = split.last_open_time + self.candle_interval
            if entry.end_time != expected_end:
                raise ValueError(
                    f"segment {entry.strategy}/{entry.segment} ends at {entry.end_time}, "
                    f"expected the split's last close {expected_end}"
                )

        has_test = "test" in evaluated
        if has_test:
            require_evaluation_id("test_evaluation_id", self.test_evaluation_id)
            require_commit_sha(
                "authorized_evaluation_code_commit_sha",
                self.authorized_evaluation_code_commit_sha,
            )
        else:
            if self.test_evaluation_id is not None:
                raise ValueError(
                    "test_evaluation_id must be null when no test segment was evaluated"
                )
            if self.authorized_evaluation_code_commit_sha is not None:
                raise ValueError(
                    "authorized_evaluation_code_commit_sha must be null when no test "
                    "segment was evaluated"
                )

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "results_schema_version": self.results_schema_version,
            "package_version": self.package_version,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "symbol": self.symbol,
            "venue": self.venue,
            "market_type": self.market_type,
            "candle_interval": self.candle_interval.isoformat(),
            "dataset_content_fingerprint": self.dataset_content_fingerprint,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "dataset_lock_sha256": self.dataset_lock_sha256,
            "quality_report_sha256": self.quality_report_sha256,
            "acquisition_evidence_sha256": self.acquisition_evidence_sha256,
            "protocol_sha256": self.protocol_sha256,
            "protocol_registration_commit_sha": self.protocol_registration_commit_sha,
            "authorized_evaluation_code_commit_sha": self.authorized_evaluation_code_commit_sha,
            "dataset_row_count": self.dataset_row_count,
            "dataset_first_open_time": self.dataset_first_open_time.isoformat(),
            "dataset_last_open_time": self.dataset_last_open_time.isoformat(),
            "quality_warnings": [warning.to_json_dict() for warning in self.quality_warnings],
            "splits": [split.to_json_dict() for split in self.splits],
            "segments": [entry.to_json_dict() for entry in self.segments],
            "accounting": self.accounting,
            "test_evaluation_id": self.test_evaluation_id,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> BenchmarkResults:
        """Strict parse feeding the shared constructor validation."""
        payload = _loads_strict(raw, "benchmark results")
        if not isinstance(payload, dict):
            raise ValueError("benchmark results JSON must be an object")
        keys = set(payload)
        if keys != _RESULTS_KEYS:
            unknown = sorted(keys - _RESULTS_KEYS)
            missing = sorted(_RESULTS_KEYS - keys)
            raise ValueError(
                f"benchmark results keys do not match schema: unknown={unknown}, missing={missing}"
            )
        interval_text = require_str("candle_interval", payload["candle_interval"])
        try:
            interval = pd.Timedelta(interval_text)
        except ValueError as exc:
            raise ValueError(f"candle_interval is unparseable: {interval_text!r}") from exc
        for label in ("quality_warnings", "splits", "segments"):
            if not isinstance(payload[label], list):
                raise ValueError(f"{label} must be an array")
        return cls(
            results_schema_version=payload["results_schema_version"],
            package_version=payload["package_version"],
            base_asset=payload["base_asset"],
            quote_asset=payload["quote_asset"],
            symbol=payload["symbol"],
            venue=payload["venue"],
            market_type=payload["market_type"],
            candle_interval=interval,
            dataset_content_fingerprint=payload["dataset_content_fingerprint"],
            dataset_manifest_sha256=payload["dataset_manifest_sha256"],
            dataset_lock_sha256=payload["dataset_lock_sha256"],
            quality_report_sha256=payload["quality_report_sha256"],
            acquisition_evidence_sha256=payload["acquisition_evidence_sha256"],
            protocol_sha256=payload["protocol_sha256"],
            protocol_registration_commit_sha=payload["protocol_registration_commit_sha"],
            authorized_evaluation_code_commit_sha=payload["authorized_evaluation_code_commit_sha"],
            dataset_row_count=payload["dataset_row_count"],
            dataset_first_open_time=parse_timestamp_field(
                "dataset_first_open_time", payload["dataset_first_open_time"]
            ),
            dataset_last_open_time=parse_timestamp_field(
                "dataset_last_open_time", payload["dataset_last_open_time"]
            ),
            quality_warnings=tuple(
                QualityWarningSummary.from_json_dict(entry) for entry in payload["quality_warnings"]
            ),
            splits=tuple(SplitBoundary.from_json_dict(entry) for entry in payload["splits"]),
            segments=tuple(SegmentMetrics.from_json_dict(entry) for entry in payload["segments"]),
            accounting=payload["accounting"],
            test_evaluation_id=payload["test_evaluation_id"],
        )
