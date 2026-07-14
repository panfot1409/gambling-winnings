"""Prove run-003's financial cells are bit-identical to run-002's (Section 16).

run-003 corrects only bootstrap fold-seam handling, result provenance, and
publication governance; the financial evaluation — data, strategies, parameters,
transaction costs, folds, and accounting — is unchanged from run-002. This
verifier loads the archived run-002 (schema v1) and run-003 (schema v2)
development results and proves that every one of the 60 fold cells, 12
independent-fold summaries, 12 pooled-reset diagnostics, and 12 full-train
exploratory cells is exactly equal, along with the data fingerprints and the
strategy/cost universe. Only identity, provenance, results-schema, and bootstrap
fields may differ. Any financial mismatch raises :class:`FinancialEquivalenceError`
— a hard stop; run-003 must never be "fixed" to match after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research._json import strict_json_loads

# The four financial result sections and the identity keys that address each cell.
_SECTIONS: dict[str, tuple[str, ...]] = {
    "fold_results": ("strategy", "cost_scenario", "fold_index"),
    "independent_fold_summaries": ("strategy", "cost_scenario"),
    "pooled_reset_oos": ("strategy", "cost_scenario"),
    "full_train_exploratory": ("strategy", "cost_scenario"),
}

# Top-level fields that pin the same data and universe (bit-identical across runs).
_SHARED_TOP_LEVEL: tuple[str, ...] = (
    "strategies",
    "cost_scenarios",
    "development_partition_sha256",
    "dataset_content_fingerprint",
    "research_train_content_fingerprint",
    "frozen_m2_dossier_sha256",
    "development_gate_event_count",
    "final_holdout_event_count",
)


class FinancialEquivalenceError(RuntimeError):
    """A financial value differs between run-002 and run-003 — a hard stop."""


@dataclass(frozen=True)
class EquivalenceSummary:
    """The counts proven equal, for the audit record."""

    fold_cells: int
    independent_fold_summaries: int
    pooled_reset_oos: int
    full_train_exploratory: int


def _load(path: str | Path) -> dict[str, Any]:
    payload = strict_json_loads(Path(path).read_bytes())
    if not isinstance(payload, dict):
        raise FinancialEquivalenceError(f"{path} is not a JSON object")
    return payload


def _index(section: str, rows: object) -> dict[tuple[Any, ...], dict[str, Any]]:
    if not isinstance(rows, list):
        raise FinancialEquivalenceError(f"section {section!r} is not a list")
    keys = _SECTIONS[section]
    indexed: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise FinancialEquivalenceError(f"section {section!r} has a non-object cell")
        identity = tuple(row.get(k) for k in keys)
        if identity in indexed:
            raise FinancialEquivalenceError(f"section {section!r} has a duplicate cell {identity}")
        indexed[identity] = row
    return indexed


def _compare_section(section: str, run002: dict[str, Any], run003: dict[str, Any]) -> int:
    left = _index(section, run002.get(section))
    right = _index(section, run003.get(section))
    if set(left) != set(right):
        only_002 = sorted(map(str, set(left) - set(right)))
        only_003 = sorted(map(str, set(right) - set(left)))
        raise FinancialEquivalenceError(
            f"section {section!r} cell sets differ: "
            f"only run-002={only_002}, only run-003={only_003}"
        )
    for identity, left_cell in left.items():
        right_cell = right[identity]
        if left_cell.keys() != right_cell.keys():
            raise FinancialEquivalenceError(
                f"section {section!r} cell {identity} has different fields: "
                f"{sorted(left_cell.keys() ^ right_cell.keys())}"
            )
        for field, value in left_cell.items():
            if right_cell[field] != value or type(right_cell[field]) is not type(value):
                raise FinancialEquivalenceError(
                    f"section {section!r} cell {identity} field {field!r} differs: "
                    f"run-002={value!r} run-003={right_cell[field]!r}"
                )
    return len(left)


def assert_financial_equivalence(
    run002_results_path: str | Path, run003_results_path: str | Path
) -> EquivalenceSummary:
    """Prove run-003's financial cells equal run-002's, or raise.

    Compares the four financial sections cell-by-cell and the data/universe
    fingerprints. Ignores identity, provenance, results-schema, and bootstrap
    fields (which run-003 is expected to change). Returns the counts proven
    equal on success.
    """
    run002 = _load(run002_results_path)
    run003 = _load(run003_results_path)

    for field in _SHARED_TOP_LEVEL:
        if field not in run002 or field not in run003:
            raise FinancialEquivalenceError(f"both results must carry {field!r}")
        if run002[field] != run003[field]:
            raise FinancialEquivalenceError(
                f"data/universe field {field!r} differs: "
                f"run-002={run002[field]!r} run-003={run003[field]!r}"
            )

    counts = {section: _compare_section(section, run002, run003) for section in _SECTIONS}
    if counts["fold_results"] != 60:
        raise FinancialEquivalenceError(
            f"expected 60 fold cells, compared {counts['fold_results']}"
        )
    for section in ("independent_fold_summaries", "pooled_reset_oos", "full_train_exploratory"):
        if counts[section] != 12:
            raise FinancialEquivalenceError(f"expected 12 {section}, compared {counts[section]}")
    return EquivalenceSummary(
        fold_cells=counts["fold_results"],
        independent_fold_summaries=counts["independent_fold_summaries"],
        pooled_reset_oos=counts["pooled_reset_oos"],
        full_train_exploratory=counts["full_train_exploratory"],
    )
