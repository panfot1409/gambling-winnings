"""Append-only, hash-chained ledger of every research degree of freedom exercised.

``research/m3d/research_multiplicity.jsonl`` records — descriptively, **not** as a
retroactive multiple-testing correction — every distinct axis of researcher choice
already exercised across M2B-M3C: each strategy specification (and its parameter
tuple), cost scenario, risk overlay, data partition, endpoint/statistic, bootstrap
method, decision-criterion set, and experiment id. Its purpose is honesty about
adaptivity: nothing may be deleted or "forgotten", benchmarks are distinguished
from candidates, and repeated use of the same specification is recorded rather
than deceptively collapsed.

The identifier sets are derived from committed artifacts (the specification catalog
and the experiment registries), so a strategy, cost scenario, endpoint, or
completed experiment cannot silently go missing: :func:`verify_research_multiplicity`
rebuilds the ledger and fails on any drift or omission. There is deliberately no
repair or truncation tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3d.candidate_catalog import build_research_specification_catalog
from eth_research.m3d.chain import chained_line_bytes, load_and_verify_chain, render_ledger_bytes
from eth_research.m3d.validation import (
    M3DValidationError,
    domain_sha256,
    require_commit_sha,
    require_mapping,
    require_str,
)

LEDGER_PATH = "research/m3d/research_multiplicity.jsonl"
LEDGER_SCHEMA_VERSION = 1
LEDGER_KIND = "research_multiplicity_ledger"

_DIMENSIONS = (
    "strategy_specification",
    "cost_scenario",
    "risk_overlay",
    "data_partition",
    "endpoint_statistic",
    "bootstrap_method",
    "decision_criterion_set",
    "experiment",
)

# Declared degrees of freedom whose members are not a bare list inside a single
# committed artifact. Each is bound to the milestone that first exercised it; the
# milestone's registration commit supplies ``first_seen_commit``.
_ENDPOINTS = (
    ("m2b", "benchmark_metrics_train_validation", "descriptive"),
    ("m3a", "mean_excess_return_oos", "primary_inferential"),
    ("m3b", "fractional_accounting_metrics", "descriptive_measurement"),
    ("m3c", "mean_daily_paired_log_excess", "primary_inferential"),
    ("m3c", "psr_diagnostic", "descriptive"),
)
_BOOTSTRAP_METHODS = (
    ("m3a", "fold_stratified_moving_block"),
    ("m3c", "fold_stratified_moving_block_seed_20260714"),
)
_DECISION_CRITERIA = (
    ("m3a", "development_comparison_rule"),
    ("m3c", "seven_part_promotion_rule"),
)
_PARTITIONS = (
    ("m2b", "m2b_train"),
    ("m2b", "m2b_validation"),
    ("m3a", "research_train"),
)
_M2B_EXPERIMENT = "m2b-train-validation-benchmark"


def _milestone_commits(repo_root: str | Path) -> dict[str, str]:
    tv = require_mapping(
        "m2b_tv", up.load_json(repo_root, "research/m2b/train_validation_results.json")
    )
    commits = {
        "m2b": require_commit_sha("m2b commit", tv["protocol_registration_commit_sha"]),
    }
    for milestone, path in (
        ("m3a", "research/m3a/experiment_registry.jsonl"),
        ("m3b", "research/m3b/experiment_registry.jsonl"),
        ("m3c", "research/m3c/experiment_registry.jsonl"),
    ):
        for event in up.jsonl_events(repo_root, path):
            mapping = require_mapping("registry event", event)
            commits[milestone] = require_commit_sha(
                "registered_code_commit_sha", mapping["registered_code_commit_sha"]
            )
            break
    return commits


def _entry(
    dimension: str, identity: str, milestone: str, commit: str, role: str | None, status: str
) -> dict[str, Any]:
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "entry_kind": "degree_of_freedom",
        "dimension": dimension,
        "identity": identity,
        "milestone": milestone,
        "first_seen_commit": commit,
        "role": role,
        "status": status,
        "fingerprint": domain_sha256(
            "research_multiplicity_dof", {"dimension": dimension, "identity": identity}
        ),
    }


def _experiments(repo_root: str | Path) -> list[tuple[str, str, str, str]]:
    """``(milestone, experiment_id, commit, status)`` for every registered experiment."""
    out: list[tuple[str, str, str, str]] = []
    for milestone, path in (
        ("m3a", "research/m3a/experiment_registry.jsonl"),
        ("m3b", "research/m3b/experiment_registry.jsonl"),
        ("m3c", "research/m3c/experiment_registry.jsonl"),
    ):
        first_commit: dict[str, str] = {}
        final_status: dict[str, str] = {}
        for event in up.jsonl_events(repo_root, path):
            mapping = require_mapping("registry event", event)
            experiment_id = require_str("experiment_id", mapping["experiment_id"])
            first_commit.setdefault(
                experiment_id,
                require_commit_sha(
                    "registered_code_commit_sha", mapping["registered_code_commit_sha"]
                ),
            )
            if mapping.get("event") == "completed":
                status = mapping.get("promotion_status")
                final_status[experiment_id] = (
                    require_str("promotion_status", status) if status else "completed"
                )
        for experiment_id in first_commit:
            out.append(
                (
                    milestone,
                    experiment_id,
                    first_commit[experiment_id],
                    final_status.get(experiment_id, "registered"),
                )
            )
    return out


def _build_records(repo_root: str | Path) -> list[dict[str, Any]]:
    from eth_research.m3d import M3D_PACKAGE_VERSION

    commits = _milestone_commits(repo_root)
    catalog = build_research_specification_catalog(repo_root).document

    genesis = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "entry_kind": "genesis",
        "package_version": M3D_PACKAGE_VERSION,
        "note": "descriptive honesty about adaptivity; not a multiple-testing correction",
    }

    entries: list[dict[str, Any]] = []

    for strategy in catalog["strategies"]:
        entries.append(
            _entry(
                "strategy_specification",
                strategy["identifier"],
                strategy["first_seen_milestone"],
                strategy["first_seen_commit"],
                strategy["role"],
                strategy["status"],
            )
        )
    for scenario in catalog["cost_scenarios"]:
        milestone = scenario["milestones"][0]
        entries.append(
            _entry(
                "cost_scenario",
                scenario["identifier"],
                milestone,
                commits[milestone],
                None,
                "exercised",
            )
        )
    for overlay in catalog["risk_overlays"]:
        entries.append(
            _entry("risk_overlay", overlay["identifier"], "m3b", commits["m3b"], None, "exercised")
        )
    breaker = catalog["drawdown_breaker"]
    entries.append(
        _entry(
            "risk_overlay",
            "drawdown_breaker",
            breaker["milestone"],
            commits[breaker["milestone"]],
            None,
            breaker["state"],
        )
    )
    for milestone, identity in _PARTITIONS:
        entries.append(
            _entry("data_partition", identity, milestone, commits[milestone], None, "exercised")
        )
    for milestone, identity, kind in _ENDPOINTS:
        entries.append(
            _entry("endpoint_statistic", identity, milestone, commits[milestone], None, kind)
        )
    for milestone, identity in _BOOTSTRAP_METHODS:
        entries.append(
            _entry("bootstrap_method", identity, milestone, commits[milestone], None, "exercised")
        )
    for milestone, identity in _DECISION_CRITERIA:
        entries.append(
            _entry(
                "decision_criterion_set", identity, milestone, commits[milestone], None, "exercised"
            )
        )
    entries.append(_entry("experiment", _M2B_EXPERIMENT, "m2b", commits["m2b"], None, "completed"))
    for milestone, experiment_id, commit, status in _experiments(repo_root):
        entries.append(_entry("experiment", experiment_id, milestone, commit, None, status))

    entries.sort(key=lambda e: (e["dimension"], e["identity"]))
    _reject_duplicate_identities(entries)
    return [genesis, *entries]


def _reject_duplicate_identities(entries: list[dict[str, Any]]) -> None:
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry["dimension"], entry["identity"])
        if key in seen:
            raise M3DValidationError(f"duplicate multiplicity identity {key}")
        seen.add(key)


def build_multiplicity_ledger_bytes(repo_root: str | Path) -> bytes:
    """Deterministically render the full multiplicity ledger file bytes."""
    return render_ledger_bytes(chained_line_bytes(_build_records(repo_root)))


def verify_research_multiplicity(repo_root: str | Path) -> list[dict[str, Any]]:
    """Verify the committed multiplicity ledger reproduces and omits nothing.

    Fails if the committed ledger is not a byte-for-byte rebuild, if its hash chain
    is broken, if a duplicate identity appears, or if any catalogued strategy, cost
    scenario, endpoint, or registered experiment is missing from it.
    """
    _raw, records = load_and_verify_chain(repo_root, LEDGER_PATH)

    genesis = records[0]
    if genesis.get("entry_kind") != "genesis" or genesis.get("kind") != LEDGER_KIND:
        raise M3DValidationError("multiplicity ledger is missing its genesis sentinel")
    entries = records[1:]
    for entry in entries:
        if entry.get("dimension") not in _DIMENSIONS:
            raise M3DValidationError(f"unknown multiplicity dimension {entry.get('dimension')!r}")

    present: dict[str, set[str]] = {}
    for entry in entries:
        present.setdefault(entry["dimension"], set()).add(entry["identity"])

    # Anti-orphan presence checks first, so an omission reports the specific
    # missing historical fact rather than a generic byte mismatch.
    catalog = build_research_specification_catalog(repo_root).document
    _require_covers(
        "strategy_specification",
        present.get("strategy_specification", set()),
        {s["identifier"] for s in catalog["strategies"]},
    )
    _require_covers(
        "cost_scenario",
        present.get("cost_scenario", set()),
        {c["identifier"] for c in catalog["cost_scenarios"]},
    )
    _require_covers(
        "endpoint_statistic",
        present.get("endpoint_statistic", set()),
        {identity for _, identity, _ in _ENDPOINTS},
    )
    registered = {experiment_id for _, experiment_id, _, _ in _experiments(repo_root)}
    _require_covers("experiment", present.get("experiment", set()), registered)

    # Then the strongest guard: the committed ledger must be an exact rebuild.
    if _raw != build_multiplicity_ledger_bytes(repo_root):
        raise M3DValidationError("committed multiplicity ledger does not match the rebuilt ledger")
    return records


def _require_covers(dimension: str, present: set[str], required: set[str]) -> None:
    if missing := required - present:
        raise M3DValidationError(
            f"multiplicity ledger is missing {dimension} entries: {sorted(missing)}"
        )
