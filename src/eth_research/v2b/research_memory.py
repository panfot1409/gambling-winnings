"""Cumulative research-memory: every strategy family the project has ever evaluated.

The dominant threat once V2A has returned a null is *research-level overfitting* — quietly retrying
"new" strategies on the same ETH history until one clears the bar. This module makes that
impossible to do silently: it binds, by semantic fingerprint, **every** strategy family already
evaluated across M3A/M3B/M3C/V2A (plus the benchmark-only families), records each family's lineage,
role, decisions, configurations and result digests, and provides a fail-closed *anti-relabel*
verifier that refuses to treat a cosmetically-disguised existing family as new.

Design:

* :class:`ResearchFamilyIdentity` is a **semantic** identity — signal family, instruments read vs
  traded, horizon/threshold/allocation structure, risk/vol/drawdown overlays, cost family, context
  requirement, benchmark, primary endpoint, partition. It deliberately excludes every *cosmetic*
  attribute (display name, class name, module path, experiment id, package version, serialization
  order, description, wrapper function, output scaling, default-parameter syntax) and the specific
  parameter *values* (a horizon shift by an immaterial amount does not create a new family). Two
  families are the same iff their identity fingerprints match.
* :data:`FAMILY_SIMILARITY_POLICY` canonicalizes known **aliases** (a rolling-extrema breakout is a
  Donchian breakout; a weighted-threshold moving average is a moving-average crossover; a
  twin-horizon trend is the dual-horizon trend) and **structural equivalences** (a volatility
  overlay is the same whether it lives in a ``RiskConfig`` or inside the engine).
  :func:`normalize_declared_family`
  applies it and fails closed on any signal family it has never seen.
* :func:`assert_family_is_new` normalizes a declared identity and refuses it if its fingerprint
  collides with any cataloged family (or any rejected family for the same partition).

Nothing here evaluates a strategy or touches market data; it is pure, offline, deterministic
governance metadata. All five committed artifacts under ``research/v2b/`` rebuild byte-for-byte from
the constants in this module and are re-verified by :func:`verify_research_memory`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from eth_research.m3d.chain import (
    GENESIS_PREVIOUS,
    chained_line_bytes,
    load_and_verify_chain,
    render_ledger_bytes,
)
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    load_canonical_json,
    require_choice,
    require_list,
    require_mapping,
    require_slug,
    sha256_bytes,
)

RESEARCH_MEMORY_SCHEMA_VERSION: int = 1

# Committed artifact relative paths (all under research/v2b/).
FAMILY_CATALOG_RELPATH: str = "research/v2b/research_family_catalog.json"
EXPOSURE_LEDGER_RELPATH: str = "research/v2b/research_exposure_ledger.jsonl"
REJECTED_INDEX_RELPATH: str = "research/v2b/rejected_family_index.json"
SIMILARITY_POLICY_RELPATH: str = "research/v2b/family_similarity_policy.json"
MEMORY_STATE_RELPATH: str = "research/v2b/research_memory_state.json"


class ResearchMemoryError(V2ValidationError):
    """A research-memory artifact was malformed, drifted, or an anti-relabel check failed."""


# --------------------------------------------------------------------------- #
# canonical semantic vocabularies (fail-closed choices)                        #
# --------------------------------------------------------------------------- #
INSTRUMENTS: frozenset[str] = frozenset({"eth", "btc", "cash"})

SIGNAL_FAMILIES: frozenset[str] = frozenset(
    {
        "passive_hold",
        "cash_hold",
        "moving_average_crossover",
        "donchian_breakout",
        "dual_horizon_trend",
        "mean_reversion_zscore",
        "single_horizon_sma_gate",
        "cross_asset_trend_confirmation",
        "cross_sectional_relative_strength",
    }
)

SIGNAL_SOURCES: frozenset[str] = frozenset(
    {"none", "own_close_price", "cross_asset_close_price", "own_realized_volatility"}
)

HORIZON_STRUCTURES: frozenset[str] = frozenset(
    {"none", "single_horizon", "dual_horizon", "channel_window", "rolling_window"}
)

THRESHOLD_STRUCTURES: frozenset[str] = frozenset(
    {
        "none",
        "sma_sign_gate",
        "sma_crossover_sign",
        "channel_break",
        "zscore_lower_band",
        "dual_trend_agreement",
        "cross_asset_confirmation_gate",
        "relative_strength_rank",
    }
)

ALLOCATION_STRUCTURES: frozenset[str] = frozenset(
    {
        "always_full_long",
        "always_cash",
        "binary_long_or_cash",
        "continuous_unit_interval",
        "single_risky_or_cash_rotation",
    }
)

RISK_OVERLAYS: frozenset[str] = frozenset(
    {"none", "max_exposure_cap", "volatility_target", "turnover_limit"}
)

COST_MODEL_FAMILIES: frozenset[str] = frozenset({"none_gross", "causal_proxy"})

CONTEXT_REQUIREMENTS: frozenset[str] = frozenset({"own_price_only", "cross_asset_required"})

BENCHMARKS: frozenset[str] = frozenset({"self", "cash", "buy_and_hold", "static_50_50"})

PRIMARY_ENDPOINTS: frozenset[str] = frozenset({"none", "paired_log_excess_return"})

PARTITIONS: frozenset[str] = frozenset({"research_train"})

ROLES: frozenset[str] = frozenset(
    {"benchmark", "measurement_instrument", "exploratory_fixed_rule", "candidate"}
)

DECISIONS: frozenset[str] = frozenset(
    {
        "benchmark_reference",
        "exploratory_only",
        "not_promoted",
        "research_stage_rejected",
        "permanently_rejected",
    }
)

MILESTONES: frozenset[str] = frozenset({"m3a", "m3b", "m3c", "v2a", "v2b"})


# --------------------------------------------------------------------------- #
# ResearchFamilyIdentity — the semantic (cosmetic-free, value-free) identity   #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ResearchFamilyIdentity:
    """The semantic identity of a strategy family (its anti-relabel fingerprint key)."""

    signal_family: str
    signal_source: str
    input_instruments: tuple[str, ...]
    executed_instruments: tuple[str, ...]
    horizon_structure: str
    threshold_structure: str
    allocation_structure: str
    risk_overlay: str
    volatility_overlay: bool
    drawdown_overlay: bool
    cost_model_family: str
    context_requirement: str
    benchmark: str
    primary_endpoint: str
    partition: str

    def __post_init__(self) -> None:
        # signal_family may be a canonical family OR a known alias (the anti-relabel verifier
        # normalizes aliases to canonical before comparing); an unrecognized mechanism fails closed
        # here at construction. Every other field must be exactly a canonical enum member.
        canonical_signal_family(self.signal_family)
        require_choice("family.signal_source", self.signal_source, SIGNAL_SOURCES)
        require_choice("family.horizon_structure", self.horizon_structure, HORIZON_STRUCTURES)
        require_choice("family.threshold_structure", self.threshold_structure, THRESHOLD_STRUCTURES)
        require_choice(
            "family.allocation_structure", self.allocation_structure, ALLOCATION_STRUCTURES
        )
        require_choice("family.risk_overlay", self.risk_overlay, RISK_OVERLAYS)
        require_choice("family.cost_model_family", self.cost_model_family, COST_MODEL_FAMILIES)
        require_choice("family.context_requirement", self.context_requirement, CONTEXT_REQUIREMENTS)
        require_choice("family.benchmark", self.benchmark, BENCHMARKS)
        require_choice("family.primary_endpoint", self.primary_endpoint, PRIMARY_ENDPOINTS)
        require_choice("family.partition", self.partition, PARTITIONS)
        for label, instruments in (
            ("input_instruments", self.input_instruments),
            ("executed_instruments", self.executed_instruments),
        ):
            if not instruments:
                raise ResearchMemoryError(f"family.{label} must be non-empty")
            for inst in instruments:
                require_choice(f"family.{label}", inst, INSTRUMENTS)
            if tuple(sorted(set(instruments))) != instruments:
                raise ResearchMemoryError(
                    f"family.{label} must be sorted and unique, got {instruments!r}"
                )

    def to_canonical(self) -> dict[str, object]:
        return {
            "signal_family": self.signal_family,
            "signal_source": self.signal_source,
            "input_instruments": list(self.input_instruments),
            "executed_instruments": list(self.executed_instruments),
            "horizon_structure": self.horizon_structure,
            "threshold_structure": self.threshold_structure,
            "allocation_structure": self.allocation_structure,
            "risk_overlay": self.risk_overlay,
            "volatility_overlay": self.volatility_overlay,
            "drawdown_overlay": self.drawdown_overlay,
            "cost_model_family": self.cost_model_family,
            "context_requirement": self.context_requirement,
            "benchmark": self.benchmark,
            "primary_endpoint": self.primary_endpoint,
            "partition": self.partition,
        }

    def fingerprint(self) -> str:
        """The lineage-free, cosmetic-free, value-free semantic identity fingerprint."""
        return canonical_sha256(self.to_canonical())

    @staticmethod
    def parse(raw: object) -> ResearchFamilyIdentity:
        obj = require_mapping("family", raw)
        keys = frozenset(obj)
        expected = frozenset(ResearchFamilyIdentity.__slots__)
        if keys != expected:
            raise ResearchMemoryError(
                f"family identity keys {sorted(keys)} != expected {sorted(expected)}"
            )
        return ResearchFamilyIdentity(
            signal_family=require_slug("family.signal_family", obj["signal_family"]),
            signal_source=require_slug("family.signal_source", obj["signal_source"]),
            input_instruments=_parse_instruments(
                "family.input_instruments", obj["input_instruments"]
            ),
            executed_instruments=_parse_instruments(
                "family.executed_instruments", obj["executed_instruments"]
            ),
            horizon_structure=require_slug("family.horizon_structure", obj["horizon_structure"]),
            threshold_structure=require_slug(
                "family.threshold_structure", obj["threshold_structure"]
            ),
            allocation_structure=require_slug(
                "family.allocation_structure", obj["allocation_structure"]
            ),
            risk_overlay=require_slug("family.risk_overlay", obj["risk_overlay"]),
            volatility_overlay=_require_bool(
                "family.volatility_overlay", obj["volatility_overlay"]
            ),
            drawdown_overlay=_require_bool("family.drawdown_overlay", obj["drawdown_overlay"]),
            cost_model_family=require_slug("family.cost_model_family", obj["cost_model_family"]),
            context_requirement=require_slug(
                "family.context_requirement", obj["context_requirement"]
            ),
            benchmark=require_slug("family.benchmark", obj["benchmark"]),
            primary_endpoint=require_slug("family.primary_endpoint", obj["primary_endpoint"]),
            partition=require_slug("family.partition", obj["partition"]),
        )


def _require_bool(label: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ResearchMemoryError(f"{label} must be a JSON boolean, got {type(value).__name__}")
    return value


def _parse_instruments(label: str, value: object) -> tuple[str, ...]:
    items = require_list(label, value, lambda lbl, v: require_slug(lbl, v))
    return tuple(items)


# --------------------------------------------------------------------------- #
# family-similarity (anti-relabel) policy                                      #
# --------------------------------------------------------------------------- #
# Cosmetic attributes that are NEVER part of a family's identity — changing any of these can never
# make an existing family "new".
IDENTITY_EXCLUDED_ATTRIBUTES: tuple[str, ...] = (
    "display_name",
    "class_name",
    "module_path",
    "experiment_id",
    "package_version",
    "serialization_order",
    "candidate_description",
    "wrapper_function",
    "output_scaling",
    "default_parameter_syntax",
    "horizon_value",
    "threshold_value",
    "lookback_value",
)

# Known signal-family aliases → canonical signal family. A relabel that renames the mechanism is
# mapped back before fingerprinting; an unknown alias fails closed (never silently "new").
SIGNAL_FAMILY_ALIASES: dict[str, str] = {
    "rolling_extrema_breakout": "donchian_breakout",
    "rolling_max_min_channel": "donchian_breakout",
    "weighted_threshold_moving_average": "moving_average_crossover",
    "dual_sma_cross": "moving_average_crossover",
    "twin_horizon_trend": "dual_horizon_trend",
    "two_speed_trend": "dual_horizon_trend",
    "zscore_mean_reversion": "mean_reversion_zscore",
    "single_ma_price_gate": "single_horizon_sma_gate",
    "always_long_passive": "passive_hold",
    "buy_and_hold": "passive_hold",
}

# Structural equivalences: a volatility/drawdown overlay is the same family attribute whether it is
# expressed through a RiskConfig or moved inside the engine; these normalize to the identity flags.
STRUCTURAL_EQUIVALENCES: dict[str, str] = {
    "engine_internal_volatility_target": "volatility_target",
    "riskconfig_volatility_target": "volatility_target",
    "engine_internal_drawdown_breaker": "drawdown_breaker",
    "riskconfig_drawdown_breaker": "drawdown_breaker",
}


@dataclass(frozen=True, slots=True)
class FamilySimilarityPolicy:
    """The declared anti-relabel policy (aliases, structural equivalences, excluded attributes)."""

    schema_version: int
    identity_excluded_attributes: tuple[str, ...]
    signal_family_aliases: tuple[tuple[str, str], ...]
    structural_equivalences: tuple[tuple[str, str], ...]

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "identity_excluded_attributes": sorted(self.identity_excluded_attributes),
            "signal_family_aliases": dict(sorted(self.signal_family_aliases)),
            "structural_equivalences": dict(sorted(self.structural_equivalences)),
            "canonical_signal_families": sorted(SIGNAL_FAMILIES),
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


FAMILY_SIMILARITY_POLICY: FamilySimilarityPolicy = FamilySimilarityPolicy(
    schema_version=RESEARCH_MEMORY_SCHEMA_VERSION,
    identity_excluded_attributes=IDENTITY_EXCLUDED_ATTRIBUTES,
    signal_family_aliases=tuple(sorted(SIGNAL_FAMILY_ALIASES.items())),
    structural_equivalences=tuple(sorted(STRUCTURAL_EQUIVALENCES.items())),
)


def canonical_signal_family(declared: str) -> str:
    """Map a declared signal-family name to its canonical form, failing closed on the unknown."""
    text = require_slug("declared_signal_family", declared)
    if text in SIGNAL_FAMILIES:
        return text
    if text in SIGNAL_FAMILY_ALIASES:
        return SIGNAL_FAMILY_ALIASES[text]
    raise ResearchMemoryError(
        f"signal family {text!r} is neither canonical nor a known alias; declare it explicitly "
        f"and add it to the similarity policy before use (fail-closed anti-relabel)"
    )


def normalize_declared_family(identity: ResearchFamilyIdentity) -> ResearchFamilyIdentity:
    """Return the identity with its signal family canonicalized through the alias policy.

    All other fields are already canonical enums; the alias map only ever collapses a renamed
    mechanism back onto its canonical family, so a cosmetic rename cannot manufacture novelty.
    """
    canonical = canonical_signal_family(identity.signal_family)
    if canonical == identity.signal_family:
        return identity
    data = identity.to_canonical()
    data["signal_family"] = canonical
    return ResearchFamilyIdentity.parse(data)


# --------------------------------------------------------------------------- #
# CatalogedFamily — identity + lineage + role + decisions + provenance         #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CatalogedFamily:
    """A family in the cumulative catalog: its semantic identity plus governance provenance."""

    family_id: str
    identity: ResearchFamilyIdentity
    role: str
    lineage: tuple[str, ...]
    decisions: tuple[str, ...]
    primary_configurations: tuple[str, ...]
    experiment_ids: tuple[str, ...]
    result_digests: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_slug("cataloged_family.family_id", self.family_id)
        require_choice("cataloged_family.role", self.role, ROLES)
        if not self.lineage:
            raise ResearchMemoryError(f"family {self.family_id!r} must record a lineage")
        for milestone in self.lineage:
            require_choice(f"family {self.family_id} lineage", milestone, MILESTONES)
        for decision in self.decisions:
            require_choice(f"family {self.family_id} decision", decision, DECISIONS)

    def to_canonical(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "identity": self.identity.to_canonical(),
            "identity_fingerprint": self.identity.fingerprint(),
            "role": self.role,
            "lineage": list(self.lineage),
            "decisions": list(self.decisions),
            "primary_configurations": list(self.primary_configurations),
            "experiment_ids": list(self.experiment_ids),
            "result_digests": list(self.result_digests),
        }

    def is_rejected(self) -> bool:
        return any(
            d in {"research_stage_rejected", "permanently_rejected", "not_promoted"}
            for d in self.decisions
        )


# --------------------------------------------------------------------------- #
# the cumulative research-family catalog (every family ever evaluated)         #
# --------------------------------------------------------------------------- #
_PASSIVE_ETH_BUY_AND_HOLD = CatalogedFamily(
    family_id="passive_eth_buy_and_hold_benchmark",
    identity=ResearchFamilyIdentity(
        signal_family="passive_hold",
        signal_source="own_close_price",
        input_instruments=("eth",),
        executed_instruments=("eth",),
        horizon_structure="none",
        threshold_structure="none",
        allocation_structure="always_full_long",
        risk_overlay="none",
        volatility_overlay=False,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="own_price_only",
        benchmark="self",
        primary_endpoint="none",
        partition="research_train",
    ),
    role="benchmark",
    lineage=("m3a", "m3b", "m3c", "v2a"),
    decisions=("benchmark_reference",),
    primary_configurations=("full_long_eth",),
    experiment_ids=("m3c_run_003", "v2a_run_001"),
)

_CASH_BENCHMARK = CatalogedFamily(
    family_id="cash_benchmark",
    identity=ResearchFamilyIdentity(
        signal_family="cash_hold",
        signal_source="none",
        input_instruments=("cash",),
        executed_instruments=("cash",),
        horizon_structure="none",
        threshold_structure="none",
        allocation_structure="always_cash",
        risk_overlay="none",
        volatility_overlay=False,
        drawdown_overlay=False,
        cost_model_family="none_gross",
        context_requirement="own_price_only",
        benchmark="self",
        primary_endpoint="none",
        partition="research_train",
    ),
    role="benchmark",
    lineage=("m3a", "m3b", "m3c", "v2a"),
    decisions=("benchmark_reference",),
    primary_configurations=("hold_cash",),
    experiment_ids=(),
)

_M3A_SMA_CROSSOVER = CatalogedFamily(
    family_id="m3a_sma_crossover",
    identity=ResearchFamilyIdentity(
        signal_family="moving_average_crossover",
        signal_source="own_close_price",
        input_instruments=("eth",),
        executed_instruments=("eth",),
        horizon_structure="dual_horizon",
        threshold_structure="sma_crossover_sign",
        allocation_structure="binary_long_or_cash",
        risk_overlay="none",
        volatility_overlay=False,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="own_price_only",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    ),
    role="exploratory_fixed_rule",
    lineage=("m3a",),
    decisions=("not_promoted",),
    primary_configurations=("sma_fast_slow_grid",),
    experiment_ids=("m3a_run_003",),
)

_M3A_DONCHIAN_BREAKOUT = CatalogedFamily(
    family_id="m3a_donchian_breakout",
    identity=ResearchFamilyIdentity(
        signal_family="donchian_breakout",
        signal_source="own_close_price",
        input_instruments=("eth",),
        executed_instruments=("eth",),
        horizon_structure="channel_window",
        threshold_structure="channel_break",
        allocation_structure="binary_long_or_cash",
        risk_overlay="none",
        volatility_overlay=False,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="own_price_only",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    ),
    role="exploratory_fixed_rule",
    lineage=("m3a",),
    decisions=("not_promoted",),
    primary_configurations=("donchian_entry_exit_grid",),
    experiment_ids=("m3a_run_003",),
)

_M3B_VOL_TARGET_BUY_AND_HOLD = CatalogedFamily(
    family_id="m3b_vol_target_buy_and_hold_30d_50pct",
    identity=ResearchFamilyIdentity(
        signal_family="passive_hold",
        signal_source="own_realized_volatility",
        input_instruments=("eth",),
        executed_instruments=("eth",),
        horizon_structure="rolling_window",
        threshold_structure="none",
        allocation_structure="continuous_unit_interval",
        risk_overlay="volatility_target",
        volatility_overlay=True,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="own_price_only",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    ),
    role="candidate",
    lineage=("m3b",),
    decisions=("not_promoted",),
    primary_configurations=("vol_target_30d_50pct",),
    experiment_ids=("m3b_run_001",),
)

_M3B_VOL_TARGET_DONCHIAN = CatalogedFamily(
    family_id="m3b_vol_target_donchian_55_20_30d_50pct",
    identity=ResearchFamilyIdentity(
        signal_family="donchian_breakout",
        signal_source="own_realized_volatility",
        input_instruments=("eth",),
        executed_instruments=("eth",),
        horizon_structure="channel_window",
        threshold_structure="channel_break",
        allocation_structure="continuous_unit_interval",
        risk_overlay="volatility_target",
        volatility_overlay=True,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="own_price_only",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    ),
    role="candidate",
    lineage=("m3b",),
    decisions=("not_promoted",),
    primary_configurations=("donchian_55_20_vol_target_30d_50pct",),
    experiment_ids=("m3b_run_001",),
)

_M3C_DUAL_HORIZON_TREND = CatalogedFamily(
    family_id="m3c_dual_horizon_trend_63_252_vol_target_30d_50pct",
    identity=ResearchFamilyIdentity(
        signal_family="dual_horizon_trend",
        signal_source="own_close_price",
        input_instruments=("eth",),
        executed_instruments=("eth",),
        horizon_structure="dual_horizon",
        threshold_structure="dual_trend_agreement",
        allocation_structure="continuous_unit_interval",
        risk_overlay="volatility_target",
        volatility_overlay=True,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="own_price_only",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    ),
    role="candidate",
    lineage=("m3c",),
    decisions=("permanently_rejected",),
    primary_configurations=("dual_horizon_63_252_vol_target_30d_50pct",),
    experiment_ids=("m3c_run_003",),
)

_V2A_MEANREV_ZSCORE = CatalogedFamily(
    family_id="v2a_meanrev_zscore_accumulation",
    identity=ResearchFamilyIdentity(
        signal_family="mean_reversion_zscore",
        signal_source="own_close_price",
        input_instruments=("eth",),
        executed_instruments=("eth",),
        horizon_structure="rolling_window",
        threshold_structure="zscore_lower_band",
        allocation_structure="binary_long_or_cash",
        risk_overlay="none",
        volatility_overlay=False,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="own_price_only",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    ),
    role="candidate",
    lineage=("v2a",),
    decisions=("research_stage_rejected",),
    primary_configurations=("lookback_20_entry_z_1.0",),
    experiment_ids=("v2a_run_001",),
)

_V2A_VOL_SCALED_HOLD = CatalogedFamily(
    family_id="v2a_vol_scaled_hold_drawdown_guard",
    identity=ResearchFamilyIdentity(
        signal_family="passive_hold",
        signal_source="own_realized_volatility",
        input_instruments=("eth",),
        executed_instruments=("eth",),
        horizon_structure="rolling_window",
        threshold_structure="none",
        allocation_structure="continuous_unit_interval",
        risk_overlay="volatility_target",
        volatility_overlay=True,
        drawdown_overlay=True,
        cost_model_family="causal_proxy",
        context_requirement="own_price_only",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    ),
    role="candidate",
    lineage=("v2a",),
    decisions=("research_stage_rejected",),
    primary_configurations=("vol_target_30d_50pct_drawdown_guard",),
    experiment_ids=("v2a_run_001",),
)

_V2A_TREND_SINGLE_HORIZON = CatalogedFamily(
    family_id="v2a_trend_regime_single_horizon",
    identity=ResearchFamilyIdentity(
        signal_family="single_horizon_sma_gate",
        signal_source="own_close_price",
        input_instruments=("eth",),
        executed_instruments=("eth",),
        horizon_structure="single_horizon",
        threshold_structure="sma_sign_gate",
        allocation_structure="binary_long_or_cash",
        risk_overlay="none",
        volatility_overlay=False,
        drawdown_overlay=False,
        cost_model_family="causal_proxy",
        context_requirement="own_price_only",
        benchmark="buy_and_hold",
        primary_endpoint="paired_log_excess_return",
        partition="research_train",
    ),
    role="candidate",
    lineage=("v2a",),
    decisions=("research_stage_rejected",),
    primary_configurations=("horizon_200",),
    experiment_ids=("v2a_run_001",),
)

# Every family the project has evaluated, ordered by identity fingerprint for a stable catalog.
RESEARCH_FAMILY_CATALOG: tuple[CatalogedFamily, ...] = tuple(
    sorted(
        (
            _PASSIVE_ETH_BUY_AND_HOLD,
            _CASH_BENCHMARK,
            _M3A_SMA_CROSSOVER,
            _M3A_DONCHIAN_BREAKOUT,
            _M3B_VOL_TARGET_BUY_AND_HOLD,
            _M3B_VOL_TARGET_DONCHIAN,
            _M3C_DUAL_HORIZON_TREND,
            _V2A_MEANREV_ZSCORE,
            _V2A_VOL_SCALED_HOLD,
            _V2A_TREND_SINGLE_HORIZON,
        ),
        key=lambda f: f.identity.fingerprint(),
    )
)


def _assert_catalog_wellformed(catalog: tuple[CatalogedFamily, ...]) -> None:
    """Every cataloged family must have a distinct identity fingerprint and a distinct id."""
    ids = [f.family_id for f in catalog]
    if len(set(ids)) != len(ids):
        raise ResearchMemoryError("duplicate family_id in the research-family catalog")
    fps = [f.identity.fingerprint() for f in catalog]
    if len(set(fps)) != len(fps):
        raise ResearchMemoryError(
            "two cataloged families share a semantic identity fingerprint (one is a relabel)"
        )


# --------------------------------------------------------------------------- #
# counts for the multiplicity policy                                           #
# --------------------------------------------------------------------------- #
def historical_candidate_families() -> tuple[CatalogedFamily, ...]:
    """Every non-benchmark family already evaluated (counts against the cumulative alpha budget)."""
    return tuple(f for f in RESEARCH_FAMILY_CATALOG if f.role != "benchmark")


def historical_candidate_family_count() -> int:
    return len(historical_candidate_families())


# --------------------------------------------------------------------------- #
# artifact builders (byte-exact, deterministic)                                #
# --------------------------------------------------------------------------- #
def build_family_catalog_bytes() -> bytes:
    _assert_catalog_wellformed(RESEARCH_FAMILY_CATALOG)
    payload = {
        "schema_version": RESEARCH_MEMORY_SCHEMA_VERSION,
        "milestone": "v2b",
        "family_count": len(RESEARCH_FAMILY_CATALOG),
        "candidate_family_count": historical_candidate_family_count(),
        "families": [f.to_canonical() for f in RESEARCH_FAMILY_CATALOG],
    }
    return canonical_json_bytes(payload)


def build_similarity_policy_bytes() -> bytes:
    return canonical_json_bytes(FAMILY_SIMILARITY_POLICY.to_canonical())


def build_rejected_family_index_bytes() -> bytes:
    rejected = [f for f in RESEARCH_FAMILY_CATALOG if f.is_rejected()]
    payload = {
        "schema_version": RESEARCH_MEMORY_SCHEMA_VERSION,
        "rejected_family_count": len(rejected),
        "rejected_families": [
            {
                "family_id": f.family_id,
                "identity_fingerprint": f.identity.fingerprint(),
                "partition": f.identity.partition,
                "decisions": list(f.decisions),
                "lineage": list(f.lineage),
            }
            for f in rejected
        ],
    }
    return canonical_json_bytes(payload)


def _exposure_ledger_records() -> list[dict[str, object]]:
    """One genesis record plus one exposure record per (family, milestone-of-lineage)."""
    records: list[dict[str, object]] = [
        {
            "kind": "research_exposure_genesis",
            "schema_version": RESEARCH_MEMORY_SCHEMA_VERSION,
            "milestone": "v2b",
            "note": "cumulative research-family exposure ledger; append-only, hash-chained",
        }
    ]
    for family in RESEARCH_FAMILY_CATALOG:
        for milestone in family.lineage:
            records.append(
                {
                    "kind": "research_family_exposure",
                    "family_id": family.family_id,
                    "identity_fingerprint": family.identity.fingerprint(),
                    "milestone": milestone,
                    "role": family.role,
                    "partition": family.identity.partition,
                    "decisions": list(family.decisions),
                }
            )
    return records


def build_exposure_ledger_bytes() -> bytes:
    return render_ledger_bytes(chained_line_bytes(_exposure_ledger_records()))


def build_memory_state_bytes() -> bytes:
    catalog_bytes = build_family_catalog_bytes()
    ledger_bytes = build_exposure_ledger_bytes()
    policy_bytes = build_similarity_policy_bytes()
    rejected_bytes = build_rejected_family_index_bytes()
    payload = {
        "schema_version": RESEARCH_MEMORY_SCHEMA_VERSION,
        "milestone": "v2b",
        "family_count": len(RESEARCH_FAMILY_CATALOG),
        "candidate_family_count": historical_candidate_family_count(),
        "rejected_family_count": sum(1 for f in RESEARCH_FAMILY_CATALOG if f.is_rejected()),
        "family_catalog_sha256": sha256_bytes(catalog_bytes),
        "exposure_ledger_sha256": sha256_bytes(ledger_bytes),
        "similarity_policy_sha256": sha256_bytes(policy_bytes),
        "rejected_family_index_sha256": sha256_bytes(rejected_bytes),
        "exposure_ledger_head_sha256": _ledger_head_sha256(ledger_bytes),
    }
    return canonical_json_bytes(payload)


def _ledger_head_sha256(ledger_bytes: bytes) -> str:
    """SHA-256 of the last chained line — the tip commitment of the append-only ledger."""
    if ledger_bytes == b"":
        return GENESIS_PREVIOUS
    lines = ledger_bytes.rstrip(b"\n").split(b"\n")
    return sha256_bytes(lines[-1])


# --------------------------------------------------------------------------- #
# anti-relabel verifier — the fail-closed novelty gate                         #
# --------------------------------------------------------------------------- #
def cataloged_fingerprints() -> frozenset[str]:
    return frozenset(f.identity.fingerprint() for f in RESEARCH_FAMILY_CATALOG)


def assert_family_is_new(identity: ResearchFamilyIdentity) -> ResearchFamilyIdentity:
    """Refuse a declared family that (after normalization) relabels any cataloged family.

    Returns the normalized identity so callers register exactly what was checked. Fails closed: an
    unknown signal family, or a fingerprint collision with any cataloged family (rejected or not),
    is rejected.
    """
    normalized = normalize_declared_family(identity)
    fp = normalized.fingerprint()
    for family in RESEARCH_FAMILY_CATALOG:
        if family.identity.fingerprint() == fp:
            raise ResearchMemoryError(
                f"declared family relabels the already-evaluated family {family.family_id!r} "
                f"(identical semantic identity {fp[:12]}…); it is not genuinely new"
            )
    return normalized


def assert_not_reviving_rejected(identity: ResearchFamilyIdentity) -> None:
    """A rejected family stays rejected for the same partition; V2B may not revive one."""
    normalized = normalize_declared_family(identity)
    fp = normalized.fingerprint()
    for family in RESEARCH_FAMILY_CATALOG:
        if family.is_rejected() and family.identity.fingerprint() == fp:
            raise ResearchMemoryError(
                f"declared family revives the rejected family {family.family_id!r} for partition "
                f"{normalized.partition!r}; rejected families stay rejected"
            )


# --------------------------------------------------------------------------- #
# top-level verifier (offline, read-only)                                      #
# --------------------------------------------------------------------------- #
def _verify_bytes(repo_root: Path, relpath: str, expected: bytes, problems: list[str]) -> None:
    path = repo_root / relpath
    if not path.exists():
        problems.append(f"{relpath} is missing")
        return
    if path.read_bytes() != expected:
        problems.append(f"{relpath} does not reproduce byte-for-byte from source")


def verify_research_memory(repo_root: str | Path) -> list[str]:
    """Return every research-memory problem (empty == all five artifacts replay cleanly)."""
    root = Path(repo_root)
    problems: list[str] = []
    try:
        _assert_catalog_wellformed(RESEARCH_FAMILY_CATALOG)
    except V2ValidationError as exc:
        problems.append(f"catalog is not well-formed: {exc}")
        return problems

    _verify_bytes(root, FAMILY_CATALOG_RELPATH, build_family_catalog_bytes(), problems)
    _verify_bytes(root, SIMILARITY_POLICY_RELPATH, build_similarity_policy_bytes(), problems)
    _verify_bytes(root, REJECTED_INDEX_RELPATH, build_rejected_family_index_bytes(), problems)
    _verify_bytes(root, EXPOSURE_LEDGER_RELPATH, build_exposure_ledger_bytes(), problems)
    _verify_bytes(root, MEMORY_STATE_RELPATH, build_memory_state_bytes(), problems)

    # The committed exposure ledger must also verify as a sound hash chain on its own bytes.
    ledger_path = root / EXPOSURE_LEDGER_RELPATH
    if ledger_path.exists() and ledger_path.read_bytes() != b"":
        try:
            load_and_verify_chain(root, EXPOSURE_LEDGER_RELPATH)
        except V2ValidationError as exc:
            problems.append(f"{EXPOSURE_LEDGER_RELPATH} is not a sound hash chain: {exc}")
    return problems


def load_family_catalog(repo_root: str | Path) -> tuple[ResearchFamilyIdentity, ...]:
    """Load the committed catalog's identities (strict-decoded), for cross-checks."""
    raw = load_canonical_json(Path(repo_root) / FAMILY_CATALOG_RELPATH)
    obj = require_mapping("family_catalog", raw)
    families = require_list("family_catalog.families", obj["families"], require_mapping)
    return tuple(ResearchFamilyIdentity.parse(f["identity"]) for f in families)


def assert_declared_families_distinct(identities: tuple[ResearchFamilyIdentity, ...]) -> None:
    """Reject a declared set in which two families collapse to the same normalized identity.

    Defeats splitting one real family into several aliased "candidates" to inflate the count or
    dodge the family budget: after normalization, every declared identity must be unique.
    """
    seen: dict[str, int] = {}
    for index, identity in enumerate(identities):
        fp = normalize_declared_family(identity).fingerprint()
        if fp in seen:
            raise ResearchMemoryError(
                f"declared family #{index} shares a semantic identity with declared family "
                f"#{seen[fp]} (an aliased split of one real family)"
            )
        seen[fp] = index
