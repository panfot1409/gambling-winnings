"""Strict, versioned run configuration for the offline research platform.

A configuration is a small JSON or TOML document that fully and deterministically describes
one research run: where the dataset comes from (a deterministic synthetic generator or a
local file), which engine, strategy, cost scenario, and optional chronological split to use,
the numeric run parameters, and where to write the output bundle.

Parsing is strict and fails closed:

* every object must contain exactly its known keys — an unknown key is an error;
* no string is coerced to a number and no ``bool`` is read as an ``int``; every number must
  be finite;
* a filesystem path must be a relative, traversal-free local path — never absolute, never a
  URL, never a reference to the governed ``research/`` roots or a ``.git`` directory;
* there are no implicit "latest", clock, network, credential, shell, or code-reference
  values anywhere, and ``overwrite`` defaults to ``False``.

The result is a frozen :class:`RunConfig`; applying it to actually run is the caller's job
(see the CLI), so this module never touches the network or the filesystem beyond reading the
config file the caller names.
"""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.api.errors import ConfigurationError
from eth_research.api.models import (
    BINARY_COST_SCENARIOS,
    ENGINES,
    FRACTIONAL_COST_SCENARIOS,
    CostSpec,
    StrategySpec,
)
from eth_research.api.serialization import (
    CanonicalError,
    require_bool,
    require_int,
    require_mapping,
    require_str,
)

__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "DatasetConfig",
    "FileDatasetConfig",
    "OutputConfig",
    "RunConfig",
    "RunParamsConfig",
    "SplitConfig",
    "SyntheticDatasetConfig",
    "load_config",
    "load_config_file",
]

CONFIG_SCHEMA_VERSION = 1

_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://")
_EVALUATE_SEGMENTS = ("train", "validation", "test")


def _exact_keys(data: dict[str, Any], allowed: set[str], label: str) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise CanonicalError(f"{label}: unexpected key(s) {extra}")


def _require_number(value: Any, field: str) -> float:
    # A user may write a whole number (``10000``) for a float field, but never a string,
    # a bool, or a non-finite value.
    if isinstance(value, bool):
        raise CanonicalError(f"{field}: expected a number, not a boolean")
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalError(f"{field}: number must be finite")
        return value
    raise CanonicalError(f"{field}: expected a finite number")


def _safe_rel_path(value: Any, field: str) -> str:
    text = require_str(value, field)
    if "\x00" in text or "\\" in text:
        raise CanonicalError(f"{field}: unsafe characters in path")
    if _URL_RE.match(text):
        raise CanonicalError(f"{field}: must be a local path, not a URL")
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        raise CanonicalError(f"{field}: must be a relative path without '..'")
    if ".git" in pure.parts:
        raise CanonicalError(f"{field}: must not reference a .git directory")
    meaningful = [part for part in pure.parts if part != "."]
    if meaningful and meaningful[0] == "research":
        raise CanonicalError(f"{field}: must not reference governed research artifacts")
    return text


# --------------------------------------------------------------------------- #
# dataset                                                                     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SyntheticDatasetConfig:
    n_periods: int = 500
    interval: str = "1D"
    start: str = "2020-01-01"
    start_price: float = 1_000.0
    drift: float = 0.0002
    volatility: float = 0.02
    seed: int = 0

    @classmethod
    def from_mapping(cls, payload: Any) -> SyntheticDatasetConfig:
        data = require_mapping(payload, "dataset.synthetic")
        _exact_keys(
            data,
            {"n_periods", "interval", "start", "start_price", "drift", "volatility", "seed"},
            "dataset.synthetic",
        )
        return cls(
            n_periods=require_int(data.get("n_periods", 500), "dataset.synthetic.n_periods"),
            interval=require_str(data.get("interval", "1D"), "dataset.synthetic.interval"),
            start=require_str(data.get("start", "2020-01-01"), "dataset.synthetic.start"),
            start_price=_require_number(
                data.get("start_price", 1_000.0), "dataset.synthetic.start_price"
            ),
            drift=_require_number(data.get("drift", 0.0002), "dataset.synthetic.drift"),
            volatility=_require_number(
                data.get("volatility", 0.02), "dataset.synthetic.volatility"
            ),
            seed=require_int(data.get("seed", 0), "dataset.synthetic.seed"),
        )


@dataclass(frozen=True)
class FileDatasetConfig:
    path: str
    interval_seconds: int
    assume_utc: bool = False
    allow_extra_columns: bool = False

    @classmethod
    def from_mapping(cls, payload: Any) -> FileDatasetConfig:
        data = require_mapping(payload, "dataset.file")
        _exact_keys(
            data, {"path", "interval_seconds", "assume_utc", "allow_extra_columns"}, "dataset.file"
        )
        return cls(
            path=_safe_rel_path(data.get("path"), "dataset.file.path"),
            interval_seconds=require_int(
                data.get("interval_seconds"), "dataset.file.interval_seconds"
            ),
            assume_utc=require_bool(data.get("assume_utc", False), "dataset.file.assume_utc"),
            allow_extra_columns=require_bool(
                data.get("allow_extra_columns", False), "dataset.file.allow_extra_columns"
            ),
        )


@dataclass(frozen=True)
class DatasetConfig:
    source: str
    synthetic: SyntheticDatasetConfig | None
    file: FileDatasetConfig | None

    @classmethod
    def from_mapping(cls, payload: Any) -> DatasetConfig:
        data = require_mapping(payload, "dataset")
        _exact_keys(data, {"source", "synthetic", "file"}, "dataset")
        source = require_str(data.get("source"), "dataset.source")
        if source == "synthetic":
            if "file" in data:
                raise CanonicalError("dataset: a synthetic source must not carry a 'file' block")
            return cls(source, SyntheticDatasetConfig.from_mapping(data.get("synthetic", {})), None)
        if source == "file":
            if "synthetic" in data:
                raise CanonicalError("dataset: a file source must not carry a 'synthetic' block")
            if "file" not in data:
                raise CanonicalError("dataset: a file source requires a 'file' block")
            return cls(source, None, FileDatasetConfig.from_mapping(data.get("file")))
        raise CanonicalError("dataset.source: expected 'synthetic' or 'file'")


# --------------------------------------------------------------------------- #
# split / run params / output                                                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SplitConfig:
    enabled: bool = False
    train_fraction: float = 0.6
    validation_fraction: float = 0.2
    evaluate: str = "validation"
    context_bars: int = 0

    @classmethod
    def from_mapping(cls, payload: Any) -> SplitConfig:
        data = require_mapping(payload, "split")
        _exact_keys(
            data,
            {"enabled", "train_fraction", "validation_fraction", "evaluate", "context_bars"},
            "split",
        )
        evaluate = require_str(data.get("evaluate", "validation"), "split.evaluate")
        if evaluate not in _EVALUATE_SEGMENTS:
            raise CanonicalError(f"split.evaluate: expected one of {_EVALUATE_SEGMENTS}")
        context_bars = require_int(data.get("context_bars", 0), "split.context_bars")
        if context_bars < 0:
            raise CanonicalError("split.context_bars: must be non-negative")
        return cls(
            enabled=require_bool(data.get("enabled", False), "split.enabled"),
            train_fraction=_require_number(data.get("train_fraction", 0.6), "split.train_fraction"),
            validation_fraction=_require_number(
                data.get("validation_fraction", 0.2), "split.validation_fraction"
            ),
            evaluate=evaluate,
            context_bars=context_bars,
        )


@dataclass(frozen=True)
class RunParamsConfig:
    initial_cash: float = 10_000.0
    risk_free_rate: float = 0.0

    @classmethod
    def from_mapping(cls, payload: Any) -> RunParamsConfig:
        data = require_mapping(payload, "run")
        _exact_keys(data, {"initial_cash", "risk_free_rate"}, "run")
        initial_cash = _require_number(data.get("initial_cash", 10_000.0), "run.initial_cash")
        if initial_cash <= 0:
            raise CanonicalError("run.initial_cash: must be positive")
        return cls(
            initial_cash=initial_cash,
            risk_free_rate=_require_number(data.get("risk_free_rate", 0.0), "run.risk_free_rate"),
        )


@dataclass(frozen=True)
class OutputConfig:
    directory: str
    overwrite: bool = False
    write_report: bool = True

    @classmethod
    def from_mapping(cls, payload: Any) -> OutputConfig:
        data = require_mapping(payload, "output")
        _exact_keys(data, {"directory", "overwrite", "write_report"}, "output")
        return cls(
            directory=_safe_rel_path(data.get("directory"), "output.directory"),
            overwrite=require_bool(data.get("overwrite", False), "output.overwrite"),
            write_report=require_bool(data.get("write_report", True), "output.write_report"),
        )


# --------------------------------------------------------------------------- #
# top-level config                                                            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RunConfig:
    config_schema_version: int
    dataset: DatasetConfig
    engine: str
    strategy: StrategySpec
    costs: CostSpec
    split: SplitConfig
    run: RunParamsConfig
    output: OutputConfig

    @classmethod
    def from_mapping(cls, payload: Any) -> RunConfig:
        data = require_mapping(payload, "config")
        _exact_keys(
            data,
            {
                "config_schema_version",
                "dataset",
                "engine",
                "strategy",
                "costs",
                "split",
                "run",
                "output",
            },
            "config",
        )
        version = require_int(data.get("config_schema_version"), "config.config_schema_version")
        if version != CONFIG_SCHEMA_VERSION:
            raise CanonicalError(
                f"config.config_schema_version: expected {CONFIG_SCHEMA_VERSION}, got {version}"
            )
        engine = require_str(data.get("engine"), "config.engine")
        if engine not in ENGINES:
            raise CanonicalError(f"config.engine: expected one of {ENGINES}")
        strategy = StrategySpec.from_dict(data.get("strategy"))
        costs = CostSpec.from_dict(data.get("costs"))
        valid_scenarios = BINARY_COST_SCENARIOS if engine == "binary" else FRACTIONAL_COST_SCENARIOS
        if costs.scenario not in valid_scenarios:
            raise CanonicalError(
                f"config.costs.scenario: {costs.scenario!r} is not valid for the {engine} engine "
                f"(expected one of {valid_scenarios})"
            )
        return cls(
            config_schema_version=version,
            dataset=DatasetConfig.from_mapping(data.get("dataset")),
            engine=engine,
            strategy=strategy,
            costs=costs,
            split=SplitConfig.from_mapping(data.get("split", {})),
            run=RunParamsConfig.from_mapping(data.get("run", {})),
            output=OutputConfig.from_mapping(data.get("output")),
        )


def load_config(raw: bytes, *, fmt: str) -> RunConfig:
    """Parse configuration bytes (``fmt`` is ``"json"`` or ``"toml"``) into a :class:`RunConfig`.

    Raises :class:`ConfigurationError` on any parse or validation failure.
    """
    try:
        if fmt == "json":
            data = strict_json_loads(raw)
        elif fmt == "toml":
            data = tomllib.loads(raw.decode("utf-8"))
        else:
            raise ConfigurationError(f"unsupported config format {fmt!r}")
        return RunConfig.from_mapping(data)
    except (CanonicalError, StrictJSONError) as exc:
        raise ConfigurationError(f"invalid configuration: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"invalid TOML configuration: {exc}") from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise ConfigurationError(f"could not read configuration: {exc}") from exc


def load_config_file(path: str | Path) -> RunConfig:
    """Read a ``.json`` or ``.toml`` config file and parse it into a :class:`RunConfig`."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        fmt = "json"
    elif suffix == ".toml":
        fmt = "toml"
    else:
        raise ConfigurationError(f"config file must be .json or .toml, got {file_path.suffix!r}")
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(f"could not read config file {file_path}: {exc}") from exc
    return load_config(raw, fmt=fmt)
