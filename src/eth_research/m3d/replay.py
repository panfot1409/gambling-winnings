"""Offline replay CLI for the prospective evidence.

``python -m eth_research.m3d.replay --repo-root . --check`` re-derives every
artifact from the committed raw bytes and runs the whole-program graph verifier;
``--deep`` additionally proves every published artifact rebuilds byte-exact. Both
prove the two sealed ledgers and the prospective evaluation ledger are byte-empty
before and after, open no socket, call no engine, and mutate no tracked file
(replay only reads and rebuilds in memory). There is no tolerance because no
strategy or statistic exists to compare — the canonical content is exact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3d.cohort import build_prospective_publication_blobs
from eth_research.m3d.validation import M3DValidationError
from eth_research.m3d.verify_m3d_program import verify_m3d_program

_LEDGERS = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)


def _assert_ledgers_byte_empty(repo_root: str | Path, phase: str) -> None:
    for relpath in _LEDGERS:
        facts = up.ledger_facts(repo_root, relpath)
        if facts["byte_count"] != 0:
            raise M3DValidationError(f"{relpath} must be byte-empty {phase} replay (HARD STOP)")


def replay(repo_root: str | Path, *, deep: bool = False) -> dict[str, Any]:
    """Rebuild + verify the whole program offline; optionally prove byte-exact republish."""
    root = Path(repo_root)
    _assert_ledgers_byte_empty(root, "before")
    checks = verify_m3d_program(root)
    result: dict[str, Any] = {"checks": len(checks), "deep": deep}
    if deep:
        blobs = build_prospective_publication_blobs(root)
        for relpath, data in blobs:
            if (root / relpath).read_bytes() != data:
                raise M3DValidationError(f"deep replay: {relpath} does not rebuild byte-exact")
        result["republished_artifacts"] = len(blobs)
    _assert_ledgers_byte_empty(root, "after")
    return result


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(description="M3D prospective cohort offline replay")
    parser.add_argument("--repo-root", default=".")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="rebuild + graph verify (default)")
    mode.add_argument("--deep", action="store_true", help="also prove byte-exact republish")
    args = parser.parse_args(argv)
    result = replay(args.repo_root, deep=args.deep)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
