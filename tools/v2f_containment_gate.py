#!/usr/bin/env python3
"""Fail-closed containment gate for the market-data egress workflow.

Runs before any network step. Exit 0 means "containment has been lawfully
lifted"; every other outcome exits nonzero and the workflow stops.

The important design point is what happens when the record is **missing**. The
obvious reading — no containment record, so nothing is contained — is exactly
the wrong one: it makes ``rm governance/v2f/containment.json`` a complete bypass
of the suspension. So absence refuses. The only way through this gate is a
record that explicitly says containment was lifted, by whom, and when.

Stdlib only, and it reads nothing but the record, so it can run before the
project environment is synced.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RECORD_RELPATH = "governance/v2f/containment.json"


class ContainmentRefusal(Exception):
    """The workflow must not proceed."""


def _load(record_path: Path) -> dict[str, Any]:
    if not record_path.is_file():
        raise ContainmentRefusal(
            f"{RECORD_RELPATH} is absent. Absence is refused, not permitted: removing "
            f"the record must never be a way to resume suspended market-data egress."
        )
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContainmentRefusal(f"{RECORD_RELPATH} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContainmentRefusal(f"{RECORD_RELPATH} must be a JSON object")
    return payload


def check(repo_root: Path) -> str:
    """Return the reason the gate opened, or raise ``ContainmentRefusal``."""
    payload = _load(repo_root / RECORD_RELPATH)

    if payload.get("kind") != "v2f_containment":
        raise ContainmentRefusal(
            f"{RECORD_RELPATH} declares kind={payload.get('kind')!r}, not 'v2f_containment'"
        )

    active = payload.get("active")
    if not isinstance(active, bool):
        raise ContainmentRefusal(
            f"{RECORD_RELPATH} field 'active' must be a JSON boolean, got {type(active).__name__}"
        )

    if active:
        raise ContainmentRefusal(
            "market-data egress is SUSPENDED under V2F-R containment: "
            + str(payload.get("reason", "no reason recorded"))
        )

    # active is False — containment claims to have been lifted. Require the lift
    # to name a human and a date, so an unattributed flag flip cannot open it.
    missing = [f for f in ("lifted_by", "lifted_on") if not payload.get(f)]
    if missing:
        raise ContainmentRefusal(
            f"{RECORD_RELPATH} sets active=false without {', '.join(missing)}; "
            f"an unattributed lift is refused"
        )
    return f"containment lifted by {payload['lifted_by']} on {payload['lifted_on']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        reason = check(args.repo_root.resolve())
    except ContainmentRefusal as exc:
        print(f"V2F-R CONTAINMENT GATE: REFUSED\n{exc}", file=sys.stderr)
        return 1
    print(f"V2F-R containment gate: open — {reason}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
