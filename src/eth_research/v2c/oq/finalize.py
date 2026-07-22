"""V2C section 18: the calculation-free finalizer for a crashed OQ-P publication.

If the runner crashed after publishing the immutable archive but before appending the ``completed``
registry event, this finalizes the run without re-executing any qualification, harness, resource
measurement, recovery campaign, or SLO evaluation. It reads the durable completion intent, verifies
that every recorded artifact is present with the recorded bytes and that the registry is still
exactly ``registered`` -> ``started`` for this id (chaining onto the recorded started hash), and
re-appends the identical ``completed`` event -- deterministically rebuilt from the intent's recorded
identity, time, reason, verdict, and five terminal digests (never recomputed). It never reconstructs
the result or recomputes an operational count.

``assess`` is read-only and classifies the state; ``finalize`` appends the recorded event only when
the run is finalizable, then clears the intent. On a clean tree with no pending intent it reports
``no-intent`` and does nothing.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from eth_research.v2c.oq.completion import (
    OQCompletionIntent,
    OQCompletionIntentError,
    clear_completion_intent,
    read_completion_intent,
)
from eth_research.v2c.oq.registry import (
    OQ_EVENT_COMPLETED,
    OQ_EVENT_FAILED,
    OQ_EVENT_REGISTERED,
    OQ_EVENT_STARTED,
    OQEvent,
    append_oq_event,
    read_oq_registry,
)

STATE_NO_INTENT: str = "no-intent"
STATE_FINALIZABLE: str = "finalizable"
STATE_ALREADY_FINALIZED: str = "already-finalized"
STATE_NOT_FINALIZABLE: str = "not-finalizable"
STATE_FAILED: str = "failed"
STATE_FINALIZED: str = "finalized"


@dataclass(frozen=True, slots=True)
class RecoveryStatus:
    """The assessed recoverable state of a (possibly crashed) OQ run."""

    state: str
    detail: str


def _verify_artifacts(repo_root: Path, intent: OQCompletionIntent) -> list[str]:
    """Every recorded artifact must be present as a regular file with its recorded bytes."""
    from eth_research.v2.strict import sha256_bytes

    problems: list[str] = []
    for relpath, sha in intent.artifacts:
        path = repo_root / relpath
        if path.is_symlink() or not path.is_file():
            problems.append(f"{relpath} (absent or not a regular file)")
        elif sha256_bytes(path.read_bytes()) != sha:
            problems.append(f"{relpath} (hash mismatch)")
    return problems


def _reconcile_intent_with_archive(repo_root: Path, intent: OQCompletionIntent) -> list[str]:
    """Re-derive the completed event's verdict and terminal digests from the ON-DISK archive bytes
    and require the intent's recorded values match.

    The intent's five terminal hashes and verdict are recorded once at build time; a corrupt or
    tampered intent that still names the real artifacts (so :func:`_verify_artifacts` passes) but
    carries a mismatched ``verdict`` / ``evidence_sha256`` / ``result_bundle_sha256`` would
    otherwise make the finalizer append a ``completed`` event the published archive cannot support
    -- which the deep verifier and oracle reject forever, permanently bricking an append-only,
    one-shot run. This reconciles the intent against the archive so nothing unsupported is appended.
    """
    from eth_research.m3d.validation import M3DValidationError
    from eth_research.v2.strict import (
        V2ValidationError,
        canonical_sha256,
        sha256_bytes,
        strict_json_loads,
    )
    from eth_research.v2c.oq.archive import (
        OQ_ARCHIVE_MANIFEST_RELNAME,
        OQ_ARCHIVE_REPORT_RELNAME,
        OQ_ARCHIVE_RESULT_RELNAME,
        archive_relpath,
    )

    problems: list[str] = []

    def _read(relname: str) -> bytes | None:
        path = repo_root / archive_relpath(relname)
        if path.is_symlink() or not path.is_file():
            problems.append(f"{relname} (absent or not a regular file)")
            return None
        return path.read_bytes()

    result_bytes = _read(OQ_ARCHIVE_RESULT_RELNAME)
    report_bytes = _read(OQ_ARCHIVE_REPORT_RELNAME)
    manifest_bytes = _read(OQ_ARCHIVE_MANIFEST_RELNAME)
    if result_bytes is None or report_bytes is None or manifest_bytes is None:
        return problems

    try:
        result = strict_json_loads(result_bytes)
    except (V2ValidationError, M3DValidationError) as exc:
        problems.append(f"oq_result.json does not parse: {exc}")
        return problems
    if not isinstance(result, dict):
        problems.append("oq_result.json is not a JSON object")
        return problems

    result_sha = sha256_bytes(result_bytes)
    report_sha = sha256_bytes(report_bytes)
    manifest_sha = sha256_bytes(manifest_bytes)
    evidence_sha = canonical_sha256({k: v for k, v in result.items() if k != "result_digest"})
    bundle_sha = canonical_sha256(
        {
            "result_sha256": result_sha,
            "report_sha256": report_sha,
            "evidence_sha256": evidence_sha,
            "archive_manifest_sha256": manifest_sha,
        }
    )
    if result.get("result_digest") != evidence_sha:
        problems.append("oq_result.json result_digest does not re-derive from its body")
    for name, recorded, derived in (
        ("result_sha256", intent.result_sha256, result_sha),
        ("report_sha256", intent.report_sha256, report_sha),
        ("archive_manifest_sha256", intent.archive_manifest_sha256, manifest_sha),
        ("evidence_sha256", intent.evidence_sha256, evidence_sha),
        ("result_bundle_sha256", intent.result_bundle_sha256, bundle_sha),
        ("verdict", intent.verdict, result.get("verdict")),
    ):
        if recorded != derived:
            problems.append(f"intent {name} {recorded!r} != archive-derived {derived!r}")
    return problems


@contextmanager
def _finalize_lock(registry_path: Path) -> Iterator[None]:
    """Hold an exclusive lock for the read-assess-append critical section.

    Two concurrent ``recover --finalize`` invocations would otherwise each assess FINALIZABLE and
    each append a ``completed`` event, leaving two ordinal-2 lines that make the registry unreadable
    forever. The ``O_EXCL`` lock makes the second invocation fail closed instead of corrupting.
    """
    lock = registry_path.with_name(registry_path.name + ".finalize.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        raise OQCompletionIntentError(
            "another finalize holds the registry lock; refusing to double-finalize"
        ) from exc
    try:
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def _rebuild_completed(registry_path: Path, intent: OQCompletionIntent) -> OQEvent:
    """Deterministically re-append the recorded ``completed`` event; never recompute it."""
    hashes = intent.terminal_hashes()
    return append_oq_event(
        registry_path,
        identity=intent.identity,
        event=OQ_EVENT_COMPLETED,
        event_time_utc=intent.event_time_utc,
        reason=intent.reason,
        result_sha256=hashes["result_sha256"],
        report_sha256=hashes["report_sha256"],
        evidence_sha256=hashes["evidence_sha256"],
        archive_manifest_sha256=hashes["archive_manifest_sha256"],
        result_bundle_sha256=hashes["result_bundle_sha256"],
        verdict=intent.verdict,
    )


def assess(repo_root: str | Path, registry_path: str | Path) -> RecoveryStatus:
    """Report whether a pending OQ run can be finalized calculation-free (read-only)."""
    root = Path(repo_root)
    intent = read_completion_intent(root)
    if intent is None:
        return RecoveryStatus(STATE_NO_INTENT, "no pending completion intent; nothing to finalize")
    events = read_oq_registry(registry_path)
    stages = [event.event for event in events]
    if stages == [OQ_EVENT_REGISTERED, OQ_EVENT_STARTED, OQ_EVENT_COMPLETED]:
        return RecoveryStatus(
            STATE_ALREADY_FINALIZED,
            f"qualification {intent.qualification_id!r} is already completed; clear the intent",
        )
    if OQ_EVENT_FAILED in stages:
        return RecoveryStatus(
            STATE_FAILED,
            f"qualification {intent.qualification_id!r} is recorded failed (stages={stages}); id "
            "is consumed and cannot be finalized",
        )
    if stages != [OQ_EVENT_REGISTERED, OQ_EVENT_STARTED]:
        return RecoveryStatus(
            STATE_NOT_FINALIZABLE,
            f"registry is not registered->started (stages={stages})",
        )
    if events[-1].entry_hash != intent.prev_hash:
        return RecoveryStatus(
            STATE_NOT_FINALIZABLE,
            "the registry's started event is not the one the intent chains onto",
        )
    problems = _verify_artifacts(root, intent)
    if problems:
        return RecoveryStatus(
            STATE_NOT_FINALIZABLE,
            "the published archive is incomplete (publication did not finish before the crash): "
            + "; ".join(problems),
        )
    mismatches = _reconcile_intent_with_archive(root, intent)
    if mismatches:
        return RecoveryStatus(
            STATE_NOT_FINALIZABLE,
            "the completion intent does not reconcile with the published archive "
            "(refusing to append a completed event the archive cannot support): "
            + "; ".join(mismatches),
        )
    return RecoveryStatus(
        STATE_FINALIZABLE,
        f"qualification {intent.qualification_id!r} published and verified; ready to complete",
    )


def finalize(repo_root: str | Path, registry_path: str | Path) -> RecoveryStatus:
    """Finalize a crashed-but-published run by re-appending the recorded ``completed`` event.

    Calculation-free: it re-appends the deterministically-rebuilt event only when :func:`assess`
    reports the run finalizable, then clears the intent. If already completed it just clears the
    intent; otherwise it returns the non-finalizable assessment and appends nothing.
    """
    root = Path(repo_root)
    reg = Path(registry_path)
    # Hold an exclusive lock across assess-then-append so two concurrent finalizes cannot both
    # append a completed event (which would leave two ordinal-2 lines and brick the registry).
    with _finalize_lock(reg):
        status = assess(root, reg)
        if status.state == STATE_ALREADY_FINALIZED:
            clear_completion_intent(root)
            return status
        if status.state != STATE_FINALIZABLE:
            return status
        intent = read_completion_intent(root)
        if intent is None:  # pragma: no cover - just assessed finalizable
            raise OQCompletionIntentError(
                "completion intent vanished between assessment and finalize"
            )
        _rebuild_completed(reg, intent)
        clear_completion_intent(root)
        return RecoveryStatus(
            STATE_FINALIZED,
            f"re-appended the recorded completed event for {intent.qualification_id!r} "
            "(calculation-free)",
        )


__all__ = [
    "STATE_ALREADY_FINALIZED",
    "STATE_FAILED",
    "STATE_FINALIZABLE",
    "STATE_FINALIZED",
    "STATE_NOT_FINALIZABLE",
    "STATE_NO_INTENT",
    "RecoveryStatus",
    "assess",
    "finalize",
]
