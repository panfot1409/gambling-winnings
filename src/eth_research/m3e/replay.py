"""Offline byte-exact replay CLI for the M3E facility.

``python -m eth_research.m3e.replay --repo-root . --check`` re-derives and verifies
the accepted base and the append-only proposal registry; ``--deep`` additionally
proves both M3E artifacts rebuild **byte-exact** from committed evidence. Both prove
the two sealed access ledgers and the prospective evaluation ledger are byte-empty
before and after, open no socket, call no engine, evaluate no strategy, and mutate no
tracked file (replay only reads and rebuilds in memory). There is no tolerance —
every artifact is exact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3e.accepted_base import (
    ACCEPTED_BASE_PATH,
    build_accepted_base_bytes,
    verify_accepted_base,
)
from eth_research.m3e.registry import REGISTRY_PATH, build_registry_bytes, verify_registry
from eth_research.m3e.validation import M3EValidationError

_LEDGERS = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)


def _assert_ledgers_byte_empty(repo_root: str | Path, phase: str) -> None:
    for relpath in _LEDGERS:
        facts = up.ledger_facts(repo_root, relpath)
        if facts["byte_count"] != 0 or facts["sha256"] != up.EMPTY_SHA256:
            raise M3EValidationError(f"{relpath} must be byte-empty {phase} replay (HARD STOP)")


def replay(repo_root: str | Path, *, deep: bool = False) -> dict[str, Any]:
    """Rebuild + verify the M3E artifacts offline; optionally prove byte-exact rebuild."""
    root = Path(repo_root)
    _assert_ledgers_byte_empty(root, "before")
    verify_accepted_base(root)
    verify_registry(root)
    result: dict[str, Any] = {"m3e_artifacts_verified": 2, "deep": deep}
    if deep:
        rebuilds = (
            (ACCEPTED_BASE_PATH, build_accepted_base_bytes(root)),
            (REGISTRY_PATH, build_registry_bytes()),
        )
        for relpath, data in rebuilds:
            if (root / relpath).read_bytes() != data:
                raise M3EValidationError(f"deep replay: {relpath} does not rebuild byte-exact")
        result["rebuilt_artifacts"] = len(rebuilds)
    _assert_ledgers_byte_empty(root, "after")
    return result


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(description="M3E review-only update offline replay")
    parser.add_argument("--repo-root", default=".")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="rebuild + verify (default)")
    mode.add_argument("--deep", action="store_true", help="also prove byte-exact rebuild")
    args = parser.parse_args(argv)
    print(json.dumps(replay(args.repo_root, deep=args.deep), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
