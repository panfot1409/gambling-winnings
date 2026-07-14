"""Deterministic per-run OOS return evidence (Milestone 3A closure, Phase 9).

The v1 development results published summary statistics but not the raw daily
observations they were computed from, so a reader could not independently
re-derive the pooled diagnostics or the bootstrap inputs. This artifact closes
that gap: for the corrective run-003 it records, per (strategy, cost scenario,
fold), the exact daily **out-of-sample net-return vector** on the research-train
partition, aligned to a per-fold timestamp axis shared by every strategy and
scenario.

From this artifact alone every pooled-reset diagnostic and every bootstrap
paired-excess input can be recomputed, and it can be reconciled byte-for-byte
against a fresh engine replay. It exposes **no** development-gate or
final-holdout value: every observation timestamp is strictly before the
development gate (2022-06-22 UTC), and the builder derives the vectors only
from research-train fold evaluations.

Size tradeoff: the artifact stores every daily OOS return (five folds x four
strategies x three scenarios, about 13.5k floats). It is therefore serialized
compactly (sorted keys, no indentation, ``allow_nan=False``) and verified by
hash rather than eyeball; the exactness it buys — independent re-derivation of
every pooled and bootstrap number — is worth the bytes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from eth_research._json import StrictJSONError, require_canonical_file_bytes, strict_json_loads
from eth_research.data.provenance import require_int, require_str, sha256_bytes
from eth_research.data.validation import (
    require_evaluation_id,
    require_finite_float,
    require_positive_int,
    require_utc_timestamp,
)

RETURN_EVIDENCE_SCHEMA_VERSION: int = 1

# The development gate opens 2022-06-22 UTC; every research-train OOS observation
# must be strictly before it. This is the return-evidence firewall.
DEVELOPMENT_GATE_FIRST_DAY: pd.Timestamp = pd.Timestamp("2022-06-22T00:00:00+00:00")


class ReturnEvidenceError(RuntimeError):
    """The return-evidence artifact is invalid or fails reconciliation."""


def _parse_ts(label: str, value: object) -> pd.Timestamp:
    text = require_str(label, value)
    try:
        ts = pd.Timestamp(text)
    except ValueError as exc:
        raise ValueError(f"{label} is unparseable: {text!r}") from exc
    return require_utc_timestamp(label, ts)


_AXIS_KEYS: frozenset[str] = frozenset({"fold_index", "oos_open_times"})
_SERIES_KEYS: frozenset[str] = frozenset({"strategy", "cost_scenario", "fold_index", "net_returns"})
_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {
        "return_evidence_schema_version",
        "experiment_id",
        "periods_per_year",
        "research_train_last_open_time",
        "strategies",
        "cost_scenarios",
        "fold_axes",
        "series",
    }
)


@dataclass(frozen=True)
class FoldReturnAxis:
    """The shared OOS open-time axis for one fold (all series align to it)."""

    fold_index: int
    oos_open_times: tuple[pd.Timestamp, ...]

    def __post_init__(self) -> None:
        require_int("fold_index", self.fold_index)
        if self.fold_index < 0:
            raise ValueError("fold_index must be non-negative")
        if not self.oos_open_times:
            raise ValueError(f"fold {self.fold_index}: empty OOS axis")
        previous: pd.Timestamp | None = None
        for ts in self.oos_open_times:
            require_utc_timestamp("oos_open_time", ts)
            if ts >= DEVELOPMENT_GATE_FIRST_DAY:
                raise ValueError(
                    f"fold {self.fold_index}: OOS open time {ts.isoformat()} is on or after the "
                    "development gate — a forbidden observation cannot appear in return evidence"
                )
            if previous is not None and ts <= previous:
                raise ValueError(f"fold {self.fold_index}: OOS open times must strictly increase")
            previous = ts

    def oos_open_times_index(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(list(self.oos_open_times))

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "oos_open_times": [ts.isoformat() for ts in self.oos_open_times],
        }

    @classmethod
    def from_json_dict(cls, payload: Any) -> FoldReturnAxis:
        if not isinstance(payload, dict) or set(payload) != _AXIS_KEYS:
            raise ValueError("fold axis keys do not match schema")
        times = payload["oos_open_times"]
        if not isinstance(times, list):
            raise ValueError("oos_open_times must be a list")
        return cls(
            fold_index=require_int("fold_index", payload["fold_index"]),
            oos_open_times=tuple(_parse_ts("oos_open_time", t) for t in times),
        )


@dataclass(frozen=True)
class ReturnSeries:
    """One (strategy, scenario, fold) daily OOS net-return vector."""

    strategy: str
    cost_scenario: str
    fold_index: int
    net_returns: tuple[float, ...]

    def __post_init__(self) -> None:
        require_str("strategy", self.strategy)
        require_str("cost_scenario", self.cost_scenario)
        require_int("fold_index", self.fold_index)
        if self.fold_index < 0:
            raise ValueError("fold_index must be non-negative")
        if not self.net_returns:
            raise ValueError("net_returns must be non-empty")
        for value in self.net_returns:
            require_finite_float("net_return", value)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "fold_index": self.fold_index,
            "net_returns": list(self.net_returns),
        }

    @classmethod
    def from_json_dict(cls, payload: Any) -> ReturnSeries:
        if not isinstance(payload, dict) or set(payload) != _SERIES_KEYS:
            raise ValueError("return series keys do not match schema")
        values = payload["net_returns"]
        if not isinstance(values, list):
            raise ValueError("net_returns must be a list")
        return cls(
            strategy=require_str("strategy", payload["strategy"]),
            cost_scenario=require_str("cost_scenario", payload["cost_scenario"]),
            fold_index=require_int("fold_index", payload["fold_index"]),
            net_returns=tuple(require_finite_float("net_return", v) for v in values),
        )


@dataclass(frozen=True)
class ReturnEvidence:
    """Per-run OOS return evidence; symmetric strict construct/parse."""

    return_evidence_schema_version: int
    experiment_id: str
    periods_per_year: float
    research_train_last_open_time: pd.Timestamp
    strategies: tuple[str, ...]
    cost_scenarios: tuple[str, ...]
    fold_axes: tuple[FoldReturnAxis, ...]
    series: tuple[ReturnSeries, ...]

    def __post_init__(self) -> None:
        if self.return_evidence_schema_version != RETURN_EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                f"return_evidence_schema_version is pinned to {RETURN_EVIDENCE_SCHEMA_VERSION}"
            )
        require_evaluation_id("experiment_id", self.experiment_id)
        require_finite_float("periods_per_year", self.periods_per_year)
        if self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be positive")
        require_utc_timestamp("research_train_last_open_time", self.research_train_last_open_time)
        if self.research_train_last_open_time >= DEVELOPMENT_GATE_FIRST_DAY:
            raise ValueError("research_train_last_open_time must precede the development gate")
        if not self.strategies:
            raise ValueError("strategies must be non-empty")
        if not self.cost_scenarios:
            raise ValueError("cost_scenarios must be non-empty")
        self._validate_grid()

    def _validate_grid(self) -> None:
        fold_count = len(self.fold_axes)
        if tuple(a.fold_index for a in self.fold_axes) != tuple(range(fold_count)):
            raise ValueError("fold_axes indices must be 0..K-1 in order")
        axis_len = {a.fold_index: len(a.oos_open_times) for a in self.fold_axes}
        # Series must be the exact canonical grid: scenario-major, strategy, fold.
        expected: list[tuple[str, str, int]] = [
            (strategy, scenario, fold)
            for scenario in self.cost_scenarios
            for strategy in self.strategies
            for fold in range(fold_count)
        ]
        actual = [(s.strategy, s.cost_scenario, s.fold_index) for s in self.series]
        if actual != expected:
            raise ValueError(
                "return series are not the exact canonical (scenario, strategy, fold) grid"
            )
        for s in self.series:
            if len(s.net_returns) != axis_len[s.fold_index]:
                raise ValueError(
                    f"series ({s.strategy},{s.cost_scenario},fold {s.fold_index}) has "
                    f"{len(s.net_returns)} returns but its fold axis has {axis_len[s.fold_index]}"
                )

    # --- Re-derivation helpers ------------------------------------------------

    def _series(self, strategy: str, scenario: str) -> tuple[ReturnSeries, ...]:
        found = tuple(
            s for s in self.series if s.strategy == strategy and s.cost_scenario == scenario
        )
        if len(found) != len(self.fold_axes):
            raise ReturnEvidenceError(f"no complete series for ({strategy}, {scenario})")
        return tuple(sorted(found, key=lambda s: s.fold_index))

    def pooled_series(self, strategy: str, scenario: str) -> pd.Series[float]:
        """The concatenated daily OOS return series (fold order), timestamp-indexed."""
        axis_by_fold = {a.fold_index: a.oos_open_times for a in self.fold_axes}
        values: list[float] = []
        index: list[pd.Timestamp] = []
        for s in self._series(strategy, scenario):
            values.extend(s.net_returns)
            index.extend(axis_by_fold[s.fold_index])
        return pd.Series(values, index=pd.DatetimeIndex(index), dtype=float)

    def pooled_returns(self, strategy: str, scenario: str) -> np.ndarray:
        return self.pooled_series(strategy, scenario).to_numpy(dtype=float)

    def fold_series(self, strategy: str, scenario: str) -> tuple[pd.Series[float], ...]:
        """The per-fold daily OOS return series (fold order), each timestamp-indexed."""
        axis_by_fold = {a.fold_index: a.oos_open_times_index() for a in self.fold_axes}
        return tuple(
            pd.Series(list(s.net_returns), index=axis_by_fold[s.fold_index], dtype=float)
            for s in self._series(strategy, scenario)
        )

    def to_json_bytes(self) -> bytes:
        payload = {
            "return_evidence_schema_version": self.return_evidence_schema_version,
            "experiment_id": self.experiment_id,
            "periods_per_year": self.periods_per_year,
            "research_train_last_open_time": self.research_train_last_open_time.isoformat(),
            "strategies": list(self.strategies),
            "cost_scenarios": list(self.cost_scenarios),
            "fold_axes": [a.to_json_dict() for a in self.fold_axes],
            "series": [s.to_json_dict() for s in self.series],
        }
        text = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return (text + "\n").encode("utf-8")

    def content_sha256(self) -> str:
        return sha256_bytes(self.to_json_bytes())

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> ReturnEvidence:
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"return evidence is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("return evidence JSON must be an object")
        keys = set(payload)
        if keys != _EVIDENCE_KEYS:
            unknown = sorted(keys - _EVIDENCE_KEYS)
            missing = sorted(_EVIDENCE_KEYS - keys)
            raise ValueError(
                f"return evidence keys do not match: unknown={unknown}, missing={missing}"
            )
        for listy in ("strategies", "cost_scenarios", "fold_axes", "series"):
            if not isinstance(payload[listy], list):
                raise ValueError(f"{listy} must be a list")
        return cls(
            return_evidence_schema_version=require_int(
                "return_evidence_schema_version", payload["return_evidence_schema_version"]
            ),
            experiment_id=require_str("experiment_id", payload["experiment_id"]),
            periods_per_year=require_finite_float("periods_per_year", payload["periods_per_year"]),
            research_train_last_open_time=_parse_ts(
                "research_train_last_open_time", payload["research_train_last_open_time"]
            ),
            strategies=tuple(require_str("strategy", s) for s in payload["strategies"]),
            cost_scenarios=tuple(
                require_str("cost_scenario", s) for s in payload["cost_scenarios"]
            ),
            fold_axes=tuple(FoldReturnAxis.from_json_dict(a) for a in payload["fold_axes"]),
            series=tuple(ReturnSeries.from_json_dict(s) for s in payload["series"]),
        )


def build_return_evidence(
    *,
    experiment_id: str,
    periods_per_year: float,
    research_train_last_open_time: pd.Timestamp,
    strategies: tuple[str, ...],
    cost_scenarios: tuple[str, ...],
    fold_returns: dict[tuple[str, str], list[pd.Series[float]]],
) -> ReturnEvidence:
    """Assemble return evidence from per-(strategy,scenario) fold return series.

    ``fold_returns`` maps ``(strategy, cost_scenario)`` to the list of daily OOS
    return series (one per fold, in fold order) as produced by the evaluator.
    All series for a given fold must share the same timestamp index (they are
    the fold's OOS bars), which becomes that fold's shared axis. Positive
    ``require_positive_int`` fold count is enforced by the grid validator.
    """
    fold_count = len(next(iter(fold_returns.values())))
    require_positive_int("fold_count", fold_count)
    # Derive each fold's shared axis from the buy_and_hold+base series if present,
    # else the first available series, and require every series to match it.
    reference_key = next(iter(fold_returns))
    axes: list[FoldReturnAxis] = []
    for fold in range(fold_count):
        axis_index = fold_returns[reference_key][fold].index
        axes.append(
            FoldReturnAxis(
                fold_index=fold,
                oos_open_times=tuple(pd.Timestamp(ts) for ts in axis_index),
            )
        )
    series: list[ReturnSeries] = []
    for scenario in cost_scenarios:
        for strategy in strategies:
            fold_series = fold_returns[(strategy, scenario)]
            if len(fold_series) != fold_count:
                raise ReturnEvidenceError(
                    f"({strategy}, {scenario}) has {len(fold_series)} folds, expected {fold_count}"
                )
            for fold in range(fold_count):
                s = fold_series[fold]
                if not s.index.equals(axes[fold].oos_open_times_index()):
                    raise ReturnEvidenceError(
                        f"({strategy}, {scenario}) fold {fold} index disagrees with the fold axis"
                    )
                series.append(
                    ReturnSeries(
                        strategy=strategy,
                        cost_scenario=scenario,
                        fold_index=fold,
                        net_returns=tuple(float(v) for v in s.to_numpy(dtype=float)),
                    )
                )
    return ReturnEvidence(
        return_evidence_schema_version=RETURN_EVIDENCE_SCHEMA_VERSION,
        experiment_id=experiment_id,
        periods_per_year=float(periods_per_year),
        research_train_last_open_time=research_train_last_open_time,
        strategies=strategies,
        cost_scenarios=cost_scenarios,
        fold_axes=tuple(axes),
        series=tuple(series),
    )


def load_return_evidence(path: str | Path) -> ReturnEvidence:
    """Strictly parse a committed return-evidence artifact."""
    raw = Path(path).read_bytes()
    try:
        require_canonical_file_bytes(raw, "return evidence")
        return ReturnEvidence.from_json_bytes(raw)
    except ValueError as exc:
        raise ReturnEvidenceError(f"invalid return evidence: {exc}") from exc
