"""Cumulative research-debt register for the legacy ETH/BTC research partitions.

This module records, in one canonical artifact ``research/v2/research_debt_state.json``, the
accumulated selection pressure the project has spent on the historical research-train partition:
the partition repeatedly observed, the number of primary family evaluations, the number of
diagnostic (sensitivity) neighborhoods, the number of result reports reviewed, the number of
adaptive research milestones, the unresolved researcher degrees of freedom, the data sources used,
the sealed partitions still untouched, the prospective-data status, and a closure status.

It deliberately does NOT fabricate a precise overfit probability. Instead it reports CLOSED
qualitative levels backed by explicit integer counts: ``low`` / ``moderate`` / ``high`` /
``closed_to_further_research``. The pre-closure pressure level is derived mechanically from the
primary-family-evaluation count on a single reused partition; the legacy research partition then
derives ``closed_to_further_research`` because further candidate-nomination research on it is barred
(see the V2AB moratorium). Every count is sourced from already-committed evidence; nothing here
evaluates a candidate, reads a sealed partition, or mutates an accepted artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    load_canonical_json,
    require_int,
    require_mapping,
)
from eth_research.v2ab import family_catalog_audit as fca
from eth_research.v2b import research_memory as rm

RESEARCH_DEBT_SCHEMA_VERSION: int = 1
RESEARCH_DEBT_RELPATH: str = "research/v2/research_debt_state.json"

_V2B_RESULT_RELPATH: str = "research/v2b/v2b_results.json"

#: The observed research partition (repeatedly reused across every milestone).
_RESEARCH_PARTITION: str = "research_train"

#: The three sealed access ledgers; each MUST stay byte-empty (never evaluated).
SEALED_LEDGER_RELPATHS: tuple[str, ...] = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)

#: The five primary result artifacts reviewed (one per adaptive milestone).
_RESULT_REPORTS: tuple[str, ...] = (
    "research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003/development_results.json",
    "research/m3b/fractional_results.json",
    "research/m3c/candidate_results.json",
    "research/v2a/results.json",
    "research/v2b/v2b_results.json",
)

#: The researcher degrees of freedom the family-wise correction does NOT eliminate (multiplicity
#: limitation: "choice of families/features/transforms"). Enumerated so they are explicit.
_UNRESOLVED_DOF: tuple[str, ...] = (
    "candidate_family_choice",
    "feature_choice",
    "signal_transform_choice",
    "cost_scenario_choice",
    "fold_structure_choice",
)

#: Data sources consumed across the research history (ETH throughout; BTC added as V2B new info).
_DATA_SOURCES: tuple[str, ...] = ("btc_usd_daily", "eth_usd_daily")

_CLOSED_STATUS: str = "closed_to_further_research"
CLOSURE_LEVELS: frozenset[str] = frozenset({"low", "moderate", "high", _CLOSED_STATUS})
_PRESSURE_LEVELS: frozenset[str] = frozenset({"low", "moderate", "high"})

_DEBT_LIMITATIONS: tuple[str, ...] = (
    "Qualitative closure level backed by explicit counts, not a calibrated overfit probability.",
    "The multiplicity correction bounds family-wise error, not the enumerated researcher freedoms.",
    "Closure is a post-run governance control over the legacy partition, not a forecast.",
)


class ResearchDebtError(V2ValidationError):
    """A research-debt artifact was malformed or drifted from the derived evidence."""


def _pressure_level(primary_evaluations: int) -> str:
    """Mechanical pre-closure pressure level from the family-evaluation count on one partition."""
    if primary_evaluations <= 3:
        return "low"
    if primary_evaluations <= 8:
        return "moderate"
    return "high"


def _diagnostic_neighborhood_count(root: Path) -> int:
    """Total sensitivity-neighbor evaluations recorded in the committed V2B results."""
    obj = require_mapping("v2b_results", load_canonical_json(root / _V2B_RESULT_RELPATH))
    result = require_mapping("v2b_results.result", obj["result"])
    candidates = result["candidates"]
    if not isinstance(candidates, list):
        raise ResearchDebtError("v2b_results.result.candidates must be a list")
    total = 0
    for i, row in enumerate(candidates):
        crow = require_mapping(f"v2b candidates[{i}]", row)
        sensitivity = require_mapping(f"v2b candidates[{i}].sensitivity", crow["sensitivity"])
        total += require_int(
            f"v2b candidates[{i}].sensitivity.neighbor_count", sensitivity["neighbor_count"]
        )
    return total


@dataclass(frozen=True, slots=True)
class ResearchDebtState:
    """The cumulative research-debt state for the legacy research partition."""

    schema_version: int
    research_partition: str
    partition_observation_count: int
    primary_family_evaluations: int
    historical_candidate_families: int
    v2a_candidate_families: int
    v2b_candidate_families: int
    diagnostic_neighborhoods: int
    result_reports_reviewed: int
    adaptive_research_milestones: int
    unresolved_researcher_degrees_of_freedom: tuple[str, ...]
    data_sources_used: tuple[str, ...]
    sealed_partitions_remaining: int
    prospective_data_status: str
    pre_closure_pressure_level: str
    closure_status: str

    def __post_init__(self) -> None:
        if self.pre_closure_pressure_level not in _PRESSURE_LEVELS:
            raise ResearchDebtError(
                f"invalid pre-closure level {self.pre_closure_pressure_level!r}"
            )
        if self.closure_status not in CLOSURE_LEVELS:
            raise ResearchDebtError(f"invalid closure status {self.closure_status!r}")

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "research_partition": self.research_partition,
            "partitions_repeatedly_observed": [
                {
                    "partition": self.research_partition,
                    "observation_count": self.partition_observation_count,
                }
            ],
            "primary_family_evaluations": self.primary_family_evaluations,
            "historical_candidate_families": self.historical_candidate_families,
            "v2a_candidate_families": self.v2a_candidate_families,
            "v2b_candidate_families": self.v2b_candidate_families,
            "diagnostic_neighborhoods": self.diagnostic_neighborhoods,
            "result_reports_reviewed": self.result_reports_reviewed,
            "adaptive_research_milestones": self.adaptive_research_milestones,
            "unresolved_researcher_degrees_of_freedom": list(
                self.unresolved_researcher_degrees_of_freedom
            ),
            "unresolved_researcher_dof_count": len(self.unresolved_researcher_degrees_of_freedom),
            "data_sources_used": list(self.data_sources_used),
            "sealed_partitions_remaining": self.sealed_partitions_remaining,
            "sealed_access_ledgers": list(SEALED_LEDGER_RELPATHS),
            "prospective_data_status": self.prospective_data_status,
            "pre_closure_pressure_level": self.pre_closure_pressure_level,
            "closure_status": self.closure_status,
            "limitations": list(_DEBT_LIMITATIONS),
        }

    @staticmethod
    def current(repo_root: str | Path) -> ResearchDebtState:
        """Derive the research-debt state from the committed evidence (never mutates anything)."""
        root = Path(repo_root)
        counts = fca.reconcile_cumulative_count(root)
        primary = counts["candidate_families"]
        return ResearchDebtState(
            schema_version=RESEARCH_DEBT_SCHEMA_VERSION,
            research_partition=_RESEARCH_PARTITION,
            partition_observation_count=len(rm.MILESTONES),
            primary_family_evaluations=primary,
            historical_candidate_families=counts["historical_candidate_families"],
            v2a_candidate_families=counts["v2a_candidate_families"],
            v2b_candidate_families=counts["v2b_candidate_families"],
            diagnostic_neighborhoods=_diagnostic_neighborhood_count(root),
            result_reports_reviewed=len(_RESULT_REPORTS),
            adaptive_research_milestones=len(rm.MILESTONES),
            unresolved_researcher_degrees_of_freedom=_UNRESOLVED_DOF,
            data_sources_used=_DATA_SOURCES,
            sealed_partitions_remaining=len(SEALED_LEDGER_RELPATHS),
            prospective_data_status="unavailable_pending_forward_collection",
            pre_closure_pressure_level=_pressure_level(primary),
            closure_status=_CLOSED_STATUS,
        )


def build_research_debt_state_bytes(repo_root: str | Path) -> bytes:
    """The canonical JSON bytes of the derived research-debt state."""
    return canonical_json_bytes(ResearchDebtState.current(repo_root).to_canonical())


def write_research_debt_state(repo_root: str | Path) -> Path:
    """Write ``research/v2/research_debt_state.json`` from the derived state and return the path."""
    root = Path(repo_root)
    path = root / RESEARCH_DEBT_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_research_debt_state_bytes(root))
    return path


def verify_research_debt(repo_root: str | Path) -> list[str]:
    """Verify the committed research-debt state; empty return means it is intact and consistent."""
    root = Path(repo_root)
    path = root / RESEARCH_DEBT_RELPATH
    if not path.exists():
        return [f"{RESEARCH_DEBT_RELPATH} is missing"]

    problems: list[str] = []

    # Sealed access ledgers must remain byte-empty (reading the ledger, never the sealed partition).
    for relpath in SEALED_LEDGER_RELPATHS:
        ledger = root / relpath
        if not ledger.exists():
            problems.append(f"sealed access ledger {relpath} is missing")
        elif ledger.stat().st_size != 0:
            problems.append(f"sealed access ledger {relpath} is not byte-empty (access recorded)")

    try:
        expected = build_research_debt_state_bytes(root)
        state = ResearchDebtState.current(root)
    except ValueError as exc:
        problems.append(f"research-debt state could not be derived: {exc}")
        return problems

    if path.read_bytes() != expected:
        problems.append(f"{RESEARCH_DEBT_RELPATH} does not reproduce byte-for-byte from evidence")

    # Internal consistency: the count split must reconcile and the closure must be terminal.
    if state.primary_family_evaluations != 10:
        problems.append(
            f"primary_family_evaluations={state.primary_family_evaluations} must reconcile to 10"
        )
    if (
        state.historical_candidate_families + state.v2b_candidate_families
        != state.primary_family_evaluations
    ):
        problems.append("historical + V2B candidate families do not sum to the primary evaluations")
    if state.closure_status != _CLOSED_STATUS:
        problems.append("closure status is not closed_to_further_research for the legacy partition")

    # Cross-check the committed document parses and carries the closed status.
    try:
        obj = require_mapping("research_debt", load_canonical_json(path))
        if obj.get("closure_status") != _CLOSED_STATUS:
            problems.append("committed closure_status is not the closed status")
        if require_int("primary_family_evaluations", obj["primary_family_evaluations"]) != 10:
            problems.append("committed primary_family_evaluations does not reconcile to 10")
    except ValueError as exc:
        problems.append(f"committed research-debt state is unreadable: {exc}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """CLI: build or verify the cumulative research-debt state."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true", help="Generate and write the debt state.")
    group.add_argument("--check", action="store_true", help="Verify the committed debt state.")
    args = parser.parse_args(argv)
    if args.build:
        path = write_research_debt_state(args.repo_root)
        print(json.dumps({"ok": True, "problems": [], "wrote": str(path)}))
        return 0
    problems = verify_research_debt(args.repo_root)
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "CLOSURE_LEVELS",
    "RESEARCH_DEBT_RELPATH",
    "SEALED_LEDGER_RELPATHS",
    "ResearchDebtError",
    "ResearchDebtState",
    "build_research_debt_state_bytes",
    "verify_research_debt",
    "write_research_debt_state",
]
