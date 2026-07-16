"""Byte-exact repository-freeze replay entrypoint for Milestone 3F.

``python -m eth_research.m3f.replay --check`` runs the whole-graph verifier and emits
a deterministic status payload (no wall clock, no strategy, no network). Nonzero exit
on any failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from eth_research.m3f.audit import verify_repository_freeze
from eth_research.m3f.cli import repo_root_parser, run_guarded
from eth_research.m3f.honest_state import derive_honest_state
from eth_research.m3f.validation import M3FValidationError


def replay_status(repo_root: str | Path) -> dict[str, Any]:
    result = verify_repository_freeze(repo_root)
    honest: dict[str, Any] | None = None
    try:
        honest = derive_honest_state(repo_root)
    except (OSError, M3FValidationError):
        honest = None
    return {
        "ok": result.ok,
        "checks": [name for name, _ in result.checks],
        "failures": result.failures,
        "m3c_verdict": (honest or {}).get("m3c_candidate_verdict"),
        "m3d_cohort_rows": (honest or {}).get("m3d_cohort_row_count"),
        "m3d_maturity": (honest or {}).get("m3d_maturity_state"),
        "m3e_active": (honest or {}).get("m3e_active"),
        "m3e_production_proposal_count": (honest or {}).get("m3e_production_proposal_count"),
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    args = repo_root_parser("M3F repository-freeze replay (read-only)").parse_args(argv)
    return run_guarded(lambda: replay_status(args.repo_root), as_json=args.json or args.check)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
