"""Immutable v2 methodology / protocol artifact for the corrective run-003.

Milestone 3A run-001 and run-002 were pre-registered against the v1
walk-forward protocol (:mod:`eth_research.walkforward`) and used the v1
moving-block bootstrap, whose blocks could cross independent-reset fold seams
(closure defect R4). The corrective run-003 keeps **every** strategy, cost,
fold, and boundary identical — it changes only the *inference* method and the
*governance/provenance* around publication — so this artifact does **not**
mutate the historical v1 protocol. Instead it is a separate, immutable v2
methodology record that:

* binds the v1 protocol by path and SHA-256 (its exact folds and boundaries
  are pinned by reference and never rewritten);
* re-pins the research-train identity and every structural constant, as a
  defense-in-depth cross-check against the v1 protocol;
* declares the fixed-rule, no-estimator-fit semantics explicitly;
* pins the primary fold-stratified bootstrap v2 and the hierarchical
  sensitivity bootstrap, with their seeds, block length, resamples,
  confidence, statistic, fold weighting, and RNG implementation;
* names the experiment family/version, the permitted data level, and the
  exact artifact schema versions (results v2, registry v2, return-evidence).

The parser is strict and symmetric: a methodology that constructs is a
methodology that parses, and vice versa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research import __version__
from eth_research._json import StrictJSONError, require_canonical_file_bytes, strict_json_loads
from eth_research.bootstrap import RNG_ALGORITHM, STATISTIC
from eth_research.bootstrap_v2 import (
    FOLD_STRATIFIED_ALGORITHM,
    HIERARCHICAL_ALGORITHM,
    FoldAwareBootstrapConfig,
)
from eth_research.costs import COST_SCENARIOS, CostScenario
from eth_research.data.provenance import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
)
from eth_research.data.validation import (
    require_fingerprint,
    require_finite_float,
)
from eth_research.experiment_registry import REGISTRY_SCHEMA_VERSION_V2
from eth_research.walkforward import (
    BOOTSTRAP_BLOCK_LENGTH,
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    INFORMATION_GAP_BARS,
    INITIAL_CASH,
    INITIAL_TRAINING_ROWS,
    MAX_CONTEXT_BARS,
    OOS_FOLD_COUNT,
    RESEARCH_TRAIN_ROWS,
    SPLIT_SEMANTICS,
    STRATEGY_NAMES,
    WALK_FORWARD_PROTOCOL_RELPATH,
)

METHODOLOGY_SCHEMA_VERSION: int = 2
METHODOLOGY_PROTOCOL_V2_RELPATH: str = "research/m3a/walk_forward_protocol_v2.json"

METHODOLOGY_ID: str = "walk-forward-fold-stratified-bootstrap-v2"
EXPERIMENT_FAMILY_V1: str = "m3a-fixed-baseline-comparison-v1"
EXPERIMENT_FAMILY_V2: str = "m3a-fixed-baseline-comparison-v2"
PERMITTED_DATA_LEVEL: str = "research_train"
NO_FIT_SEMANTICS: str = "fixed-rule-rolling-origin-oos-no-estimator-fit"
BOOTSTRAP_FOLD_WEIGHTING: str = "observation_weighted"

# Artifact schema versions pinned by this methodology. Cross-checked against the
# owning modules in the test suite so the pin cannot silently drift.
RESULTS_SCHEMA_VERSION_V2: int = 2
RETURN_EVIDENCE_SCHEMA_VERSION: int = 1

# The v1 protocol this methodology corrects (bound by SHA-256, never rewritten).
_V1_PROTOCOL_SHA256: str = "61b32d4ee18e252552c92619c8464cd20b306e313393b0c86cbbbb2093a1c160"
_DEV_PARTITION_SHA256: str = "14d61c9ad36a20b70b3f830e8470dc416319ef4accf36b90c5d2b4094ead7ac2"
_RESEARCH_TRAIN_FINGERPRINT: str = (
    "sha256:60aa988e9db786db5723c925abc794463c23ff701791173b745196c7a8b12033"
)

_SENSITIVITY_SEED: int = FoldAwareBootstrapConfig().hierarchical_seed

_SCENARIO_KEYS: frozenset[str] = frozenset({"name", "fee_rate", "slippage_rate"})
_METHODOLOGY_KEYS: frozenset[str] = frozenset(
    {
        "methodology_schema_version",
        "methodology_id",
        "package_version",
        "experiment_family",
        "corrects_experiment_family",
        "permitted_data_level",
        "base_walk_forward_protocol_path",
        "base_walk_forward_protocol_sha256",
        "development_partition_sha256",
        "research_train_content_fingerprint",
        "research_train_row_count",
        "initial_training_rows",
        "oos_fold_count",
        "information_gap_bars",
        "max_context_bars",
        "initial_cash",
        "split_semantics",
        "no_fit_semantics",
        "strategies",
        "cost_scenarios",
        "primary_bootstrap_algorithm",
        "primary_bootstrap_seed",
        "sensitivity_bootstrap_algorithm",
        "sensitivity_bootstrap_seed",
        "bootstrap_block_length",
        "bootstrap_resamples",
        "bootstrap_confidence",
        "bootstrap_statistic",
        "bootstrap_fold_weighting",
        "bootstrap_rng_algorithm",
        "results_schema_version",
        "registry_schema_version",
        "return_evidence_schema_version",
    }
)


class MethodologyError(RuntimeError):
    """The v2 methodology artifact is invalid or disagrees with the pins."""


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
class MethodologyProtocolV2:
    """Strict, byte-reproducible v2 methodology artifact for run-003."""

    methodology_schema_version: int
    methodology_id: str
    package_version: str
    experiment_family: str
    corrects_experiment_family: str
    permitted_data_level: str
    base_walk_forward_protocol_path: str
    base_walk_forward_protocol_sha256: str
    development_partition_sha256: str
    research_train_content_fingerprint: str
    research_train_row_count: int
    initial_training_rows: int
    oos_fold_count: int
    information_gap_bars: int
    max_context_bars: int
    initial_cash: float
    split_semantics: str
    no_fit_semantics: str
    strategies: tuple[str, ...]
    cost_scenarios: tuple[CostScenario, ...]
    primary_bootstrap_algorithm: str
    primary_bootstrap_seed: int
    sensitivity_bootstrap_algorithm: str
    sensitivity_bootstrap_seed: int
    bootstrap_block_length: int
    bootstrap_resamples: int
    bootstrap_confidence: float
    bootstrap_statistic: str
    bootstrap_fold_weighting: str
    bootstrap_rng_algorithm: str
    results_schema_version: int
    registry_schema_version: int
    return_evidence_schema_version: int

    def __post_init__(self) -> None:
        if self.methodology_schema_version != METHODOLOGY_SCHEMA_VERSION:
            raise ValueError(
                f"methodology_schema_version is pinned to {METHODOLOGY_SCHEMA_VERSION}, "
                f"got {self.methodology_schema_version!r}"
            )
        if self.methodology_id != METHODOLOGY_ID:
            raise ValueError(f"methodology_id is pinned to {METHODOLOGY_ID!r}")
        require_nonempty_str("package_version", self.package_version)
        if self.experiment_family != EXPERIMENT_FAMILY_V2:
            raise ValueError(f"experiment_family is pinned to {EXPERIMENT_FAMILY_V2!r}")
        if self.corrects_experiment_family != EXPERIMENT_FAMILY_V1:
            raise ValueError(f"corrects_experiment_family is pinned to {EXPERIMENT_FAMILY_V1!r}")
        if self.permitted_data_level != PERMITTED_DATA_LEVEL:
            raise ValueError(f"permitted_data_level is pinned to {PERMITTED_DATA_LEVEL!r}")
        if self.base_walk_forward_protocol_path != WALK_FORWARD_PROTOCOL_RELPATH:
            raise ValueError(
                f"base_walk_forward_protocol_path is pinned to {WALK_FORWARD_PROTOCOL_RELPATH!r}"
            )
        require_hex64("base_walk_forward_protocol_sha256", self.base_walk_forward_protocol_sha256)
        if self.base_walk_forward_protocol_sha256 != _V1_PROTOCOL_SHA256:
            raise ValueError(
                "base_walk_forward_protocol_sha256 does not match the frozen v1 protocol"
            )
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        if self.development_partition_sha256 != _DEV_PARTITION_SHA256:
            raise ValueError("development_partition_sha256 does not match the frozen partition")
        require_fingerprint(
            "research_train_content_fingerprint", self.research_train_content_fingerprint
        )
        if self.research_train_content_fingerprint != _RESEARCH_TRAIN_FINGERPRINT:
            raise ValueError(
                "research_train_content_fingerprint does not match the frozen partition"
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
        if self.no_fit_semantics != NO_FIT_SEMANTICS:
            raise ValueError(f"no_fit_semantics is pinned to {NO_FIT_SEMANTICS!r}")
        if tuple(self.strategies) != STRATEGY_NAMES:
            raise ValueError(f"strategies are pinned to {STRATEGY_NAMES}, got {self.strategies}")
        if tuple(s.name for s in self.cost_scenarios) != tuple(s.name for s in COST_SCENARIOS):
            raise ValueError("cost scenarios must be exactly the three pinned scenarios in order")
        for got, want in zip(self.cost_scenarios, COST_SCENARIOS, strict=True):
            if (got.fee_rate, got.slippage_rate) != (want.fee_rate, want.slippage_rate):
                raise ValueError(f"cost scenario {got.name!r} rates disagree with the pinned rates")
        if self.primary_bootstrap_algorithm != FOLD_STRATIFIED_ALGORITHM:
            raise ValueError(
                f"primary_bootstrap_algorithm is pinned to {FOLD_STRATIFIED_ALGORITHM!r}"
            )
        if self.primary_bootstrap_seed != BOOTSTRAP_SEED:
            raise ValueError(f"primary_bootstrap_seed is pinned to {BOOTSTRAP_SEED}")
        if self.sensitivity_bootstrap_algorithm != HIERARCHICAL_ALGORITHM:
            raise ValueError(
                f"sensitivity_bootstrap_algorithm is pinned to {HIERARCHICAL_ALGORITHM!r}"
            )
        if self.sensitivity_bootstrap_seed != _SENSITIVITY_SEED:
            raise ValueError(f"sensitivity_bootstrap_seed is pinned to {_SENSITIVITY_SEED}")
        if self.bootstrap_block_length != BOOTSTRAP_BLOCK_LENGTH:
            raise ValueError(f"bootstrap_block_length is pinned to {BOOTSTRAP_BLOCK_LENGTH}")
        if self.bootstrap_resamples != BOOTSTRAP_RESAMPLES:
            raise ValueError(f"bootstrap_resamples is pinned to {BOOTSTRAP_RESAMPLES}")
        if require_finite_float("bootstrap_confidence", self.bootstrap_confidence) != (
            BOOTSTRAP_CONFIDENCE
        ):
            raise ValueError(f"bootstrap_confidence is pinned to {BOOTSTRAP_CONFIDENCE}")
        if self.bootstrap_statistic != STATISTIC:
            raise ValueError(f"bootstrap_statistic is pinned to {STATISTIC!r}")
        if self.bootstrap_fold_weighting != BOOTSTRAP_FOLD_WEIGHTING:
            raise ValueError(f"bootstrap_fold_weighting is pinned to {BOOTSTRAP_FOLD_WEIGHTING!r}")
        if self.bootstrap_rng_algorithm != RNG_ALGORITHM:
            raise ValueError(f"bootstrap_rng_algorithm is pinned to {RNG_ALGORITHM!r}")
        if self.results_schema_version != RESULTS_SCHEMA_VERSION_V2:
            raise ValueError(f"results_schema_version is pinned to {RESULTS_SCHEMA_VERSION_V2}")
        if self.registry_schema_version != REGISTRY_SCHEMA_VERSION_V2:
            raise ValueError(f"registry_schema_version is pinned to {REGISTRY_SCHEMA_VERSION_V2}")
        if self.return_evidence_schema_version != RETURN_EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                f"return_evidence_schema_version is pinned to {RETURN_EVIDENCE_SCHEMA_VERSION}"
            )

    def to_json_bytes(self) -> bytes:
        payload = {
            "methodology_schema_version": self.methodology_schema_version,
            "methodology_id": self.methodology_id,
            "package_version": self.package_version,
            "experiment_family": self.experiment_family,
            "corrects_experiment_family": self.corrects_experiment_family,
            "permitted_data_level": self.permitted_data_level,
            "base_walk_forward_protocol_path": self.base_walk_forward_protocol_path,
            "base_walk_forward_protocol_sha256": self.base_walk_forward_protocol_sha256,
            "development_partition_sha256": self.development_partition_sha256,
            "research_train_content_fingerprint": self.research_train_content_fingerprint,
            "research_train_row_count": self.research_train_row_count,
            "initial_training_rows": self.initial_training_rows,
            "oos_fold_count": self.oos_fold_count,
            "information_gap_bars": self.information_gap_bars,
            "max_context_bars": self.max_context_bars,
            "initial_cash": self.initial_cash,
            "split_semantics": self.split_semantics,
            "no_fit_semantics": self.no_fit_semantics,
            "strategies": list(self.strategies),
            "cost_scenarios": [_scenario_to_dict(s) for s in self.cost_scenarios],
            "primary_bootstrap_algorithm": self.primary_bootstrap_algorithm,
            "primary_bootstrap_seed": self.primary_bootstrap_seed,
            "sensitivity_bootstrap_algorithm": self.sensitivity_bootstrap_algorithm,
            "sensitivity_bootstrap_seed": self.sensitivity_bootstrap_seed,
            "bootstrap_block_length": self.bootstrap_block_length,
            "bootstrap_resamples": self.bootstrap_resamples,
            "bootstrap_confidence": self.bootstrap_confidence,
            "bootstrap_statistic": self.bootstrap_statistic,
            "bootstrap_fold_weighting": self.bootstrap_fold_weighting,
            "bootstrap_rng_algorithm": self.bootstrap_rng_algorithm,
            "results_schema_version": self.results_schema_version,
            "registry_schema_version": self.registry_schema_version,
            "return_evidence_schema_version": self.return_evidence_schema_version,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> MethodologyProtocolV2:
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"methodology artifact is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("methodology artifact JSON must be an object")
        keys = set(payload)
        if keys != _METHODOLOGY_KEYS:
            unknown = sorted(keys - _METHODOLOGY_KEYS)
            missing = sorted(_METHODOLOGY_KEYS - keys)
            raise ValueError(f"methodology keys do not match: unknown={unknown}, missing={missing}")
        scenarios = payload["cost_scenarios"]
        strategies = payload["strategies"]
        if not isinstance(scenarios, list) or not isinstance(strategies, list):
            raise ValueError("strategies and cost_scenarios must be lists")
        return cls(
            methodology_schema_version=require_int(
                "methodology_schema_version", payload["methodology_schema_version"]
            ),
            methodology_id=require_str("methodology_id", payload["methodology_id"]),
            package_version=require_str("package_version", payload["package_version"]),
            experiment_family=require_str("experiment_family", payload["experiment_family"]),
            corrects_experiment_family=require_str(
                "corrects_experiment_family", payload["corrects_experiment_family"]
            ),
            permitted_data_level=require_str(
                "permitted_data_level", payload["permitted_data_level"]
            ),
            base_walk_forward_protocol_path=require_str(
                "base_walk_forward_protocol_path", payload["base_walk_forward_protocol_path"]
            ),
            base_walk_forward_protocol_sha256=require_str(
                "base_walk_forward_protocol_sha256", payload["base_walk_forward_protocol_sha256"]
            ),
            development_partition_sha256=require_str(
                "development_partition_sha256", payload["development_partition_sha256"]
            ),
            research_train_content_fingerprint=require_str(
                "research_train_content_fingerprint",
                payload["research_train_content_fingerprint"],
            ),
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
            no_fit_semantics=require_str("no_fit_semantics", payload["no_fit_semantics"]),
            strategies=tuple(require_str("strategy", s) for s in strategies),
            cost_scenarios=tuple(_scenario_from_dict(s) for s in scenarios),
            primary_bootstrap_algorithm=require_str(
                "primary_bootstrap_algorithm", payload["primary_bootstrap_algorithm"]
            ),
            primary_bootstrap_seed=require_int(
                "primary_bootstrap_seed", payload["primary_bootstrap_seed"]
            ),
            sensitivity_bootstrap_algorithm=require_str(
                "sensitivity_bootstrap_algorithm", payload["sensitivity_bootstrap_algorithm"]
            ),
            sensitivity_bootstrap_seed=require_int(
                "sensitivity_bootstrap_seed", payload["sensitivity_bootstrap_seed"]
            ),
            bootstrap_block_length=require_int(
                "bootstrap_block_length", payload["bootstrap_block_length"]
            ),
            bootstrap_resamples=require_int("bootstrap_resamples", payload["bootstrap_resamples"]),
            bootstrap_confidence=require_finite_float(
                "bootstrap_confidence", payload["bootstrap_confidence"]
            ),
            bootstrap_statistic=require_str("bootstrap_statistic", payload["bootstrap_statistic"]),
            bootstrap_fold_weighting=require_str(
                "bootstrap_fold_weighting", payload["bootstrap_fold_weighting"]
            ),
            bootstrap_rng_algorithm=require_str(
                "bootstrap_rng_algorithm", payload["bootstrap_rng_algorithm"]
            ),
            results_schema_version=require_int(
                "results_schema_version", payload["results_schema_version"]
            ),
            registry_schema_version=require_int(
                "registry_schema_version", payload["registry_schema_version"]
            ),
            return_evidence_schema_version=require_int(
                "return_evidence_schema_version", payload["return_evidence_schema_version"]
            ),
        )


def build_methodology_v2(package_version: str = __version__) -> MethodologyProtocolV2:
    """The canonical v2 methodology artifact, from the pinned constants.

    ``package_version`` defaults to the running package version so a fresh
    build stamps this code's own version; a reproduction of the committed
    artifact binds the version it recorded so a later package bump leaves the
    committed bytes byte-identical (the artifact content is version-independent).
    """
    return MethodologyProtocolV2(
        methodology_schema_version=METHODOLOGY_SCHEMA_VERSION,
        methodology_id=METHODOLOGY_ID,
        package_version=package_version,
        experiment_family=EXPERIMENT_FAMILY_V2,
        corrects_experiment_family=EXPERIMENT_FAMILY_V1,
        permitted_data_level=PERMITTED_DATA_LEVEL,
        base_walk_forward_protocol_path=WALK_FORWARD_PROTOCOL_RELPATH,
        base_walk_forward_protocol_sha256=_V1_PROTOCOL_SHA256,
        development_partition_sha256=_DEV_PARTITION_SHA256,
        research_train_content_fingerprint=_RESEARCH_TRAIN_FINGERPRINT,
        research_train_row_count=RESEARCH_TRAIN_ROWS,
        initial_training_rows=INITIAL_TRAINING_ROWS,
        oos_fold_count=OOS_FOLD_COUNT,
        information_gap_bars=INFORMATION_GAP_BARS,
        max_context_bars=MAX_CONTEXT_BARS,
        initial_cash=INITIAL_CASH,
        split_semantics=SPLIT_SEMANTICS,
        no_fit_semantics=NO_FIT_SEMANTICS,
        strategies=STRATEGY_NAMES,
        cost_scenarios=tuple(COST_SCENARIOS),
        primary_bootstrap_algorithm=FOLD_STRATIFIED_ALGORITHM,
        primary_bootstrap_seed=BOOTSTRAP_SEED,
        sensitivity_bootstrap_algorithm=HIERARCHICAL_ALGORITHM,
        sensitivity_bootstrap_seed=_SENSITIVITY_SEED,
        bootstrap_block_length=BOOTSTRAP_BLOCK_LENGTH,
        bootstrap_resamples=BOOTSTRAP_RESAMPLES,
        bootstrap_confidence=BOOTSTRAP_CONFIDENCE,
        bootstrap_statistic=STATISTIC,
        bootstrap_fold_weighting=BOOTSTRAP_FOLD_WEIGHTING,
        bootstrap_rng_algorithm=RNG_ALGORITHM,
        results_schema_version=RESULTS_SCHEMA_VERSION_V2,
        registry_schema_version=REGISTRY_SCHEMA_VERSION_V2,
        return_evidence_schema_version=RETURN_EVIDENCE_SCHEMA_VERSION,
    )


def load_methodology_v2(path: str | Path) -> MethodologyProtocolV2:
    """Strictly parse the committed v2 methodology artifact."""
    raw = Path(path).read_bytes()
    try:
        require_canonical_file_bytes(raw, "v2 methodology artifact")
        return MethodologyProtocolV2.from_json_bytes(raw)
    except ValueError as exc:
        raise MethodologyError(f"invalid v2 methodology artifact: {exc}") from exc
