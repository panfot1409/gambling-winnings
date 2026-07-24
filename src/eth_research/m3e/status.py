"""Data-only status CLI for the review-only update facility.

``python -m eth_research.m3e.status --repo-root .`` prints only safe governance
facts — the accepted-base identity and boundaries, the content fingerprint (a hash,
never a price), the maturity/authorization flags, the pinned review policy, the false
governance flags, the append-only registry summary, the workflow posture (whose
``active`` flag is derived from the committed V2D activation anchor), and the three
ledger byte counts. It never prints OHLCV values, returns,
signals, weights, positions, P&L, metrics, or rankings, and it computes none.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eth_research.m3e.accepted_base import verify_accepted_base
from eth_research.m3e.proposal import GOVERNANCE_FLAGS, REVIEW_POLICY
from eth_research.m3e.registry import verify_registry
from eth_research.m3e.validation import M3EValidationError

# Substrings a status *key* may never contain when its value is non-boolean — a
# numeric leak of a computed evaluation quantity. (Boolean governance flags such as
# ``evaluation_authorized`` / ``performance_metrics_computed`` are bool-exempt, and
# ``prospective_evaluation_byte_count`` is an integer whose key legitimately
# contains "evaluation"/"metric"; those two words are therefore intentionally absent
# from this list.) The set is otherwise the comprehensive strategy/performance
# vocabulary so a future accidental numeric field cannot slip an evaluation value
# through the data-only status.
FORBIDDEN_STATUS_KEY_SUBSTRINGS = (
    "price",
    "ohlcv",
    "return",
    "profit",
    "pnl",
    "equity",
    "signal",
    "weight",
    "position",
    "exposure",
    "leverage",
    "fill",
    "fee",
    "turnover",
    "sharpe",
    "sortino",
    "calmar",
    "cagr",
    "alpha",
    "beta",
    "volatility",
    "drawdown",
    "metric",
    "ranking",
    "recommend",
    "momentum",
)

_ACTIVATION_ANCHOR_RELPATH = "governance/v2d/prospective_activation.json"


def _activation_anchor_present(repo_root: Path) -> bool:
    """Whether the committed V2D data-only activation anchor is present.

    Reported as the ``active`` posture — the anchor is the activation switch. This is a
    plain file-presence check on purpose: m3e must not import the v2d/m3f layers that own
    the anchor's self-hash validation, so the authoritative activation gate remains
    ``python -m eth_research.v2d verify``. Whether the schedule additionally *fires* also
    requires being on the default branch, which this offline CLI cannot observe.
    """
    return (repo_root / _ACTIVATION_ANCHOR_RELPATH).is_file()


def build_status(repo_root: str | Path) -> dict[str, Any]:
    """Assemble the data-only status facts (raises if anything fails to verify)."""
    base = verify_accepted_base(repo_root)
    registry = verify_registry(repo_root)
    identity = base.document["identity"]
    ledgers = base.document["ledgers"]
    status: dict[str, Any] = {
        "kind": "m3e_review_only_update_status",
        "package_version": base.document["package_version"],
        "accepted_base": {
            "product": identity["product"],
            "venue": identity["venue"],
            "interval_seconds": identity["interval_seconds"],
            "cohort_start": base.document["cohort_start"],
            "first_open": base.first_open,
            "last_open": base.last_open,
            "row_count": base.row_count,
            "canonical_content_fingerprint": base.canonical_content_fingerprint,
            "minimum_maturity_rows": base.document["minimum_maturity_rows"],
            "maturity_state": base.document["maturity_state"],
            "evaluation_authorized": bool(base.document["evaluation_authorized"]),
        },
        "review_policy": dict(REVIEW_POLICY),
        "governance_flags": dict(GOVERNANCE_FLAGS),
        "registry": {
            "record_count": len(registry),
            "last_entry_kind": str(registry[-1]["entry_kind"]),
            "proposals_recorded": sum(1 for r in registry if r.get("entry_kind") == "proposal"),
        },
        "workflow_posture": {
            "standing_update_workflow": "m3e-prospective-update.yml",
            # Derived from the committed V2D activation anchor (the switch), not hard-coded:
            # true once the data-only collection is activated. The schedule additionally
            # fires only on the default branch (see `python -m eth_research.v2d verify`).
            "active": _activation_anchor_present(Path(repo_root)),
            "last_live_run": "29441490761",
            "last_live_outcome": "no-op",
        },
        "ledgers": {
            "development_gate_byte_count": ledgers["development_gate"]["byte_count"],
            "final_holdout_byte_count": ledgers["final_holdout"]["byte_count"],
            "prospective_evaluation_byte_count": ledgers["prospective_evaluation"]["byte_count"],
        },
    }
    _assert_no_forbidden_keys(status)
    return status


def _assert_no_forbidden_keys(node: Any) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            if any(sub in lowered for sub in FORBIDDEN_STATUS_KEY_SUBSTRINGS) and not isinstance(
                value, bool
            ):
                # A negative governance flag (a False boolean) is the honest record
                # that no such value was computed; only a value-bearing key leaks.
                raise M3EValidationError(f"status key {key!r} could leak evaluation data")
            _assert_no_forbidden_keys(value)
    elif isinstance(node, list):
        for item in node:
            _assert_no_forbidden_keys(item)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(description="M3E review-only update status (data-only)")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    print(json.dumps(build_status(args.repo_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
