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
from datetime import date
from pathlib import Path
from typing import Any

RECORD_RELPATH = "governance/v2f/containment.json"


class ContainmentRefusal(Exception):
    """The workflow must not proceed."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Refuse duplicate JSON keys instead of silently taking the last one.

    ``{"active": true, "active": false}`` is accepted by a stock JSON parser and
    resolves to ``false``. A reviewer scanning for ``"active": true`` sees it and
    moves on, while the gate opens. Duplicate keys are a defect in the document,
    not a value to resolve.
    """
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ContainmentRefusal(f"{RECORD_RELPATH}: duplicate JSON key {key!r}")
        seen[key] = value
    return seen


def _load(record_path: Path, repo_root: Path) -> dict[str, Any]:
    # A symlink is refused rather than followed: the record is hash-pinned in the
    # governed inventory, and a symlink lets the pinned path keep its digest while
    # the bytes actually read come from somewhere unpinned.
    #
    # Checked on EVERY component, not just the final one. `record_path.is_symlink()`
    # alone tests the last component, so an auditor made `governance/v2f` a symlink to
    # a directory holding `{"active": false, ...}`: the final component was then an
    # ordinary regular file, the check passed, and the gate OPENED. Refusing an
    # unreadable component too — this is a fail-closed gate, so an error establishing
    # the path's nature is a refusal, never a pass.
    current = repo_root
    for part in Path(RECORD_RELPATH).parts:
        current = current / part
        try:
            is_link = current.is_symlink()
        except OSError as exc:
            raise ContainmentRefusal(f"{RECORD_RELPATH}: cannot inspect {current}: {exc}") from exc
        if is_link:
            raise ContainmentRefusal(
                f"{RECORD_RELPATH}: {current} is a symlink; no component of the path to "
                f"the containment record may be a symlink"
            )
    if not record_path.is_file():
        raise ContainmentRefusal(
            f"{RECORD_RELPATH} is absent. Absence is refused, not permitted: removing "
            f"the record must never be a way to resume suspended market-data egress."
        )
    try:
        raw = record_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise ContainmentRefusal(f"{RECORD_RELPATH} is not readable UTF-8 text: {exc}") from exc
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ContainmentRefusal(f"{RECORD_RELPATH} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContainmentRefusal(f"{RECORD_RELPATH} must be a JSON object")
    return payload


def check(repo_root: Path) -> str:
    """Return the reason the gate opened, or raise ``ContainmentRefusal``."""
    payload = _load(repo_root / RECORD_RELPATH, repo_root)

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

    # active is False — containment claims to have been lifted. Require the lift to
    # name a human and a date. Truthiness is not enough: `lifted_by: 1` and
    # `lifted_by: " "` are both truthy and neither names anybody, so the types and
    # the date format are checked rather than assumed.
    missing = [
        field
        for field in ("lifted_by", "lifted_on")
        if not isinstance(payload.get(field), str) or not str(payload.get(field)).strip()
    ]
    if missing:
        raise ContainmentRefusal(
            f"{RECORD_RELPATH} sets active=false without a non-empty string "
            f"{', '.join(missing)}; an unattributed lift is refused"
        )
    lifted_on = str(payload["lifted_on"])
    try:
        date.fromisoformat(lifted_on)
    except ValueError as exc:
        raise ContainmentRefusal(
            f"{RECORD_RELPATH} lifted_on={lifted_on!r} is not an ISO-8601 date: {exc}"
        ) from exc
    return f"containment lifted by {payload['lifted_by']} on {lifted_on}"


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
