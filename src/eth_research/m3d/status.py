"""Data-only status CLI for the prospective cohort.

``python -m eth_research.m3d.status --repo-root .`` prints only safe governance
facts — identity, boundaries, row count, content fingerprint (a hash, never a
price), maturity state, remaining rows, the evaluation flags, and the ledger byte
counts. It never prints OHLCV values, returns, signals, weights, positions,
fills, P&L, equity, metrics, rankings, or recommendations, and it computes none.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eth_research.m3d.cohort import verify_cohort_manifest
from eth_research.m3d.maturity import evaluate_maturity
from eth_research.m3d.validation import M3DValidationError

# Substrings that must never appear in a status key (would betray a leak).
FORBIDDEN_STATUS_KEY_SUBSTRINGS = (
    "price",
    "return",
    "signal",
    "weight",
    "position",
    "fill",
    "pnl",
    "equity",
    "metric",
    "ranking",
    "recommend",
    "sharpe",
    "alpha",
    "ohlcv",
)


def build_status(repo_root: str | Path) -> dict[str, Any]:
    """Assemble the data-only status facts (raises if the cohort fails to verify)."""
    manifest = verify_cohort_manifest(repo_root)
    state = evaluate_maturity(repo_root)
    identity = manifest["identity"]
    status = {
        "kind": "prospective_cohort_status",
        "product": identity["product"],
        "venue": identity["venue"],
        "interval_seconds": identity["interval_seconds"],
        "cohort_start": manifest["cohort_start"],
        "first_open": manifest["first_open"],
        "last_open": manifest["last_open"],
        "row_count": manifest["row_count"],
        "canonical_content_fingerprint": manifest["canonical_content_fingerprint"],
        "minimum_maturity_rows": state.minimum_maturity_rows,
        "remaining_rows": state.remaining_rows,
        "maturity_state": state.maturity_state,
        "evaluation_authorized": state.evaluation_authorized,
        "strategy_evaluation_performed": bool(manifest["strategy_evaluation_performed"]),
        "candidate_declared": bool(manifest["candidate_declared"]),
        "performance_metrics_computed": bool(manifest["performance_metrics_computed"]),
        "promotion_decision_exists": bool(manifest["promotion_decision_exists"]),
        "evaluation_ledger_byte_count": manifest["evaluation_ledger"]["byte_count"],
    }
    _assert_no_forbidden_keys(status)
    return status


def _assert_no_forbidden_keys(status: dict[str, Any]) -> None:
    for key, value in status.items():
        lowered = key.lower()
        if any(sub in lowered for sub in FORBIDDEN_STATUS_KEY_SUBSTRINGS):
            # A negative governance flag (a False boolean, e.g.
            # performance_metrics_computed) is the honest record that no such
            # value was computed; only a value-bearing key would be a leak.
            if isinstance(value, bool):
                continue
            raise M3DValidationError(f"status key {key!r} could leak evaluation data")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(description="M3D prospective cohort status (data-only)")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    status = build_status(args.repo_root)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
