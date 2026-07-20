"""Independent cumulative research-family enumeration and catalog reconciliation audit.

This module RE-DERIVES, from the primary committed registries and result artifacts (never by
trusting ``research/v2b/research_family_catalog.json`` as the sole source), the complete set of
strategy families the project has evaluated, classifies each with a conservative governance
taxonomy, and reconciles the independent enumeration against the committed catalog and the
frozen multiplicity state. It confirms the cumulative candidate-family count reconciles to ten
(eight historical families, of which three are V2A, plus the two V2B cross-asset families) and that
no benchmark, sensitivity neighbor, compatibility oracle, or synthetic test strategy has inflated
that count, and that no evaluated primary family has been omitted.

Enumeration sources (primary, not the catalog):

* ``research/m3a/experiment_registry.jsonl`` -- the fixed-baseline strategy grid.
* ``research/m3b/experiment_registry.jsonl`` -- the fractional execution-risk strategy grid.
* ``research/m3c/experiment_registry.jsonl`` -- the dual-horizon grid plus its declared candidate.
* ``research/v2a/results.json`` -- the three pre-registered ETH candidate ids.
* ``research/v2b/v2b_results.json`` -- the two pre-registered cross-asset candidate ids.

Unavoidable limit, stated plainly: semantic identity CANNOT prove that two arbitrary programs are
equivalent -- program equivalence is undecidable in general. The anti-relabel control here is a
*conservative governance classifier* over a fixed, cosmetic-free semantic identity (reused from
:mod:`eth_research.v2b.research_memory`): it folds known aliases, structural overlay relocations,
and value-only parameter shifts back onto a canonical fingerprint, so a rejected family cannot be
resurrected by renaming, wrapping, moving logic, reserializing, shifting a horizon, relocating a
risk overlay between signal and engine, changing an experiment id or package version, rewriting
benchmark prose, or rescaling output while preserving decisions. It is fail-closed and may refuse a
novel family that happens to collide; it is not, and never claims to be, formal program equivalence
checking.

Read-only and result-neutral: nothing here evaluates a candidate, reads a sealed partition, or
mutates any accepted artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.v2.strict import (
    V2ValidationError,
    load_canonical_json,
    require_int,
    require_mapping,
    require_nonempty_str,
    strict_json_loads,
)
from eth_research.v2b import research_memory as rm

# --------------------------------------------------------------------------- #
# committed evidence relpaths (primary sources + reconciliation targets)       #
# --------------------------------------------------------------------------- #
M3A_REGISTRY_RELPATH: str = "research/m3a/experiment_registry.jsonl"
M3B_REGISTRY_RELPATH: str = "research/m3b/experiment_registry.jsonl"
M3C_REGISTRY_RELPATH: str = "research/m3c/experiment_registry.jsonl"
V2A_RESULTS_RELPATH: str = "research/v2a/results.json"
V2B_RESULTS_RELPATH: str = "research/v2b/v2b_results.json"
FAMILY_CATALOG_RELPATH: str = "research/v2b/research_family_catalog.json"
MULTIPLICITY_STATE_RELPATH: str = "research/v2b/research_multiplicity_state.json"

#: The governance taxonomy. Only ``candidate_family`` counts against the cumulative alpha budget;
#: other categories exist so the classifier can keep them OUT of the count (anti-inflation) and so a
#: rejected candidate cannot be relabeled into one of them.
FAMILY_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        "candidate_family",
        "benchmark",
        "risk_only_diagnostic",
        "sensitivity_neighbor",
        "compatibility_oracle",
        "synthetic_test_strategy",
    }
)

_HISTORICAL_MILESTONES: frozenset[str] = frozenset({"m3a", "m3b", "m3c", "v2a"})


class CatalogAuditError(V2ValidationError):
    """The independent enumeration failed or an evidence artifact was malformed."""


# --------------------------------------------------------------------------- #
# the conservative label -> family governance classifier                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _LabelSpec:
    """How a raw strategy/candidate label maps to a canonical family and its classification."""

    family_id: str
    classification: str
    signal_family: str
    role: str
    milestone: str


# Every raw strategy/candidate label that appears in the primary sources maps here. An unknown label
# fails closed in :func:`enumerate_historical_families` (it must be classified before it can count
# or be excluded); a silent pass-through is never allowed.
STRATEGY_CLASSIFIER: dict[str, _LabelSpec] = {
    "cash": _LabelSpec("cash_benchmark", "benchmark", "cash_hold", "benchmark", "m3a"),
    "buy_and_hold": _LabelSpec(
        "passive_eth_buy_and_hold_benchmark", "benchmark", "passive_hold", "benchmark", "m3a"
    ),
    "sma_20_50": _LabelSpec(
        "m3a_sma_crossover",
        "candidate_family",
        "moving_average_crossover",
        "exploratory_fixed_rule",
        "m3a",
    ),
    "donchian_55_20": _LabelSpec(
        "m3a_donchian_breakout",
        "candidate_family",
        "donchian_breakout",
        "exploratory_fixed_rule",
        "m3a",
    ),
    "vol_target_buy_and_hold_30d_50pct": _LabelSpec(
        "m3b_vol_target_buy_and_hold_30d_50pct",
        "candidate_family",
        "passive_hold",
        "candidate",
        "m3b",
    ),
    "vol_target_donchian_55_20_30d_50pct": _LabelSpec(
        "m3b_vol_target_donchian_55_20_30d_50pct",
        "candidate_family",
        "donchian_breakout",
        "candidate",
        "m3b",
    ),
    "dual_horizon_trend_63_252_vol_target_30d_50pct": _LabelSpec(
        "m3c_dual_horizon_trend_63_252_vol_target_30d_50pct",
        "candidate_family",
        "dual_horizon_trend",
        "candidate",
        "m3c",
    ),
    "meanrev_zscore_accumulation": _LabelSpec(
        "v2a_meanrev_zscore_accumulation",
        "candidate_family",
        "mean_reversion_zscore",
        "candidate",
        "v2a",
    ),
    "trend_regime_single_horizon": _LabelSpec(
        "v2a_trend_regime_single_horizon",
        "candidate_family",
        "single_horizon_sma_gate",
        "candidate",
        "v2a",
    ),
    "vol_scaled_hold_drawdown_guard": _LabelSpec(
        "v2a_vol_scaled_hold_drawdown_guard",
        "candidate_family",
        "passive_hold",
        "candidate",
        "v2a",
    ),
    "cross_asset_btc_confirmed_eth_trend": _LabelSpec(
        "v2b_cross_asset_btc_confirmed_eth_trend",
        "candidate_family",
        "cross_asset_trend_confirmation",
        "candidate",
        "v2b",
    ),
    "cross_asset_eth_btc_relative_strength_rotation": _LabelSpec(
        "v2b_cross_asset_eth_btc_relative_strength_rotation",
        "candidate_family",
        "cross_sectional_relative_strength",
        "candidate",
        "v2b",
    ),
}

#: The families the audit REQUIRES to be present among the enumerated candidates (the milestone's
#: explicit acceptance list plus the two V2B candidates). Missing any is a reconciliation failure.
REQUIRED_CANDIDATE_FAMILY_IDS: frozenset[str] = frozenset(
    {
        "m3a_sma_crossover",
        "m3a_donchian_breakout",
        "m3b_vol_target_buy_and_hold_30d_50pct",
        "v2a_vol_scaled_hold_drawdown_guard",
        "m3c_dual_horizon_trend_63_252_vol_target_30d_50pct",
        "v2a_meanrev_zscore_accumulation",
        "v2a_trend_regime_single_horizon",
        "v2b_cross_asset_btc_confirmed_eth_trend",
        "v2b_cross_asset_eth_btc_relative_strength_rotation",
    }
)


@dataclass(frozen=True, slots=True)
class FamilyRecord:
    """One independently enumerated family: its canonical id, classification, and provenance."""

    family_id: str
    classification: str
    signal_family: str
    role: str
    milestone: str
    source_labels: tuple[str, ...]

    @property
    def counts_against_budget(self) -> bool:
        """Only a candidate family counts against the cumulative alpha/family budget."""
        return self.classification == "candidate_family"

    def to_canonical(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "classification": self.classification,
            "signal_family": self.signal_family,
            "role": self.role,
            "milestone": self.milestone,
            "source_labels": list(self.source_labels),
            "counts_against_budget": self.counts_against_budget,
        }


# --------------------------------------------------------------------------- #
# primary-source readers                                                       #
# --------------------------------------------------------------------------- #
def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if raw == b"":
        return []
    records: list[dict[str, Any]] = []
    for index, line in enumerate(raw.rstrip(b"\n").split(b"\n")):
        if line == b"":
            raise CatalogAuditError(f"{path}: blank line at {index}")
        records.append(require_mapping(f"{path}[{index}]", strict_json_loads(line)))
    return records


def _labels_from_registry(root: Path, relpath: str) -> set[str]:
    labels: set[str] = set()
    for record in _read_jsonl(root / relpath):
        strategies = record.get("strategies")
        if isinstance(strategies, list):
            for item in strategies:
                labels.add(require_nonempty_str(f"{relpath}.strategies", item))
        candidate_id = record.get("candidate_id")
        if isinstance(candidate_id, str):
            labels.add(require_nonempty_str(f"{relpath}.candidate_id", candidate_id))
    return labels


def _labels_from_v2a(root: Path) -> set[str]:
    obj = require_mapping("v2a_results", load_canonical_json(root / V2A_RESULTS_RELPATH))
    decision = require_mapping("v2a_results.decision", obj["decision"])
    outcomes = decision["outcomes"]
    if not isinstance(outcomes, list):
        raise CatalogAuditError("v2a_results.decision.outcomes must be a list")
    labels: set[str] = set()
    for i, outcome in enumerate(outcomes):
        row = require_mapping(f"v2a_results.decision.outcomes[{i}]", outcome)
        labels.add(require_nonempty_str("v2a candidate_id", row["candidate_id"]))
    return labels


def _labels_from_v2b(root: Path) -> set[str]:
    obj = require_mapping("v2b_results", load_canonical_json(root / V2B_RESULTS_RELPATH))
    result = require_mapping("v2b_results.result", obj["result"])
    candidates = result["candidates"]
    if not isinstance(candidates, list):
        raise CatalogAuditError("v2b_results.result.candidates must be a list")
    labels: set[str] = set()
    for i, candidate in enumerate(candidates):
        row = require_mapping(f"v2b_results.result.candidates[{i}]", candidate)
        evaluation = require_mapping(f"v2b candidate[{i}].evaluation", row["evaluation"])
        labels.add(require_nonempty_str("v2b candidate_id", evaluation["candidate_id"]))
    return labels


# --------------------------------------------------------------------------- #
# independent enumeration                                                      #
# --------------------------------------------------------------------------- #
def observed_strategy_labels(repo_root: str | Path) -> frozenset[str]:
    """Every distinct raw strategy/candidate label found across the primary sources."""
    root = Path(repo_root)
    labels: set[str] = set()
    for relpath in (M3A_REGISTRY_RELPATH, M3B_REGISTRY_RELPATH, M3C_REGISTRY_RELPATH):
        labels |= _labels_from_registry(root, relpath)
    labels |= _labels_from_v2a(root)
    labels |= _labels_from_v2b(root)
    return frozenset(labels)


def enumerate_historical_families(repo_root: str | Path) -> list[FamilyRecord]:
    """Independently enumerate + classify every family evaluated across the committed milestones.

    Reads the primary registries and results (not the catalog), maps each observed label through the
    conservative governance classifier, and collapses reused labels to one record per canonical
    family. An unclassifiable label fails closed.
    """
    labels = observed_strategy_labels(repo_root)
    by_family: dict[str, tuple[_LabelSpec, set[str]]] = {}
    for label in sorted(labels):
        spec = STRATEGY_CLASSIFIER.get(label)
        if spec is None:
            raise CatalogAuditError(
                f"strategy label {label!r} is not classified; it must be declared in the "
                f"governance classifier before it can count or be excluded (fail-closed)"
            )
        if spec.classification not in FAMILY_CLASSIFICATIONS:
            raise CatalogAuditError(
                f"label {label!r} has unknown classification {spec.classification!r}"
            )
        _, seen = by_family.setdefault(spec.family_id, (spec, set()))
        seen.add(label)
    records = [
        FamilyRecord(
            family_id=spec.family_id,
            classification=spec.classification,
            signal_family=spec.signal_family,
            role=spec.role,
            milestone=spec.milestone,
            source_labels=tuple(sorted(seen)),
        )
        for spec, seen in by_family.values()
    ]
    return sorted(records, key=lambda r: r.family_id)


def reconcile_cumulative_count(repo_root: str | Path) -> dict[str, int]:
    """Return the reconciled cumulative counts derived from the independent enumeration."""
    records = enumerate_historical_families(repo_root)
    candidates = [r for r in records if r.classification == "candidate_family"]
    historical = [r for r in candidates if r.milestone in _HISTORICAL_MILESTONES]
    return {
        "candidate_families": len(candidates),
        "historical_candidate_families": len(historical),
        "v2a_candidate_families": len([r for r in candidates if r.milestone == "v2a"]),
        "v2b_candidate_families": len([r for r in candidates if r.milestone == "v2b"]),
        "benchmark_families": len([r for r in records if r.classification == "benchmark"]),
    }


# --------------------------------------------------------------------------- #
# reconciliation against the committed catalog + multiplicity state            #
# --------------------------------------------------------------------------- #
def _reconcile_committed_catalog(
    root: Path, historical: list[FamilyRecord], benchmarks: list[FamilyRecord]
) -> list[str]:
    problems: list[str] = []
    try:
        obj = require_mapping("family_catalog", load_canonical_json(root / FAMILY_CATALOG_RELPATH))
        families = obj["families"]
        if not isinstance(families, list):
            raise CatalogAuditError("family_catalog.families must be a list")
        committed_candidate: set[str] = set()
        committed_benchmark: set[str] = set()
        for i, family in enumerate(families):
            row = require_mapping(f"family_catalog.families[{i}]", family)
            fid = require_nonempty_str("family_id", row["family_id"])
            role = require_nonempty_str("role", row["role"])
            (committed_benchmark if role == "benchmark" else committed_candidate).add(fid)
        catalog_candidate_count = require_int(
            "candidate_family_count", obj["candidate_family_count"]
        )
        catalog_family_count = require_int("family_count", obj["family_count"])
    except ValueError as exc:
        return [f"committed catalog is unreadable: {exc}"]

    if committed_candidate != {r.family_id for r in historical}:
        problems.append(
            "committed catalog candidate families do not match the independent historical "
            f"enumeration (catalog={sorted(committed_candidate)})"
        )
    if committed_benchmark != {r.family_id for r in benchmarks}:
        problems.append("committed catalog benchmark families do not match the enumeration")
    if catalog_candidate_count != len(historical):
        problems.append(
            f"catalog candidate_family_count={catalog_candidate_count} != enumerated "
            f"historical {len(historical)}"
        )
    if catalog_family_count != len(historical) + len(benchmarks):
        problems.append(
            f"catalog family_count={catalog_family_count} != enumerated historical+benchmark "
            f"{len(historical) + len(benchmarks)}"
        )
    return problems


def _reconcile_multiplicity(
    root: Path, historical: list[FamilyRecord], v2a: list[FamilyRecord], v2b: list[FamilyRecord]
) -> list[str]:
    problems: list[str] = []
    try:
        obj = require_mapping(
            "multiplicity_state", load_canonical_json(root / MULTIPLICITY_STATE_RELPATH)
        )
        historical_count = require_int("historical_family_count", obj["historical_family_count"])
        v2a_count = require_int("v2a_family_count", obj["v2a_family_count"])
        v2b_max = require_int("v2b_max_family_count", obj["v2b_max_family_count"])
        total = require_int("total_family_count", obj["total_family_count"])
    except ValueError as exc:
        return [f"committed multiplicity state is unreadable: {exc}"]

    if historical_count != len(historical):
        problems.append(
            f"multiplicity historical_family_count={historical_count} != {len(historical)}"
        )
    if v2a_count != len(v2a):
        problems.append(f"multiplicity v2a_family_count={v2a_count} != enumerated {len(v2a)}")
    if len(v2b) > v2b_max:
        problems.append(f"enumerated V2B candidates {len(v2b)} exceed the frozen max {v2b_max}")
    if total != historical_count + v2b_max:
        problems.append(
            f"multiplicity total_family_count={total} != historical+v2b_max "
            f"{historical_count + v2b_max}"
        )
    if total != 10:
        problems.append(f"cumulative total_family_count={total} does not reconcile to 10")
    return problems


def verify_family_catalog(repo_root: str | Path) -> list[str]:
    """Compare the independent enumeration to the committed catalog and reconcile the counts.

    Empty return means: 8 historical candidate families (3 of them V2A) plus 2 V2B candidates equals
    10, benchmarks are 2 and excluded from the count, every required family is present, and nothing
    (benchmark, sensitivity neighbor, compatibility oracle, or synthetic strategy) has inflated it.
    """
    root = Path(repo_root)
    problems: list[str] = []
    try:
        records = enumerate_historical_families(root)
    except ValueError as exc:
        return [f"independent enumeration failed: {exc}"]

    candidates = [r for r in records if r.classification == "candidate_family"]
    benchmarks = [r for r in records if r.classification == "benchmark"]
    historical = [r for r in candidates if r.milestone in _HISTORICAL_MILESTONES]
    v2a = [r for r in candidates if r.milestone == "v2a"]
    v2b = [r for r in candidates if r.milestone == "v2b"]

    if len(candidates) != 10:
        problems.append(f"enumerated candidate families = {len(candidates)}, expected 10")
    if len(historical) != 8:
        problems.append(f"enumerated historical candidate families = {len(historical)}, expected 8")
    if len(v2a) != 3:
        problems.append(f"enumerated V2A candidate families = {len(v2a)}, expected 3")
    if len(v2b) != 2:
        problems.append(f"enumerated V2B candidate families = {len(v2b)}, expected 2")
    if len(benchmarks) != 2:
        problems.append(f"enumerated benchmark families = {len(benchmarks)}, expected 2")

    missing = REQUIRED_CANDIDATE_FAMILY_IDS - {r.family_id for r in candidates}
    if missing:
        problems.append(f"required evaluated families are omitted: {sorted(missing)}")

    for record in records:
        expected = record.classification == "candidate_family"
        if record.counts_against_budget != expected:
            problems.append(f"family {record.family_id!r} mis-counted against the budget")
        if record.classification == "candidate_family" and record.milestone not in rm.MILESTONES:
            problems.append(
                f"family {record.family_id!r} has unknown milestone {record.milestone!r}"
            )

    problems += _reconcile_committed_catalog(root, historical, benchmarks)
    problems += _reconcile_multiplicity(root, historical, v2a, v2b)
    return problems


# --------------------------------------------------------------------------- #
# anti-relabel governance control (conservative, fail-closed)                  #
# --------------------------------------------------------------------------- #
def semantic_family_fingerprint(identity: rm.ResearchFamilyIdentity) -> str:
    """The cosmetic-free, value-free, alias-normalized semantic fingerprint of a declared family."""
    return rm.normalize_declared_family(identity).fingerprint()


def is_relabel_of_evaluated_family(identity: rm.ResearchFamilyIdentity) -> bool:
    """True iff the declared family (after normalization) collides with an already-evaluated family.

    This is the conservative governance test used to refuse resurrecting a rejected family under a
    cosmetic disguise. It reuses the shared semantic identity; it does NOT attempt program
    equivalence.
    """
    try:
        rm.assert_family_is_new(identity)
    except rm.ResearchMemoryError:
        return True
    return False


def assert_not_resurrected_by_relabel(identity: rm.ResearchFamilyIdentity) -> None:
    """Fail closed if a declared family relabels any already-evaluated (cataloged) family."""
    if is_relabel_of_evaluated_family(identity):
        raise CatalogAuditError(
            f"declared family relabels an already-evaluated family "
            f"(semantic fingerprint {semantic_family_fingerprint(identity)[:12]}); it is not new"
        )


def main(argv: list[str] | None = None) -> int:
    """CLI: audit the cumulative family catalog against the independent enumeration."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--check", action="store_true", help="Verify (default action).")
    args = parser.parse_args(argv)
    _ = args.check
    problems = verify_family_catalog(args.repo_root)
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "FAMILY_CLASSIFICATIONS",
    "REQUIRED_CANDIDATE_FAMILY_IDS",
    "STRATEGY_CLASSIFIER",
    "CatalogAuditError",
    "FamilyRecord",
    "assert_not_resurrected_by_relabel",
    "enumerate_historical_families",
    "is_relabel_of_evaluated_family",
    "observed_strategy_labels",
    "reconcile_cumulative_count",
    "semantic_family_fingerprint",
    "verify_family_catalog",
]
