"""Complete, drift-proof catalog of every research specification exposed M2B-M3C.

``ResearchSpecificationCatalog`` records every strategy specification, cost
scenario, risk overlay, and drawdown-breaker state the researchers ever saw, so
hidden multiplicity and "forgotten" failed ideas cannot hide. The strategy
identifier set is **discovered** by scanning committed protocols/results/registries
(never a hand-written list): an anti-orphan invariant requires every discovered
identifier to appear exactly once, and the reverse invariant forbids any catalog
entry that does not appear in the bound artifacts. The governance classification
(role, promotion eligibility, may-evaluate-again) is a declared policy table that
must key exactly onto the discovered identifier set.

Cash and buy-and-hold are benchmarks and are never labeled alpha candidates. The
one M3C candidate is recorded ``role=candidate, status=rejected,
promotion_eligible=false, may_evaluate_again=false``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_json_bytes,
    canonical_sha256,
    domain_sha256,
    load_canonical_json_bytes,
    require_bool,
    require_commit_sha,
    require_exact,
    require_mapping,
    require_nonnegative_int,
    require_sha256_hex,
    require_str,
    require_string_sequence,
)

CATALOG_PATH = "research/m3d/research_specification_catalog.json"
CATALOG_SCHEMA_VERSION = 1
CATALOG_KIND = "research_specification_catalog"

_ROLES = ("benchmark", "exploratory_fixed_rule", "measurement_instrument", "candidate")
_MILESTONE_ORDER = ("m2b", "m3a", "m3b", "m3c")

# Declared governance classification, keyed by strategy identifier. The build step
# asserts these keys are exactly the identifiers discovered in committed artifacts
# (anti-orphan both directions). ``may_evaluate_again`` means "eligible for a
# future authorized evaluation on a NEW dataset under a new milestone" — it never
# re-opens the exhausted research-train partition (see research_train_exhaustion).
_CLASSIFICATION: dict[str, dict[str, Any]] = {
    "cash": {
        "role": "benchmark",
        "parameters": {},
        "status": "active_benchmark",
        "promotion_eligible": False,
        "rejection_reason": None,
        "parameter_selected_after_results": False,
        "may_evaluate_again": True,
    },
    "buy_and_hold": {
        "role": "benchmark",
        "parameters": {},
        "status": "active_benchmark",
        "promotion_eligible": False,
        "rejection_reason": None,
        "parameter_selected_after_results": False,
        "may_evaluate_again": True,
    },
    "moving_average_crossover": {
        "role": "exploratory_fixed_rule",
        "parameters": {"fast_window": 20, "slow_window": 50},
        "status": "exploratory_completed",
        "promotion_eligible": False,
        "rejection_reason": None,
        "parameter_selected_after_results": False,
        "may_evaluate_again": True,
    },
    "sma_20_50": {
        "role": "exploratory_fixed_rule",
        "parameters": {"fast_window": 20, "slow_window": 50},
        "status": "exploratory_completed",
        "promotion_eligible": False,
        "rejection_reason": None,
        "parameter_selected_after_results": False,
        "may_evaluate_again": True,
    },
    "donchian_55_20": {
        "role": "exploratory_fixed_rule",
        "parameters": {"entry_channel": 55, "exit_channel": 20},
        "status": "exploratory_completed",
        "promotion_eligible": False,
        "rejection_reason": None,
        "parameter_selected_after_results": False,
        "may_evaluate_again": True,
    },
    "vol_target_buy_and_hold_30d_50pct": {
        "role": "measurement_instrument",
        "parameters": {
            "base": "buy_and_hold",
            "volatility_lookback_days": 30,
            "annual_volatility_target": 0.5,
        },
        "status": "measurement_completed",
        "promotion_eligible": False,
        "rejection_reason": None,
        "parameter_selected_after_results": False,
        "may_evaluate_again": True,
    },
    "vol_target_donchian_55_20_30d_50pct": {
        "role": "measurement_instrument",
        "parameters": {
            "base": "donchian_55_20",
            "volatility_lookback_days": 30,
            "annual_volatility_target": 0.5,
        },
        "status": "measurement_completed",
        "promotion_eligible": False,
        "rejection_reason": None,
        "parameter_selected_after_results": False,
        "may_evaluate_again": True,
    },
    "dual_horizon_trend_63_252_vol_target_30d_50pct": {
        "role": "candidate",
        "parameters": {
            "fast_horizon_days": 63,
            "slow_horizon_days": 252,
            "volatility_lookback_days": 30,
            "annual_volatility_target": 0.5,
        },
        # Adaptively motivated in FORM by prior trend results, but no parameter was
        # changed after observing any number; mechanically rejected and final.
        "status": up.M3C_REJECTED_OUTCOME,
        "promotion_eligible": False,
        "rejection_reason": up.M3C_REJECTED_OUTCOME,
        "parameter_selected_after_results": False,
        "may_evaluate_again": False,
    },
}

_ENTRY_KEYS = {
    "identifier",
    "role",
    "first_seen_milestone",
    "first_seen_commit",
    "parameters",
    "specification_fingerprint",
    "partitions_exposed",
    "completed_experiment_count",
    "status",
    "promotion_eligible",
    "rejection_reason",
    "parameter_selected_after_results",
    "may_evaluate_again",
}


def _require_exact_keys(label: str, mapping: dict[str, Any], keys: set[str]) -> None:
    present = set(mapping)
    if missing := keys - present:
        raise M3DValidationError(f"{label} missing keys: {sorted(missing)}")
    if unknown := present - keys:
        raise M3DValidationError(f"{label} has unknown keys: {sorted(unknown)}")


def _strategy_names(value: object) -> list[str]:
    """Strategy identifiers from a ``strategies`` array of strings or ``{name}`` dicts."""
    names: list[str] = []
    if not isinstance(value, list):
        return names
    for item in value:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return names


def _discover(repo_root: str | Path) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Discover ``{identifier: {milestones}}`` and completed-experiment counts.

    Scans committed protocols/results/registries only. Completed count sums the
    distinct completed experiments (M3A/M3B/M3C) that included the identifier plus
    the single M2B train/validation evaluation for M2B strategies.
    """
    milestones: dict[str, set[str]] = {}
    completed: dict[str, int] = {}

    def note(identifier: str, milestone: str) -> None:
        milestones.setdefault(identifier, set()).add(milestone)
        completed.setdefault(identifier, 0)

    # M2B: protocol strategies (one train/validation evaluation each).
    m2b_protocol = up.load_json(repo_root, "research/m2b/protocol.json")
    for name in _strategy_names(require_mapping("m2b_protocol", m2b_protocol).get("strategies")):
        note(name, "m2b")
        completed[name] = completed.get(name, 0) + 1

    # M3A/M3B/M3C: registry completed events + results manifests.
    registry_specs = {
        "m3a": "research/m3a/experiment_registry.jsonl",
        "m3b": "research/m3b/experiment_registry.jsonl",
        "m3c": "research/m3c/experiment_registry.jsonl",
    }
    result_specs = {
        "m3a": ["research/m3a/development_results.json"],
        "m3b": ["research/m3b/fractional_results.json"],
        "m3c": ["research/m3c/candidate_results.json"],
    }
    for milestone, registry_path in registry_specs.items():
        seen_completed: dict[str, set[str]] = {}
        for event in up.jsonl_events(repo_root, registry_path):
            mapping = require_mapping("registry event", event)
            for name in _strategy_names(mapping.get("strategies")):
                note(name, milestone)
                if mapping.get("event") == "completed":
                    seen_completed.setdefault(name, set()).add(
                        require_str("experiment_id", mapping["experiment_id"])
                    )
        for name, experiments in seen_completed.items():
            completed[name] = completed.get(name, 0) + len(experiments)
        for result_path in result_specs[milestone]:
            for name in _strategy_names(
                require_mapping("results", up.load_json(repo_root, result_path)).get("strategies")
            ):
                note(name, milestone)

    return milestones, completed


def _first_seen_milestone(milestones: set[str]) -> str:
    for milestone in _MILESTONE_ORDER:
        if milestone in milestones:
            return milestone
    raise M3DValidationError("strategy is not exposed in any milestone")


def _partitions_for(milestones: set[str]) -> list[str]:
    partitions: set[str] = set()
    if "m2b" in milestones:
        partitions.update({"m2b_train", "m2b_validation"})
    if milestones & {"m3a", "m3b", "m3c"}:
        partitions.add("research_train")
    return sorted(partitions)


@dataclass(frozen=True)
class ResearchSpecificationCatalog:
    document: dict[str, Any]

    @classmethod
    def from_mapping(cls, doc: object) -> ResearchSpecificationCatalog:
        mapping = require_mapping("catalog", doc)
        _require_exact_keys(
            "catalog",
            mapping,
            {
                "schema_version",
                "kind",
                "package_version",
                "strategies",
                "cost_scenarios",
                "risk_overlays",
                "drawdown_breaker",
                "summary",
            },
        )
        schema_version = require_exact(
            "schema_version",
            require_nonnegative_int("schema_version", mapping["schema_version"]),
            CATALOG_SCHEMA_VERSION,
        )
        kind = require_exact("kind", require_str("kind", mapping["kind"]), CATALOG_KIND)
        package_version = require_str("package_version", mapping["package_version"])

        strategies_raw = mapping["strategies"]
        if not isinstance(strategies_raw, list):
            raise M3DValidationError("catalog.strategies must be a JSON array")
        strategies = [_validate_entry(f"strategies[{i}]", e) for i, e in enumerate(strategies_raw)]
        identifiers = [s["identifier"] for s in strategies]
        if len(identifiers) != len(set(identifiers)):
            raise M3DValidationError("duplicate strategy identifier in catalog")
        # Ordered by identifier so the artifact is stable.
        if identifiers != sorted(identifiers):
            raise M3DValidationError("catalog strategies must be sorted by identifier")

        cost_scenarios = _validate_cost_scenarios(
            "catalog.cost_scenarios", mapping["cost_scenarios"]
        )
        risk_overlays = _validate_risk_overlays("catalog.risk_overlays", mapping["risk_overlays"])
        drawdown = _validate_drawdown("catalog.drawdown_breaker", mapping["drawdown_breaker"])
        summary = _validate_summary("catalog.summary", mapping["summary"], strategies)

        document = {
            "schema_version": schema_version,
            "kind": kind,
            "package_version": package_version,
            "strategies": strategies,
            "cost_scenarios": cost_scenarios,
            "risk_overlays": risk_overlays,
            "drawdown_breaker": drawdown,
            "summary": summary,
        }
        return cls(document=document)

    @classmethod
    def build(cls, repo_root: str | Path) -> ResearchSpecificationCatalog:
        return cls.from_mapping(_derive_document(repo_root))

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.document)

    def sha256(self) -> str:
        return canonical_sha256(self.document)


def _validate_entry(label: str, doc: object) -> dict[str, Any]:
    mapping = require_mapping(label, doc)
    _require_exact_keys(label, mapping, _ENTRY_KEYS)
    role = require_str(f"{label}.role", mapping["role"])
    if role not in _ROLES:
        raise M3DValidationError(f"{label}.role must be one of {_ROLES}, got {role!r}")
    first_seen = require_str(f"{label}.first_seen_milestone", mapping["first_seen_milestone"])
    if first_seen not in _MILESTONE_ORDER:
        raise M3DValidationError(f"{label}.first_seen_milestone invalid: {first_seen!r}")
    parameters = require_mapping(f"{label}.parameters", mapping["parameters"])
    rejection = mapping["rejection_reason"]
    if rejection is not None:
        rejection = require_str(f"{label}.rejection_reason", rejection)
    entry = {
        "identifier": require_str(f"{label}.identifier", mapping["identifier"]),
        "role": role,
        "first_seen_milestone": first_seen,
        "first_seen_commit": require_commit_sha(
            f"{label}.first_seen_commit", mapping["first_seen_commit"]
        ),
        "parameters": parameters,
        "specification_fingerprint": require_sha256_hex(
            f"{label}.specification_fingerprint", mapping["specification_fingerprint"]
        ),
        "partitions_exposed": list(
            require_string_sequence(f"{label}.partitions_exposed", mapping["partitions_exposed"])
        ),
        "completed_experiment_count": require_nonnegative_int(
            f"{label}.completed_experiment_count", mapping["completed_experiment_count"]
        ),
        "status": require_str(f"{label}.status", mapping["status"]),
        "promotion_eligible": require_bool(
            f"{label}.promotion_eligible", mapping["promotion_eligible"]
        ),
        "rejection_reason": rejection,
        "parameter_selected_after_results": require_bool(
            f"{label}.parameter_selected_after_results", mapping["parameter_selected_after_results"]
        ),
        "may_evaluate_again": require_bool(
            f"{label}.may_evaluate_again", mapping["may_evaluate_again"]
        ),
    }
    # Benchmarks are never candidates; a candidate must be a real candidate role.
    if entry["identifier"] in {"cash", "buy_and_hold"} and role != "benchmark":
        raise M3DValidationError(f"{entry['identifier']} must be a benchmark, not {role}")
    if role == "candidate" and entry["promotion_eligible"]:
        raise M3DValidationError(
            f"{label}: a candidate here is rejected and not promotion-eligible"
        )
    # Recompute the specification fingerprint and require it to match.
    expected_fp = domain_sha256(
        "strategy_specification",
        {"identifier": entry["identifier"], "role": role, "parameters": parameters},
    )
    if entry["specification_fingerprint"] != expected_fp:
        raise M3DValidationError(f"{label}.specification_fingerprint mismatch")
    return entry


def _validate_cost_scenarios(label: str, doc: object) -> list[dict[str, Any]]:
    if not isinstance(doc, list):
        raise M3DValidationError(f"{label} must be a JSON array")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(doc):
        mapping = require_mapping(f"{label}[{i}]", item)
        _require_exact_keys(f"{label}[{i}]", mapping, {"identifier", "milestones"})
        out.append(
            {
                "identifier": require_str(f"{label}[{i}].identifier", mapping["identifier"]),
                "milestones": list(
                    require_string_sequence(f"{label}[{i}].milestones", mapping["milestones"])
                ),
            }
        )
    ids = [c["identifier"] for c in out]
    if ids != sorted(ids):
        raise M3DValidationError(f"{label} must be sorted by identifier")
    return out


def _validate_risk_overlays(label: str, doc: object) -> list[dict[str, Any]]:
    if not isinstance(doc, list):
        raise M3DValidationError(f"{label} must be a JSON array")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(doc):
        mapping = require_mapping(f"{label}[{i}]", item)
        _require_exact_keys(f"{label}[{i}]", mapping, {"identifier", "parameters", "milestones"})
        out.append(
            {
                "identifier": require_str(f"{label}[{i}].identifier", mapping["identifier"]),
                "parameters": require_mapping(f"{label}[{i}].parameters", mapping["parameters"]),
                "milestones": list(
                    require_string_sequence(f"{label}[{i}].milestones", mapping["milestones"])
                ),
            }
        )
    return out


def _validate_drawdown(label: str, doc: object) -> dict[str, Any]:
    mapping = require_mapping(label, doc)
    _require_exact_keys(label, mapping, {"state", "enabled", "executed", "milestone"})
    return {
        "state": require_str(f"{label}.state", mapping["state"]),
        "enabled": require_bool(f"{label}.enabled", mapping["enabled"]),
        "executed": require_bool(f"{label}.executed", mapping["executed"]),
        "milestone": require_str(f"{label}.milestone", mapping["milestone"]),
    }


def _validate_summary(label: str, doc: object, strategies: list[dict[str, Any]]) -> dict[str, Any]:
    mapping = require_mapping(label, doc)
    _require_exact_keys(
        label, mapping, {"strategy_count", "candidate_count", "benchmark_count", "rejected_count"}
    )
    out = {
        key: require_nonnegative_int(f"{label}.{key}", mapping[key])
        for key in ("strategy_count", "candidate_count", "benchmark_count", "rejected_count")
    }
    if out["strategy_count"] != len(strategies):
        raise M3DValidationError(f"{label}.strategy_count must equal the number of strategies")
    if out["candidate_count"] != sum(1 for s in strategies if s["role"] == "candidate"):
        raise M3DValidationError(f"{label}.candidate_count mismatch")
    if out["benchmark_count"] != sum(1 for s in strategies if s["role"] == "benchmark"):
        raise M3DValidationError(f"{label}.benchmark_count mismatch")
    if out["rejected_count"] != sum(1 for s in strategies if s["rejection_reason"] is not None):
        raise M3DValidationError(f"{label}.rejected_count mismatch")
    return out


def _derive_document(repo_root: str | Path) -> dict[str, Any]:
    from eth_research.m3d import M3D_PACKAGE_VERSION

    milestones, completed = _discover(repo_root)
    discovered = set(milestones)
    declared = set(_CLASSIFICATION)
    if missing := discovered - declared:
        raise M3DValidationError(f"strategies discovered but not classified: {sorted(missing)}")
    if orphaned := declared - discovered:
        raise M3DValidationError(
            f"classified strategies not found in artifacts: {sorted(orphaned)}"
        )

    first_commits = {
        "m2b": require_commit_sha(
            "m2b commit",
            require_mapping(
                "m2b_tv", up.load_json(repo_root, "research/m2b/train_validation_results.json")
            )["protocol_registration_commit_sha"],
        ),
        "m3a": _first_registry_commit(repo_root, "research/m3a/experiment_registry.jsonl"),
        "m3b": _first_registry_commit(repo_root, "research/m3b/experiment_registry.jsonl"),
        "m3c": _first_registry_commit(repo_root, "research/m3c/experiment_registry.jsonl"),
    }

    strategies: list[dict[str, Any]] = []
    for identifier in sorted(discovered):
        classification = _CLASSIFICATION[identifier]
        milestone = _first_seen_milestone(milestones[identifier])
        entry = {
            "identifier": identifier,
            "role": classification["role"],
            "first_seen_milestone": milestone,
            "first_seen_commit": first_commits[milestone],
            "parameters": classification["parameters"],
            "specification_fingerprint": domain_sha256(
                "strategy_specification",
                {
                    "identifier": identifier,
                    "role": classification["role"],
                    "parameters": classification["parameters"],
                },
            ),
            "partitions_exposed": _partitions_for(milestones[identifier]),
            "completed_experiment_count": completed[identifier],
            "status": classification["status"],
            "promotion_eligible": classification["promotion_eligible"],
            "rejection_reason": classification["rejection_reason"],
            "parameter_selected_after_results": classification["parameter_selected_after_results"],
            "may_evaluate_again": classification["may_evaluate_again"],
        }
        strategies.append(entry)

    cost_scenarios = _derive_cost_scenarios(repo_root)
    risk_overlays = _derive_risk_overlays(repo_root)
    drawdown = _derive_drawdown(repo_root)

    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "kind": CATALOG_KIND,
        "package_version": M3D_PACKAGE_VERSION,
        "strategies": strategies,
        "cost_scenarios": cost_scenarios,
        "risk_overlays": risk_overlays,
        "drawdown_breaker": drawdown,
        "summary": {
            "strategy_count": len(strategies),
            "candidate_count": sum(1 for s in strategies if s["role"] == "candidate"),
            "benchmark_count": sum(1 for s in strategies if s["role"] == "benchmark"),
            "rejected_count": sum(1 for s in strategies if s["rejection_reason"] is not None),
        },
    }


def _first_registry_commit(repo_root: str | Path, path: str) -> str:
    for event in up.jsonl_events(repo_root, path):
        mapping = require_mapping("registry event", event)
        return require_commit_sha(
            "registered_code_commit_sha", mapping["registered_code_commit_sha"]
        )
    raise M3DValidationError(f"{path} has no events")


def _derive_cost_scenarios(repo_root: str | Path) -> list[dict[str, Any]]:
    milestone_scenarios: dict[str, set[str]] = {}
    sources = {
        "m3a": "research/m3a/development_results.json",
        "m3b": "research/m3b/fractional_results.json",
        "m3c": "research/m3c/candidate_results.json",
    }
    for milestone, path in sources.items():
        results = require_mapping("results", up.load_json(repo_root, path))
        for scenario in require_string_sequence(
            f"{milestone} cost_scenarios", results.get("cost_scenarios", [])
        ):
            milestone_scenarios.setdefault(scenario, set()).add(milestone)
    return [
        {"identifier": scenario, "milestones": sorted(milestone_scenarios[scenario])}
        for scenario in sorted(milestone_scenarios)
    ]


def _derive_risk_overlays(repo_root: str | Path) -> list[dict[str, Any]]:
    protocol = require_mapping(
        "m3b_protocol", up.load_json(repo_root, "research/m3b/fractional_protocol.json")
    )
    return [
        {
            "identifier": "volatility_target_30d_50pct",
            "parameters": {
                "annual_volatility_target": protocol["annual_volatility_target"],
                "volatility_lookback": protocol["volatility_lookback"],
                "volatility_min_observations": protocol["volatility_min_observations"],
                "volatility_denominator_floor": protocol["volatility_denominator_floor"],
            },
            "milestones": ["m3b", "m3c"],
        }
    ]


def _derive_drawdown(repo_root: str | Path) -> dict[str, Any]:
    protocol = require_mapping(
        "m3b_protocol", up.load_json(repo_root, "research/m3b/fractional_protocol.json")
    )
    enabled = require_bool("drawdown_breaker_enabled", protocol["drawdown_breaker_enabled"])
    return {
        "state": "declared_disabled" if not enabled else "declared_enabled",
        "enabled": enabled,
        "executed": False,
        "milestone": "m3b",
    }


def build_research_specification_catalog(repo_root: str | Path) -> ResearchSpecificationCatalog:
    """Derive the specification catalog from committed upstream artifacts."""
    return ResearchSpecificationCatalog.build(repo_root)


def verify_research_specification_catalog(repo_root: str | Path) -> ResearchSpecificationCatalog:
    """Verify the committed catalog re-derives byte-for-byte and stays anti-orphan."""
    committed_raw, committed_doc = load_canonical_json_bytes(
        Path(repo_root) / CATALOG_PATH, "research_specification_catalog"
    )
    committed = ResearchSpecificationCatalog.from_mapping(committed_doc)
    rebuilt = build_research_specification_catalog(repo_root)
    if committed.to_json_bytes() != rebuilt.to_json_bytes():
        raise M3DValidationError(
            "committed specification catalog does not match the rebuilt catalog"
        )
    if committed_raw != rebuilt.to_json_bytes():
        raise M3DValidationError("committed catalog bytes are not canonical")
    return committed
