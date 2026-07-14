"""Comprehensive M3B run-archive verifier (closure Section 10).

One read-only entry point that re-proves the *entire* closure surface for the one
published run: the hash-chained registry lifecycle and the v1 published run; the
genuine immutable archive v2; the legacy completion audit; the hash-chained
artifact-annotation chain and every annotated target; the append-only report
errata; the execution-trace commitments (structurally, and — with ``deep=True`` —
by full replay); both sealed access ledgers byte-empty; and the filesystem shape
(a real registry file, no pending completion intent, the expected run directory).

It aggregates the individual verifiers into a single ordered list of named checks
so an auditor (or CI) has one command to run. It evaluates no sealed partition,
touches the network, or mutates a byte. :func:`verify_m3b_run_archive` raises the
underlying typed error on the first failure; the CLI prints the passed checks::

    python -m eth_research.fractional.verify_run_archive --repo-root . [--deep]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from eth_research._json import require_canonical_file_bytes, strict_json_loads
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.fractional.archive import verify_published_run
from eth_research.fractional.archive_v2 import verify_archive_v2
from eth_research.fractional.artifact_annotations import verify_artifact_annotations
from eth_research.fractional.completion import read_completion_intent
from eth_research.fractional.execution_trace import (
    EXECUTION_TRACE_COMMITMENTS_RELPATH,
    verify_execution_trace_commitments,
)
from eth_research.fractional.legacy_completion_audit import verify_legacy_completion_audit
from eth_research.fractional.protocol import RUN_001_EXPERIMENT_ID
from eth_research.fractional.registry import M3B_REGISTRY_RELPATH
from eth_research.fractional.report_erratum import verify_fractional_report_errata
from eth_research.fractional.results import FRACTIONAL_RESULTS_RELPATH

_GATE_LEDGER_RELPATH: str = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"
_EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_RUN_DIR_RELPATH: str = "research/m3b/experiments/run-001"


class M3BRunArchiveError(RuntimeError):
    """The comprehensive M3B run-archive verification failed a structural check."""


def _verify_trace_commitments_structural(root: Path) -> None:
    path = root / EXECUTION_TRACE_COMMITMENTS_RELPATH
    if not path.exists() or path.is_symlink() or not path.is_file():
        raise M3BRunArchiveError("execution_trace_commitments.json is missing or not a file")
    raw = path.read_bytes()
    try:
        require_canonical_file_bytes(raw, "execution trace commitments")
        payload: Any = strict_json_loads(raw)
    except ValueError as exc:
        raise M3BRunArchiveError(f"execution_trace_commitments.json not canonical: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("cell_count") != 75:
        raise M3BRunArchiveError("execution_trace_commitments.json does not carry 75 cells")
    results_sha = sha256_bytes(
        require_canonical_file_bytes(
            (root / FRACTIONAL_RESULTS_RELPATH).read_bytes(), "fractional results"
        )
    )
    if payload.get("fractional_results_sha256") != results_sha:
        raise M3BRunArchiveError("trace commitments do not bind the committed results digest")


def verify_m3b_run_archive(
    repo_root: str | Path,
    experiment_id: str = RUN_001_EXPERIMENT_ID,
    *,
    deep: bool = False,
) -> tuple[str, ...]:
    """Re-prove the entire closure surface for one published run. Read-only.

    Returns the ordered list of passed checks (24, or 25 with ``deep=True``).
    Raises the underlying typed error (or :class:`M3BRunArchiveError`) on the
    first violation. ``deep`` additionally replays the 75-cell execution-trace
    commitments byte-for-byte and is therefore slow.
    """
    root = Path(repo_root)
    checks: list[str] = []

    if experiment_id != RUN_001_EXPERIMENT_ID:
        raise M3BRunArchiveError(
            f"only {RUN_001_EXPERIMENT_ID!r} is published in M3B, got {experiment_id!r}"
        )
    checks.append("experiment_id_recognized")

    registry_path = root / M3B_REGISTRY_RELPATH
    if not registry_path.exists() or registry_path.is_symlink() or not registry_path.is_file():
        raise M3BRunArchiveError("the M3B registry is missing or not a real file")
    checks.append("registry_is_a_real_file")

    run_dir = root / _RUN_DIR_RELPATH
    if not run_dir.is_dir():
        raise M3BRunArchiveError(f"run directory {_RUN_DIR_RELPATH} is missing")
    checks.append("run_directory_present")

    # Both sealed access ledgers must be byte-empty — checked up front so this
    # critical invariant is the authoritative failure, not a downstream verifier's.
    for label, relpath in (
        ("development_gate_ledger_byte_empty", _GATE_LEDGER_RELPATH),
        ("final_holdout_ledger_byte_empty", _HOLDOUT_LEDGER_RELPATH),
    ):
        path = root / relpath
        if path.is_symlink() or not path.is_file() or sha256_file(path) != _EMPTY_SHA256:
            raise M3BRunArchiveError(f"sealed ledger {relpath} is missing or not byte-empty")
        checks.append(label)

    # v1 published run (registry lifecycle + artifacts + manifest): 6 checks.
    checks.extend(verify_published_run(root))
    # Genuine immutable archive v2: 4 checks.
    checks.extend(verify_archive_v2(root))
    # Legacy completion audit: 4 checks.
    checks.extend(verify_legacy_completion_audit(root))
    # Hash-chained artifact annotations: 2 checks.
    checks.extend(verify_artifact_annotations(root))

    # Append-only report errata (may be empty; verifying returns the ids).
    verify_fractional_report_errata(root)
    checks.append("report_errata_verified")

    # Execution-trace commitments: structural (fast) + optional deep replay.
    _verify_trace_commitments_structural(root)
    checks.append("trace_commitments_present_and_bind_results")
    if deep:
        verify_execution_trace_commitments(root)
        checks.append("trace_commitments_replay_byte_for_byte")

    # No unfinalized publication is pending.
    if read_completion_intent(root) is not None:
        raise M3BRunArchiveError("a pending completion intent is present (run is unfinalized)")
    checks.append("no_pending_completion_intent")

    return tuple(checks)


def main(argv: list[str] | None = None) -> int:
    """CLI: run the comprehensive M3B run-archive verification."""
    parser = argparse.ArgumentParser(
        prog="eth_research.fractional.verify_run_archive",
        description="Comprehensive read-only verification of the published M3B run archive.",
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--experiment-id", default=RUN_001_EXPERIMENT_ID)
    parser.add_argument(
        "--deep", action="store_true", help="also replay the execution-trace commitments (slow)"
    )
    args = parser.parse_args(argv)
    try:
        checks = verify_m3b_run_archive(args.repo_root, args.experiment_id, deep=args.deep)
    except (RuntimeError, ValueError) as exc:
        print(f"verification FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"M3B run archive verified ({len(checks)} checks):")
    for check in checks:
        print(f"  - {check}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
