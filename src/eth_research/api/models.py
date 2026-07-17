"""Public, frozen, canonical-JSON-serializable value models for the offline API.

These are the intentional public *value objects*: small immutable dataclasses that
describe a dataset, a strategy, a cost scenario, a split, and the parameters of a
research run, plus the validation report and dataset handles. They carry no behaviour
beyond strict construction and canonical (de)serialization, and they never embed raw
market data, absolute filesystem paths, credentials, or environment identity — only the
minimal, deterministic identity a downstream result or receipt needs to bind a run.

``ResearchResult`` and ``RunReceipt`` live in :mod:`eth_research.api.results` and
:mod:`eth_research.api.receipt` respectively, co-located with the functions that build
and verify them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from eth_research.api.serialization import (
    CanonicalError,
    canonical_json_bytes,
    require_bool,
    require_finite_float,
    require_int,
    require_list,
    require_mapping,
    require_str,
    strict_load_canonical,
)

# The public API contract version, independent of the package version. It is bumped only
# on a breaking change to the public surface (see docs/VERSIONING_AND_COMPATIBILITY).
API_VERSION = "1.0"

VALIDATION_REPORT_SCHEMA_VERSION = 1

#: Built-in binary strategy identifiers accepted by ``StrategySpec`` / the CLI.
BINARY_STRATEGY_KINDS = (
    "buy_and_hold",
    "cash",
    "moving_average_crossover",
    "donchian_channel",
)
#: Built-in fractional strategy identifiers (pre-composed, no free parameters).
FRACTIONAL_STRATEGY_KINDS = (
    "cash",
    "buy_and_hold",
    "donchian_55_20",
    "vol_target_buy_and_hold_30d_50pct",
    "vol_target_donchian_55_20_30d_50pct",
)
#: Cost scenario names for each engine (disjoint sets).
BINARY_COST_SCENARIOS = ("base", "stressed", "severe")
FRACTIONAL_COST_SCENARIOS = ("compatibility_v1", "causal_proxy_base", "causal_proxy_stressed")

ENGINES = ("binary", "fractional")


def _iso_utc(ts: pd.Timestamp) -> str:
    """Deterministic ISO-8601 UTC string for a tz-aware canonical timestamp."""
    return ts.tz_convert("UTC").isoformat()


@runtime_checkable
class DatasetHandle(Protocol):
    """Structural type for anything the run functions accept as a dataset.

    Both :class:`ValidatedDataset` and :class:`CanonicalDataset` satisfy it: the validated
    in-memory frame, its content fingerprint, the bar interval, and the row count.
    """

    @property
    def frame(self) -> pd.DataFrame: ...

    @property
    def fingerprint(self) -> str: ...

    @property
    def interval_seconds(self) -> int: ...

    @property
    def row_count(self) -> int: ...


# --------------------------------------------------------------------------- #
# validation report                                                           #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ValidationFinding:
    """One dataset-quality finding, without raw data examples.

    Deliberately omits the internal finding's ``first_examples`` so that no market
    value is ever serialized into a public artifact.
    """

    code: str
    severity: str  # "error" | "warning"
    count: int
    description: str

    def __post_init__(self) -> None:
        if self.severity not in ("error", "warning"):
            raise CanonicalError(f"severity: expected 'error' or 'warning', got {self.severity!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "count": self.count,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> ValidationFinding:
        data = require_mapping(payload, "finding")
        return cls(
            code=require_str(data.get("code"), "finding.code"),
            severity=require_str(data.get("severity"), "finding.severity"),
            count=require_int(data.get("count"), "finding.count"),
            description=require_str(
                data.get("description"), "finding.description", allow_empty=True
            ),
        )


@dataclass(frozen=True)
class ValidationReport:
    """A public summary of a dataset-quality audit (counts and per-code findings)."""

    schema_version: int
    row_count: int
    interval_seconds: int
    error_count: int
    warning_count: int
    findings: tuple[ValidationFinding, ...]

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "row_count": self.row_count,
            "interval_seconds": self.interval_seconds,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "findings": [f.to_dict() for f in self.findings],
        }

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Any) -> ValidationReport:
        data = require_mapping(payload, "validation_report")
        findings = tuple(
            ValidationFinding.from_dict(item)
            for item in require_list(data.get("findings"), "validation_report.findings")
        )
        return cls(
            schema_version=require_int(
                data.get("schema_version"), "validation_report.schema_version"
            ),
            row_count=require_int(data.get("row_count"), "validation_report.row_count"),
            interval_seconds=require_int(
                data.get("interval_seconds"), "validation_report.interval_seconds"
            ),
            error_count=require_int(data.get("error_count"), "validation_report.error_count"),
            warning_count=require_int(data.get("warning_count"), "validation_report.warning_count"),
            findings=findings,
        )

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> ValidationReport:
        return cls.from_dict(strict_load_canonical(raw, "validation_report"))


# --------------------------------------------------------------------------- #
# dataset spec + handles                                                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DatasetSpec:
    """How to interpret a raw OHLCV frame: the interval and timezone/column policy."""

    interval_seconds: int
    assume_utc: bool = False
    allow_extra_columns: bool = False

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise CanonicalError("interval_seconds: must be a positive integer")

    @property
    def interval(self) -> pd.Timedelta:
        return pd.Timedelta(seconds=self.interval_seconds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interval_seconds": self.interval_seconds,
            "assume_utc": self.assume_utc,
            "allow_extra_columns": self.allow_extra_columns,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> DatasetSpec:
        data = require_mapping(payload, "dataset_spec")
        return cls(
            interval_seconds=require_int(
                data.get("interval_seconds"), "dataset_spec.interval_seconds"
            ),
            assume_utc=require_bool(data.get("assume_utc", False), "dataset_spec.assume_utc"),
            allow_extra_columns=require_bool(
                data.get("allow_extra_columns", False), "dataset_spec.allow_extra_columns"
            ),
        )


@dataclass(frozen=True)
class ValidatedDataset:
    """A canonical, schema-validated OHLCV frame plus its serializable identity.

    ``frame`` is the in-memory validated data; it is excluded from equality and repr so
    the handle stays comparable by identity and never dumps market data.
    """

    frame: pd.DataFrame = field(compare=False, repr=False)
    fingerprint: str
    row_count: int
    interval_seconds: int
    start_time: str
    end_time: str
    report: ValidationReport = field(compare=False)

    def identity(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "row_count": self.row_count,
            "interval_seconds": self.interval_seconds,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


@dataclass(frozen=True)
class CanonicalDataset:
    """A canonical dataset loaded from an on-disk manifest, with the manifest digest."""

    frame: pd.DataFrame = field(compare=False, repr=False)
    fingerprint: str
    row_count: int
    interval_seconds: int
    start_time: str
    end_time: str
    manifest_sha256: str

    def identity(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "row_count": self.row_count,
            "interval_seconds": self.interval_seconds,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "manifest_sha256": self.manifest_sha256,
        }


# --------------------------------------------------------------------------- #
# split spec                                                                  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ChronologicalSplitSpec:
    """Fractions for a train / validation / test chronological split (test = remainder)."""

    train_fraction: float = 0.6
    validation_fraction: float = 0.2

    def __post_init__(self) -> None:
        for label, value in (
            ("train_fraction", self.train_fraction),
            ("validation_fraction", self.validation_fraction),
        ):
            if not isinstance(value, float) or not 0.0 < value < 1.0:
                raise CanonicalError(f"{label}: must be a float strictly between 0 and 1")
        if self.train_fraction + self.validation_fraction >= 1.0:
            raise CanonicalError(
                "train_fraction + validation_fraction must be < 1 (test is the remainder)"
            )

    @property
    def test_fraction(self) -> float:
        return 1.0 - self.train_fraction - self.validation_fraction

    def to_dict(self) -> dict[str, Any]:
        return {
            "train_fraction": self.train_fraction,
            "validation_fraction": self.validation_fraction,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> ChronologicalSplitSpec:
        data = require_mapping(payload, "split_spec")
        return cls(
            train_fraction=require_finite_float(
                data.get("train_fraction"), "split_spec.train_fraction"
            ),
            validation_fraction=require_finite_float(
                data.get("validation_fraction"), "split_spec.validation_fraction"
            ),
        )


# --------------------------------------------------------------------------- #
# strategy spec                                                                #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StrategySpec:
    """A built-in strategy identity: a ``kind`` id plus its fixed integer parameters.

    ``params`` is an ordered tuple of ``(name, value)`` pairs so the spec stays hashable
    and canonically serializable. Use :meth:`create` for a keyword-argument constructor.
    """

    kind: str
    params: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        require_str(self.kind, "strategy.kind")
        seen: set[str] = set()
        for name, value in self.params:
            if not isinstance(name, str) or name == "":
                raise CanonicalError("strategy.params: parameter names must be non-empty strings")
            if isinstance(value, bool) or not isinstance(value, int):
                raise CanonicalError(f"strategy.params.{name}: must be an integer")
            if name in seen:
                raise CanonicalError(f"strategy.params.{name}: duplicated")
            seen.add(name)
        # Canonicalize parameter order so the spec is an object-level fixed point:
        # ``x == StrategySpec.from_dict(x.to_dict())`` for any construction order.
        object.__setattr__(self, "params", tuple(sorted(self.params)))

    @classmethod
    def create(cls, kind: str, **params: int) -> StrategySpec:
        return cls(kind=kind, params=tuple(sorted(params.items())))

    def param_dict(self) -> dict[str, int]:
        return dict(self.params)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, payload: Any) -> StrategySpec:
        data = require_mapping(payload, "strategy")
        raw_params = require_mapping(data.get("params", {}), "strategy.params")
        params = tuple(
            (
                require_str(name, "strategy.params key", allow_empty=False),
                require_int(value, f"strategy.params.{name}"),
            )
            for name, value in sorted(raw_params.items())
        )
        return cls(kind=require_str(data.get("kind"), "strategy.kind"), params=params)


# --------------------------------------------------------------------------- #
# cost spec                                                                    #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CostSpec:
    """A named cost scenario. The scenario name determines the engine it belongs to."""

    scenario: str

    def __post_init__(self) -> None:
        require_str(self.scenario, "cost.scenario")

    def to_dict(self) -> dict[str, Any]:
        return {"scenario": self.scenario}

    @classmethod
    def from_dict(cls, payload: Any) -> CostSpec:
        data = require_mapping(payload, "cost")
        return cls(scenario=require_str(data.get("scenario"), "cost.scenario"))


# --------------------------------------------------------------------------- #
# engine run params                                                            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BinaryBacktestSpec:
    """Numeric run parameters for the binary (all-in / all-out) engine."""

    initial_cash: float = 10_000.0
    context_bars: int = 0
    risk_free_rate: float = 0.0

    def __post_init__(self) -> None:
        _validate_run_params(self.initial_cash, self.context_bars, self.risk_free_rate)

    def to_dict(self) -> dict[str, Any]:
        return _run_params_dict(self.initial_cash, self.context_bars, self.risk_free_rate)

    @classmethod
    def from_dict(cls, payload: Any) -> BinaryBacktestSpec:
        cash, bars, rfr = _run_params_from_dict(payload, "binary_backtest_spec")
        return cls(initial_cash=cash, context_bars=bars, risk_free_rate=rfr)


@dataclass(frozen=True)
class FractionalBacktestSpec:
    """Numeric run parameters for the fractional (continuous-exposure) engine."""

    initial_cash: float = 10_000.0
    context_bars: int = 0
    risk_free_rate: float = 0.0

    def __post_init__(self) -> None:
        _validate_run_params(self.initial_cash, self.context_bars, self.risk_free_rate)

    def to_dict(self) -> dict[str, Any]:
        return _run_params_dict(self.initial_cash, self.context_bars, self.risk_free_rate)

    @classmethod
    def from_dict(cls, payload: Any) -> FractionalBacktestSpec:
        cash, bars, rfr = _run_params_from_dict(payload, "fractional_backtest_spec")
        return cls(initial_cash=cash, context_bars=bars, risk_free_rate=rfr)


def _validate_run_params(initial_cash: float, context_bars: int, risk_free_rate: float) -> None:
    if not isinstance(initial_cash, float) or not initial_cash > 0.0:
        raise CanonicalError("initial_cash: must be a positive number")
    if isinstance(context_bars, bool) or not isinstance(context_bars, int) or context_bars < 0:
        raise CanonicalError("context_bars: must be a non-negative integer")
    if not isinstance(risk_free_rate, float):
        raise CanonicalError("risk_free_rate: must be a number")


def _run_params_dict(
    initial_cash: float, context_bars: int, risk_free_rate: float
) -> dict[str, Any]:
    return {
        "initial_cash": initial_cash,
        "context_bars": context_bars,
        "risk_free_rate": risk_free_rate,
    }


def _run_params_from_dict(payload: Any, label: str) -> tuple[float, int, float]:
    data = require_mapping(payload, label)
    return (
        require_finite_float(data.get("initial_cash", 10_000.0), f"{label}.initial_cash"),
        require_int(data.get("context_bars", 0), f"{label}.context_bars"),
        require_finite_float(data.get("risk_free_rate", 0.0), f"{label}.risk_free_rate"),
    )


# --------------------------------------------------------------------------- #
# composite run spec                                                           #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ResearchRunSpec:
    """The complete, serializable description of one research run.

    Binds the engine, the dataset interpretation, the optional split, the strategy, the
    cost scenario, and the numeric run parameters into a single canonical record that a
    result and a receipt reference.
    """

    engine: str
    dataset: DatasetSpec
    strategy: StrategySpec
    cost: CostSpec
    initial_cash: float
    context_bars: int
    risk_free_rate: float
    split: ChronologicalSplitSpec | None = None
    #: Content fingerprint of the warm-up context, when one was supplied. Bound alongside
    #: ``context_bars`` so two runs with equal-length but different context content are
    #: distinguishable in the run identity (``None`` when no context was used).
    context_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.engine not in ENGINES:
            raise CanonicalError(f"engine: expected one of {ENGINES}, got {self.engine!r}")
        _validate_run_params(self.initial_cash, self.context_bars, self.risk_free_rate)
        if self.context_fingerprint is not None:
            require_str(self.context_fingerprint, "research_run_spec.context_fingerprint")

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "dataset": self.dataset.to_dict(),
            "strategy": self.strategy.to_dict(),
            "cost": self.cost.to_dict(),
            "initial_cash": self.initial_cash,
            "context_bars": self.context_bars,
            "context_fingerprint": self.context_fingerprint,
            "risk_free_rate": self.risk_free_rate,
            "split": self.split.to_dict() if self.split is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> ResearchRunSpec:
        data = require_mapping(payload, "research_run_spec")
        split_raw = data.get("split")
        raw_context_fp = data.get("context_fingerprint")
        context_fingerprint = (
            None
            if raw_context_fp is None
            else require_str(raw_context_fp, "research_run_spec.context_fingerprint")
        )
        return cls(
            engine=require_str(data.get("engine"), "research_run_spec.engine"),
            dataset=DatasetSpec.from_dict(data.get("dataset")),
            strategy=StrategySpec.from_dict(data.get("strategy")),
            cost=CostSpec.from_dict(data.get("cost")),
            initial_cash=require_finite_float(
                data.get("initial_cash"), "research_run_spec.initial_cash"
            ),
            context_bars=require_int(data.get("context_bars"), "research_run_spec.context_bars"),
            risk_free_rate=require_finite_float(
                data.get("risk_free_rate"), "research_run_spec.risk_free_rate"
            ),
            split=ChronologicalSplitSpec.from_dict(split_raw) if split_raw is not None else None,
            context_fingerprint=context_fingerprint,
        )
