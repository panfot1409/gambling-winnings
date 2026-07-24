"""Read-only anchors and derivations over the frozen upstream milestones.

Every M3D governance artifact (program snapshot, specification catalog,
multiplicity ledger, data-use ledger, research-train exhaustion decision) binds
the same committed M2B/M3A/M3B/M3C bytes. This module is the single read-only
surface they share: the declared artifact anchor paths, path-safe resolution,
committed-file hashing, strict JSON loading, and append-only ledger facts.

Nothing here writes, repairs, or interprets a strategy. It reads committed bytes
and reports their hashes and a few strictly-parsed provenance facts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research.m3d.validation import (
    M3DValidationError,
    sha256_bytes,
    strict_json_loads,
)

# --------------------------------------------------------------------------- #
# Replay-stable governance constants (committed facts; never live git)         #
# --------------------------------------------------------------------------- #
UPSTREAM_MAIN_SHA = "a7640e35c861e72413c9a0154e2ae3af0a075889"
M3C_ACCEPTED_HEAD = "c50872431534f199dd0ba78ef86967bcd0b94e4c"
RESEARCH_TRAIN_FINGERPRINT = (
    "sha256:60aa988e9db786db5723c925abc794463c23ff701791173b745196c7a8b12033"
)
DEVELOPMENT_GATE_FINGERPRINT = (
    "sha256:97747723e0fcd141ea346b1d4ca784bf782f887280d4515f69609eb9c2392b1a"
)
FINAL_HOLDOUT_FINGERPRINT = (
    "sha256:71c1214d6f1322d3fc9fec84bbf92e910c7a94b6f5c4683cdbace071ce2f6c22"
)
M2B_DATASET_FINGERPRINT = "sha256:273f89eb07ae882784e40c2bc2ef2be5db93ddb3efa7de6270880ad1b7dd5718"
M2B_FIRST_OPEN = "2016-05-23T00:00:00+00:00"
M2B_LAST_OPEN = "2026-07-11T00:00:00+00:00"
M2B_ROW_COUNT = 3702
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

M3C_CANDIDATE_ID = "dual_horizon_trend_63_252_vol_target_30d_50pct"
M3C_CANDIDATE_FINGERPRINT = "d45d3bdf7a3dca7003e8382995e5a350d0c9e61edf47e87e294d151070f4cae6"
M3C_EXPERIMENT_ID = "m3c-dual-horizon-trend-v1-run-001"
M3C_REJECTED_OUTCOME = "rejected_for_development_gate_promotion"

# The two sealed access ledgers that must stay byte-empty forever.
SEALED_LEDGERS: dict[str, str] = {
    "development_gate": "research/m3a/development_gate_access.jsonl",
    "final_holdout": "research/m2b/test_evaluations.jsonl",
}

# The prospective evaluation ledger M3D creates and never appends.
PROSPECTIVE_EVALUATION_LEDGER = "research/m3d/prospective_evaluations.jsonl"

# Declared committed artifact anchors per milestone. Binding a known set is a
# deliberate governance decision; drift on any of them fails verification.
ANCHORS: dict[str, dict[str, str]] = {
    "m2b": {
        "frozen_dossier": "research/m2b/frozen_dossier.json",
        "dataset_lock": "research/m2b/dataset_lock.json",
        "dataset_manifest": "research/m2b/dataset_manifest.json",
        "protocol": "research/m2b/protocol.json",
        "quality_report": "research/m2b/quality_report.json",
        "holdout_identity": "research/m2b/holdout_identity.json",
        "runtime_contract": "research/m2b/runtime_contract.json",
    },
    "m3a": {
        "walk_forward_protocol": "research/m3a/walk_forward_protocol.json",
        "walk_forward_protocol_v2": "research/m3a/walk_forward_protocol_v2.json",
        "experiment_registry": "research/m3a/experiment_registry.jsonl",
        "development_partition": "research/m3a/development_partition.json",
        "development_results": "research/m3a/development_results.json",
        "run003_results": (
            "research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003/development_results.json"
        ),
        "run003_manifest": (
            "research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003/artifact_manifest.json"
        ),
        "run003_return_evidence": (
            "research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003/return_evidence.json"
        ),
        "artifact_errata": "research/m3a/artifact_errata.jsonl",
        "errata_run003": "research/m3a/errata/m3a-run003-report-zero-inclusion-v1.json",
    },
    "m3b": {
        "fractional_protocol": "research/m3b/fractional_protocol.json",
        "experiment_registry": "research/m3b/experiment_registry.jsonl",
        "fractional_results": "research/m3b/fractional_results.json",
        "fractional_report": "research/m3b/fractional_report.md",
        "run001_archive_v2": "research/m3b/experiments/run-001/immutable-v2/archive_v2.json",
        "run001_immutable_results": (
            "research/m3b/experiments/run-001/immutable-v2/fractional_results.json"
        ),
        "run001_manifest": "research/m3b/experiments/run-001/manifest.json",
        "execution_trace_commitments": "research/m3b/execution_trace_commitments.json",
        "artifact_errata": "research/m3b/artifact_errata.jsonl",
        "artifact_annotations": "research/m3b/artifact_annotations.jsonl",
    },
    "m3c": {
        "protocol": "research/m3c/protocol.json",
        "research_lineage": "research/m3c/research_lineage.json",
        "research_budget": "research/m3c/research_budget.json",
        "experiment_registry": "research/m3c/experiment_registry.jsonl",
        "candidate_results": "research/m3c/candidate_results.json",
        "candidate_report": "research/m3c/candidate_report.md",
        "candidate_decision": "research/m3c/candidate_decision.json",
        "run001_manifest": "research/m3c/experiments/run-001/manifest.json",
    },
}


def resolve(repo_root: str | Path, relpath: str) -> Path:
    """Resolve ``relpath`` under ``repo_root`` with strict path safety.

    Rejects absolute paths, parent traversal, and non-regular files (including
    symlinks). Prevents an anchor path from escaping the repository or pointing
    at a device/symlink target whose bytes are not what is committed.
    """
    if not isinstance(relpath, str) or not relpath:
        raise M3DValidationError("relpath must be a non-empty string")
    pure = Path(relpath)
    if pure.is_absolute() or any(part == ".." for part in pure.parts):
        raise M3DValidationError(f"unsafe path {relpath!r}")
    root = Path(repo_root).resolve()
    candidate = (root / pure).resolve()
    if root != candidate and root not in candidate.parents:
        raise M3DValidationError(f"path {relpath!r} escapes repo root")
    # Reject a symlink at any component of the relative chain. ``candidate`` above is
    # already resolved (it followed every link), so ``candidate.is_symlink()`` can never
    # be true for an in-repo symlink; the component walk below is what actually enforces
    # the docstring's "no symlink" guarantee (mirrors m3f.validation.safe_repo_path).
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise M3DValidationError(f"path {relpath!r} is not a regular file")
    if not candidate.is_file():
        raise M3DValidationError(f"path {relpath!r} is not a regular file")
    return candidate


def read_bytes(repo_root: str | Path, relpath: str) -> bytes:
    return resolve(repo_root, relpath).read_bytes()


def hash_file(repo_root: str | Path, relpath: str) -> str:
    """Bare lowercase-hex SHA-256 of a committed file's exact bytes."""
    return sha256_bytes(read_bytes(repo_root, relpath))


def load_json(repo_root: str | Path, relpath: str) -> Any:
    """Strictly decode a committed JSON artifact (dup-key/NaN/Inf rejecting)."""
    return strict_json_loads(read_bytes(repo_root, relpath))


def jsonl_events(repo_root: str | Path, relpath: str) -> list[Any]:
    """Every non-empty line of an append-only ledger, strictly decoded."""
    raw = read_bytes(repo_root, relpath)
    return [strict_json_loads(line) for line in raw.splitlines() if line.strip()]


def ledger_facts(repo_root: str | Path, relpath: str) -> dict[str, Any]:
    """``{path, byte_count, event_count, sha256}`` for an append-only ledger."""
    raw = read_bytes(repo_root, relpath)
    event_count = sum(1 for line in raw.splitlines() if line.strip())
    return {
        "path": relpath,
        "byte_count": len(raw),
        "event_count": event_count,
        "sha256": sha256_bytes(raw),
    }


def anchor_hashes(repo_root: str | Path, milestone: str) -> dict[str, str]:
    """``{logical_name: sha256}`` for every declared anchor of ``milestone``."""
    anchors = ANCHORS[milestone]
    return {name: hash_file(repo_root, path) for name, path in sorted(anchors.items())}


def sealed_ledger_facts(repo_root: str | Path) -> dict[str, dict[str, Any]]:
    """Byte/event/hash facts for both sealed access ledgers, sorted by name."""
    return {name: ledger_facts(repo_root, path) for name, path in sorted(SEALED_LEDGERS.items())}
