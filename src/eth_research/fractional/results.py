"""Immutable results model for the Milestone 3B fractional experiment (Phase 16).

``FractionalResults`` is the strict, symmetric record of the one preregistered
run: 75 fold cells (5 strategies x 3 cost scenarios x 5 research-train OOS folds)
and 15 per-(strategy, scenario) aggregates, each re-derivable from the fold cells
so the summary can never drift from the primitives. It binds the frozen protocol,
partition, and dossier, and pins both sealed access-ledger event counts at zero.

No bootstrap, no alpha-significance claim, no scenario/cell omitted for being
ugly. Every number is a reconciled output of ``run_fractional_backtest``.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from typing import Any

import pandas as pd

from eth_research._json import strict_json_loads
from eth_research.fractional.cost_model import SCENARIOS
from eth_research.fractional.protocol import EXPERIMENT_FAMILY
from eth_research.fractional.strategies import STRATEGY_NAMES
from eth_research.fractional.validation import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_nonnegative_int,
    require_positive_int,
    require_real,
    require_str,
    require_tuple,
)
from eth_research.walkforward import OOS_FOLD_COUNT

FRACTIONAL_RESULTS_SCHEMA_VERSION: int = 1
FRACTIONAL_RESULTS_RELPATH: str = "research/m3b/fractional_results.json"
FRACTIONAL_REPORT_RELPATH: str = "research/m3b/fractional_report.md"
_SCENARIO_NAMES: tuple[str, ...] = tuple(s.name for s in SCENARIOS)
_BUY_AND_HOLD: str = "buy_and_hold"
_CASH: str = "cash"


class ResultsError(ValueError):
    """The fractional results failed strict validation."""


def _ts(value: pd.Timestamp) -> str:
    return value.isoformat()


def _opt(value: float | None) -> float | None:
    return None if value is None else float(value)


def _require_list(value: object) -> list[Any]:
    """Decode a JSON array (never coerce a scalar or object into a sequence)."""
    if not isinstance(value, list):
        raise ResultsError(f"expected a JSON array, got {type(value).__name__}")
    return value


@dataclass(frozen=True)
class FractionalFoldCell:
    """One (fold, strategy, cost-scenario) reconciled result."""

    fold_index: int
    strategy: str
    cost_scenario: str
    oos_row_count: int
    oos_first_open_time: pd.Timestamp
    oos_last_open_time: pd.Timestamp
    initial_cash: float
    marked_terminal_equity: float
    terminal_liquidation_equity: float
    marked_total_return: float
    liquidation_total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown: float
    num_fills: int
    num_partial_fills: int
    total_traded_notional: float
    turnover: float
    total_fees: float
    average_achieved_exposure: float
    time_in_market: float

    def to_dict(self) -> dict[str, Any]:
        # Float-typed fields are coerced so serialization is idempotent even when
        # a producer stores an integer value (e.g. ``sum([])`` over empty fills
        # yields ``int 0``); ``from_dict`` always parses these back as floats.
        return {
            "fold_index": self.fold_index,
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "oos_row_count": self.oos_row_count,
            "oos_first_open_time": _ts(self.oos_first_open_time),
            "oos_last_open_time": _ts(self.oos_last_open_time),
            "initial_cash": float(self.initial_cash),
            "marked_terminal_equity": float(self.marked_terminal_equity),
            "terminal_liquidation_equity": float(self.terminal_liquidation_equity),
            "marked_total_return": float(self.marked_total_return),
            "liquidation_total_return": float(self.liquidation_total_return),
            "annualized_return": float(self.annualized_return),
            "annualized_volatility": float(self.annualized_volatility),
            "sharpe_ratio": _opt(self.sharpe_ratio),
            "sortino_ratio": _opt(self.sortino_ratio),
            "max_drawdown": float(self.max_drawdown),
            "num_fills": self.num_fills,
            "num_partial_fills": self.num_partial_fills,
            "total_traded_notional": float(self.total_traded_notional),
            "turnover": float(self.turnover),
            "total_fees": float(self.total_fees),
            "average_achieved_exposure": float(self.average_achieved_exposure),
            "time_in_market": float(self.time_in_market),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FractionalFoldCell:
        if set(payload) != _CELL_KEYS:
            raise ResultsError(f"fold cell keys do not match: {sorted(payload)}")
        sharpe = payload["sharpe_ratio"]
        sortino = payload["sortino_ratio"]
        first_open = require_str("oos_first_open_time", payload["oos_first_open_time"])
        last_open = require_str("oos_last_open_time", payload["oos_last_open_time"])
        return cls(
            fold_index=require_nonnegative_int("fold_index", payload["fold_index"]),
            strategy=require_nonempty_str("strategy", payload["strategy"]),
            cost_scenario=require_nonempty_str("cost_scenario", payload["cost_scenario"]),
            oos_row_count=require_positive_int("oos_row_count", payload["oos_row_count"]),
            oos_first_open_time=pd.Timestamp(first_open),
            oos_last_open_time=pd.Timestamp(last_open),
            initial_cash=require_real("initial_cash", payload["initial_cash"]),
            marked_terminal_equity=require_real(
                "marked_terminal_equity", payload["marked_terminal_equity"]
            ),
            terminal_liquidation_equity=require_real(
                "terminal_liquidation_equity", payload["terminal_liquidation_equity"]
            ),
            marked_total_return=require_real("marked_total_return", payload["marked_total_return"]),
            liquidation_total_return=require_real(
                "liquidation_total_return", payload["liquidation_total_return"]
            ),
            annualized_return=require_real("annualized_return", payload["annualized_return"]),
            annualized_volatility=require_real(
                "annualized_volatility", payload["annualized_volatility"]
            ),
            sharpe_ratio=None if sharpe is None else require_real("sharpe_ratio", sharpe),
            sortino_ratio=None if sortino is None else require_real("sortino_ratio", sortino),
            max_drawdown=require_real("max_drawdown", payload["max_drawdown"]),
            num_fills=require_nonnegative_int("num_fills", payload["num_fills"]),
            num_partial_fills=require_nonnegative_int(
                "num_partial_fills", payload["num_partial_fills"]
            ),
            total_traded_notional=require_real(
                "total_traded_notional", payload["total_traded_notional"]
            ),
            turnover=require_real("turnover", payload["turnover"]),
            total_fees=require_real("total_fees", payload["total_fees"]),
            average_achieved_exposure=require_real(
                "average_achieved_exposure", payload["average_achieved_exposure"]
            ),
            time_in_market=require_real("time_in_market", payload["time_in_market"]),
        )


_CELL_KEYS = frozenset(
    {
        "fold_index",
        "strategy",
        "cost_scenario",
        "oos_row_count",
        "oos_first_open_time",
        "oos_last_open_time",
        "initial_cash",
        "marked_terminal_equity",
        "terminal_liquidation_equity",
        "marked_total_return",
        "liquidation_total_return",
        "annualized_return",
        "annualized_volatility",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown",
        "num_fills",
        "num_partial_fills",
        "total_traded_notional",
        "turnover",
        "total_fees",
        "average_achieved_exposure",
        "time_in_market",
    }
)


@dataclass(frozen=True)
class FractionalAggregate:
    """Per-(strategy, cost-scenario) summary re-derived from the five folds."""

    strategy: str
    cost_scenario: str
    fold_count: int
    median_marked_return: float
    median_liquidation_return: float
    worst_max_drawdown: float
    median_sharpe_ratio: float | None
    median_turnover: float
    total_fills: int
    median_average_exposure: float
    fraction_positive_marked_folds: float
    fraction_beating_buy_and_hold: float
    fraction_beating_cash: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "fold_count": self.fold_count,
            "median_marked_return": float(self.median_marked_return),
            "median_liquidation_return": float(self.median_liquidation_return),
            "worst_max_drawdown": float(self.worst_max_drawdown),
            "median_sharpe_ratio": _opt(self.median_sharpe_ratio),
            "median_turnover": float(self.median_turnover),
            "total_fills": self.total_fills,
            "median_average_exposure": float(self.median_average_exposure),
            "fraction_positive_marked_folds": float(self.fraction_positive_marked_folds),
            "fraction_beating_buy_and_hold": float(self.fraction_beating_buy_and_hold),
            "fraction_beating_cash": float(self.fraction_beating_cash),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FractionalAggregate:
        if set(payload) != _AGG_KEYS:
            raise ResultsError(f"aggregate keys do not match: {sorted(payload)}")
        median_sharpe = payload["median_sharpe_ratio"]
        return cls(
            strategy=require_nonempty_str("strategy", payload["strategy"]),
            cost_scenario=require_nonempty_str("cost_scenario", payload["cost_scenario"]),
            fold_count=require_positive_int("fold_count", payload["fold_count"]),
            median_marked_return=require_real(
                "median_marked_return", payload["median_marked_return"]
            ),
            median_liquidation_return=require_real(
                "median_liquidation_return", payload["median_liquidation_return"]
            ),
            worst_max_drawdown=require_real("worst_max_drawdown", payload["worst_max_drawdown"]),
            median_sharpe_ratio=(
                None
                if median_sharpe is None
                else require_real("median_sharpe_ratio", median_sharpe)
            ),
            median_turnover=require_real("median_turnover", payload["median_turnover"]),
            total_fills=require_nonnegative_int("total_fills", payload["total_fills"]),
            median_average_exposure=require_real(
                "median_average_exposure", payload["median_average_exposure"]
            ),
            fraction_positive_marked_folds=require_real(
                "fraction_positive_marked_folds", payload["fraction_positive_marked_folds"]
            ),
            fraction_beating_buy_and_hold=require_real(
                "fraction_beating_buy_and_hold", payload["fraction_beating_buy_and_hold"]
            ),
            fraction_beating_cash=require_real(
                "fraction_beating_cash", payload["fraction_beating_cash"]
            ),
        )


_AGG_KEYS = frozenset(
    {
        "strategy",
        "cost_scenario",
        "fold_count",
        "median_marked_return",
        "median_liquidation_return",
        "worst_max_drawdown",
        "median_sharpe_ratio",
        "median_turnover",
        "total_fills",
        "median_average_exposure",
        "fraction_positive_marked_folds",
        "fraction_beating_buy_and_hold",
        "fraction_beating_cash",
    }
)


def _median_optional(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return float(statistics.median(present)) if present else None


def build_aggregates(cells: tuple[FractionalFoldCell, ...]) -> tuple[FractionalAggregate, ...]:
    """Re-derive the per-(strategy, scenario) aggregates from the fold cells."""
    by_cell = {(c.strategy, c.cost_scenario, c.fold_index): c for c in cells}
    aggregates: list[FractionalAggregate] = []
    for scenario in _SCENARIO_NAMES:
        for strategy in STRATEGY_NAMES:
            group = sorted(
                (c for c in cells if c.strategy == strategy and c.cost_scenario == scenario),
                key=lambda c: c.fold_index,
            )
            marked = [c.marked_total_return for c in group]
            bnh = [
                by_cell[(_BUY_AND_HOLD, scenario, c.fold_index)].marked_total_return for c in group
            ]
            cash = [by_cell[(_CASH, scenario, c.fold_index)].marked_total_return for c in group]
            aggregates.append(
                FractionalAggregate(
                    strategy=strategy,
                    cost_scenario=scenario,
                    fold_count=len(group),
                    median_marked_return=float(statistics.median(marked)),
                    median_liquidation_return=float(
                        statistics.median([c.liquidation_total_return for c in group])
                    ),
                    worst_max_drawdown=min(c.max_drawdown for c in group),
                    median_sharpe_ratio=_median_optional([c.sharpe_ratio for c in group]),
                    median_turnover=float(statistics.median([c.turnover for c in group])),
                    total_fills=sum(c.num_fills for c in group),
                    median_average_exposure=float(
                        statistics.median([c.average_achieved_exposure for c in group])
                    ),
                    fraction_positive_marked_folds=sum(1 for r in marked if r > 0.0) / len(group),
                    fraction_beating_buy_and_hold=sum(
                        1 for r, b in zip(marked, bnh, strict=True) if r > b
                    )
                    / len(group),
                    fraction_beating_cash=sum(1 for r, c in zip(marked, cash, strict=True) if r > c)
                    / len(group),
                )
            )
    return tuple(aggregates)


@dataclass(frozen=True)
class FractionalResults:
    """The immutable, strict record of the one preregistered fractional run."""

    fractional_results_schema_version: int
    experiment_id: str
    experiment_family: str
    package_version: str
    execution_code_commit_sha: str
    registered_code_commit_sha: str
    execution_source_tree_fingerprint: str
    fractional_protocol_path: str
    fractional_protocol_sha256: str
    frozen_m2_dossier_sha256: str
    development_partition_sha256: str
    research_train_content_fingerprint: str
    strategies: tuple[str, ...]
    cost_scenarios: tuple[str, ...]
    fold_cells: tuple[FractionalFoldCell, ...]
    aggregates: tuple[FractionalAggregate, ...]
    development_gate_event_count: int
    final_holdout_event_count: int

    def __post_init__(self) -> None:
        if self.fractional_results_schema_version != FRACTIONAL_RESULTS_SCHEMA_VERSION:
            raise ResultsError("unexpected schema version")
        if self.experiment_family != EXPERIMENT_FAMILY:
            raise ResultsError("wrong experiment family")
        if not self.experiment_id.startswith(EXPERIMENT_FAMILY):
            raise ResultsError("experiment_id must belong to the family")
        if self.strategies != STRATEGY_NAMES:
            raise ResultsError("strategies must match the five pinned strategies")
        if self.cost_scenarios != _SCENARIO_NAMES:
            raise ResultsError("cost scenarios must match the three frozen scenarios")
        if self.development_gate_event_count != 0 or self.final_holdout_event_count != 0:
            raise ResultsError("both sealed access ledgers must have zero events")
        require_hex64("frozen_m2_dossier_sha256", self.frozen_m2_dossier_sha256)
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        require_hex64("fractional_protocol_sha256", self.fractional_protocol_sha256)
        self._validate_grid()

    def _validate_grid(self) -> None:
        expected = {
            (strategy, scenario, fold)
            for strategy in STRATEGY_NAMES
            for scenario in _SCENARIO_NAMES
            for fold in range(OOS_FOLD_COUNT)
        }
        seen = {(c.strategy, c.cost_scenario, c.fold_index) for c in self.fold_cells}
        if len(self.fold_cells) != len(expected):
            raise ResultsError(f"expected {len(expected)} fold cells, got {len(self.fold_cells)}")
        if seen != expected:
            raise ResultsError("fold cells do not cover the exact (strategy, scenario, fold) grid")
        for cell in self.fold_cells:
            if not (-1.0 <= cell.max_drawdown <= 0.0):
                raise ResultsError(f"max_drawdown out of [-1, 0]: {cell.max_drawdown!r}")
            if not (-1e-9 <= cell.average_achieved_exposure <= 1.0 + 1e-9):
                raise ResultsError("average exposure out of [0, 1]")
            if cell.marked_terminal_equity <= 0.0:
                raise ResultsError("non-positive terminal equity")
            if cell.terminal_liquidation_equity > cell.marked_terminal_equity + 1e-6:
                raise ResultsError("liquidation equity exceeds marked equity")
        rederived = build_aggregates(self.fold_cells)
        if tuple(a.to_dict() for a in self.aggregates) != tuple(a.to_dict() for a in rederived):
            raise ResultsError("aggregates do not re-derive from the fold cells")

    def to_json_bytes(self) -> bytes:
        payload = {
            "fractional_results_schema_version": self.fractional_results_schema_version,
            "experiment_id": self.experiment_id,
            "experiment_family": self.experiment_family,
            "package_version": self.package_version,
            "execution_code_commit_sha": self.execution_code_commit_sha,
            "registered_code_commit_sha": self.registered_code_commit_sha,
            "execution_source_tree_fingerprint": self.execution_source_tree_fingerprint,
            "fractional_protocol_path": self.fractional_protocol_path,
            "fractional_protocol_sha256": self.fractional_protocol_sha256,
            "frozen_m2_dossier_sha256": self.frozen_m2_dossier_sha256,
            "development_partition_sha256": self.development_partition_sha256,
            "research_train_content_fingerprint": self.research_train_content_fingerprint,
            "strategies": list(self.strategies),
            "cost_scenarios": list(self.cost_scenarios),
            "fold_cells": [c.to_dict() for c in self.fold_cells],
            "aggregates": [a.to_dict() for a in self.aggregates],
            "development_gate_event_count": self.development_gate_event_count,
            "final_holdout_event_count": self.final_holdout_event_count,
        }
        return (
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n"
        ).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> FractionalResults:
        payload = strict_json_loads(raw)
        if not isinstance(payload, dict) or set(payload) != _RESULTS_KEYS:
            raise ResultsError("results keys do not match the schema")
        cells = tuple(FractionalFoldCell.from_dict(c) for c in _require_list(payload["fold_cells"]))
        aggregates = tuple(
            FractionalAggregate.from_dict(a) for a in _require_list(payload["aggregates"])
        )
        return cls(
            fractional_results_schema_version=require_int(
                "fractional_results_schema_version", payload["fractional_results_schema_version"]
            ),
            experiment_id=require_nonempty_str("experiment_id", payload["experiment_id"]),
            experiment_family=require_nonempty_str(
                "experiment_family", payload["experiment_family"]
            ),
            package_version=require_nonempty_str("package_version", payload["package_version"]),
            execution_code_commit_sha=require_str(
                "execution_code_commit_sha", payload["execution_code_commit_sha"]
            ),
            registered_code_commit_sha=require_str(
                "registered_code_commit_sha", payload["registered_code_commit_sha"]
            ),
            execution_source_tree_fingerprint=require_nonempty_str(
                "execution_source_tree_fingerprint", payload["execution_source_tree_fingerprint"]
            ),
            fractional_protocol_path=require_nonempty_str(
                "fractional_protocol_path", payload["fractional_protocol_path"]
            ),
            fractional_protocol_sha256=require_hex64(
                "fractional_protocol_sha256", payload["fractional_protocol_sha256"]
            ),
            frozen_m2_dossier_sha256=require_hex64(
                "frozen_m2_dossier_sha256", payload["frozen_m2_dossier_sha256"]
            ),
            development_partition_sha256=require_hex64(
                "development_partition_sha256", payload["development_partition_sha256"]
            ),
            research_train_content_fingerprint=require_nonempty_str(
                "research_train_content_fingerprint", payload["research_train_content_fingerprint"]
            ),
            strategies=require_tuple("strategies", payload["strategies"], require_nonempty_str),
            cost_scenarios=require_tuple(
                "cost_scenarios", payload["cost_scenarios"], require_nonempty_str
            ),
            fold_cells=cells,
            aggregates=aggregates,
            development_gate_event_count=require_nonnegative_int(
                "development_gate_event_count", payload["development_gate_event_count"]
            ),
            final_holdout_event_count=require_nonnegative_int(
                "final_holdout_event_count", payload["final_holdout_event_count"]
            ),
        )


_RESULTS_KEYS = frozenset(
    {
        "fractional_results_schema_version",
        "experiment_id",
        "experiment_family",
        "package_version",
        "execution_code_commit_sha",
        "registered_code_commit_sha",
        "execution_source_tree_fingerprint",
        "fractional_protocol_path",
        "fractional_protocol_sha256",
        "frozen_m2_dossier_sha256",
        "development_partition_sha256",
        "research_train_content_fingerprint",
        "strategies",
        "cost_scenarios",
        "fold_cells",
        "aggregates",
        "development_gate_event_count",
        "final_holdout_event_count",
    }
)


def _pct(value: float) -> str:
    return f"{value * 100.0:+.2f}%"


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_fractional_report(results: FractionalResults) -> str:
    """Render the Markdown report purely from the validated results model.

    Deterministic: a fresh clone renders identical bytes from the committed
    results, so replay byte-compares it. Every reported number is a field of a
    reconciled fold cell or a re-derivable aggregate — the renderer computes
    nothing new. Losing folds and severe-cost failures are shown exactly as
    computed; no cell is omitted for being inconvenient.
    """
    lines: list[str] = []
    add = lines.append
    agg_by = {(a.strategy, a.cost_scenario): a for a in results.aggregates}
    cells_by = {(c.strategy, c.cost_scenario, c.fold_index): c for c in results.fold_cells}
    folds = sorted({c.fold_index for c in results.fold_cells})

    add("# Milestone 3B fractional execution-risk report (run-001)")
    add("")
    add("## 1. Research-only disclaimer")
    add("")
    add(
        "> Research observations on historical data — **not** a profitability claim, "
        "**not** expected future returns, and **not** investment advice. No alpha is "
        "claimed and nothing was optimized: the five strategies, three cost scenarios, "
        "and every tolerance were fixed and pre-registered before this single execution. "
        "The spread, slippage, and market-impact terms are transparent deterministic "
        "proxies driven by lagged liquidity — they are **not** venue-calibrated and make "
        "no empirical accuracy claim. This engine cannot and does not move money."
    )
    add("")
    add(f"- Experiment id: `{results.experiment_id}`")
    add(f"- Experiment family: `{results.experiment_family}`")
    add(f"- Recorded package version: `{results.package_version}`")
    add(f"- Registered code commit: `{results.registered_code_commit_sha}`")
    add(f"- Execution code commit: `{results.execution_code_commit_sha}`")
    add(f"- Execution source-tree fingerprint: `{results.execution_source_tree_fingerprint}`")
    add(f"- Pre-registered protocol: `{results.fractional_protocol_path}`")
    add(f"- Protocol digest: `{results.fractional_protocol_sha256}`")
    add("")
    add("## 2. Data-access boundaries")
    add("")
    add("| level | dates (UTC) | rows | M3B access |")
    add("| --- | --- | ---: | --- |")
    add("| research train | 2016-05-23 .. 2022-06-21 | 2221 | evaluated |")
    add("| development gate | 2022-06-22 .. 2024-06-30 | 740 | **not evaluated (forbidden)** |")
    add("| final holdout | 2024-07-01 .. 2026-07-11 | 741 | **not evaluated (forbidden)** |")
    add("")
    add(
        f"- Development-gate ledger events: **{results.development_gate_event_count}** "
        f"(byte-empty). Final-holdout ledger events: **{results.final_holdout_event_count}** "
        "(byte-empty). Only the five research-train rolling-origin OOS folds are evaluated; "
        "no estimator is fit and no parameter is selected on any observed output."
    )
    add(f"- Research-train content fingerprint: `{results.research_train_content_fingerprint}`")
    add("")
    add("## 3. Execution model")
    add("")
    add(
        "Each cell is a fractional long-only cash/ETH backtest. Orders execute at the "
        "**next** bar's reference open (decision at bar `t` fills at `open[t]`), liquidity "
        "is estimated only from rows strictly before the fill bar (no same-bar volume), and "
        "a deterministic partial fill applies when the target exceeds the participation cap. "
        "Costs decompose into explicit fee, half-spread, base slippage, and lagged-liquidity "
        "market-impact terms. `compatibility_v1` reproduces the binary Milestone 3A engine "
        "bit-for-bit; `causal_proxy_base` and `causal_proxy_stressed` add the causal "
        "liquidity/impact overlay at two severities. Returns are shown both marked to the "
        "final close and after a modeled terminal liquidation."
    )
    add("")
    add("## 4. Per-(strategy, scenario) aggregates over the five folds")
    add("")
    for scenario in results.cost_scenarios:
        add(f"### {scenario}")
        add("")
        add(
            "| strategy | median marked | median liquidation | worst drawdown | "
            "median Sharpe | median turnover | median exposure | +folds | > B&H | > cash |"
        )
        add("| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
        for strategy in results.strategies:
            a = agg_by[(strategy, scenario)]
            add(
                f"| {strategy} | {_pct(a.median_marked_return)} | "
                f"{_pct(a.median_liquidation_return)} | {_pct(a.worst_max_drawdown)} | "
                f"{_ratio(a.median_sharpe_ratio)} | {a.median_turnover:.2f}x | "
                f"{a.median_average_exposure:.0%} | "
                f"{a.fraction_positive_marked_folds:.0%} | "
                f"{a.fraction_beating_buy_and_hold:.0%} | "
                f"{a.fraction_beating_cash:.0%} |"
            )
        add("")
    add("## 5. Full fold grid (marked total return)")
    add("")
    add(
        "Every one of the 75 (strategy, scenario, fold) cells, shown as computed. Fold "
        "windows are the pre-registered rolling-origin OOS segments; losing folds are "
        "retained verbatim."
    )
    add("")
    for scenario in results.cost_scenarios:
        add(f"### {scenario}")
        add("")
        header = "| strategy | " + " | ".join(f"fold {i}" for i in folds) + " |"
        add(header)
        add("| --- | " + " | ".join("---:" for _ in folds) + " |")
        for strategy in results.strategies:
            row = [strategy]
            for fold in folds:
                row.append(_pct(cells_by[(strategy, scenario, fold)].marked_total_return))
            add("| " + " | ".join(row) + " |")
        add("")
    add("## 6. Honest reading")
    add("")
    add(
        "This is a single in-sample research-train execution, not live or test performance. "
        "The cost scenarios shrink net return monotonically in the modeled frictions, the "
        "vol-target strategies trade more and pay more, and buy-and-hold is hard to beat over "
        "this ETH bull-market window — every cell, including the unflattering ones, is "
        "reported. No alpha is claimed, nothing was tuned, no cell was dropped, no bootstrap "
        "or significance test was run, and no candidate is promoted. The development gate and "
        "the final holdout remain sealed and byte-empty."
    )
    add("")
    return "\n".join(lines) + "\n"


def load_fractional_results(path: str) -> FractionalResults:
    """Strictly parse a committed fractional results file."""
    from pathlib import Path

    from eth_research._json import require_canonical_file_bytes

    raw = require_canonical_file_bytes(Path(path).read_bytes(), "fractional results")
    return FractionalResults.from_json_bytes(raw)
