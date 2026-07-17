"""Shared argparse plumbing for the read-only M3F CLIs.

Every M3F CLI is read-only: it verifies committed bytes and exits nonzero on any
failure. None fetches data, evaluates a strategy, mutates a ledger, or writes an
accepted artifact.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any


def repo_root_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--check", action="store_true", help="verify committed bytes (read-only)")
    parser.add_argument("--deep", action="store_true", help="run the full graph (read-only)")
    parser.add_argument("--json", action="store_true", help="emit deterministic JSON")
    return parser


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True) if as_json else json.dumps(payload))


def run_guarded(fn: Callable[[], dict[str, Any]], *, as_json: bool) -> int:
    """Run ``fn``; print its payload; return 0 on ``ok`` true, else 1."""
    payload = fn()
    emit(payload, as_json=as_json)
    return 0 if payload.get("ok") else 1
