"""Fable 5 audit source freeze — pin the audit's own tooling and its committed conclusions.

The Fable 5 full-system audit adds tooling (this ``fable5`` subpackage) and remediates two source
files (``fractional/engine.py``, ``v2ab/commercial_truth.py``). A replay CI must be able to prove
that the audit *logic* itself, the two fixes, and the audit's committed governance artifacts have
not drifted since the freeze. This module builds and verifies that byte-level freeze.

It pins, by sha256:

- **frozen source** — the ``fable5`` audit modules plus the two remediated files;
- **frozen governance** — the audit manifest, findings, remediation state, system inventory, and the
  derived paper-readiness state;
- **sealed ledgers** — asserted byte-empty (the empty-file sha256), re-affirming the sealed
  partitions were never opened by this audit.

The freeze evaluates no strategy, opens no sealed value, and mutates only its own artifact.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

FABLE5_SOURCE_FREEZE_RELPATH = "governance/v2/fable5_source_freeze.json"
FABLE5_SOURCE_FREEZE_SCHEMA_VERSION = 1

#: The V2C merge commit MV2C — the baseline this audit ran against.
BASELINE_MERGE_COMMIT = "09fc9c0204a3cd71e0c7c84ba9dd605b9a5f811b"

#: sha256 of the empty byte string — the fixed value every sealed ledger must hash to.
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: Audit tooling + the two remediated source files, pinned to their frozen bytes.
FROZEN_SOURCE_RELPATHS: tuple[str, ...] = (
    "src/eth_research/v2/fable5/__init__.py",
    "src/eth_research/v2/fable5/__main__.py",
    "src/eth_research/v2/fable5/inventory.py",
    "src/eth_research/v2/fable5/paper_readiness.py",
    "src/eth_research/v2/fable5/freeze.py",
    "src/eth_research/fractional/engine.py",
    "src/eth_research/v2ab/commercial_truth.py",
)

#: The audit's committed governance artifacts, pinned to their frozen bytes.
FROZEN_GOVERNANCE_RELPATHS: tuple[str, ...] = (
    "governance/v2/fable5_system_inventory.json",
    "governance/v2/fable5_findings.json",
    "governance/v2/fable5_remediation_state.json",
    "governance/v2/fable5_audit_manifest.json",
    "governance/v2/paper_readiness_state.json",
)

_SEALED_LEDGERS: tuple[str, ...] = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)


class Fable5FreezeError(RuntimeError):
    """The live tree disagrees with the committed Fable 5 source freeze."""


def _sha256_file(root: Path, rel: str) -> str:
    data = (root / rel).read_bytes()
    return hashlib.sha256(data).hexdigest()


def build_source_freeze(repo_root: str | Path) -> dict[str, object]:
    """Build the Fable 5 source-freeze mapping by hashing the frozen files under ``repo_root``.

    Raises :class:`Fable5FreezeError` if a frozen file is missing, or if any sealed ledger is not
    byte-empty (a sealed partition must never have been opened by this audit).
    """
    root = Path(repo_root)
    frozen_source: dict[str, str] = {}
    for rel in FROZEN_SOURCE_RELPATHS:
        if not (root / rel).is_file():
            raise Fable5FreezeError(f"frozen source file missing: {rel}")
        frozen_source[rel] = _sha256_file(root, rel)

    frozen_governance: dict[str, str] = {}
    for rel in FROZEN_GOVERNANCE_RELPATHS:
        if not (root / rel).is_file():
            raise Fable5FreezeError(f"frozen governance artifact missing: {rel}")
        frozen_governance[rel] = _sha256_file(root, rel)

    sealed: dict[str, dict[str, object]] = {}
    for rel in _SEALED_LEDGERS:
        path = root / rel
        if not path.is_file():
            raise Fable5FreezeError(f"sealed ledger missing: {rel}")
        size = path.stat().st_size
        digest = _sha256_file(root, rel)
        if size != 0 or digest != EMPTY_SHA256:
            raise Fable5FreezeError(f"sealed ledger not byte-empty: {rel}")
        sealed[rel] = {"byte_count": size, "sha256": digest}

    return {
        "schema_version": FABLE5_SOURCE_FREEZE_SCHEMA_VERSION,
        "baseline_merge_commit": BASELINE_MERGE_COMMIT,
        "forbidden_capabilities_absent": True,
        "frozen_source_sha256": frozen_source,
        "frozen_governance_sha256": frozen_governance,
        "expected_sealed_ledgers": sealed,
    }


def verify_source_freeze(repo_root: str | Path, committed: dict[str, object]) -> list[str]:
    """Re-derive the freeze from the live tree and prove it matches ``committed``, failing closed.

    Returns the list of check names that passed; raises :class:`Fable5FreezeError` on any drift.
    """
    root = Path(repo_root)
    live = build_source_freeze(root)
    problems: list[str] = []

    for field in ("frozen_source_sha256", "frozen_governance_sha256", "expected_sealed_ledgers"):
        if committed.get(field) != live[field]:
            committed_map = committed.get(field)
            live_map = live[field]
            if isinstance(committed_map, dict) and isinstance(live_map, dict):
                for key in sorted(set(committed_map) | set(live_map)):
                    if committed_map.get(key) != live_map.get(key):
                        problems.append(f"{field}: {key} drifted")
            else:
                problems.append(f"{field}: shape mismatch")

    if committed.get("baseline_merge_commit") != BASELINE_MERGE_COMMIT:
        problems.append("baseline_merge_commit mismatch")
    if committed.get("forbidden_capabilities_absent") is not True:
        problems.append("forbidden_capabilities_absent not asserted")

    if problems:
        raise Fable5FreezeError(
            "Fable 5 source-freeze verification failed:\n  - " + "\n  - ".join(problems)
        )
    return [
        "frozen_source_match",
        "frozen_governance_match",
        "sealed_ledgers_byte_empty",
        "baseline_match",
    ]


def load_committed_freeze(repo_root: str | Path) -> dict[str, object]:
    """Read the committed ``fable5_source_freeze.json`` as a dict (raises if absent/malformed)."""
    path = Path(repo_root) / FABLE5_SOURCE_FREEZE_RELPATH
    if not path.is_file():
        raise Fable5FreezeError(f"missing committed source freeze: {FABLE5_SOURCE_FREEZE_RELPATH}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise Fable5FreezeError("committed source freeze is not a JSON object")
    return data
