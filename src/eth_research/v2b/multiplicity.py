"""Cumulative family-wise multiplicity + alpha-spending policy, and the new-information requirement.

V2A returned a null; the danger now is spending a fresh 5% every time a "new" family is tried until
one clears by chance. This module preregisters — **before** any V2B result exists — a cumulative,
family-wise multiple-comparisons policy that counts *every* candidate family the project has ever
evaluated (from :mod:`eth_research.v2b.research_memory`) plus V2B's own, and derives the
conservative per-family threshold V2B's primary nomination test must clear.

Correction: a preregistered **Holm-Bonferroni** family-wise procedure over the cumulative family
count. The single most-conservative (rank-1) per-family level is the Bonferroni bound
``cumulative_alpha / total_families`` — this module exposes exactly that as the frozen V2B
threshold, so the primary decision accounts for both V2B's ≤ 2 families and the full documented
research history. Diagnostics keep their own unadjusted intervals; only the *primary* verdict is
corrected.

This is a frequentist correction applied to *adaptively developed* research. It bounds the
family-wise false-positive rate **given the enumerated families**; it does **not** eliminate
researcher degrees of freedom (choice of families, features, transforms). That honesty is stated
here and in the docs, and the policy never resets (a new package version, a new instrument, or a new
benchmark does not refresh the budget).

The module also freezes the **new-information requirement** (§6): a V2B candidate is eligible only
because it consumes a genuinely new input (BTC-USD). A candidate whose decisions are invariant to
its BTC inputs, or that silently falls back to an ETH-only rule when BTC is unavailable, is not a
valid V2B candidate; missing BTC evidence must yield *no signal*, never a hidden ETH-only strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    require_choice,
    require_mapping,
)
from eth_research.v2b import research_memory as rm

MULTIPLICITY_SCHEMA_VERSION: int = 1
MULTIPLICITY_STATE_RELPATH: str = "research/v2b/research_multiplicity_state.json"

# The whole-program family-wise error budget (Type-I). Fixed before any V2B result; never reset.
CUMULATIVE_ALPHA_BUDGET: float = 0.05
# The prior per-test nominal alpha used by the accepted milestones (M3C DECISION_ALPHA).
HISTORICAL_NOMINAL_ALPHA: float = 0.05
# V2B may register at most two genuinely new candidate families (milestone §8).
V2B_MAX_CANDIDATE_FAMILIES: int = 2
CORRECTION_METHOD: str = "holm_bonferroni_familywise"
TIE_BEHAVIOR: str = "highest_primary_point_estimate_else_none"

_CORRECTIONS: frozenset[str] = frozenset({"holm_bonferroni_familywise"})


class MultiplicityError(V2ValidationError):
    """A multiplicity artifact was malformed or drifted from the frozen policy."""


@dataclass(frozen=True, slots=True)
class ResearchMultiplicityState:
    """The frozen, cumulative family-wise multiplicity + alpha-spending state."""

    schema_version: int
    historical_family_count: int
    historical_primary_test_count: int
    historical_nominal_alpha: float
    v2a_family_count: int
    v2b_max_family_count: int
    cumulative_alpha_budget: float
    correction_method: str
    tie_behavior: str
    no_reset: bool

    def __post_init__(self) -> None:
        require_choice("multiplicity.correction_method", self.correction_method, _CORRECTIONS)
        if not 0.0 < self.cumulative_alpha_budget < 1.0:
            raise MultiplicityError("cumulative_alpha_budget must be in (0, 1)")
        if self.historical_family_count < 0 or self.v2b_max_family_count <= 0:
            raise MultiplicityError("family counts must be non-negative / positive")
        if not self.no_reset:
            raise MultiplicityError("the multiplicity policy must declare no_reset = true")

    def total_family_count(self) -> int:
        """Every candidate family ever evaluated plus V2B's maximum — the correction denominator."""
        return self.historical_family_count + self.v2b_max_family_count

    def corrected_per_family_alpha(self) -> float:
        """Conservative (Bonferroni/Holm rank-1) per-family level the primary test must clear."""
        return self.cumulative_alpha_budget / self.total_family_count()

    def corrected_one_sided_confidence(self) -> float:
        """One-sided bootstrap confidence implied by the corrected per-family alpha."""
        return 1.0 - self.corrected_per_family_alpha()

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "historical_family_count": self.historical_family_count,
            "historical_primary_test_count": self.historical_primary_test_count,
            "historical_nominal_alpha": self.historical_nominal_alpha,
            "v2a_family_count": self.v2a_family_count,
            "v2b_max_family_count": self.v2b_max_family_count,
            "cumulative_alpha_budget": self.cumulative_alpha_budget,
            "total_family_count": self.total_family_count(),
            "correction_method": self.correction_method,
            "corrected_per_family_alpha": self.corrected_per_family_alpha(),
            "corrected_one_sided_confidence": self.corrected_one_sided_confidence(),
            "tie_behavior": self.tie_behavior,
            "no_reset": self.no_reset,
            "research_family_catalog_sha256": _catalog_sha256(),
            "limitations": [
                "Frequentist family-wise correction over the ENUMERATED families; it does not "
                "eliminate researcher degrees of freedom (choice of families/features/transforms).",
                "The budget never resets: a new package version, the addition of BTC, or a changed "
                "benchmark does not refresh alpha.",
                "Diagnostics report unadjusted intervals; only the primary nomination verdict is "
                "corrected.",
            ],
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @staticmethod
    def current() -> ResearchMultiplicityState:
        """The frozen V2B multiplicity state, derived from the cumulative research catalog."""
        v2a = [
            f for f in rm.RESEARCH_FAMILY_CATALOG if f.role != "benchmark" and "v2a" in f.lineage
        ]
        return ResearchMultiplicityState(
            schema_version=MULTIPLICITY_SCHEMA_VERSION,
            historical_family_count=rm.historical_candidate_family_count(),
            historical_primary_test_count=rm.historical_candidate_family_count(),
            historical_nominal_alpha=HISTORICAL_NOMINAL_ALPHA,
            v2a_family_count=len(v2a),
            v2b_max_family_count=V2B_MAX_CANDIDATE_FAMILIES,
            cumulative_alpha_budget=CUMULATIVE_ALPHA_BUDGET,
            correction_method=CORRECTION_METHOD,
            tie_behavior=TIE_BEHAVIOR,
            no_reset=True,
        )

    @staticmethod
    def parse(raw: object) -> ResearchMultiplicityState:
        obj = require_mapping("multiplicity_state", raw)
        state = ResearchMultiplicityState.current()
        if canonical_sha256(obj) != state.fingerprint():
            raise MultiplicityError(
                "committed multiplicity state drifted from the frozen policy / research catalog"
            )
        return state


def _catalog_sha256() -> str:
    return canonical_sha256([f.identity.fingerprint() for f in rm.RESEARCH_FAMILY_CATALOG])


def build_multiplicity_state_bytes() -> bytes:
    return canonical_json_bytes(ResearchMultiplicityState.current().to_canonical())


def verify_multiplicity(repo_root: str | Path) -> list[str]:
    """Return problems with the committed multiplicity state (empty == reproduces + parses)."""
    path = Path(repo_root) / MULTIPLICITY_STATE_RELPATH
    problems: list[str] = []
    if not path.exists():
        problems.append(f"{MULTIPLICITY_STATE_RELPATH} is missing")
        return problems
    if path.read_bytes() != build_multiplicity_state_bytes():
        problems.append(f"{MULTIPLICITY_STATE_RELPATH} does not reproduce byte-for-byte")
    return problems


# --------------------------------------------------------------------------- #
# §6 new-information requirement (the genuinely-new-input contract)             #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class NewInformationRequirement:
    """The contract a V2B candidate must satisfy to count as using a genuinely new input source."""

    required_input_instrument: str
    required_context: str
    no_eth_only_fallback: bool
    missing_input_behavior: str
    prefix_sensitivity_required: bool
    future_input_inertness_required: bool

    def to_canonical(self) -> dict[str, object]:
        return {
            "required_input_instrument": self.required_input_instrument,
            "required_context": self.required_context,
            "no_eth_only_fallback": self.no_eth_only_fallback,
            "missing_input_behavior": self.missing_input_behavior,
            "prefix_sensitivity_required": self.prefix_sensitivity_required,
            "future_input_inertness_required": self.future_input_inertness_required,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


NEW_INFORMATION_REQUIREMENT: NewInformationRequirement = NewInformationRequirement(
    required_input_instrument="btc",
    required_context="cross_asset_required",
    no_eth_only_fallback=True,
    missing_input_behavior="refuse_no_signal",
    prefix_sensitivity_required=True,
    future_input_inertness_required=True,
)


def assert_uses_new_information(identity: rm.ResearchFamilyIdentity) -> None:
    """A V2B candidate family must read BTC and require cross-asset context (fail-closed)."""
    required = NEW_INFORMATION_REQUIREMENT.required_input_instrument
    if required not in identity.input_instruments:
        raise MultiplicityError(
            f"V2B candidate does not read {required!r} "
            f"(input_instruments={identity.input_instruments}); it does not use the new information"
        )
    if identity.context_requirement != NEW_INFORMATION_REQUIREMENT.required_context:
        raise MultiplicityError(
            f"V2B candidate context {identity.context_requirement!r} != required "
            f"{NEW_INFORMATION_REQUIREMENT.required_context!r}; a missing-BTC ETH-only fallback is "
            f"forbidden"
        )
