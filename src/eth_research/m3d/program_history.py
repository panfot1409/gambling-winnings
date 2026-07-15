"""Frozen, machine-verifiable snapshot of the M2B/M3A/M3B/M3C research program.

``ResearchProgramSnapshot`` binds — without repairing or rewriting — the
repository identity, package version, every key upstream artifact hash, the M2B
dataset boundaries, both sealed-ledger facts, the release-tag debt, and the exact
current conclusions (real M2B data frozen; research-train laboratory; one M3C
candidate rejected; development gate and final holdout untouched; nothing
promotable). Construction and parsing share one strict invariant surface:
``build`` derives the document from committed bytes and then runs it through the
same ``from_mapping`` validator that ``verify`` applies to the committed file, so
a document that would be rejected on load can never be produced on build.
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
    load_canonical_json_bytes,
    require_bool,
    require_commit_sha,
    require_exact,
    require_fingerprint,
    require_mapping,
    require_nonnegative_int,
    require_sha256_hex,
    require_str,
)

SNAPSHOT_PATH = "research/m3d/research_program_snapshot.json"
SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_KIND = "research_program_snapshot"

# Declared, replay-stable release-tag debt: the two untagged development versions
# relevant to M3D governance. M3D must not create either tag.
_UPSTREAM_M3C_VERSION = "0.6.0"

_CONCLUSIONS: dict[str, Any] = {
    "m2b": "real Coinbase ETH-USD data frozen; original final holdout never accessed",
    "m3a": "research-train development laboratory; no development-gate access",
    "m3b": "fractional long-only accounting / execution-risk measurement run completed; "
    "no development-gate access",
    "m3c": "exactly one adaptively-motivated candidate evaluated on the research train and "
    "mechanically rejected",
    "development_gate": "untouched",
    "final_holdout": "untouched",
    "promotable_strategy_exists": False,
}


def _require_exact_keys(label: str, mapping: dict[str, Any], keys: set[str]) -> None:
    present = set(mapping)
    missing = keys - present
    unknown = present - keys
    if missing:
        raise M3DValidationError(f"{label} missing keys: {sorted(missing)}")
    if unknown:
        raise M3DValidationError(f"{label} has unknown keys: {sorted(unknown)}")


def _validate_ledger_facts(label: str, doc: object) -> dict[str, Any]:
    mapping = require_mapping(label, doc)
    _require_exact_keys(label, mapping, {"path", "byte_count", "event_count", "sha256"})
    return {
        "path": require_str(f"{label}.path", mapping["path"]),
        "byte_count": require_nonnegative_int(f"{label}.byte_count", mapping["byte_count"]),
        "event_count": require_nonnegative_int(f"{label}.event_count", mapping["event_count"]),
        "sha256": require_sha256_hex(f"{label}.sha256", mapping["sha256"]),
    }


def _validate_artifacts(label: str, doc: object, names: set[str]) -> dict[str, str]:
    mapping = require_mapping(label, doc)
    _require_exact_keys(label, mapping, names)
    return {name: require_sha256_hex(f"{label}.{name}", mapping[name]) for name in sorted(names)}


def _validate_milestone(
    label: str, doc: object, extra_keys: dict[str, Any], anchor_names: set[str]
) -> dict[str, Any]:
    mapping = require_mapping(label, doc)
    base_keys = {"conclusion", "gate_accessed", "holdout_accessed", "artifacts"}
    _require_exact_keys(label, mapping, base_keys | set(extra_keys))
    out: dict[str, Any] = {
        "conclusion": require_str(f"{label}.conclusion", mapping["conclusion"]),
        "gate_accessed": require_exact(
            f"{label}.gate_accessed",
            require_bool(f"{label}.gate_accessed", mapping["gate_accessed"]),
            False,
        ),
        "holdout_accessed": require_exact(
            f"{label}.holdout_accessed",
            require_bool(f"{label}.holdout_accessed", mapping["holdout_accessed"]),
            False,
        ),
        "artifacts": _validate_artifacts(f"{label}.artifacts", mapping["artifacts"], anchor_names),
    }
    for key, validator in extra_keys.items():
        out[key] = validator(f"{label}.{key}", mapping[key])
    return out


@dataclass(frozen=True)
class ResearchProgramSnapshot:
    """A validated research-program snapshot document."""

    document: dict[str, Any]

    @classmethod
    def from_mapping(cls, doc: object) -> ResearchProgramSnapshot:
        mapping = require_mapping("snapshot", doc)
        _require_exact_keys(
            "snapshot",
            mapping,
            {
                "schema_version",
                "kind",
                "package_version",
                "attestation",
                "repository",
                "sealed_ledgers",
                "release_tag_debt",
                "milestones",
                "conclusions",
            },
        )
        schema_version = require_exact(
            "schema_version",
            require_nonnegative_int("schema_version", mapping["schema_version"]),
            SNAPSHOT_SCHEMA_VERSION,
        )
        kind = require_exact("kind", require_str("kind", mapping["kind"]), SNAPSHOT_KIND)
        package_version = require_str("package_version", mapping["package_version"])

        attestation = require_mapping("attestation", mapping["attestation"])
        _require_exact_keys("attestation", attestation, {"kind", "is_cryptographic"})
        attestation_out = {
            "kind": require_exact(
                "attestation.kind",
                require_str("attestation.kind", attestation["kind"]),
                "operational_hash_binding",
            ),
            "is_cryptographic": require_exact(
                "attestation.is_cryptographic",
                require_bool("attestation.is_cryptographic", attestation["is_cryptographic"]),
                False,
            ),
        }

        repository = require_mapping("repository", mapping["repository"])
        _require_exact_keys(
            "repository",
            repository,
            {"upstream_main_sha", "m3c_accepted_head", "research_train_content_fingerprint"},
        )
        repository_out = {
            "upstream_main_sha": require_commit_sha(
                "repository.upstream_main_sha", repository["upstream_main_sha"]
            ),
            "m3c_accepted_head": require_commit_sha(
                "repository.m3c_accepted_head", repository["m3c_accepted_head"]
            ),
            "research_train_content_fingerprint": require_fingerprint(
                "repository.research_train_content_fingerprint",
                repository["research_train_content_fingerprint"],
            ),
        }

        sealed = require_mapping("sealed_ledgers", mapping["sealed_ledgers"])
        _require_exact_keys("sealed_ledgers", sealed, {"development_gate", "final_holdout"})
        sealed_out = {
            "development_gate": _validate_ledger_facts(
                "sealed_ledgers.development_gate", sealed["development_gate"]
            ),
            "final_holdout": _validate_ledger_facts(
                "sealed_ledgers.final_holdout", sealed["final_holdout"]
            ),
        }

        debt = require_mapping("release_tag_debt", mapping["release_tag_debt"])
        _require_exact_keys(
            "release_tag_debt",
            debt,
            {
                "current_development_version",
                "current_version_tagged",
                "upstream_m3c_version",
                "upstream_m3c_tagged",
            },
        )
        debt_out = {
            "current_development_version": require_str(
                "release_tag_debt.current_development_version",
                debt["current_development_version"],
            ),
            "current_version_tagged": require_exact(
                "release_tag_debt.current_version_tagged",
                require_bool(
                    "release_tag_debt.current_version_tagged", debt["current_version_tagged"]
                ),
                False,
            ),
            "upstream_m3c_version": require_str(
                "release_tag_debt.upstream_m3c_version", debt["upstream_m3c_version"]
            ),
            "upstream_m3c_tagged": require_exact(
                "release_tag_debt.upstream_m3c_tagged",
                require_bool("release_tag_debt.upstream_m3c_tagged", debt["upstream_m3c_tagged"]),
                False,
            ),
        }

        milestones = require_mapping("milestones", mapping["milestones"])
        _require_exact_keys("milestones", milestones, {"m2b", "m3a", "m3b", "m3c"})
        milestones_out = {
            "m2b": _validate_milestone(
                "milestones.m2b",
                milestones["m2b"],
                {"dataset": _validate_dataset},
                set(up.ANCHORS["m2b"]),
            ),
            "m3a": _validate_milestone(
                "milestones.m3a",
                milestones["m3a"],
                {"latest_completed_experiment": require_str},
                set(up.ANCHORS["m3a"]),
            ),
            "m3b": _validate_milestone(
                "milestones.m3b",
                milestones["m3b"],
                {"completed_experiment": require_str},
                set(up.ANCHORS["m3b"]),
            ),
            "m3c": _validate_milestone(
                "milestones.m3c",
                milestones["m3c"],
                {
                    "experiment_id": require_str,
                    "candidate_id": require_str,
                    "candidate_fingerprint": require_sha256_hex,
                    "outcome": require_str,
                },
                set(up.ANCHORS["m3c"]),
            ),
        }

        conclusions = require_mapping("conclusions", mapping["conclusions"])
        _require_exact_keys("conclusions", conclusions, set(_CONCLUSIONS))
        conclusions_out: dict[str, Any] = {}
        for key, expected in _CONCLUSIONS.items():
            if isinstance(expected, bool):
                conclusions_out[key] = require_exact(
                    f"conclusions.{key}",
                    require_bool(f"conclusions.{key}", conclusions[key]),
                    expected,
                )
            else:
                conclusions_out[key] = require_str(f"conclusions.{key}", conclusions[key])

        # Cross-field invariants that must hold regardless of committed bytes.
        if milestones_out["m3c"]["outcome"] != up.M3C_REJECTED_OUTCOME:
            raise M3DValidationError("M3C outcome must remain the rejection verdict")
        for name, facts in sealed_out.items():
            if facts["byte_count"] != 0 or facts["event_count"] != 0:
                raise M3DValidationError(f"sealed ledger {name} must be byte-empty")
            if facts["sha256"] != up.EMPTY_SHA256:
                raise M3DValidationError(f"sealed ledger {name} must hash to the empty SHA-256")

        document = {
            "schema_version": schema_version,
            "kind": kind,
            "package_version": package_version,
            "attestation": attestation_out,
            "repository": repository_out,
            "sealed_ledgers": sealed_out,
            "release_tag_debt": debt_out,
            "milestones": milestones_out,
            "conclusions": conclusions_out,
        }
        return cls(document=document)

    @classmethod
    def build(cls, repo_root: str | Path) -> ResearchProgramSnapshot:
        return cls.from_mapping(_derive_document(repo_root))

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.document)

    def sha256(self) -> str:
        return canonical_sha256(self.document)


def _validate_dataset(label: str, doc: object) -> dict[str, Any]:
    mapping = require_mapping(label, doc)
    _require_exact_keys(
        label, mapping, {"content_fingerprint", "first_open", "last_open", "row_count"}
    )
    return {
        "content_fingerprint": require_fingerprint(
            f"{label}.content_fingerprint", mapping["content_fingerprint"]
        ),
        "first_open": require_str(f"{label}.first_open", mapping["first_open"]),
        "last_open": require_str(f"{label}.last_open", mapping["last_open"]),
        "row_count": require_nonnegative_int(f"{label}.row_count", mapping["row_count"]),
    }


def _derive_document(repo_root: str | Path) -> dict[str, Any]:
    """Deterministically derive the snapshot document from committed bytes."""
    from eth_research.m3d import M3D_PACKAGE_VERSION

    lock = up.load_json(repo_root, "research/m2b/dataset_lock.json")
    lock_map = require_mapping("dataset_lock", lock)

    m3a_results = require_mapping(
        "m3a_results", up.load_json(repo_root, "research/m3a/development_results.json")
    )
    m3a_access = require_mapping("m3a_access", m3a_results["data_access_declaration"])
    m3a_gate_accessed = not require_str(
        "m3a gate access", m3a_access["development_gate"]
    ).startswith("not evaluated")
    m3a_holdout_accessed = not require_str(
        "m3a holdout access", m3a_access["final_holdout"]
    ).startswith("not evaluated")

    m3b_results = require_mapping(
        "m3b_results", up.load_json(repo_root, "research/m3b/fractional_results.json")
    )

    m3c_decision = require_mapping(
        "m3c_decision", up.load_json(repo_root, "research/m3c/candidate_decision.json")
    )
    m3c_registry_completed = _last_completed_event(
        up.jsonl_events(repo_root, "research/m3c/experiment_registry.jsonl")
    )
    m3a_completed = _last_completed_event(
        up.jsonl_events(repo_root, "research/m3a/experiment_registry.jsonl")
    )
    m3b_completed = _last_completed_event(
        up.jsonl_events(repo_root, "research/m3b/experiment_registry.jsonl")
    )

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "kind": SNAPSHOT_KIND,
        "package_version": M3D_PACKAGE_VERSION,
        "attestation": {"kind": "operational_hash_binding", "is_cryptographic": False},
        "repository": {
            "upstream_main_sha": up.UPSTREAM_MAIN_SHA,
            "m3c_accepted_head": up.M3C_ACCEPTED_HEAD,
            "research_train_content_fingerprint": up.RESEARCH_TRAIN_FINGERPRINT,
        },
        "sealed_ledgers": up.sealed_ledger_facts(repo_root),
        "release_tag_debt": {
            "current_development_version": M3D_PACKAGE_VERSION,
            "current_version_tagged": False,
            "upstream_m3c_version": _UPSTREAM_M3C_VERSION,
            "upstream_m3c_tagged": False,
        },
        "milestones": {
            "m2b": {
                "conclusion": _CONCLUSIONS["m2b"],
                "gate_accessed": False,
                "holdout_accessed": False,
                "dataset": {
                    "content_fingerprint": require_fingerprint(
                        "dataset_lock.content_fingerprint", lock_map["content_fingerprint"]
                    ),
                    "first_open": require_str(
                        "dataset_lock.first_open_time", lock_map["first_open_time"]
                    ),
                    "last_open": require_str(
                        "dataset_lock.last_open_time", lock_map["last_open_time"]
                    ),
                    "row_count": require_nonnegative_int(
                        "dataset_lock.row_count", lock_map["row_count"]
                    ),
                },
                "artifacts": up.anchor_hashes(repo_root, "m2b"),
            },
            "m3a": {
                "conclusion": _CONCLUSIONS["m3a"],
                "gate_accessed": m3a_gate_accessed,
                "holdout_accessed": m3a_holdout_accessed,
                "latest_completed_experiment": require_str(
                    "m3a completed id", m3a_completed["experiment_id"]
                ),
                "artifacts": up.anchor_hashes(repo_root, "m3a"),
            },
            "m3b": {
                "conclusion": _CONCLUSIONS["m3b"],
                "gate_accessed": require_nonnegative_int(
                    "m3b gate events", m3b_results["development_gate_event_count"]
                )
                != 0,
                "holdout_accessed": require_nonnegative_int(
                    "m3b holdout events", m3b_results["final_holdout_event_count"]
                )
                != 0,
                "completed_experiment": require_str(
                    "m3b completed id", m3b_completed["experiment_id"]
                ),
                "artifacts": up.anchor_hashes(repo_root, "m3b"),
            },
            "m3c": {
                "conclusion": _CONCLUSIONS["m3c"],
                "gate_accessed": require_bool(
                    "m3c gate accessed", m3c_decision["development_gate_accessed"]
                ),
                "holdout_accessed": require_bool(
                    "m3c holdout accessed", m3c_decision["final_holdout_accessed"]
                ),
                "experiment_id": require_str("m3c experiment id", m3c_decision["experiment_id"]),
                "candidate_id": require_str(
                    "m3c candidate id", m3c_registry_completed["candidate_id"]
                ),
                "candidate_fingerprint": require_sha256_hex(
                    "m3c candidate fingerprint", m3c_registry_completed["candidate_fingerprint"]
                ),
                "outcome": require_str("m3c outcome", m3c_decision["outcome"]),
                "artifacts": up.anchor_hashes(repo_root, "m3c"),
            },
        },
        "conclusions": dict(_CONCLUSIONS),
    }


def _last_completed_event(events: list[Any]) -> dict[str, Any]:
    completed = [
        require_mapping("registry event", e)
        for e in events
        if isinstance(e, dict) and e.get("event") == "completed"
    ]
    if not completed:
        raise M3DValidationError("registry has no completed event")
    return completed[-1]


def build_research_program_snapshot(repo_root: str | Path) -> ResearchProgramSnapshot:
    """Derive the research-program snapshot from committed upstream artifacts."""
    return ResearchProgramSnapshot.build(repo_root)


def verify_research_program_snapshot(repo_root: str | Path) -> ResearchProgramSnapshot:
    """Verify the committed snapshot re-derives byte-for-byte and stays honest.

    Rebuilds the snapshot from committed upstream bytes and requires the
    committed ``research_program_snapshot.json`` to be byte-identical, then
    re-checks the standing invariants (sealed ledgers empty, M3C rejected,
    nothing promotable, no false gate/holdout access).
    """
    committed_raw, committed_doc = load_canonical_json_bytes(
        Path(repo_root) / SNAPSHOT_PATH, "research_program_snapshot"
    )
    committed = ResearchProgramSnapshot.from_mapping(committed_doc)
    rebuilt = build_research_program_snapshot(repo_root)
    if committed.to_json_bytes() != rebuilt.to_json_bytes():
        raise M3DValidationError(
            "committed research-program snapshot does not match the rebuilt snapshot"
        )
    if committed_raw != rebuilt.to_json_bytes():
        raise M3DValidationError("committed snapshot bytes are not canonical")
    doc = committed.document
    if doc["conclusions"]["promotable_strategy_exists"] is not False:
        raise M3DValidationError("no strategy may be promotable")
    if doc["milestones"]["m3c"]["outcome"] != up.M3C_REJECTED_OUTCOME:
        raise M3DValidationError("M3C candidate must remain rejected")
    for milestone in doc["milestones"].values():
        if milestone["gate_accessed"] or milestone["holdout_accessed"]:
            raise M3DValidationError("no milestone may claim gate/holdout access")
    return committed
