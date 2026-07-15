"""Research-train exhaustion policy and the adaptive-overfitting guard.

The repeatedly-inspected research-train partition is permanently classified
``exhausted_for_new_candidate_research``. Byte-for-byte replay, schema/provenance
verification, regression tests with pre-existing expected outputs, nonfinancial
infrastructure tests, and independent audit of already-published claims remain
allowed; new candidate generation, parameter selection, ranking, performance
comparison, statistical inference, gate-candidate selection, strategy changes
driven by research-train output, and new M3A/M3B/M3C runs are forbidden.

:func:`require_operation_allowed` is the standing guard every new M3D data entry
point calls before touching a historical partition. It resolves a partition by its
**content fingerprint** (or a known name), so renaming, copying a protocol,
aliasing a path, or changing a version/commit cannot evade the policy, and it is
fail-closed: an unknown operation kind is refused, not permitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3d.data_use import LEDGER_PATH as DATA_USE_LEDGER_PATH
from eth_research.m3d.multiplicity import LEDGER_PATH as MULTIPLICITY_LEDGER_PATH
from eth_research.m3d.validation import (
    M3DValidationError,
    canonical_json_bytes,
    canonical_sha256,
    load_canonical_json_bytes,
    require_exact,
    require_fingerprint,
    require_mapping,
    require_nonnegative_int,
    require_sha256_hex,
    require_str,
    require_string_sequence,
)

DECISION_PATH = "research/m3d/research_train_exhaustion.json"
DECISION_SCHEMA_VERSION = 1
DECISION_KIND = "research_train_exhaustion_decision"
CLASSIFICATION = "exhausted_for_new_candidate_research"

# Operations that remain permitted on the exhausted partitions.
ALLOWED_OPERATIONS: frozenset[str] = frozenset(
    {
        "byte_for_byte_replay",
        "schema_verification",
        "provenance_verification",
        "regression_test_expected_output",
        "nonfinancial_infrastructure_test",
        "independent_audit_of_published_claims",
    }
)

# Operations that are permanently forbidden on the exhausted partitions.
FORBIDDEN_OPERATIONS: frozenset[str] = frozenset(
    {
        "new_candidate_generation",
        "new_parameter_selection",
        "new_strategy_ranking",
        "new_performance_comparison",
        "new_statistical_inference",
        "new_bootstrap",
        "select_candidate_for_development_gate",
        "change_strategy_from_research_output",
        "create_m3a_run_004",
        "create_m3b_run_002",
        "create_m3c_run_002",
        "relabel_specification_to_evade",
    }
)

# The historical partitions the policy protects, keyed by canonical name.
_PROTECTED_FINGERPRINTS: dict[str, str] = {
    "research_train": up.RESEARCH_TRAIN_FINGERPRINT,
    "development_gate": up.DEVELOPMENT_GATE_FINGERPRINT,
    "final_holdout": up.FINAL_HOLDOUT_FINGERPRINT,
    "m2b_train": up.RESEARCH_TRAIN_FINGERPRINT,  # same bytes, benchmark-era name
    "m2b_validation": up.DEVELOPMENT_GATE_FINGERPRINT,
}
_PROTECTED_FINGERPRINT_SET = frozenset(_PROTECTED_FINGERPRINTS.values())


class ExhaustedPartitionError(M3DValidationError):
    """A forbidden operation was attempted on an exhausted/sealed partition."""


def is_protected_partition(partition_identity: str) -> bool:
    """True if ``partition_identity`` names or fingerprints a protected partition.

    Accepts a canonical partition name or a ``sha256:`` content fingerprint;
    resolution is by fingerprint so a renamed/aliased partition is still caught.
    """
    if not isinstance(partition_identity, str) or not partition_identity:
        raise M3DValidationError("partition_identity must be a non-empty string")
    if partition_identity in _PROTECTED_FINGERPRINTS:
        return True
    return partition_identity in _PROTECTED_FINGERPRINT_SET


def require_operation_allowed(partition_identity: str, operation_kind: str) -> None:
    """Fail-closed guard: forbid new-candidate-research operations on exhausted data.

    Raises :class:`ExhaustedPartitionError` for a forbidden operation on a protected
    partition, and :class:`M3DValidationError` for an unrecognized operation kind
    (fail-closed) or a partition that is protected but whose operation is neither
    explicitly allowed nor forbidden. Operations on unprotected partitions (e.g. the
    future prospective cohort) are outside this guard's scope and pass through.
    """
    if not isinstance(operation_kind, str) or not operation_kind:
        raise M3DValidationError("operation_kind must be a non-empty string")
    if operation_kind not in ALLOWED_OPERATIONS and operation_kind not in FORBIDDEN_OPERATIONS:
        raise M3DValidationError(f"unknown operation kind {operation_kind!r} (fail-closed)")
    if not is_protected_partition(partition_identity):
        return
    if operation_kind in FORBIDDEN_OPERATIONS:
        raise ExhaustedPartitionError(
            f"operation {operation_kind!r} is forbidden on the exhausted partition "
            f"{partition_identity!r} ({CLASSIFICATION})"
        )


@dataclass(frozen=True)
class ResearchTrainExhaustionDecision:
    document: dict[str, Any]

    @classmethod
    def from_mapping(cls, doc: object) -> ResearchTrainExhaustionDecision:
        mapping = require_mapping("exhaustion_decision", doc)
        _require_exact_keys(
            "exhaustion_decision",
            mapping,
            {
                "schema_version",
                "kind",
                "package_version",
                "classification",
                "research_train",
                "m3c_outcome",
                "bound_hashes",
                "allowed_operations",
                "forbidden_operations",
            },
        )
        schema_version = require_exact(
            "schema_version",
            require_nonnegative_int("schema_version", mapping["schema_version"]),
            DECISION_SCHEMA_VERSION,
        )
        kind = require_exact("kind", require_str("kind", mapping["kind"]), DECISION_KIND)
        package_version = require_str("package_version", mapping["package_version"])
        classification = require_exact(
            "classification",
            require_str("classification", mapping["classification"]),
            CLASSIFICATION,
        )
        m3c_outcome = require_exact(
            "m3c_outcome",
            require_str("m3c_outcome", mapping["m3c_outcome"]),
            up.M3C_REJECTED_OUTCOME,
        )

        research_train = require_mapping("research_train", mapping["research_train"])
        _require_exact_keys(
            "research_train",
            research_train,
            {"content_fingerprint", "first_open", "last_open", "row_count"},
        )
        research_train_out = {
            "content_fingerprint": require_exact(
                "research_train.content_fingerprint",
                require_fingerprint(
                    "research_train.content_fingerprint", research_train["content_fingerprint"]
                ),
                up.RESEARCH_TRAIN_FINGERPRINT,
            ),
            "first_open": require_str("research_train.first_open", research_train["first_open"]),
            "last_open": require_str("research_train.last_open", research_train["last_open"]),
            "row_count": require_nonnegative_int(
                "research_train.row_count", research_train["row_count"]
            ),
        }

        bound = require_mapping("bound_hashes", mapping["bound_hashes"])
        _require_exact_keys("bound_hashes", bound, set(_BOUND_HASH_SOURCES))
        bound_out = {
            name: require_sha256_hex(f"bound_hashes.{name}", bound[name])
            for name in sorted(_BOUND_HASH_SOURCES)
        }

        allowed = require_string_sequence("allowed_operations", mapping["allowed_operations"])
        forbidden = require_string_sequence("forbidden_operations", mapping["forbidden_operations"])
        if set(allowed) != ALLOWED_OPERATIONS:
            raise M3DValidationError("allowed_operations must match the policy constant")
        if set(forbidden) != FORBIDDEN_OPERATIONS:
            raise M3DValidationError("forbidden_operations must match the policy constant")
        if set(allowed) & set(forbidden):
            raise M3DValidationError("allowed and forbidden operations overlap")

        document = {
            "schema_version": schema_version,
            "kind": kind,
            "package_version": package_version,
            "classification": classification,
            "research_train": research_train_out,
            "m3c_outcome": m3c_outcome,
            "bound_hashes": bound_out,
            "allowed_operations": sorted(allowed),
            "forbidden_operations": sorted(forbidden),
        }
        return cls(document=document)

    @classmethod
    def build(cls, repo_root: str | Path) -> ResearchTrainExhaustionDecision:
        return cls.from_mapping(_derive_document(repo_root))

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.document)

    def sha256(self) -> str:
        return canonical_sha256(self.document)


# Logical name -> committed artifact whose SHA-256 the decision binds.
_BOUND_HASH_SOURCES: dict[str, str] = {
    "program_snapshot": "research/m3d/research_program_snapshot.json",
    "specification_catalog": "research/m3d/research_specification_catalog.json",
    "multiplicity_ledger": MULTIPLICITY_LEDGER_PATH,
    "data_use_ledger": DATA_USE_LEDGER_PATH,
    "m3a_registry": "research/m3a/experiment_registry.jsonl",
    "m3b_registry": "research/m3b/experiment_registry.jsonl",
    "m3c_registry": "research/m3c/experiment_registry.jsonl",
    "m3c_decision": "research/m3c/candidate_decision.json",
}


def _require_exact_keys(label: str, mapping: dict[str, Any], keys: set[str]) -> None:
    present = set(mapping)
    if missing := keys - present:
        raise M3DValidationError(f"{label} missing keys: {sorted(missing)}")
    if unknown := present - keys:
        raise M3DValidationError(f"{label} has unknown keys: {sorted(unknown)}")


def _derive_document(repo_root: str | Path) -> dict[str, Any]:
    from eth_research.m3d import M3D_PACKAGE_VERSION

    facts = require_mapping(
        "development_partition", up.load_json(repo_root, "research/m3a/development_partition.json")
    )
    research_train = next(
        require_mapping("partition", p)
        for p in facts["partitions"]
        if require_mapping("partition", p)["name"] == "research_train"
    )
    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "kind": DECISION_KIND,
        "package_version": M3D_PACKAGE_VERSION,
        "classification": CLASSIFICATION,
        "research_train": {
            "content_fingerprint": require_fingerprint(
                "research_train fingerprint", research_train["content_fingerprint"]
            ),
            "first_open": require_str(
                "research_train first_open", research_train["first_open_time"]
            ),
            "last_open": require_str("research_train last_open", research_train["last_open_time"]),
            "row_count": require_nonnegative_int(
                "research_train row_count", research_train["row_count"]
            ),
        },
        "m3c_outcome": up.M3C_REJECTED_OUTCOME,
        "bound_hashes": {
            name: up.hash_file(repo_root, path)
            for name, path in sorted(_BOUND_HASH_SOURCES.items())
        },
        "allowed_operations": sorted(ALLOWED_OPERATIONS),
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
    }


def build_research_train_exhaustion(repo_root: str | Path) -> ResearchTrainExhaustionDecision:
    """Derive the research-train exhaustion decision from committed artifacts."""
    return ResearchTrainExhaustionDecision.build(repo_root)


def verify_research_train_exhaustion(repo_root: str | Path) -> ResearchTrainExhaustionDecision:
    """Verify the committed exhaustion decision reproduces and stays bound.

    Requires a byte-for-byte rebuild (so any drift in a bound artifact hash, the
    classification, the M3C outcome, or the operation vocabularies fails), and
    re-checks that the guard would forbid a representative new-candidate operation.
    """
    committed_raw, committed_doc = load_canonical_json_bytes(
        Path(repo_root) / DECISION_PATH, "research_train_exhaustion"
    )
    committed = ResearchTrainExhaustionDecision.from_mapping(committed_doc)
    rebuilt = build_research_train_exhaustion(repo_root)
    if committed.to_json_bytes() != rebuilt.to_json_bytes():
        raise M3DValidationError(
            "committed exhaustion decision does not match the rebuilt decision"
        )
    if committed_raw != rebuilt.to_json_bytes():
        raise M3DValidationError("committed exhaustion decision bytes are not canonical")
    # The guard must still forbid new candidate research on the research train.
    try:
        require_operation_allowed(up.RESEARCH_TRAIN_FINGERPRINT, "new_candidate_generation")
    except ExhaustedPartitionError:
        pass
    else:  # pragma: no cover - defensive
        raise M3DValidationError("guard failed to forbid new candidate generation")
    return committed
