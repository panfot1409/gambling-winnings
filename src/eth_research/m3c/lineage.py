"""Strict, immutable adaptive-research lineage.

The new M3C candidate was conceived *after* observing earlier SMA, Donchian,
volatility-target, cost, and risk results. This module records that adaptivity
honestly instead of pretending the candidate emerged in a statistical vacuum: it
enumerates every **distinct hypothesis family** (not every corrective republication
or cost cell), binds each to the committed artifact where it was first evaluated
(full real SHA-256, never abbreviated), and forces the count of distinct historical
candidate families to be exactly right. The independent development gate — never
touched here — is what protects against this adaptive history; research-train
inference alone does not establish out-of-sample alpha, even if the primary passes.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.m3c.candidate import CANDIDATE_FINGERPRINT, M3C_CANDIDATE_ID
from eth_research.m3c.validation import (
    canonical_sha256,
    require_bool,
    require_exact_keys,
    require_hex64,
    require_int,
    require_mapping,
    require_nonempty_str,
    require_positive_int,
    require_safe_relative_path,
    require_str,
    require_tuple,
)

LINEAGE_SCHEMA_VERSION: int = 1


def _require_git_commit(label: str, value: object) -> str:
    """A 40-character lowercase hex git commit SHA-1 (or the zero-hash sentinel)."""
    text = require_str(label, value)
    if len(text) != 40 or any(c not in "0123456789abcdef" for c in text):
        raise ValueError(f"{label} must be exactly 40 lowercase hex characters, got {text!r}")
    return text


# The count the parser pins: distinct *candidate* families ever posed across the
# project (benchmarks excluded). Any drift is rejected.
EXPECTED_CANDIDATE_FAMILY_COUNT: int = 5

_ENTRY_KEYS = frozenset(
    {
        "hypothesis_id",
        "family_id",
        "kind",
        "canonical_fingerprint",
        "fixed_parameters",
        "first_evaluation_milestone",
        "first_experiment_id",
        "first_evaluation_commit",
        "immutable_result_path",
        "immutable_result_sha256",
        "observed_status",
        "republication_relationship",
        "adaptive_relationship",
        "formally_promotion_tested",
        "counts_against_candidate_budget",
    }
)
_KINDS = ("benchmark", "candidate")


@dataclass(frozen=True)
class LineageEntry:
    """One distinct hypothesis family, bound to its first committed evaluation."""

    hypothesis_id: str
    family_id: str
    kind: str
    canonical_fingerprint: str
    fixed_parameters: dict[str, object]
    first_evaluation_milestone: str
    first_experiment_id: str
    first_evaluation_commit: str
    immutable_result_path: str
    immutable_result_sha256: str
    observed_status: str
    republication_relationship: str
    adaptive_relationship: str
    formally_promotion_tested: bool
    counts_against_candidate_budget: bool

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}, got {self.kind!r}")
        # A benchmark is never a promotion candidate and never spends candidate budget.
        if self.kind == "benchmark" and (
            self.formally_promotion_tested or self.counts_against_candidate_budget
        ):
            raise ValueError(f"benchmark {self.family_id!r} cannot be a budgeted candidate")

    def to_dict(self) -> dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "family_id": self.family_id,
            "kind": self.kind,
            "canonical_fingerprint": self.canonical_fingerprint,
            "fixed_parameters": self.fixed_parameters,
            "first_evaluation_milestone": self.first_evaluation_milestone,
            "first_experiment_id": self.first_experiment_id,
            "first_evaluation_commit": self.first_evaluation_commit,
            "immutable_result_path": self.immutable_result_path,
            "immutable_result_sha256": self.immutable_result_sha256,
            "observed_status": self.observed_status,
            "republication_relationship": self.republication_relationship,
            "adaptive_relationship": self.adaptive_relationship,
            "formally_promotion_tested": self.formally_promotion_tested,
            "counts_against_candidate_budget": self.counts_against_candidate_budget,
        }

    @classmethod
    def from_dict(cls, payload: object) -> LineageEntry:
        data = require_mapping("lineage_entry", payload)
        require_exact_keys("lineage_entry", data, _ENTRY_KEYS)
        return cls(
            hypothesis_id=require_nonempty_str("hypothesis_id", data["hypothesis_id"]),
            family_id=require_nonempty_str("family_id", data["family_id"]),
            kind=require_nonempty_str("kind", data["kind"]),
            canonical_fingerprint=require_hex64(
                "canonical_fingerprint", data["canonical_fingerprint"]
            ),
            fixed_parameters=require_mapping("fixed_parameters", data["fixed_parameters"]),
            first_evaluation_milestone=require_nonempty_str(
                "first_evaluation_milestone", data["first_evaluation_milestone"]
            ),
            first_experiment_id=require_nonempty_str(
                "first_experiment_id", data["first_experiment_id"]
            ),
            first_evaluation_commit=_require_git_commit(
                "first_evaluation_commit", data["first_evaluation_commit"]
            ),
            immutable_result_path=require_safe_relative_path(
                "immutable_result_path", data["immutable_result_path"], prefix="research/"
            ),
            immutable_result_sha256=require_hex64(
                "immutable_result_sha256", data["immutable_result_sha256"]
            ),
            observed_status=require_nonempty_str("observed_status", data["observed_status"]),
            republication_relationship=require_str(
                "republication_relationship", data["republication_relationship"]
            ),
            adaptive_relationship=require_str(
                "adaptive_relationship", data["adaptive_relationship"]
            ),
            formally_promotion_tested=require_bool(
                "formally_promotion_tested", data["formally_promotion_tested"]
            ),
            counts_against_candidate_budget=require_bool(
                "counts_against_candidate_budget", data["counts_against_candidate_budget"]
            ),
        )


@dataclass(frozen=True)
class ResearchLineage:
    """The full ordered, de-duplicated lineage with a pinned candidate-family count."""

    lineage_schema_version: int
    candidate_family_count: int
    new_candidate_family_id: str
    new_candidate_fingerprint: str
    entries: tuple[LineageEntry, ...]

    _KEYS = frozenset(
        {
            "lineage_schema_version",
            "candidate_family_count",
            "new_candidate_family_id",
            "new_candidate_fingerprint",
            "entries",
        }
    )

    def __post_init__(self) -> None:
        if self.lineage_schema_version != LINEAGE_SCHEMA_VERSION:
            raise ValueError("lineage_schema_version must be 1")
        ids = [e.hypothesis_id for e in self.entries]
        families = [e.family_id for e in self.entries]
        fingerprints = [e.canonical_fingerprint for e in self.entries]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate hypothesis id in lineage")
        if len(set(families)) != len(families):
            raise ValueError("duplicate family id in lineage")
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("duplicate canonical fingerprint under conflicting identities")
        candidates = [e for e in self.entries if e.kind == "candidate"]
        if self.candidate_family_count != len(candidates):
            raise ValueError(
                f"candidate_family_count {self.candidate_family_count} != {len(candidates)} entries"
            )
        if self.candidate_family_count != EXPECTED_CANDIDATE_FAMILY_COUNT:
            raise ValueError(
                f"expected exactly {EXPECTED_CANDIDATE_FAMILY_COUNT} distinct candidate families"
            )
        new = [e for e in candidates if e.family_id == self.new_candidate_family_id]
        if len(new) != 1:
            raise ValueError("the new candidate family must appear exactly once")
        if new[0].canonical_fingerprint != self.new_candidate_fingerprint:
            raise ValueError("new_candidate_fingerprint does not match its entry")
        if new[0].canonical_fingerprint != CANDIDATE_FINGERPRINT:
            raise ValueError(
                "the new candidate entry must carry the composed candidate fingerprint"
            )
        if new[0].first_evaluation_milestone != "M3C":
            raise ValueError("the new candidate is first evaluated in M3C")

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "lineage_schema_version": self.lineage_schema_version,
            "candidate_family_count": self.candidate_family_count,
            "new_candidate_family_id": self.new_candidate_family_id,
            "new_candidate_fingerprint": self.new_candidate_fingerprint,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, payload: object) -> ResearchLineage:
        data = require_mapping("research_lineage", payload)
        require_exact_keys("research_lineage", data, cls._KEYS)
        return cls(
            lineage_schema_version=require_positive_int(
                "lineage_schema_version", data["lineage_schema_version"]
            ),
            candidate_family_count=require_int(
                "candidate_family_count", data["candidate_family_count"]
            ),
            new_candidate_family_id=require_nonempty_str(
                "new_candidate_family_id", data["new_candidate_family_id"]
            ),
            new_candidate_fingerprint=require_hex64(
                "new_candidate_fingerprint", data["new_candidate_fingerprint"]
            ),
            entries=require_tuple(
                "entries", data["entries"], lambda _l, v: LineageEntry.from_dict(v)
            ),
        )


def _fp(family_id: str, kind: str, params: dict[str, object]) -> str:
    """A deterministic, content-addressed identity for a historical family."""
    return canonical_sha256({"family_id": family_id, "kind": kind, "fixed_parameters": params})


# Real committed bindings gathered from the repository (full SHA-256, never abbreviated).
_M3A_RESULT = (
    "research/m3a/experiments/m3a-fixed-baseline-comparison-v1-run-001/development_results.json"
)
_M3A_RESULT_SHA = "b8616248c72e863210de131f91a7ea90e6810ff20c13440375ed385b3c8ed67a"
_M3A_EXPERIMENT = "m3a-fixed-baseline-comparison-v1-run-001"
_M3A_COMMIT = "3fa95f78d0e49f0d548244125c1cb028362eeee8"
_M3B_RESULT = "research/m3b/fractional_results.json"
_M3B_RESULT_SHA = "81f94fab60f4f168bf5bb237c1e32e0d4567f4325ee6c541af7feffca2ab9dfc"
_M3B_EXPERIMENT = "m3b-fractional-execution-risk-v1-run-001"
_M3B_COMMIT = "b00aa3babc1ba6ac2fd2a2ba77186708d5074250"
# The new candidate is first evaluated in M3C; its immutable result does not exist
# until execution P, so the lineage binds the destination path with the empty-content
# SHA-256 as an honest "not yet evaluated" placeholder.
_EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_PENDING_COMMIT = "0" * 40  # git zero-hash (SHA-1): the candidate has no first-eval commit yet


def build_m3c_lineage() -> ResearchLineage:
    """The seven real lineage entries: two benchmarks + five candidate families."""
    entries = (
        LineageEntry(
            hypothesis_id="benchmark.cash",
            family_id="cash",
            kind="benchmark",
            canonical_fingerprint=_fp("cash", "benchmark", {"target": 0.0}),
            fixed_parameters={"target": 0.0},
            first_evaluation_milestone="M3A",
            first_experiment_id=_M3A_EXPERIMENT,
            first_evaluation_commit=_M3A_COMMIT,
            immutable_result_path=_M3A_RESULT,
            immutable_result_sha256=_M3A_RESULT_SHA,
            observed_status="benchmark",
            republication_relationship="re-evaluated verbatim in M3B and M3C as a fixed benchmark",
            adaptive_relationship="none; holds nothing",
            formally_promotion_tested=False,
            counts_against_candidate_budget=False,
        ),
        LineageEntry(
            hypothesis_id="benchmark.buy_and_hold",
            family_id="buy_and_hold",
            kind="benchmark",
            canonical_fingerprint=_fp("buy_and_hold", "benchmark", {"target": 1.0}),
            fixed_parameters={"target": 1.0},
            first_evaluation_milestone="M3A",
            first_experiment_id=_M3A_EXPERIMENT,
            first_evaluation_commit=_M3A_COMMIT,
            immutable_result_path=_M3A_RESULT,
            immutable_result_sha256=_M3A_RESULT_SHA,
            observed_status="benchmark",
            republication_relationship="re-evaluated verbatim in M3B and M3C as the comparator",
            adaptive_relationship="none; the always-long reference",
            formally_promotion_tested=False,
            counts_against_candidate_budget=False,
        ),
        LineageEntry(
            hypothesis_id="candidate.sma_20_50",
            family_id="sma_20_50",
            kind="candidate",
            canonical_fingerprint=_fp("sma_20_50", "candidate", {"fast": 20, "slow": 50}),
            fixed_parameters={"fast_window": 20, "slow_window": 50},
            first_evaluation_milestone="M3A",
            first_experiment_id=_M3A_EXPERIMENT,
            first_evaluation_commit=_M3A_COMMIT,
            immutable_result_path=_M3A_RESULT,
            immutable_result_sha256=_M3A_RESULT_SHA,
            observed_status="observed; primary bootstrap interval straddled zero (no alpha)",
            republication_relationship="corrective M3A run-002/003 republications, not new trials",
            adaptive_relationship="an early moving-average trend hypothesis",
            formally_promotion_tested=True,
            counts_against_candidate_budget=True,
        ),
        LineageEntry(
            hypothesis_id="candidate.donchian_55_20",
            family_id="donchian_55_20",
            kind="candidate",
            canonical_fingerprint=_fp("donchian_55_20", "candidate", {"entry": 55, "exit": 20}),
            fixed_parameters={"entry_window": 55, "exit_window": 20},
            first_evaluation_milestone="M3A",
            first_experiment_id=_M3A_EXPERIMENT,
            first_evaluation_commit=_M3A_COMMIT,
            immutable_result_path=_M3A_RESULT,
            immutable_result_sha256=_M3A_RESULT_SHA,
            observed_status="observed; primary bootstrap interval straddled zero (no alpha)",
            republication_relationship="corrective M3A run-002/003; re-used as M3B/M3C benchmark",
            adaptive_relationship="a breakout/channel trend hypothesis",
            formally_promotion_tested=True,
            counts_against_candidate_budget=True,
        ),
        LineageEntry(
            hypothesis_id="candidate.vol_target_buy_and_hold_30d_50pct",
            family_id="vol_target_buy_and_hold_30d_50pct",
            kind="candidate",
            canonical_fingerprint=_fp(
                "vol_target_buy_and_hold_30d_50pct",
                "candidate",
                {"base": "buy_and_hold", "vol_lookback": 30, "annual_target": 0.5},
            ),
            fixed_parameters={"base": "buy_and_hold", "vol_lookback": 30, "annual_target": 0.5},
            first_evaluation_milestone="M3B",
            first_experiment_id=_M3B_EXPERIMENT,
            first_evaluation_commit=_M3B_COMMIT,
            immutable_result_path=_M3B_RESULT,
            immutable_result_sha256=_M3B_RESULT_SHA,
            observed_status="observed (M3B measurement cell); no promotion decision made",
            republication_relationship="single M3B run-001 evaluation; not republished",
            adaptive_relationship="a volatility-managed variant of buy-and-hold",
            formally_promotion_tested=False,
            counts_against_candidate_budget=True,
        ),
        LineageEntry(
            hypothesis_id="candidate.vol_target_donchian_55_20_30d_50pct",
            family_id="vol_target_donchian_55_20_30d_50pct",
            kind="candidate",
            canonical_fingerprint=_fp(
                "vol_target_donchian_55_20_30d_50pct",
                "candidate",
                {"base": "donchian_55_20", "vol_lookback": 30, "annual_target": 0.5},
            ),
            fixed_parameters={"base": "donchian_55_20", "vol_lookback": 30, "annual_target": 0.5},
            first_evaluation_milestone="M3B",
            first_experiment_id=_M3B_EXPERIMENT,
            first_evaluation_commit=_M3B_COMMIT,
            immutable_result_path=_M3B_RESULT,
            immutable_result_sha256=_M3B_RESULT_SHA,
            observed_status="observed (M3B cell); re-used as an M3C benchmark",
            republication_relationship="single M3B run-001 evaluation; not republished",
            adaptive_relationship="vol-managed trend variant motivating the M3C consensus rule",
            formally_promotion_tested=False,
            counts_against_candidate_budget=True,
        ),
        LineageEntry(
            hypothesis_id="candidate.dual_horizon_trend_63_252_vol_target_30d_50pct",
            family_id=M3C_CANDIDATE_ID,
            kind="candidate",
            canonical_fingerprint=CANDIDATE_FINGERPRINT,
            fixed_parameters={
                "medium_horizon": 63,
                "long_horizon": 252,
                "vol_lookback": 30,
                "annual_target": 0.5,
            },
            first_evaluation_milestone="M3C",
            first_experiment_id="m3c-dual-horizon-trend-v1-run-001",
            # The lineage is frozen BEFORE the candidate is evaluated, so its own
            # first-evaluation commit and result are genuinely unknown here: the git
            # zero-hash sentinel + empty-content SHA-256 record "pending / not yet
            # evaluated" honestly (the executed result is verified via the registry
            # and archive at replay, not back-patched into this immutable lineage).
            first_evaluation_commit=_PENDING_COMMIT,
            immutable_result_path="research/m3c/candidate_results.json",
            immutable_result_sha256=_EMPTY_SHA,
            observed_status="not yet evaluated at lineage-commit time (M3C run-001 evaluates once)",
            republication_relationship="none; first and only evaluation",
            adaptive_relationship=(
                "ADAPTIVELY MOTIVATED by the earlier SMA/Donchian/vol-target trend evidence above; "
                "so M3C results are research-train exploratory evidence, not out-of-sample alpha"
            ),
            formally_promotion_tested=True,
            counts_against_candidate_budget=True,
        ),
    )
    return ResearchLineage(
        lineage_schema_version=LINEAGE_SCHEMA_VERSION,
        candidate_family_count=EXPECTED_CANDIDATE_FAMILY_COUNT,
        new_candidate_family_id=M3C_CANDIDATE_ID,
        new_candidate_fingerprint=CANDIDATE_FINGERPRINT,
        entries=entries,
    )
