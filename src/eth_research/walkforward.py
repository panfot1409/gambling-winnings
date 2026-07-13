"""Pre-registered expanding-window walk-forward protocol (Milestone 3A).

The research-train partition (2221 rows, 2016-05-23 .. 2022-06-21 UTC) is
tiled into an initial training block of 1095 rows and five contiguous
out-of-sample (OOS) development folds over the remaining 1126 rows,
distributed as evenly as possible (226, 225, 225, 225, 225). The training
window **expands**: fold ``k`` trains on every row before its OOS block.

Guarantees, all validated by the strict models here:

* every research-train row belongs to the initial-training block or to
  exactly one OOS fold — no overlap, no gap, no shuffle;
* information gap 0 bars — there is no ML label horizon; a signal from the
  prior close executes at the next open;
* fold context comes only from rows strictly before the fold's OOS start,
  capped at 55 bars, and contributes no P&L;
* each fold resets to an independent 10,000 USD — a comparison device,
  **not** one continuously traded portfolio;
* both marked and hypothetical liquidation equity are reported.

The protocol is pre-registered: committed, with green CI, before any real
research-train number is computed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research import __version__
from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.costs import COST_SCENARIOS, CostScenario
from eth_research.data.provenance import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
)
from eth_research.data.validation import (
    require_finite_float,
    require_nonnegative_int,
    require_positive_int,
    require_utc_timestamp,
)

WALK_FORWARD_SCHEMA_VERSION: int = 1
WALK_FORWARD_PROTOCOL_RELPATH: str = "research/m3a/walk_forward_protocol.json"

INITIAL_TRAINING_ROWS: int = 1095
OOS_FOLD_COUNT: int = 5
RESEARCH_TRAIN_ROWS: int = 2221
INFORMATION_GAP_BARS: int = 0
MAX_CONTEXT_BARS: int = 55
INITIAL_CASH: float = 10_000.0
SPLIT_SEMANTICS: str = "expanding-window-walk-forward-v1"

STRATEGY_NAMES: tuple[str, ...] = ("cash", "buy_and_hold", "sma_20_50", "donchian_55_20")

# Pinned deterministic block-bootstrap configuration (see bootstrap.py).
BOOTSTRAP_ALGORITHM: str = "moving-block-bootstrap-v1"
BOOTSTRAP_SEED: int = 20260713
BOOTSTRAP_BLOCK_LENGTH: int = 30
BOOTSTRAP_RESAMPLES: int = 5000
BOOTSTRAP_CONFIDENCE: float = 0.95

_FOLD_KEYS: frozenset[str] = frozenset(
    {
        "fold_index",
        "training_row_count",
        "context_row_count",
        "oos_row_count",
        "oos_first_open_time",
        "oos_last_open_time",
    }
)
_SCENARIO_KEYS: frozenset[str] = frozenset({"name", "fee_rate", "slippage_rate"})
_PROTOCOL_KEYS: frozenset[str] = frozenset(
    {
        "walk_forward_schema_version",
        "package_version",
        "development_partition_sha256",
        "research_train_content_fingerprint",
        "research_train_row_count",
        "initial_training_rows",
        "oos_fold_count",
        "information_gap_bars",
        "max_context_bars",
        "initial_cash",
        "split_semantics",
        "strategies",
        "cost_scenarios",
        "bootstrap_algorithm",
        "bootstrap_seed",
        "bootstrap_block_length",
        "bootstrap_resamples",
        "bootstrap_confidence",
        "folds",
    }
)


class WalkForwardError(RuntimeError):
    """The walk-forward protocol is invalid or disagrees with the data."""


def _parse_ts(label: str, value: object) -> pd.Timestamp:
    text = require_str(label, value)
    try:
        ts = pd.Timestamp(text)
    except ValueError as exc:
        raise ValueError(f"{label} is unparseable: {text!r}") from exc
    return require_utc_timestamp(label, ts)


@dataclass(frozen=True)
class FoldBoundary:
    """The mechanical bounds of one expanding-window OOS fold."""

    fold_index: int
    training_row_count: int
    context_row_count: int
    oos_row_count: int
    oos_first_open_time: pd.Timestamp
    oos_last_open_time: pd.Timestamp

    def __post_init__(self) -> None:
        require_nonnegative_int("fold_index", self.fold_index)
        require_positive_int("training_row_count", self.training_row_count)
        require_nonnegative_int("context_row_count", self.context_row_count)
        require_positive_int("oos_row_count", self.oos_row_count)
        require_utc_timestamp("oos_first_open_time", self.oos_first_open_time)
        require_utc_timestamp("oos_last_open_time", self.oos_last_open_time)
        if self.oos_first_open_time > self.oos_last_open_time:
            raise ValueError("oos_first_open_time must not be after oos_last_open_time")
        if self.context_row_count > MAX_CONTEXT_BARS:
            raise ValueError(f"context_row_count exceeds the {MAX_CONTEXT_BARS}-bar cap")
        if self.context_row_count > self.training_row_count:
            raise ValueError("context cannot exceed the training window")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "training_row_count": self.training_row_count,
            "context_row_count": self.context_row_count,
            "oos_row_count": self.oos_row_count,
            "oos_first_open_time": self.oos_first_open_time.isoformat(),
            "oos_last_open_time": self.oos_last_open_time.isoformat(),
        }

    @classmethod
    def from_json_dict(cls, payload: Any) -> FoldBoundary:
        if not isinstance(payload, dict) or set(payload) != _FOLD_KEYS:
            raise ValueError("fold boundary keys do not match schema")
        return cls(
            fold_index=require_int("fold_index", payload["fold_index"]),
            training_row_count=require_int("training_row_count", payload["training_row_count"]),
            context_row_count=require_int("context_row_count", payload["context_row_count"]),
            oos_row_count=require_int("oos_row_count", payload["oos_row_count"]),
            oos_first_open_time=_parse_ts("oos_first_open_time", payload["oos_first_open_time"]),
            oos_last_open_time=_parse_ts("oos_last_open_time", payload["oos_last_open_time"]),
        )


def _scenario_to_dict(scenario: CostScenario) -> dict[str, Any]:
    return {
        "name": scenario.name,
        "fee_rate": scenario.fee_rate,
        "slippage_rate": scenario.slippage_rate,
    }


def _scenario_from_dict(payload: Any) -> CostScenario:
    if not isinstance(payload, dict) or set(payload) != _SCENARIO_KEYS:
        raise ValueError("cost scenario keys do not match schema")
    return CostScenario(
        name=require_str("name", payload["name"]),
        fee_rate=require_finite_float("fee_rate", payload["fee_rate"]),
        slippage_rate=require_finite_float("slippage_rate", payload["slippage_rate"]),
    )


@dataclass(frozen=True)
class WalkForwardProtocol:
    """Strict, byte-reproducible pre-registered walk-forward protocol."""

    walk_forward_schema_version: int
    package_version: str
    development_partition_sha256: str
    research_train_content_fingerprint: str
    research_train_row_count: int
    initial_training_rows: int
    oos_fold_count: int
    information_gap_bars: int
    max_context_bars: int
    initial_cash: float
    split_semantics: str
    strategies: tuple[str, ...]
    cost_scenarios: tuple[CostScenario, ...]
    bootstrap_algorithm: str
    bootstrap_seed: int
    bootstrap_block_length: int
    bootstrap_resamples: int
    bootstrap_confidence: float
    folds: tuple[FoldBoundary, ...]

    def __post_init__(self) -> None:
        version = require_int("walk_forward_schema_version", self.walk_forward_schema_version)
        if version != WALK_FORWARD_SCHEMA_VERSION:
            raise ValueError(f"unsupported walk-forward schema version {version!r}")
        require_nonempty_str("package_version", self.package_version)
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        from eth_research.data.validation import require_fingerprint

        require_fingerprint(
            "research_train_content_fingerprint", self.research_train_content_fingerprint
        )
        if self.research_train_row_count != RESEARCH_TRAIN_ROWS:
            raise ValueError(f"research_train_row_count is pinned to {RESEARCH_TRAIN_ROWS}")
        if self.initial_training_rows != INITIAL_TRAINING_ROWS:
            raise ValueError(f"initial_training_rows is pinned to {INITIAL_TRAINING_ROWS}")
        if self.oos_fold_count != OOS_FOLD_COUNT:
            raise ValueError(f"oos_fold_count is pinned to {OOS_FOLD_COUNT}")
        if self.information_gap_bars != INFORMATION_GAP_BARS:
            raise ValueError(f"information_gap_bars is pinned to {INFORMATION_GAP_BARS}")
        if self.max_context_bars != MAX_CONTEXT_BARS:
            raise ValueError(f"max_context_bars is pinned to {MAX_CONTEXT_BARS}")
        if require_finite_float("initial_cash", self.initial_cash) != INITIAL_CASH:
            raise ValueError(f"initial_cash is pinned to {INITIAL_CASH}")
        if self.split_semantics != SPLIT_SEMANTICS:
            raise ValueError(f"split_semantics is pinned to {SPLIT_SEMANTICS!r}")
        if tuple(self.strategies) != STRATEGY_NAMES:
            raise ValueError(f"strategies are pinned to {STRATEGY_NAMES}, got {self.strategies}")
        if tuple(s.name for s in self.cost_scenarios) != tuple(s.name for s in COST_SCENARIOS):
            raise ValueError("cost scenarios must be exactly the three pinned scenarios in order")
        for got, want in zip(self.cost_scenarios, COST_SCENARIOS, strict=True):
            if (got.fee_rate, got.slippage_rate) != (want.fee_rate, want.slippage_rate):
                raise ValueError(f"cost scenario {got.name!r} rates disagree with the pinned rates")
        if self.bootstrap_algorithm != BOOTSTRAP_ALGORITHM:
            raise ValueError(f"bootstrap_algorithm is pinned to {BOOTSTRAP_ALGORITHM!r}")
        if self.bootstrap_seed != BOOTSTRAP_SEED:
            raise ValueError(f"bootstrap_seed is pinned to {BOOTSTRAP_SEED}")
        if self.bootstrap_block_length != BOOTSTRAP_BLOCK_LENGTH:
            raise ValueError(f"bootstrap_block_length is pinned to {BOOTSTRAP_BLOCK_LENGTH}")
        if self.bootstrap_resamples != BOOTSTRAP_RESAMPLES:
            raise ValueError(f"bootstrap_resamples is pinned to {BOOTSTRAP_RESAMPLES}")
        if require_finite_float("bootstrap_confidence", self.bootstrap_confidence) != (
            BOOTSTRAP_CONFIDENCE
        ):
            raise ValueError(f"bootstrap_confidence is pinned to {BOOTSTRAP_CONFIDENCE}")
        self._validate_folds()

    def _validate_folds(self) -> None:
        if len(self.folds) != self.oos_fold_count:
            raise ValueError(f"expected {self.oos_fold_count} folds, got {len(self.folds)}")
        indices = tuple(fold.fold_index for fold in self.folds)
        if indices != tuple(range(self.oos_fold_count)):
            raise ValueError(f"fold indices must be 0..{self.oos_fold_count - 1}, got {indices}")
        # Expanding training and contiguous, gapless, non-overlapping OOS
        # coverage of exactly rows [initial_training_rows : research_train].
        expected_train = self.initial_training_rows
        total_oos = 0
        previous_last: pd.Timestamp | None = None
        for fold in self.folds:
            if fold.training_row_count != expected_train:
                raise ValueError(
                    f"fold {fold.fold_index}: training_row_count {fold.training_row_count} is not "
                    f"the expanding expectation {expected_train}"
                )
            if fold.oos_last_open_time < fold.oos_first_open_time:
                raise ValueError(f"fold {fold.fold_index}: OOS bounds reversed")
            if previous_last is not None and fold.oos_first_open_time <= previous_last:
                raise ValueError(f"fold {fold.fold_index}: OOS overlaps the previous fold")
            previous_last = fold.oos_last_open_time
            total_oos += fold.oos_row_count
            expected_train += fold.oos_row_count
        if self.initial_training_rows + total_oos != self.research_train_row_count:
            raise ValueError(
                "initial training + OOS rows do not cover the research-train partition exactly"
            )

    def to_json_bytes(self) -> bytes:
        payload = {
            "walk_forward_schema_version": self.walk_forward_schema_version,
            "package_version": self.package_version,
            "development_partition_sha256": self.development_partition_sha256,
            "research_train_content_fingerprint": self.research_train_content_fingerprint,
            "research_train_row_count": self.research_train_row_count,
            "initial_training_rows": self.initial_training_rows,
            "oos_fold_count": self.oos_fold_count,
            "information_gap_bars": self.information_gap_bars,
            "max_context_bars": self.max_context_bars,
            "initial_cash": self.initial_cash,
            "split_semantics": self.split_semantics,
            "strategies": list(self.strategies),
            "cost_scenarios": [_scenario_to_dict(s) for s in self.cost_scenarios],
            "bootstrap_algorithm": self.bootstrap_algorithm,
            "bootstrap_seed": self.bootstrap_seed,
            "bootstrap_block_length": self.bootstrap_block_length,
            "bootstrap_resamples": self.bootstrap_resamples,
            "bootstrap_confidence": self.bootstrap_confidence,
            "folds": [fold.to_json_dict() for fold in self.folds],
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> WalkForwardProtocol:
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"walk-forward protocol is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("walk-forward protocol JSON must be an object")
        keys = set(payload)
        if keys != _PROTOCOL_KEYS:
            unknown = sorted(keys - _PROTOCOL_KEYS)
            missing = sorted(_PROTOCOL_KEYS - keys)
            raise ValueError(
                f"walk-forward protocol keys do not match: unknown={unknown}, missing={missing}"
            )
        for listy in ("strategies", "cost_scenarios", "folds"):
            if not isinstance(payload[listy], list):
                raise ValueError(f"{listy} must be a list")
        return cls(
            walk_forward_schema_version=require_int(
                "walk_forward_schema_version", payload["walk_forward_schema_version"]
            ),
            package_version=require_str("package_version", payload["package_version"]),
            development_partition_sha256=payload["development_partition_sha256"],
            research_train_content_fingerprint=payload["research_train_content_fingerprint"],
            research_train_row_count=require_int(
                "research_train_row_count", payload["research_train_row_count"]
            ),
            initial_training_rows=require_int(
                "initial_training_rows", payload["initial_training_rows"]
            ),
            oos_fold_count=require_int("oos_fold_count", payload["oos_fold_count"]),
            information_gap_bars=require_int(
                "information_gap_bars", payload["information_gap_bars"]
            ),
            max_context_bars=require_int("max_context_bars", payload["max_context_bars"]),
            initial_cash=require_finite_float("initial_cash", payload["initial_cash"]),
            split_semantics=require_str("split_semantics", payload["split_semantics"]),
            strategies=tuple(require_str("strategy", s) for s in payload["strategies"]),
            cost_scenarios=tuple(_scenario_from_dict(s) for s in payload["cost_scenarios"]),
            bootstrap_algorithm=require_str("bootstrap_algorithm", payload["bootstrap_algorithm"]),
            bootstrap_seed=require_int("bootstrap_seed", payload["bootstrap_seed"]),
            bootstrap_block_length=require_int(
                "bootstrap_block_length", payload["bootstrap_block_length"]
            ),
            bootstrap_resamples=require_int("bootstrap_resamples", payload["bootstrap_resamples"]),
            bootstrap_confidence=require_finite_float(
                "bootstrap_confidence", payload["bootstrap_confidence"]
            ),
            folds=tuple(FoldBoundary.from_json_dict(f) for f in payload["folds"]),
        )


@dataclass(frozen=True)
class FoldFrames:
    """The materialized frames for one fold (all within research train)."""

    fold_index: int
    training: pd.DataFrame
    context: pd.DataFrame
    oos: pd.DataFrame


def _even_fold_sizes(total: int, folds: int) -> tuple[int, ...]:
    """Distribute ``total`` rows across ``folds`` as evenly as possible.

    Earlier folds absorb the remainder, so sizes are non-increasing and
    differ by at most one (e.g. 1126 over 5 → 226, 225, 225, 225, 225).
    """
    base, remainder = divmod(total, folds)
    return tuple(base + (1 if i < remainder else 0) for i in range(folds))


def build_fold_boundaries(research_train: pd.DataFrame) -> tuple[FoldBoundary, ...]:
    """Derive the five expanding-window fold boundaries mechanically."""
    if len(research_train) != RESEARCH_TRAIN_ROWS:
        raise WalkForwardError(
            f"walk-forward requires exactly {RESEARCH_TRAIN_ROWS} research-train rows, "
            f"got {len(research_train)}"
        )
    index = research_train.index
    sizes = _even_fold_sizes(RESEARCH_TRAIN_ROWS - INITIAL_TRAINING_ROWS, OOS_FOLD_COUNT)
    boundaries: list[FoldBoundary] = []
    oos_start = INITIAL_TRAINING_ROWS
    for fold_index, size in enumerate(sizes):
        oos_end = oos_start + size
        boundaries.append(
            FoldBoundary(
                fold_index=fold_index,
                training_row_count=oos_start,
                context_row_count=min(MAX_CONTEXT_BARS, oos_start),
                oos_row_count=size,
                oos_first_open_time=index[oos_start],
                oos_last_open_time=index[oos_end - 1],
            )
        )
        oos_start = oos_end
    return tuple(boundaries)


def build_walk_forward_protocol(
    research_train: pd.DataFrame, *, development_partition_sha256: str
) -> WalkForwardProtocol:
    """Derive the pre-registered protocol from the research-train partition."""
    from eth_research.data.provenance import content_fingerprint

    return WalkForwardProtocol(
        walk_forward_schema_version=WALK_FORWARD_SCHEMA_VERSION,
        package_version=__version__,
        development_partition_sha256=development_partition_sha256,
        research_train_content_fingerprint=content_fingerprint(research_train),
        research_train_row_count=len(research_train),
        initial_training_rows=INITIAL_TRAINING_ROWS,
        oos_fold_count=OOS_FOLD_COUNT,
        information_gap_bars=INFORMATION_GAP_BARS,
        max_context_bars=MAX_CONTEXT_BARS,
        initial_cash=INITIAL_CASH,
        split_semantics=SPLIT_SEMANTICS,
        strategies=STRATEGY_NAMES,
        cost_scenarios=COST_SCENARIOS,
        bootstrap_algorithm=BOOTSTRAP_ALGORITHM,
        bootstrap_seed=BOOTSTRAP_SEED,
        bootstrap_block_length=BOOTSTRAP_BLOCK_LENGTH,
        bootstrap_resamples=BOOTSTRAP_RESAMPLES,
        bootstrap_confidence=BOOTSTRAP_CONFIDENCE,
        folds=build_fold_boundaries(research_train),
    )


def build_fold_frames(
    research_train: pd.DataFrame, protocol: WalkForwardProtocol
) -> tuple[FoldFrames, ...]:
    """Materialize each fold's (training, context, OOS) frames by position.

    Context is exactly the ``context_row_count`` rows immediately before the
    OOS block — strictly inside the (expanding) training window, so it never
    touches an OOS row and creates no P&L. The frames are sliced positionally
    from the research-train partition; nothing is shuffled.
    """
    if len(research_train) != protocol.research_train_row_count:
        raise WalkForwardError("research-train frame does not match the protocol row count")
    frames: list[FoldFrames] = []
    for fold in protocol.folds:
        train_end = fold.training_row_count
        oos_end = train_end + fold.oos_row_count
        training = research_train.iloc[:train_end]
        context = research_train.iloc[train_end - fold.context_row_count : train_end]
        oos = research_train.iloc[train_end:oos_end]
        # Positional guarantees: context ends exactly where OOS begins, and
        # the OOS block matches the pre-registered bounds.
        if oos.index[0] != fold.oos_first_open_time or oos.index[-1] != fold.oos_last_open_time:
            raise WalkForwardError(f"fold {fold.fold_index}: OOS frame disagrees with the protocol")
        if len(context) > 0 and context.index[-1] >= oos.index[0]:
            raise WalkForwardError(f"fold {fold.fold_index}: context overlaps the OOS block")
        frames.append(
            FoldFrames(
                fold_index=fold.fold_index,
                training=training.copy(),
                context=context.copy(),
                oos=oos.copy(),
            )
        )
    return tuple(frames)


def load_walk_forward_protocol(path: str | Path) -> WalkForwardProtocol:
    """Strictly parse a committed walk-forward protocol file."""
    file = Path(path)
    try:
        return WalkForwardProtocol.from_json_bytes(file.read_bytes())
    except ValueError as exc:
        raise WalkForwardError(f"invalid walk-forward protocol {file.name!r}: {exc}") from exc
