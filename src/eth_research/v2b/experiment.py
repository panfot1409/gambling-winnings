"""The V2B one-shot registration (R) and execution (P) drivers, and their offline CLI.

Two governed boundaries wrap the pure evaluation:

* **register (R)** appends the single ``registered`` event — governance only, no research — after
  re-asserting the frozen budget and protocol identity.
* **execute (P)** appends ``started`` (which permanently consumes the one-shot budget), runs the ONE
  authorized :func:`~eth_research.v2b.orchestrator.run_one_shot`, publishes the immutable results
  bundle, and appends a single terminal event (``completed`` on success, ``failed`` otherwise).

Timestamps are supplied by the caller — the drivers take ISO-8601 strings; only :func:`main` reads a
wall clock (and only when ``--timestamp`` is omitted), so the modules stay free of hidden
nondeterminism. The registry lifecycle guards (R-before-P, at-most-one ``started``, single terminal)
live in :mod:`eth_research.v2b.governance`; these drivers only call ``append_event``.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import eth_research
from eth_research.v2.registry import RegistryEvent
from eth_research.v2.strict import V2ValidationError, require_nonempty_str
from eth_research.v2b.governance import (
    COMPLETED,
    FAILED,
    REGISTERED,
    STARTED,
    V2B_REGISTRY_RELPATH,
    append_event,
    protocol_fingerprint,
    read_events,
    verify_budget,
    verify_protocol_identity,
)
from eth_research.v2b.orchestrator import run_one_shot
from eth_research.v2b.publication import PublicationReceipt, publish_results
from eth_research.v2b.results import build_results

#: The single-use run identifier (a slug — ``require_slug`` forbids hyphens).
V2B_RUN_ID: str = "v2b_run_001"


class V2BExperimentError(V2ValidationError):
    """A V2B registration or execution precondition was violated."""


def _registry_path(repo_root: str | Path) -> Path:
    return Path(repo_root) / V2B_REGISTRY_RELPATH


def register(repo_root: str | Path, *, run_id: str = V2B_RUN_ID, timestamp: str) -> RegistryEvent:
    """Append the single ``registered`` event (R) after re-asserting the frozen governance."""
    root = Path(repo_root)
    verify_budget(root)  # raises on drift from the fixed one-shot discipline
    verify_protocol_identity(root)  # raises if the committed protocol identity does not reproduce
    registry = _registry_path(root)
    if read_events(registry):
        raise V2BExperimentError("the v2b registry already has events; registration is single-use")
    return append_event(
        registry,
        REGISTERED,
        run_id,
        protocol_fingerprint=protocol_fingerprint(root),
        timestamp=timestamp,
    )


def execute(
    repo_root: str | Path, *, run_id: str = V2B_RUN_ID, started_at: str, completed_at: str
) -> PublicationReceipt:
    """Run the ONE authorized evaluation (P): started -> run_one_shot -> publish -> terminal."""
    root = Path(repo_root)
    verify_budget(root)
    verify_protocol_identity(root)
    registry = _registry_path(root)
    fingerprint = protocol_fingerprint(root)

    # A `started` permanently consumes the one-shot budget (the governance guard rejects a second
    # one and requires a prior `registered`).
    append_event(registry, STARTED, run_id, protocol_fingerprint=fingerprint, timestamp=started_at)
    try:
        outcome = run_one_shot(root)
        if outcome.protocol_fingerprint != fingerprint:
            raise V2BExperimentError("the run's protocol fingerprint drifted mid-run")
        frozen = build_results(outcome, run_id=run_id, package_version=eth_research.__version__)
        receipt = publish_results(root, frozen)
    except Exception as exc:
        append_event(
            registry,
            FAILED,
            run_id,
            protocol_fingerprint=fingerprint,
            timestamp=completed_at,
            payload={"reason": type(exc).__name__},
        )
        raise
    append_event(
        registry,
        COMPLETED,
        run_id,
        protocol_fingerprint=fingerprint,
        timestamp=completed_at,
        payload={"results_fingerprint": frozen.fingerprint()},
    )
    return receipt


def _resolve_timestamp(value: str | None) -> str:
    """A tz-aware ISO-8601 timestamp; only here (the CLI wrapper) may a wall clock be read."""
    if value is None:
        return datetime.now().astimezone().isoformat()
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise V2BExperimentError("--timestamp must be timezone-aware (e.g. 2026-07-20T00:00:00Z)")
    return require_nonempty_str("timestamp", value)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(description="V2B one-shot registration/execution (offline).")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--timestamp", default=None, help="tz-aware ISO-8601 event time; defaults to now."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--register", action="store_true", help="Append the `registered` event (R).")
    group.add_argument("--execute", action="store_true", help="Run the one-shot evaluation (P).")
    args = parser.parse_args(argv)

    root = Path(args.repo_root)
    timestamp = _resolve_timestamp(args.timestamp)
    if args.register:
        event = register(root, timestamp=timestamp)
        print(f"registered run {event.run_id!r} at seq {event.seq}")
        return 0
    receipt = execute(root, started_at=timestamp, completed_at=timestamp)
    print(f"completed: {receipt.results_path} (results_fingerprint={receipt.results_fingerprint})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
