"""Comprehensive M3C run-archive verifier.

One read-only entry point that re-proves the whole surface for the one published
candidate run: the hash-chained registry lifecycle, the re-validating results, the
mechanically re-derived decision, the byte-for-byte re-rendered report, the
manifest/bundle chain, the promotion verdict, both sealed access ledgers
byte-empty, no pending completion intent, and the run directory shape. With
``--deep`` it additionally reconstructs the research-train partition offline and
re-runs the 75-cell grid to reproduce the committed results, decision, and report
**byte-for-byte** (the full replay).

It evaluates no sealed partition, touches the network, or mutates a byte::

    python -m eth_research.m3c.verify_archive --repo-root . [--deep]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eth_research.data.provenance import sha256_file
from eth_research.m3c.archive import M3C_MANIFEST_RELPATH, verify_published_run
from eth_research.m3c.completion import read_completion_intent
from eth_research.m3c.registry import M3C_REGISTRY_RELPATH
from eth_research.m3c.replay import check_replay

_GATE_LEDGER_RELPATH: str = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"
_EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_RUN_DIR_RELPATH: str = "research/m3c/experiments/run-001"


class M3CRunArchiveError(RuntimeError):
    """The comprehensive M3C run-archive verification failed a structural check."""


def verify_m3c_run_archive(repo_root: str | Path, *, deep: bool = False) -> tuple[str, ...]:
    """Re-prove the entire published-run surface. Read-only.

    Returns the ordered passed checks. Raises the underlying typed error (or
    :class:`M3CRunArchiveError`) on the first violation. ``deep`` additionally
    reproduces the results/decision/report byte-for-byte from the raw committed
    data and is therefore slow.
    """
    root = Path(repo_root)
    checks: list[str] = []

    registry_path = root / M3C_REGISTRY_RELPATH
    if not registry_path.exists() or registry_path.is_symlink() or not registry_path.is_file():
        raise M3CRunArchiveError("the M3C registry is missing or not a real file")
    checks.append("registry_is_a_real_file")

    manifest_path = root / M3C_MANIFEST_RELPATH
    if not manifest_path.is_file():
        raise M3CRunArchiveError(f"run directory {_RUN_DIR_RELPATH} manifest is missing")
    checks.append("run_directory_present")

    for label, relpath in (
        ("development_gate_ledger_byte_empty", _GATE_LEDGER_RELPATH),
        ("final_holdout_ledger_byte_empty", _HOLDOUT_LEDGER_RELPATH),
    ):
        path = root / relpath
        if path.is_symlink() or not path.is_file() or sha256_file(path) != _EMPTY_SHA256:
            raise M3CRunArchiveError(f"sealed ledger {relpath} is missing or not byte-empty")
        checks.append(label)

    # v1 published run: registry lifecycle + results revalidate + decision re-derives
    # + report re-renders + manifest/bundle/verdict chain.
    checks.extend(verify_published_run(root))

    if read_completion_intent(root) is not None:
        raise M3CRunArchiveError("a pending completion intent is present (run is unfinalized)")
    checks.append("no_pending_completion_intent")

    if deep:
        state, *_ = check_replay(root)
        if state != "completed":
            raise M3CRunArchiveError(f"deep replay expected a completed run, got {state!r}")
        checks.append("deep_replay_reproduces_byte_for_byte")

    return tuple(checks)


def main(argv: list[str] | None = None) -> int:
    """CLI: run the comprehensive M3C run-archive verification."""
    parser = argparse.ArgumentParser(
        prog="eth_research.m3c.verify_archive",
        description="Comprehensive read-only verification of the published M3C run archive.",
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--deep", action="store_true", help="also reproduce results/decision/report (slow)"
    )
    args = parser.parse_args(argv)
    try:
        checks = verify_m3c_run_archive(args.repo_root, deep=args.deep)
    except (RuntimeError, ValueError) as exc:
        print(f"verification FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"M3C run archive verified ({len(checks)} checks):")
    for check in checks:
        print(f"  - {check}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
