"""The one-shot governed candidate-research budget.

V2A gets a single, tightly bounded chance to look at the authorized research-train partition with a
candidate strategy. The budget fixes that discipline as data:

* at most **three** genuinely distinct candidate families may be defined (before any results);
* the programme executes the governed evaluation **exactly once**;
* a *started* run consumes the one-shot budget even if it later fails — there is no second attempt;
* the budget is never repaired or reset.

This module holds the policy constants and their strict parser. The append-only hash-chained
registry (a later phase) is what physically records the single ``started`` event and enforces the
consume-on-start rule against a real ledger; the registry reads the constants declared here so the
two can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_bool,
    require_exact_keys,
    require_int,
    require_mapping,
    require_positive_int,
)

BUDGET_SCHEMA_VERSION: int = 1

# The hard ceilings. Distinct candidate *families*, not parameterizations: three families is the
# most V2A may pose, and the governed evaluation runs once.
MAX_CANDIDATE_FAMILIES: int = 3
MAX_RESEARCH_EXECUTIONS: int = 1


class BudgetError(V2ValidationError):
    """A candidate set or execution ledger exceeded the one-shot research budget."""


@dataclass(frozen=True, slots=True)
class OneShotResearchBudget:
    """The committed, hashable statement of the one-shot candidate-research discipline."""

    schema_version: int
    max_candidate_families: int
    max_research_executions: int
    consume_on_start: bool
    allow_repair_or_reset: bool

    @staticmethod
    def current() -> OneShotResearchBudget:
        return OneShotResearchBudget(
            schema_version=BUDGET_SCHEMA_VERSION,
            max_candidate_families=MAX_CANDIDATE_FAMILIES,
            max_research_executions=MAX_RESEARCH_EXECUTIONS,
            consume_on_start=True,
            allow_repair_or_reset=False,
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "max_candidate_families": self.max_candidate_families,
            "max_research_executions": self.max_research_executions,
            "consume_on_start": self.consume_on_start,
            "allow_repair_or_reset": self.allow_repair_or_reset,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


_BUDGET_KEYS = frozenset(
    {
        "schema_version",
        "max_candidate_families",
        "max_research_executions",
        "consume_on_start",
        "allow_repair_or_reset",
    }
)


def parse_budget(raw: object) -> OneShotResearchBudget:
    """Strictly decode a committed budget artifact and re-assert the fixed one-shot discipline."""
    obj = require_mapping("budget", raw)
    require_exact_keys("budget", obj, _BUDGET_KEYS)
    parsed = OneShotResearchBudget(
        schema_version=require_int("budget.schema_version", obj["schema_version"]),
        max_candidate_families=require_positive_int(
            "budget.max_candidate_families", obj["max_candidate_families"]
        ),
        max_research_executions=require_positive_int(
            "budget.max_research_executions", obj["max_research_executions"]
        ),
        consume_on_start=require_bool("budget.consume_on_start", obj["consume_on_start"]),
        allow_repair_or_reset=require_bool(
            "budget.allow_repair_or_reset", obj["allow_repair_or_reset"]
        ),
    )
    if parsed.fingerprint() != OneShotResearchBudget.current().fingerprint():
        raise BudgetError("budget content drifted from the fixed one-shot research budget")
    return parsed


def require_within_family_budget(label: str, family_count: object) -> int:
    """Return the family count iff it is within ``MAX_CANDIDATE_FAMILIES`` (and >= 1)."""
    count = require_positive_int(label, family_count)
    if count > MAX_CANDIDATE_FAMILIES:
        raise BudgetError(
            f"{label} defines {count} candidate families, exceeding the budget of "
            f"{MAX_CANDIDATE_FAMILIES}"
        )
    return count


def require_within_execution_budget(label: str, started_count: object) -> int:
    """Return the started-run count iff it is within ``MAX_RESEARCH_EXECUTIONS`` (may be 0)."""
    count = require_int(label, started_count)
    if count < 0:
        raise BudgetError(f"{label} must be non-negative, got {count}")
    if count > MAX_RESEARCH_EXECUTIONS:
        raise BudgetError(
            f"{label} records {count} started research executions, exceeding the one-shot budget "
            f"of {MAX_RESEARCH_EXECUTIONS}"
        )
    return count
