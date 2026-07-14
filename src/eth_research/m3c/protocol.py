"""Frozen pre-registration protocol for the one Milestone 3C candidate experiment.

``M3CProtocol`` pins **everything** the single preregistered research-train run
will do — the fixed candidate and its canonical fingerprint, the five-strategy
benchmark grid, the three frozen cost scenarios, the reused expanding-window
folds and 252-bar common context, the frozen primary endpoint and its
fold-seam-aware bootstrap configuration, the decision alpha, and the bindings to
the lineage, budget, dossier, and partition — so the experiment is declared in
full before any real number is computed and replays byte-identically.

Every constant is re-pinned in ``__post_init__``: a reordered strategy or cost
list, a changed fold boundary, a changed initial cash, a non-empty sealed-ledger
hash, or a drifted bootstrap parameter is rejected. The two sealed access ledgers
are bound as the empty-content SHA-256, recording that neither was ever written.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from eth_research._json import require_canonical_file_bytes
from eth_research.data.provenance import content_fingerprint
from eth_research.fractional.cost_model import SCENARIOS
from eth_research.m3c.candidate import (
    CANDIDATE_FINGERPRINT,
    M3C_CANDIDATE_ID,
    M3C_MAX_CONTEXT_BARS,
    M3C_STRATEGY_NAMES,
)
from eth_research.m3c.results import (
    M3C_BUDGET_RELPATH,
    M3C_EXPERIMENT_FAMILY,
    M3C_EXPERIMENT_ID,
    M3C_LINEAGE_RELPATH,
    M3C_PROTOCOL_RELPATH,
    PRIMARY_COMPARATOR,
    PRIMARY_SCENARIO,
    PRIMARY_STATISTIC,
)
from eth_research.m3c.statistics import (
    M3C_BOOTSTRAP_ALGORITHM,
    M3C_BOOTSTRAP_CONFIDENCE,
    M3C_BOOTSTRAP_RESAMPLES,
    M3C_BOOTSTRAP_SEED,
)
from eth_research.m3c.validation import (
    canonical_json_bytes,
    require_exact_keys,
    require_exact_string,
    require_hex64,
    require_int,
    require_mapping,
    require_nonempty_str,
    require_positive_int,
    require_positive_real,
    require_sha256_fingerprint,
    require_tuple,
    require_unit_interval,
    strict_json_loads,
)
from eth_research.walkforward import (
    INITIAL_CASH,
    INITIAL_TRAINING_ROWS,
    OOS_FOLD_COUNT,
    RESEARCH_TRAIN_ROWS,
    WalkForwardProtocol,
)

M3C_PROTOCOL_SCHEMA_VERSION: int = 1
PERMITTED_DATA_LEVEL: str = "research_train"
BOOTSTRAP_BLOCK_LENGTH_RULE: str = "floor(n**(1/3))"
DECISION_ALPHA: float = 0.05

# SHA-256 of empty content: both sealed access ledgers are byte-empty, so their
# committed digests are this value and nothing else.
EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

PROMOTION_CRITERIA: tuple[str, ...] = ("P1", "P2", "P3", "P4", "P5", "P6", "P7")
_SCENARIO_NAMES: tuple[str, ...] = tuple(s.name for s in SCENARIOS)

# Re-exported here so callers may import the protocol relpath from this module.
__all__ = [
    "EMPTY_SHA256",
    "M3C_PROTOCOL_RELPATH",
    "M3C_PROTOCOL_SCHEMA_VERSION",
    "M3CProtocol",
    "ProtocolError",
    "build_m3c_protocol",
    "load_m3c_protocol",
]


class ProtocolError(ValueError):
    """The M3C protocol failed strict validation."""


@dataclass(frozen=True)
class M3CProtocol:
    """The immutable, preregistered M3C candidate experiment protocol."""

    m3c_protocol_schema_version: int
    package_version: str
    experiment_id: str
    experiment_family: str
    candidate_id: str
    candidate_fingerprint: str
    permitted_data_level: str
    research_train_row_count: int
    initial_training_rows: int
    oos_fold_count: int
    max_context_bars: int
    initial_cash: float
    strategies: tuple[str, ...]
    cost_scenarios: tuple[str, ...]
    frozen_m2_dossier_sha256: str
    development_partition_sha256: str
    research_train_content_fingerprint: str
    lineage_path: str
    lineage_sha256: str
    budget_path: str
    budget_sha256: str
    primary_scenario: str
    primary_comparator: str
    primary_statistic: str
    bootstrap_algorithm: str
    bootstrap_seed: int
    bootstrap_resamples: int
    bootstrap_confidence: float
    bootstrap_block_length_rule: str
    decision_alpha: float
    development_gate_ledger_sha256: str
    final_holdout_ledger_sha256: str
    promotion_criteria: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.m3c_protocol_schema_version != M3C_PROTOCOL_SCHEMA_VERSION:
            raise ProtocolError("unexpected schema version")
        if self.experiment_id != M3C_EXPERIMENT_ID:
            raise ProtocolError(f"experiment_id must be {M3C_EXPERIMENT_ID!r}")
        if self.experiment_family != M3C_EXPERIMENT_FAMILY:
            raise ProtocolError(f"experiment_family must be {M3C_EXPERIMENT_FAMILY!r}")
        if self.candidate_id != M3C_CANDIDATE_ID:
            raise ProtocolError("candidate_id is pinned to the one M3C candidate")
        if self.candidate_fingerprint != CANDIDATE_FINGERPRINT:
            raise ProtocolError("candidate_fingerprint does not match the composed candidate")
        if self.permitted_data_level != PERMITTED_DATA_LEVEL:
            raise ProtocolError("permitted_data_level must be research_train")
        if self.research_train_row_count != RESEARCH_TRAIN_ROWS:
            raise ProtocolError(f"research_train_row_count must be {RESEARCH_TRAIN_ROWS}")
        if self.initial_training_rows != INITIAL_TRAINING_ROWS:
            raise ProtocolError(f"initial_training_rows must be {INITIAL_TRAINING_ROWS}")
        if self.oos_fold_count != OOS_FOLD_COUNT:
            raise ProtocolError(f"oos_fold_count must be {OOS_FOLD_COUNT}")
        if self.max_context_bars != M3C_MAX_CONTEXT_BARS:
            raise ProtocolError(f"max_context_bars must be {M3C_MAX_CONTEXT_BARS}")
        if self.initial_cash != INITIAL_CASH:
            raise ProtocolError(f"initial_cash must be {INITIAL_CASH}")
        if self.strategies != M3C_STRATEGY_NAMES:
            raise ProtocolError("strategies must match the five pinned M3C strategies in order")
        if self.cost_scenarios != _SCENARIO_NAMES:
            raise ProtocolError("cost scenarios must match the three frozen scenarios in order")
        if self.primary_scenario != PRIMARY_SCENARIO:
            raise ProtocolError(f"primary_scenario must be {PRIMARY_SCENARIO!r}")
        if self.primary_comparator != PRIMARY_COMPARATOR:
            raise ProtocolError(f"primary_comparator must be {PRIMARY_COMPARATOR!r}")
        if self.primary_statistic != PRIMARY_STATISTIC:
            raise ProtocolError(f"primary_statistic must be {PRIMARY_STATISTIC!r}")
        if self.bootstrap_algorithm != M3C_BOOTSTRAP_ALGORITHM:
            raise ProtocolError(f"bootstrap_algorithm must be {M3C_BOOTSTRAP_ALGORITHM!r}")
        if self.bootstrap_seed != M3C_BOOTSTRAP_SEED:
            raise ProtocolError(f"bootstrap_seed must be {M3C_BOOTSTRAP_SEED}")
        if self.bootstrap_resamples != M3C_BOOTSTRAP_RESAMPLES:
            raise ProtocolError(f"bootstrap_resamples must be {M3C_BOOTSTRAP_RESAMPLES}")
        if self.bootstrap_confidence != M3C_BOOTSTRAP_CONFIDENCE:
            raise ProtocolError(f"bootstrap_confidence must be {M3C_BOOTSTRAP_CONFIDENCE}")
        if self.bootstrap_block_length_rule != BOOTSTRAP_BLOCK_LENGTH_RULE:
            raise ProtocolError(
                f"bootstrap_block_length_rule must be {BOOTSTRAP_BLOCK_LENGTH_RULE!r}"
            )
        if self.decision_alpha != DECISION_ALPHA:
            raise ProtocolError(f"decision_alpha must be {DECISION_ALPHA}")
        if self.development_gate_ledger_sha256 != EMPTY_SHA256:
            raise ProtocolError("development-gate ledger must be the empty-content SHA-256")
        if self.final_holdout_ledger_sha256 != EMPTY_SHA256:
            raise ProtocolError("final-holdout ledger must be the empty-content SHA-256")
        if self.promotion_criteria != PROMOTION_CRITERIA:
            raise ProtocolError(f"promotion_criteria must be {PROMOTION_CRITERIA}")
        require_hex64("frozen_m2_dossier_sha256", self.frozen_m2_dossier_sha256)
        require_hex64("development_partition_sha256", self.development_partition_sha256)
        require_hex64("lineage_sha256", self.lineage_sha256)
        require_hex64("budget_sha256", self.budget_sha256)
        require_sha256_fingerprint(
            "research_train_content_fingerprint", self.research_train_content_fingerprint
        )

    def to_json_bytes(self) -> bytes:
        payload = {
            "m3c_protocol_schema_version": self.m3c_protocol_schema_version,
            "package_version": self.package_version,
            "experiment_id": self.experiment_id,
            "experiment_family": self.experiment_family,
            "candidate_id": self.candidate_id,
            "candidate_fingerprint": self.candidate_fingerprint,
            "permitted_data_level": self.permitted_data_level,
            "research_train_row_count": self.research_train_row_count,
            "initial_training_rows": self.initial_training_rows,
            "oos_fold_count": self.oos_fold_count,
            "max_context_bars": self.max_context_bars,
            "initial_cash": self.initial_cash,
            "strategies": list(self.strategies),
            "cost_scenarios": list(self.cost_scenarios),
            "frozen_m2_dossier_sha256": self.frozen_m2_dossier_sha256,
            "development_partition_sha256": self.development_partition_sha256,
            "research_train_content_fingerprint": self.research_train_content_fingerprint,
            "lineage_path": self.lineage_path,
            "lineage_sha256": self.lineage_sha256,
            "budget_path": self.budget_path,
            "budget_sha256": self.budget_sha256,
            "primary_scenario": self.primary_scenario,
            "primary_comparator": self.primary_comparator,
            "primary_statistic": self.primary_statistic,
            "bootstrap_algorithm": self.bootstrap_algorithm,
            "bootstrap_seed": self.bootstrap_seed,
            "bootstrap_resamples": self.bootstrap_resamples,
            "bootstrap_confidence": self.bootstrap_confidence,
            "bootstrap_block_length_rule": self.bootstrap_block_length_rule,
            "decision_alpha": self.decision_alpha,
            "development_gate_ledger_sha256": self.development_gate_ledger_sha256,
            "final_holdout_ledger_sha256": self.final_holdout_ledger_sha256,
            "promotion_criteria": list(self.promotion_criteria),
        }
        return canonical_json_bytes(payload)

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> M3CProtocol:
        data = require_mapping("m3c_protocol", strict_json_loads(raw))
        require_exact_keys("m3c_protocol", data, _PROTOCOL_KEYS)
        return cls(
            m3c_protocol_schema_version=require_int(
                "m3c_protocol_schema_version", data["m3c_protocol_schema_version"]
            ),
            package_version=require_nonempty_str("package_version", data["package_version"]),
            experiment_id=require_nonempty_str("experiment_id", data["experiment_id"]),
            experiment_family=require_nonempty_str("experiment_family", data["experiment_family"]),
            candidate_id=require_nonempty_str("candidate_id", data["candidate_id"]),
            candidate_fingerprint=require_hex64(
                "candidate_fingerprint", data["candidate_fingerprint"]
            ),
            permitted_data_level=require_nonempty_str(
                "permitted_data_level", data["permitted_data_level"]
            ),
            research_train_row_count=require_positive_int(
                "research_train_row_count", data["research_train_row_count"]
            ),
            initial_training_rows=require_positive_int(
                "initial_training_rows", data["initial_training_rows"]
            ),
            oos_fold_count=require_positive_int("oos_fold_count", data["oos_fold_count"]),
            max_context_bars=require_positive_int("max_context_bars", data["max_context_bars"]),
            initial_cash=require_positive_real("initial_cash", data["initial_cash"]),
            strategies=require_tuple("strategies", data["strategies"], require_nonempty_str),
            cost_scenarios=require_tuple(
                "cost_scenarios", data["cost_scenarios"], require_nonempty_str
            ),
            frozen_m2_dossier_sha256=require_hex64(
                "frozen_m2_dossier_sha256", data["frozen_m2_dossier_sha256"]
            ),
            development_partition_sha256=require_hex64(
                "development_partition_sha256", data["development_partition_sha256"]
            ),
            research_train_content_fingerprint=require_nonempty_str(
                "research_train_content_fingerprint", data["research_train_content_fingerprint"]
            ),
            lineage_path=require_nonempty_str("lineage_path", data["lineage_path"]),
            lineage_sha256=require_hex64("lineage_sha256", data["lineage_sha256"]),
            budget_path=require_nonempty_str("budget_path", data["budget_path"]),
            budget_sha256=require_hex64("budget_sha256", data["budget_sha256"]),
            primary_scenario=require_nonempty_str("primary_scenario", data["primary_scenario"]),
            primary_comparator=require_nonempty_str(
                "primary_comparator", data["primary_comparator"]
            ),
            primary_statistic=require_nonempty_str("primary_statistic", data["primary_statistic"]),
            bootstrap_algorithm=require_nonempty_str(
                "bootstrap_algorithm", data["bootstrap_algorithm"]
            ),
            bootstrap_seed=require_int("bootstrap_seed", data["bootstrap_seed"]),
            bootstrap_resamples=require_positive_int(
                "bootstrap_resamples", data["bootstrap_resamples"]
            ),
            bootstrap_confidence=require_unit_interval(
                "bootstrap_confidence", data["bootstrap_confidence"]
            ),
            bootstrap_block_length_rule=require_nonempty_str(
                "bootstrap_block_length_rule", data["bootstrap_block_length_rule"]
            ),
            decision_alpha=require_unit_interval("decision_alpha", data["decision_alpha"]),
            development_gate_ledger_sha256=require_exact_string(
                "development_gate_ledger_sha256",
                data["development_gate_ledger_sha256"],
                EMPTY_SHA256,
            ),
            final_holdout_ledger_sha256=require_exact_string(
                "final_holdout_ledger_sha256", data["final_holdout_ledger_sha256"], EMPTY_SHA256
            ),
            promotion_criteria=require_tuple(
                "promotion_criteria", data["promotion_criteria"], require_nonempty_str
            ),
        )


_PROTOCOL_KEYS = frozenset(
    {
        "m3c_protocol_schema_version",
        "package_version",
        "experiment_id",
        "experiment_family",
        "candidate_id",
        "candidate_fingerprint",
        "permitted_data_level",
        "research_train_row_count",
        "initial_training_rows",
        "oos_fold_count",
        "max_context_bars",
        "initial_cash",
        "strategies",
        "cost_scenarios",
        "frozen_m2_dossier_sha256",
        "development_partition_sha256",
        "research_train_content_fingerprint",
        "lineage_path",
        "lineage_sha256",
        "budget_path",
        "budget_sha256",
        "primary_scenario",
        "primary_comparator",
        "primary_statistic",
        "bootstrap_algorithm",
        "bootstrap_seed",
        "bootstrap_resamples",
        "bootstrap_confidence",
        "bootstrap_block_length_rule",
        "decision_alpha",
        "development_gate_ledger_sha256",
        "final_holdout_ledger_sha256",
        "promotion_criteria",
    }
)


def build_m3c_protocol(
    *,
    research_train: pd.DataFrame,
    wf_protocol: WalkForwardProtocol,
    package_version: str,
    lineage_sha256: str,
    budget_sha256: str,
    frozen_m2_dossier_sha256: str,
    development_partition_sha256: str,
) -> M3CProtocol:
    """Derive the frozen protocol from the research-train partition and the folds.

    ``research_train_content_fingerprint`` is derived from the data actually bound
    and must equal the fingerprint recorded in the committed walk-forward protocol;
    every other field is pinned to its canonical constant. The two sealed access
    ledgers are bound as the empty-content SHA-256.
    """
    fingerprint = content_fingerprint(research_train)
    if fingerprint != wf_protocol.research_train_content_fingerprint:
        raise ProtocolError(
            "research-train content fingerprint disagrees with the frozen walk-forward protocol"
        )
    return M3CProtocol(
        m3c_protocol_schema_version=M3C_PROTOCOL_SCHEMA_VERSION,
        package_version=package_version,
        experiment_id=M3C_EXPERIMENT_ID,
        experiment_family=M3C_EXPERIMENT_FAMILY,
        candidate_id=M3C_CANDIDATE_ID,
        candidate_fingerprint=CANDIDATE_FINGERPRINT,
        permitted_data_level=PERMITTED_DATA_LEVEL,
        research_train_row_count=RESEARCH_TRAIN_ROWS,
        initial_training_rows=INITIAL_TRAINING_ROWS,
        oos_fold_count=OOS_FOLD_COUNT,
        max_context_bars=M3C_MAX_CONTEXT_BARS,
        initial_cash=INITIAL_CASH,
        strategies=M3C_STRATEGY_NAMES,
        cost_scenarios=_SCENARIO_NAMES,
        frozen_m2_dossier_sha256=frozen_m2_dossier_sha256,
        development_partition_sha256=development_partition_sha256,
        research_train_content_fingerprint=fingerprint,
        lineage_path=M3C_LINEAGE_RELPATH,
        lineage_sha256=lineage_sha256,
        budget_path=M3C_BUDGET_RELPATH,
        budget_sha256=budget_sha256,
        primary_scenario=PRIMARY_SCENARIO,
        primary_comparator=PRIMARY_COMPARATOR,
        primary_statistic=PRIMARY_STATISTIC,
        bootstrap_algorithm=M3C_BOOTSTRAP_ALGORITHM,
        bootstrap_seed=M3C_BOOTSTRAP_SEED,
        bootstrap_resamples=M3C_BOOTSTRAP_RESAMPLES,
        bootstrap_confidence=M3C_BOOTSTRAP_CONFIDENCE,
        bootstrap_block_length_rule=BOOTSTRAP_BLOCK_LENGTH_RULE,
        decision_alpha=DECISION_ALPHA,
        development_gate_ledger_sha256=EMPTY_SHA256,
        final_holdout_ledger_sha256=EMPTY_SHA256,
        promotion_criteria=PROMOTION_CRITERIA,
    )


def load_m3c_protocol(path: str | Path) -> M3CProtocol:
    """Strictly parse a committed M3C protocol file."""
    raw = require_canonical_file_bytes(Path(path).read_bytes(), "m3c protocol")
    return M3CProtocol.from_json_bytes(raw)
