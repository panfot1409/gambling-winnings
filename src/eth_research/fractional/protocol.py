"""Frozen pre-registration protocol for the Milestone 3B fractional experiment.

``fractional_protocol.json`` pins **everything** the one preregistered
research-train run will do — the five strategies, the three frozen cost
scenarios, the five reused walk-forward folds, every risk and tolerance
parameter, and the dataset/partition/fold bindings — so the experiment is
declared in full before any real number is computed and replays byte-identically.

The cost/liquidity settings are a **deterministic causal research proxy, not a
calibrated venue model** (daily OHLCV only); this is recorded in the protocol.
No parameter here is selected from observed output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research import __version__
from eth_research._json import require_canonical_file_bytes, strict_json_loads
from eth_research.data.provenance import sha256_file
from eth_research.development import (
    DEVELOPMENT_PARTITION_RELPATH,
    FROZEN_M2_DOSSIER_RELPATH,
    RESEARCH_TRAIN,
    load_development_partition,
)
from eth_research.fractional.accounting import DEFAULT_TOLERANCES
from eth_research.fractional.cost_model import SCENARIOS, CostScenario
from eth_research.fractional.risk import (
    ANNUAL_VOLATILITY_TARGET,
    DEFAULT_MAX_ABS_WEIGHT_CHANGE,
    VOLATILITY_DENOMINATOR_FLOOR,
    VOLATILITY_LOOKBACK,
    VOLATILITY_MIN_OBSERVATIONS,
)
from eth_research.fractional.strategies import STRATEGY_NAMES
from eth_research.fractional.validation import (
    require_bool,
    require_hex64,
    require_int,
    require_nonempty_str,
    require_nonnegative_real,
    require_positive_int,
    require_positive_real,
    require_tuple,
)
from eth_research.walkforward import (
    INITIAL_CASH,
    OOS_FOLD_COUNT,
    RESEARCH_TRAIN_ROWS,
    WALK_FORWARD_PROTOCOL_RELPATH,
)

FRACTIONAL_PROTOCOL_SCHEMA_VERSION: int = 1
FRACTIONAL_PROTOCOL_RELPATH: str = "research/m3b/fractional_protocol.json"
EXPERIMENT_FAMILY: str = "m3b-fractional-execution-risk-v1"
RUN_001_EXPERIMENT_ID: str = "m3b-fractional-execution-risk-v1-run-001"
PERMITTED_DATA_LEVEL: str = "research_train"
COST_CALIBRATION: str = "deterministic-causal-liquidity-and-impact-proxy-not-venue-calibrated"
BOOTSTRAP: str = "none"

_SCENARIO_KEYS = frozenset(
    {
        "name",
        "fee_rate",
        "half_spread_rate",
        "base_slippage_rate",
        "impact_coefficient",
        "impact_cap",
        "liquidity_lookback",
        "liquidity_min_observations",
        "max_participation",
    }
)


class ProtocolError(ValueError):
    """The fractional protocol failed strict validation."""


def _scenario_to_dict(scenario: CostScenario) -> dict[str, object]:
    return {
        "name": scenario.name,
        "fee_rate": scenario.fee_rate,
        "half_spread_rate": scenario.half_spread_rate,
        "base_slippage_rate": scenario.base_slippage_rate,
        "impact_coefficient": scenario.impact_coefficient,
        "impact_cap": scenario.impact_cap,
        "liquidity_lookback": scenario.liquidity_lookback,
        "liquidity_min_observations": scenario.liquidity_min_observations,
        "max_participation": scenario.max_participation,
    }


def _scenario_from_dict(payload: dict[str, Any]) -> CostScenario:
    if set(payload) != _SCENARIO_KEYS:
        raise ProtocolError(f"cost scenario keys do not match: {sorted(payload)}")
    max_participation = payload["max_participation"]
    return CostScenario(
        name=require_nonempty_str("name", payload["name"]),
        fee_rate=require_nonnegative_real("fee_rate", payload["fee_rate"]),
        half_spread_rate=require_nonnegative_real("half_spread_rate", payload["half_spread_rate"]),
        base_slippage_rate=require_nonnegative_real(
            "base_slippage_rate", payload["base_slippage_rate"]
        ),
        impact_coefficient=require_nonnegative_real(
            "impact_coefficient", payload["impact_coefficient"]
        ),
        impact_cap=require_nonnegative_real("impact_cap", payload["impact_cap"]),
        liquidity_lookback=require_positive_int(
            "liquidity_lookback", payload["liquidity_lookback"]
        ),
        liquidity_min_observations=require_positive_int(
            "liquidity_min_observations", payload["liquidity_min_observations"]
        ),
        max_participation=(
            None
            if max_participation is None
            else require_positive_real("max_participation", max_participation)
        ),
    )


@dataclass(frozen=True)
class FractionalProtocol:
    """The immutable, preregistered fractional experiment protocol."""

    fractional_protocol_schema_version: int
    package_version: str
    experiment_family: str
    permitted_data_level: str
    frozen_m2_dossier_sha256: str
    development_partition_sha256: str
    research_train_content_fingerprint: str
    research_train_row_count: int
    walk_forward_protocol_path: str
    walk_forward_protocol_sha256: str
    oos_fold_count: int
    initial_cash: float
    strategies: tuple[str, ...]
    cost_scenarios: tuple[CostScenario, ...]
    liquidity_lookback: int
    liquidity_min_observations: int
    volatility_lookback: int
    volatility_min_observations: int
    annual_volatility_target: float
    volatility_denominator_floor: float
    turnover_max_abs_weight_change: float
    drawdown_breaker_enabled: bool
    cash_tolerance: float
    quantity_tolerance: float
    weight_tolerance: float
    solver_tolerance: float
    no_trade_epsilon: float
    notional_epsilon: float
    solver_max_iterations: int
    experiment_cells: int
    bootstrap: str
    cost_calibration: str

    def __post_init__(self) -> None:
        if self.fractional_protocol_schema_version != FRACTIONAL_PROTOCOL_SCHEMA_VERSION:
            raise ProtocolError("unexpected schema version")
        if self.experiment_family != EXPERIMENT_FAMILY:
            raise ProtocolError(f"experiment_family must be {EXPERIMENT_FAMILY!r}")
        if self.permitted_data_level != PERMITTED_DATA_LEVEL:
            raise ProtocolError("permitted_data_level must be research_train")
        if self.strategies != STRATEGY_NAMES:
            raise ProtocolError("strategies must match the five pinned fractional strategies")
        if tuple(s.name for s in self.cost_scenarios) != tuple(s.name for s in SCENARIOS):
            raise ProtocolError("cost scenarios must match the three frozen scenarios")
        if self.research_train_row_count != RESEARCH_TRAIN_ROWS:
            raise ProtocolError("research_train_row_count must be 2221")
        if self.oos_fold_count != OOS_FOLD_COUNT:
            raise ProtocolError("oos_fold_count must be 5")
        if self.drawdown_breaker_enabled:
            raise ProtocolError("the drawdown breaker is disabled for run-001")
        if self.bootstrap != BOOTSTRAP:
            raise ProtocolError("bootstrap must be 'none'")
        expected_cells = len(STRATEGY_NAMES) * len(SCENARIOS) * OOS_FOLD_COUNT
        if self.experiment_cells != expected_cells:
            raise ProtocolError(f"experiment_cells must be {expected_cells}")
        require_hex64("frozen_m2_dossier_sha256", self.frozen_m2_dossier_sha256)
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        require_hex64("walk_forward_protocol_sha256", self.walk_forward_protocol_sha256)
        for scenario in self.cost_scenarios:
            if scenario not in SCENARIOS:
                raise ProtocolError(f"cost scenario {scenario.name!r} is not a frozen scenario")

    def to_json_bytes(self) -> bytes:
        payload = {
            "fractional_protocol_schema_version": self.fractional_protocol_schema_version,
            "package_version": self.package_version,
            "experiment_family": self.experiment_family,
            "permitted_data_level": self.permitted_data_level,
            "frozen_m2_dossier_sha256": self.frozen_m2_dossier_sha256,
            "development_partition_sha256": self.development_partition_sha256,
            "research_train_content_fingerprint": self.research_train_content_fingerprint,
            "research_train_row_count": self.research_train_row_count,
            "walk_forward_protocol_path": self.walk_forward_protocol_path,
            "walk_forward_protocol_sha256": self.walk_forward_protocol_sha256,
            "oos_fold_count": self.oos_fold_count,
            "initial_cash": self.initial_cash,
            "strategies": list(self.strategies),
            "cost_scenarios": [_scenario_to_dict(s) for s in self.cost_scenarios],
            "liquidity_lookback": self.liquidity_lookback,
            "liquidity_min_observations": self.liquidity_min_observations,
            "volatility_lookback": self.volatility_lookback,
            "volatility_min_observations": self.volatility_min_observations,
            "annual_volatility_target": self.annual_volatility_target,
            "volatility_denominator_floor": self.volatility_denominator_floor,
            "turnover_max_abs_weight_change": self.turnover_max_abs_weight_change,
            "drawdown_breaker_enabled": self.drawdown_breaker_enabled,
            "cash_tolerance": self.cash_tolerance,
            "quantity_tolerance": self.quantity_tolerance,
            "weight_tolerance": self.weight_tolerance,
            "solver_tolerance": self.solver_tolerance,
            "no_trade_epsilon": self.no_trade_epsilon,
            "notional_epsilon": self.notional_epsilon,
            "solver_max_iterations": self.solver_max_iterations,
            "experiment_cells": self.experiment_cells,
            "bootstrap": self.bootstrap,
            "cost_calibration": self.cost_calibration,
        }
        return (
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n"
        ).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> FractionalProtocol:
        payload = strict_json_loads(raw)
        if not isinstance(payload, dict):
            raise ProtocolError("protocol must be a JSON object")
        scenarios = payload.get("cost_scenarios")
        if not isinstance(scenarios, list):
            raise ProtocolError("cost_scenarios must be a list")
        parsed = cls(
            fractional_protocol_schema_version=require_int(
                "fractional_protocol_schema_version",
                payload["fractional_protocol_schema_version"],
            ),
            package_version=require_nonempty_str("package_version", payload["package_version"]),
            experiment_family=require_nonempty_str(
                "experiment_family", payload["experiment_family"]
            ),
            permitted_data_level=require_nonempty_str(
                "permitted_data_level", payload["permitted_data_level"]
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
            research_train_row_count=require_positive_int(
                "research_train_row_count", payload["research_train_row_count"]
            ),
            walk_forward_protocol_path=require_nonempty_str(
                "walk_forward_protocol_path", payload["walk_forward_protocol_path"]
            ),
            walk_forward_protocol_sha256=require_hex64(
                "walk_forward_protocol_sha256", payload["walk_forward_protocol_sha256"]
            ),
            oos_fold_count=require_positive_int("oos_fold_count", payload["oos_fold_count"]),
            initial_cash=require_positive_real("initial_cash", payload["initial_cash"]),
            strategies=require_tuple("strategies", payload["strategies"], require_nonempty_str),
            cost_scenarios=tuple(_scenario_from_dict(s) for s in scenarios),
            liquidity_lookback=require_positive_int(
                "liquidity_lookback", payload["liquidity_lookback"]
            ),
            liquidity_min_observations=require_positive_int(
                "liquidity_min_observations", payload["liquidity_min_observations"]
            ),
            volatility_lookback=require_positive_int(
                "volatility_lookback", payload["volatility_lookback"]
            ),
            volatility_min_observations=require_positive_int(
                "volatility_min_observations", payload["volatility_min_observations"]
            ),
            annual_volatility_target=require_positive_real(
                "annual_volatility_target", payload["annual_volatility_target"]
            ),
            volatility_denominator_floor=require_positive_real(
                "volatility_denominator_floor", payload["volatility_denominator_floor"]
            ),
            turnover_max_abs_weight_change=require_nonnegative_real(
                "turnover_max_abs_weight_change", payload["turnover_max_abs_weight_change"]
            ),
            drawdown_breaker_enabled=require_bool(
                "drawdown_breaker_enabled", payload["drawdown_breaker_enabled"]
            ),
            cash_tolerance=require_nonnegative_real("cash_tolerance", payload["cash_tolerance"]),
            quantity_tolerance=require_nonnegative_real(
                "quantity_tolerance", payload["quantity_tolerance"]
            ),
            weight_tolerance=require_nonnegative_real(
                "weight_tolerance", payload["weight_tolerance"]
            ),
            solver_tolerance=require_nonnegative_real(
                "solver_tolerance", payload["solver_tolerance"]
            ),
            no_trade_epsilon=require_nonnegative_real(
                "no_trade_epsilon", payload["no_trade_epsilon"]
            ),
            notional_epsilon=require_nonnegative_real(
                "notional_epsilon", payload["notional_epsilon"]
            ),
            solver_max_iterations=require_positive_int(
                "solver_max_iterations", payload["solver_max_iterations"]
            ),
            experiment_cells=require_positive_int("experiment_cells", payload["experiment_cells"]),
            bootstrap=require_nonempty_str("bootstrap", payload["bootstrap"]),
            cost_calibration=require_nonempty_str("cost_calibration", payload["cost_calibration"]),
        )
        expected = {
            "fractional_protocol_schema_version",
            "package_version",
            "experiment_family",
            "permitted_data_level",
            "frozen_m2_dossier_sha256",
            "development_partition_sha256",
            "research_train_content_fingerprint",
            "research_train_row_count",
            "walk_forward_protocol_path",
            "walk_forward_protocol_sha256",
            "oos_fold_count",
            "initial_cash",
            "strategies",
            "cost_scenarios",
            "liquidity_lookback",
            "liquidity_min_observations",
            "volatility_lookback",
            "volatility_min_observations",
            "annual_volatility_target",
            "volatility_denominator_floor",
            "turnover_max_abs_weight_change",
            "drawdown_breaker_enabled",
            "cash_tolerance",
            "quantity_tolerance",
            "weight_tolerance",
            "solver_tolerance",
            "no_trade_epsilon",
            "notional_epsilon",
            "solver_max_iterations",
            "experiment_cells",
            "bootstrap",
            "cost_calibration",
        }
        if set(payload) != expected:
            raise ProtocolError(
                f"protocol keys do not match: unexpected={sorted(set(payload) - expected)}"
            )
        return parsed


def build_fractional_protocol(
    repo_root: str | Path, *, package_version: str = __version__
) -> FractionalProtocol:
    """Assemble the protocol from the committed dataset/partition/fold artifacts.

    ``package_version`` defaults to the running version; a reproduction binds the
    committed protocol's recorded version so the bytes stay stable across a bump.
    """
    root = Path(repo_root)
    partition = load_development_partition(root / DEVELOPMENT_PARTITION_RELPATH)
    research_train = next(p for p in partition.partitions if p.name == RESEARCH_TRAIN)
    tol = DEFAULT_TOLERANCES
    return FractionalProtocol(
        fractional_protocol_schema_version=FRACTIONAL_PROTOCOL_SCHEMA_VERSION,
        package_version=package_version,
        experiment_family=EXPERIMENT_FAMILY,
        permitted_data_level=PERMITTED_DATA_LEVEL,
        frozen_m2_dossier_sha256=sha256_file(root / FROZEN_M2_DOSSIER_RELPATH),
        development_partition_sha256=sha256_file(root / DEVELOPMENT_PARTITION_RELPATH),
        research_train_content_fingerprint=research_train.content_fingerprint,
        research_train_row_count=research_train.row_count,
        walk_forward_protocol_path=WALK_FORWARD_PROTOCOL_RELPATH,
        walk_forward_protocol_sha256=sha256_file(root / WALK_FORWARD_PROTOCOL_RELPATH),
        oos_fold_count=OOS_FOLD_COUNT,
        initial_cash=INITIAL_CASH,
        strategies=STRATEGY_NAMES,
        cost_scenarios=SCENARIOS,
        liquidity_lookback=SCENARIOS[1].liquidity_lookback,
        liquidity_min_observations=SCENARIOS[1].liquidity_min_observations,
        volatility_lookback=VOLATILITY_LOOKBACK,
        volatility_min_observations=VOLATILITY_MIN_OBSERVATIONS,
        annual_volatility_target=ANNUAL_VOLATILITY_TARGET,
        volatility_denominator_floor=VOLATILITY_DENOMINATOR_FLOOR,
        turnover_max_abs_weight_change=DEFAULT_MAX_ABS_WEIGHT_CHANGE,
        drawdown_breaker_enabled=False,
        cash_tolerance=tol.cash_tolerance,
        quantity_tolerance=tol.quantity_tolerance,
        weight_tolerance=tol.weight_tolerance,
        solver_tolerance=tol.solver_tolerance,
        no_trade_epsilon=tol.no_trade_epsilon,
        notional_epsilon=tol.notional_epsilon,
        solver_max_iterations=tol.max_iterations,
        experiment_cells=len(STRATEGY_NAMES) * len(SCENARIOS) * OOS_FOLD_COUNT,
        bootstrap=BOOTSTRAP,
        cost_calibration=COST_CALIBRATION,
    )


def load_fractional_protocol(path: str | Path) -> FractionalProtocol:
    """Strictly parse a committed fractional protocol file."""
    raw = require_canonical_file_bytes(Path(path).read_bytes(), "fractional protocol")
    return FractionalProtocol.from_json_bytes(raw)
