"""The fixed M3C candidate, its canonical fingerprint, and the research budget.

The one permitted candidate ``dual_horizon_trend_63_252_vol_target_30d_50pct`` is a
:class:`FractionalStrategy` pairing the new :class:`DualHorizonTrend` directional
signal with the reviewed M3B 30-day / 50%-annual volatility overlay (via
``RiskConfig``) and **no turnover limiter** and **no drawdown breaker**. Its
canonical fingerprint binds every defining constant so the registry can refuse a
re-parameterized candidate smuggled in under the same name. The declared volatility
constants are asserted equal to the reviewed ``fractional.risk`` constants, so a
drift between the fingerprint and the engine that actually runs is caught here.

The :class:`ResearchBudget` encodes the one-candidate, one-primary-comparison,
zero-search, zero-gate-access, no-post-result-change policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.fractional.risk import (
    ANNUAL_VOLATILITY_TARGET,
    ANNUALIZATION_FACTOR,
    VOLATILITY_LOOKBACK,
    VOLATILITY_MIN_OBSERVATIONS,
)
from eth_research.fractional.strategies import FractionalStrategy, RiskConfig
from eth_research.m3c.strategy import LONG_HORIZON, MEDIUM_HORIZON, DualHorizonTrend
from eth_research.m3c.validation import (
    canonical_sha256,
    require_bool,
    require_exact_keys,
    require_exact_string,
    require_mapping,
    require_nonnegative_int,
    require_positive_int,
    require_sha256_fingerprint,
    require_unit_interval,
)

CANDIDATE_SCHEMA_VERSION: int = 1
M3C_CANDIDATE_ID: str = "dual_horizon_trend_63_252_vol_target_30d_50pct"
M3C_CANDIDATE_FAMILY: str = "dual_horizon_trend_63_252_vol_target_30d_50pct"

# The candidate's context requirement: the 252-day momentum needs 252 prior closes,
# so each fold warms up on up to 252 strictly-earlier bars (M3B used 55; see the
# plan). Context creates no P&L; benchmark lookbacks (<= 55) are unaffected.
M3C_MAX_CONTEXT_BARS: int = LONG_HORIZON  # 252

# ``sqrt(365.25)`` annualization → the squared periods-per-year the overlay uses.
_ANNUALIZATION_PERIODS: float = round(ANNUALIZATION_FACTOR**2, 6)


def _candidate_identity() -> dict[str, object]:
    """The canonical, order-independent identity dict hashed into the fingerprint."""
    return {
        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
        "candidate_id": M3C_CANDIDATE_ID,
        "signal": "dual_horizon_trend",
        "medium_horizon": MEDIUM_HORIZON,
        "long_horizon": LONG_HORIZON,
        "volatility_lookback": VOLATILITY_LOOKBACK,
        "volatility_min_observations": VOLATILITY_MIN_OBSERVATIONS,
        "annual_volatility_target": ANNUAL_VOLATILITY_TARGET,
        "annualization_periods_per_year": _ANNUALIZATION_PERIODS,
        "std_convention": "sample_ddof_1",
        "max_exposure": 1.0,
        "min_exposure": 0.0,
        "turnover_limit": None,
        "drawdown_breaker_enabled": False,
        "initial_target": 0,
        "context_max_bars": M3C_MAX_CONTEXT_BARS,
        "execution": "next_open_t_plus_1",
        "shorting": False,
        "leverage": False,
    }


CANDIDATE_FINGERPRINT: str = canonical_sha256(_candidate_identity())


def build_candidate_strategy() -> FractionalStrategy:
    """The one fixed candidate as a reusable-engine :class:`FractionalStrategy`.

    Volatility scaling is the reviewed M3B overlay (``volatility_target=True``); the
    constants above are asserted equal to the ``fractional.risk`` constants so the
    fingerprint cannot silently diverge from the engine that runs.
    """
    if (VOLATILITY_LOOKBACK, VOLATILITY_MIN_OBSERVATIONS) != (30, 30):
        raise ValueError("reviewed volatility lookback/min-observations drifted from 30/30")
    if ANNUAL_VOLATILITY_TARGET != 0.50:
        raise ValueError("reviewed annual volatility target drifted from 0.50")
    risk = RiskConfig(
        max_exposure=1.0,
        volatility_target=True,
        turnover_limit=None,  # the candidate has NO turnover limiter (unlike M3B vol_*)
        drawdown_breaker=False,
    )
    return FractionalStrategy(
        M3C_CANDIDATE_ID,
        DualHorizonTrend(medium_horizon=MEDIUM_HORIZON, long_horizon=LONG_HORIZON),
        risk,
        warmup_bars=LONG_HORIZON,
    )


# The M3C benchmark grid: four fixed prior benchmarks + the one new candidate, in
# this exact evaluation order. Only item 5 is a new candidate.
M3C_STRATEGY_NAMES: tuple[str, ...] = (
    "cash",
    "buy_and_hold",
    "donchian_55_20",
    "vol_target_donchian_55_20_30d_50pct",
    M3C_CANDIDATE_ID,
)


def build_m3c_strategies() -> tuple[FractionalStrategy, ...]:
    """The five pinned M3C grid strategies, benchmarks first, candidate last."""
    from eth_research.fractional.strategies import STRATEGIES_BY_NAME

    benchmarks = tuple(STRATEGIES_BY_NAME[name] for name in M3C_STRATEGY_NAMES[:-1])
    return (*benchmarks, build_candidate_strategy())


# --------------------------------------------------------------------------- budget


@dataclass(frozen=True)
class ResearchBudget:
    """The immutable one-candidate research budget for the milestone."""

    budget_schema_version: int
    milestone: str
    max_new_candidate_families: int
    permitted_candidate_id: str
    permitted_candidate_fingerprint: str
    permitted_primary_comparisons: int
    parameter_searches_permitted: int
    sensitivity_candidates_permitted: int
    development_gate_accesses_permitted: int
    final_holdout_accesses_permitted: int
    strategy_fitting_permitted: bool
    post_result_parameter_changes_permitted: bool
    primary_alpha_level: float
    bootstrap_confidence: float

    _KEYS = frozenset(
        {
            "budget_schema_version",
            "milestone",
            "max_new_candidate_families",
            "permitted_candidate_id",
            "permitted_candidate_fingerprint",
            "permitted_primary_comparisons",
            "parameter_searches_permitted",
            "sensitivity_candidates_permitted",
            "development_gate_accesses_permitted",
            "final_holdout_accesses_permitted",
            "strategy_fitting_permitted",
            "post_result_parameter_changes_permitted",
            "primary_alpha_level",
            "bootstrap_confidence",
        }
    )

    def __post_init__(self) -> None:
        if self.budget_schema_version != 1:
            raise ValueError("budget_schema_version must be 1")
        if self.milestone != "M3C":
            raise ValueError("milestone must be 'M3C'")
        if self.max_new_candidate_families != 1:
            raise ValueError("M3C permits exactly one new candidate family")
        if self.permitted_candidate_id != M3C_CANDIDATE_ID:
            raise ValueError("permitted_candidate_id is pinned to the one M3C candidate")
        if self.permitted_candidate_fingerprint != CANDIDATE_FINGERPRINT:
            raise ValueError("permitted_candidate_fingerprint does not match the candidate")
        if self.permitted_primary_comparisons != 1:
            raise ValueError("exactly one primary comparison is permitted")
        for label, value in (
            ("parameter_searches_permitted", self.parameter_searches_permitted),
            ("sensitivity_candidates_permitted", self.sensitivity_candidates_permitted),
            ("development_gate_accesses_permitted", self.development_gate_accesses_permitted),
            ("final_holdout_accesses_permitted", self.final_holdout_accesses_permitted),
        ):
            if value != 0:
                raise ValueError(f"{label} must be 0 in M3C, got {value!r}")
        if not isinstance(self.strategy_fitting_permitted, bool) or self.strategy_fitting_permitted:
            raise ValueError("strategy_fitting_permitted must be False")
        if (
            not isinstance(self.post_result_parameter_changes_permitted, bool)
            or self.post_result_parameter_changes_permitted
        ):
            raise ValueError("post_result_parameter_changes_permitted must be False")
        if self.primary_alpha_level != 0.05:
            raise ValueError("primary_alpha_level is pinned to 0.05")
        if self.bootstrap_confidence != 0.95:
            raise ValueError("bootstrap_confidence is pinned to 0.95")

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "budget_schema_version": self.budget_schema_version,
            "milestone": self.milestone,
            "max_new_candidate_families": self.max_new_candidate_families,
            "permitted_candidate_id": self.permitted_candidate_id,
            "permitted_candidate_fingerprint": self.permitted_candidate_fingerprint,
            "permitted_primary_comparisons": self.permitted_primary_comparisons,
            "parameter_searches_permitted": self.parameter_searches_permitted,
            "sensitivity_candidates_permitted": self.sensitivity_candidates_permitted,
            "development_gate_accesses_permitted": self.development_gate_accesses_permitted,
            "final_holdout_accesses_permitted": self.final_holdout_accesses_permitted,
            "strategy_fitting_permitted": self.strategy_fitting_permitted,
            "post_result_parameter_changes_permitted": self.post_result_parameter_changes_permitted,
            "primary_alpha_level": self.primary_alpha_level,
            "bootstrap_confidence": self.bootstrap_confidence,
        }

    @classmethod
    def from_dict(cls, payload: object) -> ResearchBudget:
        data = require_mapping("research_budget", payload)
        require_exact_keys("research_budget", data, cls._KEYS)
        return cls(
            budget_schema_version=require_positive_int(
                "budget_schema_version", data["budget_schema_version"]
            ),
            milestone=require_exact_string("milestone", data["milestone"], "M3C"),
            max_new_candidate_families=require_positive_int(
                "max_new_candidate_families", data["max_new_candidate_families"]
            ),
            permitted_candidate_id=require_exact_string(
                "permitted_candidate_id", data["permitted_candidate_id"], M3C_CANDIDATE_ID
            ),
            permitted_candidate_fingerprint=require_sha256_fingerprint(
                "permitted_candidate_fingerprint", data["permitted_candidate_fingerprint"]
            ),
            permitted_primary_comparisons=require_positive_int(
                "permitted_primary_comparisons", data["permitted_primary_comparisons"]
            ),
            parameter_searches_permitted=require_nonnegative_int(
                "parameter_searches_permitted", data["parameter_searches_permitted"]
            ),
            sensitivity_candidates_permitted=require_nonnegative_int(
                "sensitivity_candidates_permitted", data["sensitivity_candidates_permitted"]
            ),
            development_gate_accesses_permitted=require_nonnegative_int(
                "development_gate_accesses_permitted", data["development_gate_accesses_permitted"]
            ),
            final_holdout_accesses_permitted=require_nonnegative_int(
                "final_holdout_accesses_permitted", data["final_holdout_accesses_permitted"]
            ),
            strategy_fitting_permitted=require_bool(
                "strategy_fitting_permitted", data["strategy_fitting_permitted"]
            ),
            post_result_parameter_changes_permitted=require_bool(
                "post_result_parameter_changes_permitted",
                data["post_result_parameter_changes_permitted"],
            ),
            primary_alpha_level=require_unit_interval(
                "primary_alpha_level", data["primary_alpha_level"]
            ),
            bootstrap_confidence=require_unit_interval(
                "bootstrap_confidence", data["bootstrap_confidence"]
            ),
        )


def build_research_budget() -> ResearchBudget:
    """The one canonical M3C research budget."""
    return ResearchBudget(
        budget_schema_version=1,
        milestone="M3C",
        max_new_candidate_families=1,
        permitted_candidate_id=M3C_CANDIDATE_ID,
        permitted_candidate_fingerprint=CANDIDATE_FINGERPRINT,
        permitted_primary_comparisons=1,
        parameter_searches_permitted=0,
        sensitivity_candidates_permitted=0,
        development_gate_accesses_permitted=0,
        final_holdout_accesses_permitted=0,
        strategy_fitting_permitted=False,
        post_result_parameter_changes_permitted=False,
        primary_alpha_level=0.05,
        bootstrap_confidence=0.95,
    )
