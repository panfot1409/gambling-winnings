"""Strict, byte-stable result models for the one Milestone 3C candidate run.

``M3CResults`` is the immutable record of the single preregistered experiment on
the research-train partition: 75 fold cells (5 strategies x 3 cost scenarios x 5
OOS folds), 15 per-(strategy, scenario) aggregates re-derived from those cells,
the five ``causal_proxy_base`` candidate-vs-buy-and-hold paired comparisons, the
frozen primary bootstrap interval, and the fragile secondary Probabilistic
Sharpe diagnostic. Every aggregate reconciles from the fold cells and every
cell's modeled-cost total reconciles from its own additive decomposition, so a
published summary can never drift from the primitives it claims to summarize.

This module mirrors the reviewed Milestone 3B results model exactly: exact key
sets, decode-not-repair strict parsing (``bool`` is not an int, non-finite reals
are rejected, undefined ratios are ``null`` only), canonical sorted-key JSON with
a trailing newline, byte-stable ``to_json_bytes``/``from_json_bytes``, and
reconcile-before-serialize. It computes no financial number the engine did not
already produce, drops no losing cell, and pins both sealed access-ledger event
counts at zero. Nothing here is an alpha claim.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from eth_research._json import require_canonical_file_bytes
from eth_research.data.provenance import content_fingerprint
from eth_research.fractional.cost_model import SCENARIOS, SCENARIOS_BY_NAME, CostScenario
from eth_research.fractional.engine import FractionalBacktestResult
from eth_research.m3c.candidate import M3C_CANDIDATE_ID, M3C_STRATEGY_NAMES
from eth_research.m3c.experiment import M3CCellRun
from eth_research.m3c.statistics import (
    M3C_BOOTSTRAP_ALGORITHM,
    M3C_BOOTSTRAP_CONFIDENCE,
    BootstrapResult,
    ProbabilisticSharpe,
    paired_log_excess,
)
from eth_research.m3c.validation import (
    canonical_json_bytes,
    require_bool,
    require_exact_keys,
    require_hex64,
    require_int,
    require_mapping,
    require_nonempty_str,
    require_nonnegative_int,
    require_nonnegative_real,
    require_positive_int,
    require_positive_real,
    require_real,
    require_safe_relative_path,
    require_sha256_fingerprint,
    require_str,
    require_tuple,
    strict_json_loads,
)
from eth_research.walkforward import OOS_FOLD_COUNT, WalkForwardProtocol

if TYPE_CHECKING:  # pragma: no cover - type-only import (breaks the results<->decision cycle)
    from eth_research.m3c.decision import CandidateDecision

M3C_RESULTS_SCHEMA_VERSION: int = 1

# Experiment identity (defined here; the protocol and decision modules import it).
M3C_EXPERIMENT_ID: str = "m3c-dual-horizon-trend-v1-run-001"
M3C_EXPERIMENT_FAMILY: str = "m3c-dual-horizon-trend-v1"

# Canonical committed relpaths for the whole M3C artifact set. They live here as a
# single source of truth so the protocol/decision modules import them one-directionally.
M3C_RESULTS_RELPATH: str = "research/m3c/candidate_results.json"
M3C_REPORT_RELPATH: str = "research/m3c/candidate_report.md"
M3C_PROTOCOL_RELPATH: str = "research/m3c/protocol.json"
M3C_LINEAGE_RELPATH: str = "research/m3c/research_lineage.json"
M3C_BUDGET_RELPATH: str = "research/m3c/research_budget.json"

# The frozen primary endpoint (see docs/M3C_PLAN.md §7).
PRIMARY_SCENARIO: str = "causal_proxy_base"
PRIMARY_COMPARATOR: str = "buy_and_hold"
PRIMARY_STATISTIC: str = "mean_paired_daily_log_excess"

_SCENARIO_NAMES: tuple[str, ...] = tuple(s.name for s in SCENARIOS)
_BUY_AND_HOLD: str = "buy_and_hold"
_COST_RECONCILE_TOLERANCE: float = 1e-9


class M3CResultsError(ValueError):
    """The M3C candidate results failed strict validation."""


def _ts(value: pd.Timestamp) -> str:
    return value.isoformat()


def _opt(value: float | None) -> float | None:
    return None if value is None else float(value)


def _finite_or_none(value: float) -> float | None:
    """A NaN performance ratio (zero-volatility fold) serializes as ``null``."""
    return None if math.isnan(value) else float(value)


def _require_list(value: object) -> list[Any]:
    """Decode a JSON array (never coerce a scalar or object into a sequence)."""
    if not isinstance(value, list):
        raise M3CResultsError(f"expected a JSON array, got {type(value).__name__}")
    return value


def _median_optional(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return float(statistics.median(present)) if present else None


# --------------------------------------------------------------------------- fold cell


@dataclass(frozen=True)
class M3CFoldCell:
    """One reconciled (strategy, cost-scenario, fold) result with a cost decomposition."""

    strategy: str
    cost_scenario: str
    fold_index: int
    oos_first_open_time: pd.Timestamp
    oos_last_open_time: pd.Timestamp
    oos_row_count: int
    context_row_count: int
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
    num_no_fill_bars: int
    average_requested_exposure: float
    average_achieved_exposure: float
    gross_notional: float
    total_fees: float
    spread_cost: float
    base_slippage_cost: float
    liquidity_impact_cost: float
    total_modeled_cost: float
    trace_commitment: str

    def __post_init__(self) -> None:
        components = (
            self.total_fees,
            self.spread_cost,
            self.base_slippage_cost,
            self.liquidity_impact_cost,
        )
        for label, value in zip(
            ("total_fees", "spread_cost", "base_slippage_cost", "liquidity_impact_cost"),
            components,
            strict=True,
        ):
            if value < 0.0:
                raise M3CResultsError(f"{label} must be >= 0, got {value!r}")
        expected = (
            self.total_fees
            + self.spread_cost
            + self.base_slippage_cost
            + (self.liquidity_impact_cost)
        )
        if abs(self.total_modeled_cost - expected) > _COST_RECONCILE_TOLERANCE:
            raise M3CResultsError(
                "total_modeled_cost does not reconcile with its additive decomposition "
                f"(got {self.total_modeled_cost!r}, components sum to {expected!r})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "fold_index": self.fold_index,
            "oos_first_open_time": _ts(self.oos_first_open_time),
            "oos_last_open_time": _ts(self.oos_last_open_time),
            "oos_row_count": self.oos_row_count,
            "context_row_count": self.context_row_count,
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
            "num_no_fill_bars": self.num_no_fill_bars,
            "average_requested_exposure": float(self.average_requested_exposure),
            "average_achieved_exposure": float(self.average_achieved_exposure),
            "gross_notional": float(self.gross_notional),
            "total_fees": float(self.total_fees),
            "spread_cost": float(self.spread_cost),
            "base_slippage_cost": float(self.base_slippage_cost),
            "liquidity_impact_cost": float(self.liquidity_impact_cost),
            "total_modeled_cost": float(self.total_modeled_cost),
            "trace_commitment": self.trace_commitment,
        }

    @classmethod
    def from_dict(cls, payload: object) -> M3CFoldCell:
        data = require_mapping("fold_cell", payload)
        require_exact_keys("fold_cell", data, _CELL_KEYS)
        sharpe = data["sharpe_ratio"]
        sortino = data["sortino_ratio"]
        return cls(
            strategy=require_nonempty_str("strategy", data["strategy"]),
            cost_scenario=require_nonempty_str("cost_scenario", data["cost_scenario"]),
            fold_index=require_nonnegative_int("fold_index", data["fold_index"]),
            oos_first_open_time=pd.Timestamp(
                require_str("oos_first_open_time", data["oos_first_open_time"])
            ),
            oos_last_open_time=pd.Timestamp(
                require_str("oos_last_open_time", data["oos_last_open_time"])
            ),
            oos_row_count=require_positive_int("oos_row_count", data["oos_row_count"]),
            context_row_count=require_nonnegative_int(
                "context_row_count", data["context_row_count"]
            ),
            initial_cash=require_positive_real("initial_cash", data["initial_cash"]),
            marked_terminal_equity=require_real(
                "marked_terminal_equity", data["marked_terminal_equity"]
            ),
            terminal_liquidation_equity=require_real(
                "terminal_liquidation_equity", data["terminal_liquidation_equity"]
            ),
            marked_total_return=require_real("marked_total_return", data["marked_total_return"]),
            liquidation_total_return=require_real(
                "liquidation_total_return", data["liquidation_total_return"]
            ),
            annualized_return=require_real("annualized_return", data["annualized_return"]),
            annualized_volatility=require_nonnegative_real(
                "annualized_volatility", data["annualized_volatility"]
            ),
            sharpe_ratio=None if sharpe is None else require_real("sharpe_ratio", sharpe),
            sortino_ratio=None if sortino is None else require_real("sortino_ratio", sortino),
            max_drawdown=require_real("max_drawdown", data["max_drawdown"]),
            num_fills=require_nonnegative_int("num_fills", data["num_fills"]),
            num_partial_fills=require_nonnegative_int(
                "num_partial_fills", data["num_partial_fills"]
            ),
            num_no_fill_bars=require_nonnegative_int("num_no_fill_bars", data["num_no_fill_bars"]),
            average_requested_exposure=require_real(
                "average_requested_exposure", data["average_requested_exposure"]
            ),
            average_achieved_exposure=require_real(
                "average_achieved_exposure", data["average_achieved_exposure"]
            ),
            gross_notional=require_nonnegative_real("gross_notional", data["gross_notional"]),
            total_fees=require_nonnegative_real("total_fees", data["total_fees"]),
            spread_cost=require_nonnegative_real("spread_cost", data["spread_cost"]),
            base_slippage_cost=require_nonnegative_real(
                "base_slippage_cost", data["base_slippage_cost"]
            ),
            liquidity_impact_cost=require_nonnegative_real(
                "liquidity_impact_cost", data["liquidity_impact_cost"]
            ),
            total_modeled_cost=require_nonnegative_real(
                "total_modeled_cost", data["total_modeled_cost"]
            ),
            trace_commitment=require_hex64("trace_commitment", data["trace_commitment"]),
        )


_CELL_KEYS = frozenset(
    {
        "strategy",
        "cost_scenario",
        "fold_index",
        "oos_first_open_time",
        "oos_last_open_time",
        "oos_row_count",
        "context_row_count",
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
        "num_no_fill_bars",
        "average_requested_exposure",
        "average_achieved_exposure",
        "gross_notional",
        "total_fees",
        "spread_cost",
        "base_slippage_cost",
        "liquidity_impact_cost",
        "total_modeled_cost",
        "trace_commitment",
    }
)


# --------------------------------------------------------------------------- aggregate


@dataclass(frozen=True)
class M3CAggregate:
    """Per-(strategy, cost-scenario) summary re-derived from the five fold cells."""

    strategy: str
    cost_scenario: str
    fold_count: int
    median_marked_return: float
    median_liquidation_return: float
    median_max_drawdown: float
    worst_max_drawdown: float
    median_sharpe: float | None
    median_turnover: float
    total_fills: int
    median_average_exposure: float
    fraction_positive_marked_folds: float
    fraction_beating_buy_and_hold: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_scenario": self.cost_scenario,
            "fold_count": self.fold_count,
            "median_marked_return": float(self.median_marked_return),
            "median_liquidation_return": float(self.median_liquidation_return),
            "median_max_drawdown": float(self.median_max_drawdown),
            "worst_max_drawdown": float(self.worst_max_drawdown),
            "median_sharpe": _opt(self.median_sharpe),
            "median_turnover": float(self.median_turnover),
            "total_fills": self.total_fills,
            "median_average_exposure": float(self.median_average_exposure),
            "fraction_positive_marked_folds": float(self.fraction_positive_marked_folds),
            "fraction_beating_buy_and_hold": float(self.fraction_beating_buy_and_hold),
        }

    @classmethod
    def from_dict(cls, payload: object) -> M3CAggregate:
        data = require_mapping("aggregate", payload)
        require_exact_keys("aggregate", data, _AGG_KEYS)
        median_sharpe = data["median_sharpe"]
        return cls(
            strategy=require_nonempty_str("strategy", data["strategy"]),
            cost_scenario=require_nonempty_str("cost_scenario", data["cost_scenario"]),
            fold_count=require_positive_int("fold_count", data["fold_count"]),
            median_marked_return=require_real("median_marked_return", data["median_marked_return"]),
            median_liquidation_return=require_real(
                "median_liquidation_return", data["median_liquidation_return"]
            ),
            median_max_drawdown=require_real("median_max_drawdown", data["median_max_drawdown"]),
            worst_max_drawdown=require_real("worst_max_drawdown", data["worst_max_drawdown"]),
            median_sharpe=(
                None if median_sharpe is None else require_real("median_sharpe", median_sharpe)
            ),
            median_turnover=require_nonnegative_real("median_turnover", data["median_turnover"]),
            total_fills=require_nonnegative_int("total_fills", data["total_fills"]),
            median_average_exposure=require_real(
                "median_average_exposure", data["median_average_exposure"]
            ),
            fraction_positive_marked_folds=require_real(
                "fraction_positive_marked_folds", data["fraction_positive_marked_folds"]
            ),
            fraction_beating_buy_and_hold=require_real(
                "fraction_beating_buy_and_hold", data["fraction_beating_buy_and_hold"]
            ),
        )


_AGG_KEYS = frozenset(
    {
        "strategy",
        "cost_scenario",
        "fold_count",
        "median_marked_return",
        "median_liquidation_return",
        "median_max_drawdown",
        "worst_max_drawdown",
        "median_sharpe",
        "median_turnover",
        "total_fills",
        "median_average_exposure",
        "fraction_positive_marked_folds",
        "fraction_beating_buy_and_hold",
    }
)


def build_m3c_aggregates(cells: tuple[M3CFoldCell, ...]) -> tuple[M3CAggregate, ...]:
    """Re-derive the 15 per-(strategy, scenario) aggregates from the fold cells."""
    by_cell = {(c.strategy, c.cost_scenario, c.fold_index): c for c in cells}
    aggregates: list[M3CAggregate] = []
    for scenario in _SCENARIO_NAMES:
        for strategy in M3C_STRATEGY_NAMES:
            group = sorted(
                (c for c in cells if c.strategy == strategy and c.cost_scenario == scenario),
                key=lambda c: c.fold_index,
            )
            marked = [c.marked_total_return for c in group]
            bnh = [
                by_cell[(_BUY_AND_HOLD, scenario, c.fold_index)].marked_total_return for c in group
            ]
            turnovers = [c.gross_notional / c.initial_cash for c in group]
            aggregates.append(
                M3CAggregate(
                    strategy=strategy,
                    cost_scenario=scenario,
                    fold_count=len(group),
                    median_marked_return=float(statistics.median(marked)),
                    median_liquidation_return=float(
                        statistics.median([c.liquidation_total_return for c in group])
                    ),
                    median_max_drawdown=float(statistics.median([c.max_drawdown for c in group])),
                    worst_max_drawdown=min(c.max_drawdown for c in group),
                    median_sharpe=_median_optional([c.sharpe_ratio for c in group]),
                    median_turnover=float(statistics.median(turnovers)),
                    total_fills=sum(c.num_fills for c in group),
                    median_average_exposure=float(
                        statistics.median([c.average_achieved_exposure for c in group])
                    ),
                    fraction_positive_marked_folds=sum(1 for r in marked if r > 0.0) / len(group),
                    fraction_beating_buy_and_hold=sum(
                        1 for r, b in zip(marked, bnh, strict=True) if r > b
                    )
                    / len(group),
                )
            )
    return tuple(aggregates)


# ------------------------------------------------------------------- paired comparison


@dataclass(frozen=True)
class M3CFoldPairedComparison:
    """The candidate-vs-buy-and-hold ``causal_proxy_base`` comparison for one fold."""

    fold_index: int
    oos_row_count: int
    candidate_marked_return: float
    buy_and_hold_marked_return: float
    mean_daily_paired_log_excess: float
    candidate_beats_bnh: bool

    def __post_init__(self) -> None:
        beats = self.candidate_marked_return > self.buy_and_hold_marked_return
        if self.candidate_beats_bnh != beats:
            raise M3CResultsError(
                f"candidate_beats_bnh {self.candidate_beats_bnh!r} disagrees with the marked "
                f"returns for fold {self.fold_index}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_index": self.fold_index,
            "oos_row_count": self.oos_row_count,
            "candidate_marked_return": float(self.candidate_marked_return),
            "buy_and_hold_marked_return": float(self.buy_and_hold_marked_return),
            "mean_daily_paired_log_excess": float(self.mean_daily_paired_log_excess),
            "candidate_beats_bnh": self.candidate_beats_bnh,
        }

    @classmethod
    def from_dict(cls, payload: object) -> M3CFoldPairedComparison:
        data = require_mapping("paired_comparison", payload)
        require_exact_keys("paired_comparison", data, _PAIRED_KEYS)
        return cls(
            fold_index=require_nonnegative_int("fold_index", data["fold_index"]),
            oos_row_count=require_positive_int("oos_row_count", data["oos_row_count"]),
            candidate_marked_return=require_real(
                "candidate_marked_return", data["candidate_marked_return"]
            ),
            buy_and_hold_marked_return=require_real(
                "buy_and_hold_marked_return", data["buy_and_hold_marked_return"]
            ),
            mean_daily_paired_log_excess=require_real(
                "mean_daily_paired_log_excess", data["mean_daily_paired_log_excess"]
            ),
            candidate_beats_bnh=require_bool("candidate_beats_bnh", data["candidate_beats_bnh"]),
        )


_PAIRED_KEYS = frozenset(
    {
        "fold_index",
        "oos_row_count",
        "candidate_marked_return",
        "buy_and_hold_marked_return",
        "mean_daily_paired_log_excess",
        "candidate_beats_bnh",
    }
)


# ------------------------------------------------------------------------- bootstrap


@dataclass(frozen=True)
class M3CBootstrapResult:
    """The frozen primary interval, mirroring ``statistics.BootstrapResult``."""

    algorithm: str
    seed: int
    resamples: int
    confidence: float
    observation_count: int
    fold_count: int
    block_lengths: tuple[int, ...]
    point_estimate: float
    ci_lower: float
    ci_upper: float

    def __post_init__(self) -> None:
        if self.algorithm != M3C_BOOTSTRAP_ALGORITHM:
            raise M3CResultsError(f"bootstrap algorithm must be {M3C_BOOTSTRAP_ALGORITHM!r}")
        if self.confidence != M3C_BOOTSTRAP_CONFIDENCE:
            raise M3CResultsError(f"bootstrap confidence must be {M3C_BOOTSTRAP_CONFIDENCE!r}")
        if self.observation_count < 2:
            raise M3CResultsError("bootstrap requires at least two observations")
        if self.fold_count < 1:
            raise M3CResultsError("bootstrap fold_count must be positive")
        if len(self.block_lengths) != self.fold_count:
            raise M3CResultsError("block_lengths length must equal fold_count")
        if any(length < 1 for length in self.block_lengths):
            raise M3CResultsError("every block length must be >= 1")
        if self.ci_lower > self.ci_upper:
            raise M3CResultsError("ci_lower must not exceed ci_upper")

    @property
    def lower_bound_above_zero(self) -> bool:
        return self.ci_lower > 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "seed": self.seed,
            "resamples": self.resamples,
            "confidence": float(self.confidence),
            "observation_count": self.observation_count,
            "fold_count": self.fold_count,
            "block_lengths": list(self.block_lengths),
            "point_estimate": float(self.point_estimate),
            "ci_lower": float(self.ci_lower),
            "ci_upper": float(self.ci_upper),
        }

    @classmethod
    def from_dict(cls, payload: object) -> M3CBootstrapResult:
        data = require_mapping("bootstrap", payload)
        require_exact_keys("bootstrap", data, _BOOTSTRAP_KEYS)
        return cls(
            algorithm=require_nonempty_str("algorithm", data["algorithm"]),
            seed=require_int("seed", data["seed"]),
            resamples=require_positive_int("resamples", data["resamples"]),
            confidence=require_real("confidence", data["confidence"]),
            observation_count=require_positive_int("observation_count", data["observation_count"]),
            fold_count=require_positive_int("fold_count", data["fold_count"]),
            block_lengths=require_tuple(
                "block_lengths", data["block_lengths"], require_positive_int
            ),
            point_estimate=require_real("point_estimate", data["point_estimate"]),
            ci_lower=require_real("ci_lower", data["ci_lower"]),
            ci_upper=require_real("ci_upper", data["ci_upper"]),
        )


_BOOTSTRAP_KEYS = frozenset(
    {
        "algorithm",
        "seed",
        "resamples",
        "confidence",
        "observation_count",
        "fold_count",
        "block_lengths",
        "point_estimate",
        "ci_lower",
        "ci_upper",
    }
)


# ----------------------------------------------------------------------------- PSR


@dataclass(frozen=True)
class M3CPSRDiagnostic:
    """A secondary, descriptive Probabilistic Sharpe diagnostic (never a decision input)."""

    observed_sharpe: float
    benchmark_sharpe: float
    sample_size: int
    skewness: float
    kurtosis: float
    psr: float

    def __post_init__(self) -> None:
        if self.sample_size < 3:
            raise M3CResultsError("PSR requires at least three observations")
        if not 0.0 <= self.psr <= 1.0:
            raise M3CResultsError(f"psr must be within [0, 1], got {self.psr!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_sharpe": float(self.observed_sharpe),
            "benchmark_sharpe": float(self.benchmark_sharpe),
            "sample_size": self.sample_size,
            "skewness": float(self.skewness),
            "kurtosis": float(self.kurtosis),
            "psr": float(self.psr),
        }

    @classmethod
    def from_dict(cls, payload: object) -> M3CPSRDiagnostic:
        data = require_mapping("psr_diagnostic", payload)
        require_exact_keys("psr_diagnostic", data, _PSR_KEYS)
        return cls(
            observed_sharpe=require_real("observed_sharpe", data["observed_sharpe"]),
            benchmark_sharpe=require_real("benchmark_sharpe", data["benchmark_sharpe"]),
            sample_size=require_positive_int("sample_size", data["sample_size"]),
            skewness=require_real("skewness", data["skewness"]),
            kurtosis=require_real("kurtosis", data["kurtosis"]),
            psr=require_real("psr", data["psr"]),
        )


_PSR_KEYS = frozenset(
    {
        "observed_sharpe",
        "benchmark_sharpe",
        "sample_size",
        "skewness",
        "kurtosis",
        "psr",
    }
)


# ------------------------------------------------------------------------- top level


@dataclass(frozen=True)
class M3CResults:
    """The immutable, strict record of the one preregistered M3C candidate run."""

    m3c_results_schema_version: int
    experiment_id: str
    experiment_family: str
    package_version: str
    execution_code_commit_sha: str
    registered_code_commit_sha: str
    execution_source_tree_fingerprint: str
    protocol_path: str
    protocol_sha256: str
    lineage_path: str
    lineage_sha256: str
    budget_path: str
    budget_sha256: str
    frozen_m2_dossier_sha256: str
    development_partition_sha256: str
    research_train_content_fingerprint: str
    strategies: tuple[str, ...]
    cost_scenarios: tuple[str, ...]
    fold_cells: tuple[M3CFoldCell, ...]
    aggregates: tuple[M3CAggregate, ...]
    primary_scenario: str
    primary_comparator: str
    paired_comparisons: tuple[M3CFoldPairedComparison, ...]
    bootstrap: M3CBootstrapResult
    psr_diagnostic: M3CPSRDiagnostic
    development_gate_event_count: int
    final_holdout_event_count: int

    def __post_init__(self) -> None:
        if self.m3c_results_schema_version != M3C_RESULTS_SCHEMA_VERSION:
            raise M3CResultsError("unexpected schema version")
        if self.experiment_family != M3C_EXPERIMENT_FAMILY:
            raise M3CResultsError("wrong experiment family")
        if not self.experiment_id.startswith(M3C_EXPERIMENT_FAMILY):
            raise M3CResultsError("experiment_id must belong to the family")
        if self.strategies != M3C_STRATEGY_NAMES:
            raise M3CResultsError("strategies must match the five pinned M3C strategies in order")
        if self.cost_scenarios != _SCENARIO_NAMES:
            raise M3CResultsError("cost scenarios must match the three frozen scenarios in order")
        if self.primary_scenario != PRIMARY_SCENARIO:
            raise M3CResultsError(f"primary_scenario must be {PRIMARY_SCENARIO!r}")
        if self.primary_comparator != PRIMARY_COMPARATOR:
            raise M3CResultsError(f"primary_comparator must be {PRIMARY_COMPARATOR!r}")
        if self.development_gate_event_count != 0 or self.final_holdout_event_count != 0:
            raise M3CResultsError("both sealed access ledgers must have zero events")
        require_hex64("protocol_sha256", self.protocol_sha256)
        require_hex64("lineage_sha256", self.lineage_sha256)
        require_hex64("budget_sha256", self.budget_sha256)
        require_hex64("frozen_m2_dossier_sha256", self.frozen_m2_dossier_sha256)
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        require_sha256_fingerprint(
            "research_train_content_fingerprint", self.research_train_content_fingerprint
        )
        require_safe_relative_path("protocol_path", self.protocol_path, prefix="research/")
        require_safe_relative_path("lineage_path", self.lineage_path, prefix="research/")
        require_safe_relative_path("budget_path", self.budget_path, prefix="research/")
        self._validate_grid()
        self._validate_paired_and_bootstrap()

    def _validate_grid(self) -> None:
        expected = {
            (strategy, scenario, fold)
            for strategy in M3C_STRATEGY_NAMES
            for scenario in _SCENARIO_NAMES
            for fold in range(OOS_FOLD_COUNT)
        }
        seen = {(c.strategy, c.cost_scenario, c.fold_index) for c in self.fold_cells}
        if len(self.fold_cells) != len(expected):
            raise M3CResultsError(
                f"expected {len(expected)} fold cells, got {len(self.fold_cells)}"
            )
        if seen != expected:
            raise M3CResultsError(
                "fold cells do not cover the exact (strategy, scenario, fold) grid"
            )
        for cell in self.fold_cells:
            if not (-1.0 <= cell.max_drawdown <= 0.0):
                raise M3CResultsError(f"max_drawdown out of [-1, 0]: {cell.max_drawdown!r}")
            if not (-1e-9 <= cell.average_achieved_exposure <= 1.0 + 1e-9):
                raise M3CResultsError("average achieved exposure out of [0, 1]")
            if not (-1e-9 <= cell.average_requested_exposure <= 1.0 + 1e-9):
                raise M3CResultsError("average requested exposure out of [0, 1]")
            if cell.marked_terminal_equity <= 0.0:
                raise M3CResultsError("non-positive terminal marked equity")
            if cell.terminal_liquidation_equity > cell.marked_terminal_equity + 1e-6:
                raise M3CResultsError("liquidation equity exceeds marked equity")
        if len(self.aggregates) != len(M3C_STRATEGY_NAMES) * len(_SCENARIO_NAMES):
            raise M3CResultsError(
                f"expected {len(M3C_STRATEGY_NAMES) * len(_SCENARIO_NAMES)} aggregates"
            )
        rederived = build_m3c_aggregates(self.fold_cells)
        if tuple(a.to_dict() for a in self.aggregates) != tuple(a.to_dict() for a in rederived):
            raise M3CResultsError("aggregates do not re-derive from the fold cells")

    def _validate_paired_and_bootstrap(self) -> None:
        if len(self.paired_comparisons) != OOS_FOLD_COUNT:
            raise M3CResultsError(f"expected {OOS_FOLD_COUNT} paired comparisons")
        folds = [pc.fold_index for pc in self.paired_comparisons]
        if sorted(folds) != list(range(OOS_FOLD_COUNT)):
            raise M3CResultsError("paired comparisons must cover folds 0..4 exactly once")
        by_cell = {(c.strategy, c.cost_scenario, c.fold_index): c for c in self.fold_cells}
        for pc in self.paired_comparisons:
            cand = by_cell[(M3C_CANDIDATE_ID, PRIMARY_SCENARIO, pc.fold_index)]
            bnh = by_cell[(_BUY_AND_HOLD, PRIMARY_SCENARIO, pc.fold_index)]
            if pc.oos_row_count != cand.oos_row_count:
                raise M3CResultsError(
                    f"paired comparison fold {pc.fold_index} row count disagrees with the cell"
                )
            if pc.candidate_marked_return != cand.marked_total_return:
                raise M3CResultsError(
                    f"paired comparison fold {pc.fold_index} candidate return disagrees"
                )
            if pc.buy_and_hold_marked_return != bnh.marked_total_return:
                raise M3CResultsError(
                    f"paired comparison fold {pc.fold_index} buy_and_hold return disagrees"
                )
        candidate_base_days = sum(
            by_cell[(M3C_CANDIDATE_ID, PRIMARY_SCENARIO, fold)].oos_row_count
            for fold in range(OOS_FOLD_COUNT)
        )
        if self.bootstrap.observation_count != candidate_base_days:
            raise M3CResultsError(
                "bootstrap observation_count must equal the total candidate causal_proxy_base "
                f"OOS days ({candidate_base_days}), got {self.bootstrap.observation_count}"
            )
        if self.bootstrap.fold_count != OOS_FOLD_COUNT:
            raise M3CResultsError("bootstrap fold_count must equal the OOS fold count")

    def to_json_bytes(self) -> bytes:
        payload = {
            "m3c_results_schema_version": self.m3c_results_schema_version,
            "experiment_id": self.experiment_id,
            "experiment_family": self.experiment_family,
            "package_version": self.package_version,
            "execution_code_commit_sha": self.execution_code_commit_sha,
            "registered_code_commit_sha": self.registered_code_commit_sha,
            "execution_source_tree_fingerprint": self.execution_source_tree_fingerprint,
            "protocol_path": self.protocol_path,
            "protocol_sha256": self.protocol_sha256,
            "lineage_path": self.lineage_path,
            "lineage_sha256": self.lineage_sha256,
            "budget_path": self.budget_path,
            "budget_sha256": self.budget_sha256,
            "frozen_m2_dossier_sha256": self.frozen_m2_dossier_sha256,
            "development_partition_sha256": self.development_partition_sha256,
            "research_train_content_fingerprint": self.research_train_content_fingerprint,
            "strategies": list(self.strategies),
            "cost_scenarios": list(self.cost_scenarios),
            "fold_cells": [c.to_dict() for c in self.fold_cells],
            "aggregates": [a.to_dict() for a in self.aggregates],
            "primary_scenario": self.primary_scenario,
            "primary_comparator": self.primary_comparator,
            "paired_comparisons": [p.to_dict() for p in self.paired_comparisons],
            "bootstrap": self.bootstrap.to_dict(),
            "psr_diagnostic": self.psr_diagnostic.to_dict(),
            "development_gate_event_count": self.development_gate_event_count,
            "final_holdout_event_count": self.final_holdout_event_count,
        }
        return canonical_json_bytes(payload)

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> M3CResults:
        payload = strict_json_loads(raw)
        data = require_mapping("m3c_results", payload)
        require_exact_keys("m3c_results", data, _RESULTS_KEYS)
        cells = tuple(M3CFoldCell.from_dict(c) for c in _require_list(data["fold_cells"]))
        aggregates = tuple(M3CAggregate.from_dict(a) for a in _require_list(data["aggregates"]))
        paired = tuple(
            M3CFoldPairedComparison.from_dict(p) for p in _require_list(data["paired_comparisons"])
        )
        return cls(
            m3c_results_schema_version=require_int(
                "m3c_results_schema_version", data["m3c_results_schema_version"]
            ),
            experiment_id=require_nonempty_str("experiment_id", data["experiment_id"]),
            experiment_family=require_nonempty_str("experiment_family", data["experiment_family"]),
            package_version=require_nonempty_str("package_version", data["package_version"]),
            execution_code_commit_sha=require_str(
                "execution_code_commit_sha", data["execution_code_commit_sha"]
            ),
            registered_code_commit_sha=require_str(
                "registered_code_commit_sha", data["registered_code_commit_sha"]
            ),
            execution_source_tree_fingerprint=require_nonempty_str(
                "execution_source_tree_fingerprint", data["execution_source_tree_fingerprint"]
            ),
            protocol_path=require_nonempty_str("protocol_path", data["protocol_path"]),
            protocol_sha256=require_hex64("protocol_sha256", data["protocol_sha256"]),
            lineage_path=require_nonempty_str("lineage_path", data["lineage_path"]),
            lineage_sha256=require_hex64("lineage_sha256", data["lineage_sha256"]),
            budget_path=require_nonempty_str("budget_path", data["budget_path"]),
            budget_sha256=require_hex64("budget_sha256", data["budget_sha256"]),
            frozen_m2_dossier_sha256=require_hex64(
                "frozen_m2_dossier_sha256", data["frozen_m2_dossier_sha256"]
            ),
            development_partition_sha256=require_hex64(
                "development_partition_sha256", data["development_partition_sha256"]
            ),
            research_train_content_fingerprint=require_nonempty_str(
                "research_train_content_fingerprint", data["research_train_content_fingerprint"]
            ),
            strategies=require_tuple("strategies", data["strategies"], require_nonempty_str),
            cost_scenarios=require_tuple(
                "cost_scenarios", data["cost_scenarios"], require_nonempty_str
            ),
            fold_cells=cells,
            aggregates=aggregates,
            primary_scenario=require_nonempty_str("primary_scenario", data["primary_scenario"]),
            primary_comparator=require_nonempty_str(
                "primary_comparator", data["primary_comparator"]
            ),
            paired_comparisons=paired,
            bootstrap=M3CBootstrapResult.from_dict(data["bootstrap"]),
            psr_diagnostic=M3CPSRDiagnostic.from_dict(data["psr_diagnostic"]),
            development_gate_event_count=require_nonnegative_int(
                "development_gate_event_count", data["development_gate_event_count"]
            ),
            final_holdout_event_count=require_nonnegative_int(
                "final_holdout_event_count", data["final_holdout_event_count"]
            ),
        )


_RESULTS_KEYS = frozenset(
    {
        "m3c_results_schema_version",
        "experiment_id",
        "experiment_family",
        "package_version",
        "execution_code_commit_sha",
        "registered_code_commit_sha",
        "execution_source_tree_fingerprint",
        "protocol_path",
        "protocol_sha256",
        "lineage_path",
        "lineage_sha256",
        "budget_path",
        "budget_sha256",
        "frozen_m2_dossier_sha256",
        "development_partition_sha256",
        "research_train_content_fingerprint",
        "strategies",
        "cost_scenarios",
        "fold_cells",
        "aggregates",
        "primary_scenario",
        "primary_comparator",
        "paired_comparisons",
        "bootstrap",
        "psr_diagnostic",
        "development_gate_event_count",
        "final_holdout_event_count",
    }
)


# --------------------------------------------------------------------------- builders


def _decompose_costs(
    result: FractionalBacktestResult, scenario: CostScenario
) -> tuple[float, float, float, float, float, int, float]:
    """Additive cost decomposition + no-fill count + requested exposure from the bars.

    For each executed bar the price shortfall against the reference open,
    ``|fill_price - reference_open| * |executed_quantity|``, is split into a
    half-spread term, a base-slippage term, and a residual liquidity-impact term
    (clamped at zero for float noise) using the scenario's per-notional rates on
    ``reference_open * |executed_quantity|``. This reproduces the cost model's own
    ``reference_notional * rate`` decomposition, so ``compatibility_v1``
    (half-spread and impact both off) yields spread and impact of zero.

    ``num_no_fill_bars`` counts bars where the solver selected a trade side but a
    constraint bound the fill to zero (``partial`` with no executed quantity) — the
    honest "wanted to trade, nothing filled" count, distinct from "already at target".
    """
    total_fees = 0.0
    spread = 0.0
    base = 0.0
    impact = 0.0
    gross = 0.0
    no_fill = 0
    requested_sum = 0.0
    for bar in result.bars:
        requested_sum += bar.executable_target
        if bar.partial and bar.executed_quantity == 0.0:
            no_fill += 1
        if bar.executed_quantity != 0.0 and bar.fill_price is not None:
            quantity = abs(bar.executed_quantity)
            notional = bar.reference_open * quantity
            gross += notional
            total_fees += bar.fee
            shortfall = abs(bar.fill_price - bar.reference_open) * quantity
            spread_bar = scenario.half_spread_rate * notional
            base_bar = scenario.base_slippage_rate * notional
            impact_bar = shortfall - spread_bar - base_bar
            if impact_bar < 0.0:
                impact_bar = 0.0
            spread += spread_bar
            base += base_bar
            impact += impact_bar
    average_requested = requested_sum / len(result.bars)
    return total_fees, spread, base, impact, gross, no_fill, average_requested


def _fold_cell(run: M3CCellRun, scenario: CostScenario, trace_commitment: str) -> M3CFoldCell:
    """Reduce one reconciled cell run to its immutable, cost-decomposed fold cell."""
    total_fees, spread, base, impact, gross, no_fill, avg_requested = _decompose_costs(
        run.result, scenario
    )
    initial_cash = run.result.initial_cash
    liquidation_equity = run.metrics.terminal_liquidation_equity
    return M3CFoldCell(
        strategy=run.strategy,
        cost_scenario=run.cost_scenario,
        fold_index=run.fold_index,
        oos_first_open_time=run.result.equity.index[0],
        oos_last_open_time=run.result.equity.index[-1],
        oos_row_count=len(run.result.equity),
        context_row_count=run.context_row_count,
        initial_cash=initial_cash,
        marked_terminal_equity=run.metrics.terminal_equity,
        terminal_liquidation_equity=liquidation_equity,
        marked_total_return=run.metrics.total_return,
        liquidation_total_return=liquidation_equity / initial_cash - 1.0,
        annualized_return=run.metrics.annualized_return,
        annualized_volatility=run.metrics.annualized_volatility,
        sharpe_ratio=_finite_or_none(run.metrics.sharpe_ratio),
        sortino_ratio=_finite_or_none(run.metrics.sortino_ratio),
        max_drawdown=run.metrics.max_drawdown,
        num_fills=run.metrics.num_fills,
        num_partial_fills=run.metrics.num_partial_fills,
        num_no_fill_bars=no_fill,
        average_requested_exposure=avg_requested,
        average_achieved_exposure=run.metrics.average_achieved_exposure,
        gross_notional=gross,
        total_fees=total_fees,
        spread_cost=spread,
        base_slippage_cost=base,
        liquidity_impact_cost=impact,
        total_modeled_cost=total_fees + spread + base + impact,
        trace_commitment=trace_commitment,
    )


def _paired_comparisons(
    runs_by: dict[tuple[str, str, int], M3CCellRun],
    cells_by: dict[tuple[str, str, int], M3CFoldCell],
) -> tuple[M3CFoldPairedComparison, ...]:
    """Candidate-vs-buy-and-hold ``causal_proxy_base`` paired comparison per fold."""
    comparisons: list[M3CFoldPairedComparison] = []
    for fold in range(OOS_FOLD_COUNT):
        cand_run = runs_by[(M3C_CANDIDATE_ID, PRIMARY_SCENARIO, fold)]
        bnh_run = runs_by[(_BUY_AND_HOLD, PRIMARY_SCENARIO, fold)]
        cand_returns = cand_run.marked_daily_returns
        bnh_returns = bnh_run.marked_daily_returns
        if not cand_returns.index.equals(bnh_returns.index):
            raise M3CResultsError(
                f"fold {fold}: candidate and buy_and_hold OOS indices differ; cannot pair"
            )
        log_excess = paired_log_excess(cand_returns.to_numpy(), bnh_returns.to_numpy())
        cand_cell = cells_by[(M3C_CANDIDATE_ID, PRIMARY_SCENARIO, fold)]
        bnh_cell = cells_by[(_BUY_AND_HOLD, PRIMARY_SCENARIO, fold)]
        comparisons.append(
            M3CFoldPairedComparison(
                fold_index=fold,
                oos_row_count=len(cand_returns),
                candidate_marked_return=cand_cell.marked_total_return,
                buy_and_hold_marked_return=bnh_cell.marked_total_return,
                mean_daily_paired_log_excess=float(log_excess.mean()),
                candidate_beats_bnh=(cand_cell.marked_total_return > bnh_cell.marked_total_return),
            )
        )
    return tuple(comparisons)


def build_m3c_results(
    *,
    cell_runs: tuple[M3CCellRun, ...],
    wf_protocol: WalkForwardProtocol,
    package_version: str,
    execution_code_commit_sha: str,
    registered_code_commit_sha: str,
    execution_source_tree_fingerprint: str,
    protocol_sha256: str,
    lineage_sha256: str,
    budget_sha256: str,
    frozen_m2_dossier_sha256: str,
    development_partition_sha256: str,
    research_train: pd.DataFrame,
    primary_bootstrap: BootstrapResult,
    psr: ProbabilisticSharpe,
    trace_commitments: dict[tuple[str, str, int], str],
) -> M3CResults:
    """Assemble the strict results model from the 75 reconciled cell runs.

    Re-derives the research-train content fingerprint from the data actually
    evaluated and fails closed if it disagrees with the frozen walk-forward
    protocol, decomposes every cell's modeled cost, re-derives the aggregates,
    and computes the five ``causal_proxy_base`` paired comparisons. The provided
    ``primary_bootstrap`` and ``psr`` (computed once by the orchestrator) are
    recorded verbatim; both sealed access-ledger counts are pinned at zero.
    """
    fingerprint = content_fingerprint(research_train)
    if fingerprint != wf_protocol.research_train_content_fingerprint:
        raise M3CResultsError(
            "research-train content fingerprint disagrees with the frozen walk-forward protocol"
        )
    cells: list[M3CFoldCell] = []
    for run in cell_runs:
        key = (run.strategy, run.cost_scenario, run.fold_index)
        if key not in trace_commitments:
            raise M3CResultsError(f"missing trace commitment for cell {key}")
        scenario = SCENARIOS_BY_NAME[run.cost_scenario]
        cells.append(_fold_cell(run, scenario, trace_commitments[key]))
    fold_cells = tuple(cells)
    runs_by = {(r.strategy, r.cost_scenario, r.fold_index): r for r in cell_runs}
    cells_by = {(c.strategy, c.cost_scenario, c.fold_index): c for c in fold_cells}
    return M3CResults(
        m3c_results_schema_version=M3C_RESULTS_SCHEMA_VERSION,
        experiment_id=M3C_EXPERIMENT_ID,
        experiment_family=M3C_EXPERIMENT_FAMILY,
        package_version=package_version,
        execution_code_commit_sha=execution_code_commit_sha,
        registered_code_commit_sha=registered_code_commit_sha,
        execution_source_tree_fingerprint=execution_source_tree_fingerprint,
        protocol_path=M3C_PROTOCOL_RELPATH,
        protocol_sha256=protocol_sha256,
        lineage_path=M3C_LINEAGE_RELPATH,
        lineage_sha256=lineage_sha256,
        budget_path=M3C_BUDGET_RELPATH,
        budget_sha256=budget_sha256,
        frozen_m2_dossier_sha256=frozen_m2_dossier_sha256,
        development_partition_sha256=development_partition_sha256,
        research_train_content_fingerprint=fingerprint,
        strategies=M3C_STRATEGY_NAMES,
        cost_scenarios=_SCENARIO_NAMES,
        fold_cells=fold_cells,
        aggregates=build_m3c_aggregates(fold_cells),
        primary_scenario=PRIMARY_SCENARIO,
        primary_comparator=PRIMARY_COMPARATOR,
        paired_comparisons=_paired_comparisons(runs_by, cells_by),
        bootstrap=M3CBootstrapResult(
            algorithm=primary_bootstrap.algorithm,
            seed=primary_bootstrap.seed,
            resamples=primary_bootstrap.resamples,
            confidence=primary_bootstrap.confidence,
            observation_count=primary_bootstrap.observation_count,
            fold_count=primary_bootstrap.fold_count,
            block_lengths=tuple(primary_bootstrap.block_lengths),
            point_estimate=primary_bootstrap.point_estimate,
            ci_lower=primary_bootstrap.ci_lower,
            ci_upper=primary_bootstrap.ci_upper,
        ),
        psr_diagnostic=M3CPSRDiagnostic(
            observed_sharpe=psr.observed_sharpe,
            benchmark_sharpe=psr.benchmark_sharpe,
            sample_size=psr.sample_size,
            skewness=psr.skewness,
            kurtosis=psr.kurtosis,
            psr=psr.psr,
        ),
        development_gate_event_count=0,
        final_holdout_event_count=0,
    )


def load_m3c_results(path: str | Path) -> M3CResults:
    """Strictly parse a committed M3C candidate results file."""
    raw = require_canonical_file_bytes(Path(path).read_bytes(), "m3c results")
    return M3CResults.from_json_bytes(raw)


# ----------------------------------------------------------------------------- report


def _pct(value: float) -> str:
    return f"{value * 100.0:+.2f}%"


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _usd(value: float) -> str:
    return f"{value:,.2f}"


def render_m3c_report(results: M3CResults, decision: CandidateDecision) -> str:
    """Render the Markdown candidate report, leading with the mechanical decision.

    Deterministic (no timestamps), so a fresh clone renders identical bytes. Every
    financial figure is a field of the reconciled results model or a re-derivable
    aggregate; no number is invented and no losing fold is omitted. The report
    states the exact promotion rule with each criterion's committed pass/fail, and
    frames the run as research-train-only development evidence for an adaptively
    motivated candidate — never an out-of-sample, alpha, or trading claim.
    """
    lines: list[str] = []
    add = lines.append
    eligible = decision.outcome == "eligible_for_development_gate_review"
    agg_by = {(a.strategy, a.cost_scenario): a for a in results.aggregates}
    cells_by = {(c.strategy, c.cost_scenario, c.fold_index): c for c in results.fold_cells}
    folds = sorted({c.fold_index for c in results.fold_cells})

    add("# Milestone 3C candidate report (run-001)")
    add("")
    add("## 1. Decision")
    add("")
    verdict = (
        "ELIGIBLE FOR INDEPENDENT DEVELOPMENT-GATE REVIEW"
        if eligible
        else "REJECTED FOR DEVELOPMENT-GATE PROMOTION"
    )
    add(f"> ## {verdict}")
    add(">")
    if eligible:
        add(
            "> This is **only** eligibility for an independent development-gate review. It is "
            "**not** gate authorization, promotion, an alpha claim, or approval to trade. The "
            "development gate and the final holdout remain sealed and were never accessed."
        )
    else:
        add(
            "> The candidate did **not** satisfy the frozen promotion rule and is retained, "
            "unchanged, as rejected. No parameter is altered to make it pass. The development "
            "gate and the final holdout remain sealed and were never accessed."
        )
    add("")
    add(f"- Experiment id: `{results.experiment_id}`")
    add(f"- Experiment family: `{results.experiment_family}`")
    add(f"- Decision outcome: `{decision.outcome}`")
    add(f"- Recorded package version: `{results.package_version}`")
    add(f"- Registered code commit: `{results.registered_code_commit_sha}`")
    add(f"- Execution code commit: `{results.execution_code_commit_sha}`")
    add(f"- Committed results digest: `{decision.results_sha256}`")
    add("")
    add("### Promotion rule (frozen before execution) and per-criterion outcome")
    add("")
    add(
        "The decision is generated mechanically from the committed results and the frozen "
        "rule: the candidate is eligible **iff all seven criteria pass**, else it is rejected."
    )
    add("")
    add("| criterion | requirement | observed | pass |")
    add("| --- | --- | --- | :---: |")
    for criterion in decision.criteria:
        mark = "PASS" if criterion.passed else "FAIL"
        add(
            f"| {criterion.criterion_id} | {criterion.description} | "
            f"{criterion.observed_value} | {mark} |"
        )
    add("")
    add("## 2. Research-only framing")
    add("")
    add(
        "> These are observations on the **research-train** partition only — in-sample "
        "development evidence for a **single, adaptively motivated** candidate whose horizons, "
        "volatility target, costs, folds, seed, and decision rule were all fixed before this one "
        "execution. Prior related trend strategies (SMA, Donchian, volatility-target variants) "
        "were already observed, so this candidate is adaptively motivated and its research-train "
        "result is **not** out-of-sample evidence. **No alpha is claimed**, nothing was tuned or "
        "optimized, and no cost figure is venue-calibrated. The independent development gate — "
        "the safeguard against this adaptive history — was never accessed, and this engine "
        "cannot move money."
    )
    add("")
    add("## 3. Data-access boundaries")
    add("")
    add("| level | rows | M3C access |")
    add("| --- | ---: | --- |")
    add("| research train | 2221 | evaluated (OOS folds only) |")
    add("| development gate | n/a | **sealed — never accessed** |")
    add("| final holdout | n/a | **sealed — never accessed** |")
    add("")
    add(
        f"- Development-gate ledger events: **{results.development_gate_event_count}**. "
        f"Final-holdout ledger events: **{results.final_holdout_event_count}**. "
        f"Research-train content fingerprint: `{results.research_train_content_fingerprint}`."
    )
    add("")
    add("## 4. Primary endpoint (frozen)")
    add("")
    b = results.bootstrap
    add(
        f"Under `{results.primary_scenario}`, mean paired daily log-return excess of the "
        f"candidate over `{results.primary_comparator}`, with a fold-seam-aware "
        f"{b.confidence:.0%} moving-block bootstrap ({b.algorithm}, seed {b.seed}, "
        f"{b.resamples} resamples, {b.observation_count} paired OOS days)."
    )
    add("")
    add(
        f"- Point estimate: `{b.point_estimate:.6g}`; "
        f"{b.confidence:.0%} interval: `[{b.ci_lower:.6g}, {b.ci_upper:.6g}]`; "
        f"lower bound above zero: **{b.lower_bound_above_zero}**."
    )
    add("- Per-fold candidate vs buy-and-hold (marked total return, causal_proxy_base):")
    add("")
    add("| fold | OOS days | candidate | buy_and_hold | mean daily log-excess | candidate wins |")
    add("| ---: | ---: | ---: | ---: | ---: | :---: |")
    for pc in sorted(results.paired_comparisons, key=lambda p: p.fold_index):
        add(
            f"| {pc.fold_index} | {pc.oos_row_count} | {_pct(pc.candidate_marked_return)} | "
            f"{_pct(pc.buy_and_hold_marked_return)} | {pc.mean_daily_paired_log_excess:.6g} | "
            f"{'yes' if pc.candidate_beats_bnh else 'no'} |"
        )
    add("")
    add("## 5. Per-(strategy, scenario) aggregates over the five folds")
    add("")
    for scenario in results.cost_scenarios:
        add(f"### {scenario}")
        add("")
        add(
            "| strategy | median marked | median liquidation | median drawdown | "
            "worst drawdown | median Sharpe | median turnover | +folds | > B&H |"
        )
        add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for strategy in results.strategies:
            a = agg_by[(strategy, scenario)]
            add(
                f"| {strategy} | {_pct(a.median_marked_return)} | "
                f"{_pct(a.median_liquidation_return)} | {_pct(a.median_max_drawdown)} | "
                f"{_pct(a.worst_max_drawdown)} | {_ratio(a.median_sharpe)} | "
                f"{a.median_turnover:.2f}x | {a.fraction_positive_marked_folds:.0%} | "
                f"{a.fraction_beating_buy_and_hold:.0%} |"
            )
        add("")
    add("## 6. Full fold grid (marked total return) — every losing fold retained")
    add("")
    for scenario in results.cost_scenarios:
        add(f"### {scenario}")
        add("")
        add("| strategy | " + " | ".join(f"fold {i}" for i in folds) + " |")
        add("| --- | " + " | ".join("---:" for _ in folds) + " |")
        for strategy in results.strategies:
            row = [strategy]
            for fold in folds:
                row.append(_pct(cells_by[(strategy, scenario, fold)].marked_total_return))
            add("| " + " | ".join(row) + " |")
        add("")
    add("## 7. Modeled cost and fill diagnostics (candidate)")
    add("")
    add(
        "| scenario | fold | fees | spread | base slippage | liquidity impact | total | "
        "fills | partial | no-fill |"
    )
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for scenario in results.cost_scenarios:
        for fold in folds:
            c = cells_by[(M3C_CANDIDATE_ID, scenario, fold)]
            add(
                f"| {scenario} | {fold} | {_usd(c.total_fees)} | {_usd(c.spread_cost)} | "
                f"{_usd(c.base_slippage_cost)} | {_usd(c.liquidity_impact_cost)} | "
                f"{_usd(c.total_modeled_cost)} | {c.num_fills} | {c.num_partial_fills} | "
                f"{c.num_no_fill_bars} |"
            )
    add("")
    add("## 8. Secondary Probabilistic Sharpe diagnostic (fragile)")
    add("")
    psr = results.psr_diagnostic
    add(
        "> The Probabilistic Sharpe Ratio below is a **fragile secondary** descriptor only: "
        "five folds plus an adaptive research history cannot support a credible overfitting "
        "claim, and it **cannot** rescue a failed primary or add any inferential weight."
    )
    add("")
    add(
        f"- Observed daily paired-excess Sharpe: `{psr.observed_sharpe:.6g}` "
        f"(benchmark `{psr.benchmark_sharpe:.6g}`, n = {psr.sample_size}); "
        f"skewness `{psr.skewness:.6g}`, kurtosis `{psr.kurtosis:.6g}`; PSR `{psr.psr:.6g}`."
    )
    add("")
    add("## 9. Limitations")
    add("")
    add(
        "- One in-sample research-train execution of one adaptively motivated candidate; not "
        "live, test, or gate performance."
    )
    add(
        "- The costs are transparent deterministic proxies driven by lagged liquidity, not a "
        "venue-calibrated model, and make no empirical-accuracy claim."
    )
    add(
        "- A single fold-seam-aware bootstrap on an adaptive dataset carries no significance "
        "claim; only the independent, sealed development gate can address the adaptive history."
    )
    add(
        "- Eligibility, if any, means only that an independent development-gate review may "
        "consider the candidate; it is not promotion, not an alpha claim, and not approval to "
        "trade."
    )
    add("")
    return "\n".join(lines) + "\n"
