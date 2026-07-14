"""Calculation-free finalizer for a crashed run-003 publication (N6).

If the orchestrator crashed after publishing the run archive but before it
appended the ``completed`` registry event, this tool finalizes the run without
re-running any strategy, backtest, metric, or bootstrap. It reads the durable
completion intent, verifies that every recorded artifact is present with the
recorded bytes and that the canonical registry is still exactly
``registered`` -> ``started`` for the intent's experiment id (with the started
line the intent chains onto), and appends the exact ``completed`` event the
intent recorded. It never reconstructs the dataset or recomputes a result::

    python -m eth_research.m3a_recovery --status
    python -m eth_research.m3a_recovery --finalize

``--status`` is read-only and always exits 0. ``--finalize`` exits 0 only when
the run is finalized (or already was) and non-zero otherwise, so it is safe to
invoke unconditionally: on a clean tree with no pending intent it reports
``no-intent`` and does nothing.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.development_completion import (
    CompletionIntent,
    CompletionIntentError,
    clear_completion_intent,
    read_completion_intent,
)
from eth_research.experiment_registry import (
    EVENT_COMPLETED,
    EVENT_FAILED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    EXPERIMENT_REGISTRY_RELPATH,
    RegistryError,
    append_registry_event,
    latest_registry_line_sha256,
    read_registry,
)

STATE_NO_INTENT: str = "no-intent"
STATE_FINALIZABLE: str = "finalizable"
STATE_ALREADY_FINALIZED: str = "already-finalized"
STATE_NOT_FINALIZABLE: str = "not-finalizable"
STATE_FAILED: str = "failed"
STATE_FINALIZED: str = "finalized"


@dataclass(frozen=True)
class RecoveryStatus:
    """The assessed recoverable state of a (possibly crashed) run."""

    state: str
    detail: str


def _verify_artifacts(root: Path, intent: CompletionIntent) -> list[str]:
    """Every recorded artifact must be present as a regular file with its bytes."""
    problems: list[str] = []
    for artifact in intent.artifacts:
        path = root / artifact.relpath
        if path.is_symlink() or not path.is_file():
            problems.append(f"{artifact.relpath} (absent or not a regular file)")
        elif sha256_file(path) != artifact.sha256:
            problems.append(f"{artifact.relpath} (hash mismatch)")
    return problems


def assess(repo_root: str | Path) -> RecoveryStatus:
    """Report whether a pending run can be finalized calculation-free.

    Read-only: it reads the completion intent and the canonical registry, hashes
    the published artifacts, and classifies the state. It never appends.
    """
    root = Path(repo_root)
    intent = read_completion_intent(root)
    if intent is None:
        return RecoveryStatus(STATE_NO_INTENT, "no pending completion intent; nothing to finalize")
    registry_path = root / EXPERIMENT_REGISTRY_RELPATH
    events = read_registry(registry_path)
    history = [e for e in events if e.experiment_id == intent.experiment_id]
    stages = [e.event for e in history]
    if stages == [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]:
        completed_sha = sha256_bytes(history[2].to_json_line()[:-1])
        if completed_sha != intent.completed_event_sha256:
            return RecoveryStatus(
                STATE_NOT_FINALIZABLE,
                "the registry's 'completed' event does not match the recorded intent",
            )
        return RecoveryStatus(
            STATE_ALREADY_FINALIZED,
            f"experiment {intent.experiment_id!r} is already completed; the intent can be cleared",
        )
    if EVENT_FAILED in stages:
        return RecoveryStatus(
            STATE_FAILED,
            f"experiment {intent.experiment_id!r} is recorded failed (stages={stages}); the id is "
            "consumed and cannot be finalized",
        )
    if stages != [EVENT_REGISTERED, EVENT_STARTED]:
        return RecoveryStatus(
            STATE_NOT_FINALIZABLE,
            f"experiment {intent.experiment_id!r} is not registered→started (stages={stages})",
        )
    latest = latest_registry_line_sha256(registry_path)
    if latest != intent.previous_event_sha256:
        return RecoveryStatus(
            STATE_NOT_FINALIZABLE,
            "the registry's last line is not the started event the intent chains onto",
        )
    problems = _verify_artifacts(root, intent)
    if problems:
        return RecoveryStatus(
            STATE_NOT_FINALIZABLE,
            "the published archive is incomplete (publication did not finish before the crash): "
            + "; ".join(problems),
        )
    return RecoveryStatus(
        STATE_FINALIZABLE,
        f"experiment {intent.experiment_id!r} published and verified; ready to append 'completed'",
    )


def finalize(repo_root: str | Path) -> RecoveryStatus:
    """Finalize a crashed-but-published run by appending the recorded event.

    Calculation-free: it appends the exact ``completed`` event the intent
    recorded (never recomputing it) only when :func:`assess` reports the run is
    finalizable, then clears the intent. If the run is already completed it just
    clears the intent; otherwise it returns the non-finalizable assessment
    unchanged and appends nothing.
    """
    root = Path(repo_root)
    status = assess(root)
    if status.state == STATE_ALREADY_FINALIZED:
        clear_completion_intent(root)
        return status
    if status.state != STATE_FINALIZABLE:
        return status
    intent = read_completion_intent(root)
    if intent is None:  # pragma: no cover - just assessed finalizable
        raise CompletionIntentError("completion intent vanished between assessment and finalize")
    append_registry_event(root / EXPERIMENT_REGISTRY_RELPATH, intent.completed_event)
    clear_completion_intent(root)
    return RecoveryStatus(
        STATE_FINALIZED,
        f"appended the recorded 'completed' event for {intent.experiment_id!r} (calculation-free)",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: report the recoverable state, or finalize a crashed publication."""
    parser = argparse.ArgumentParser(
        prog="eth_research.m3a_recovery",
        description="Finalize a crashed run-003 publication without recomputation.",
    )
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="report the recoverable state")
    group.add_argument(
        "--finalize",
        action="store_true",
        help="append the recorded 'completed' event, calculation-free",
    )
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    try:
        status = assess(root) if args.status else finalize(root)
    except (CompletionIntentError, RegistryError) as exc:
        print(f"recovery refused: {exc}", file=sys.stderr)
        return 1
    print(f"{status.state}: {status.detail}")
    if args.status:
        return 0
    # --finalize is safe to invoke unconditionally: "nothing to do" states
    # (finalized just now, already finalized, or no pending intent) succeed;
    # only a genuinely stuck run (not-finalizable / failed) is an error.
    return 0 if status.state in (STATE_FINALIZED, STATE_ALREADY_FINALIZED, STATE_NO_INTENT) else 1


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
