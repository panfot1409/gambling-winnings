"""V2C sections 17-18: the crash-recoverable OQ completion intent.

At OQ-P the orchestrator publishes the immutable archive and then appends the registry's
``completed`` event. A crash in the window *after* publication but *before* that append would strand
at ``started`` with a fully published archive and no way to finalize without re-executing the whole
qualification. To make that window recoverable without any recomputation, the runner writes this
completion intent durably *before* it publishes: it records the exact identity, event time, reason,
verdict, and five terminal digests of the ``completed`` event it will append, together with the byte
SHA-256 of every artifact the publication writes.

The calculation-free finalizer (:mod:`eth_research.v2c.oq.finalize`) can then verify that every
recorded artifact is present with the recorded bytes and that the registry is still exactly
``registered`` -> ``started`` for this id (chaining onto the recorded started hash), and re-append
the identical ``completed`` event -- deterministically rebuilt from the recorded fields, not
recomputed from the run. On a clean run the runner clears the intent immediately after the append,
so its mere presence signals an unfinalized run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.m3d.validation import M3DValidationError
from eth_research.publication import durable_remove, durable_write_bytes
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    require_exact_keys,
    require_hex64,
    require_mapping,
    require_nonempty_str,
    strict_json_loads,
)
from eth_research.v2c.oq.archive import (
    OQ_ARCHIVE_MANIFEST_RELNAME,
    OQ_ARCHIVE_REPORT_RELNAME,
    OQ_ARCHIVE_RESULT_RELNAME,
    OQArchive,
    archive_artifact_digests,
    archive_relpath,
)
from eth_research.v2c.oq.registry import (
    OQ_VERDICT_NOT_QUALIFIED,
    OQ_VERDICT_QUALIFIED,
    QualificationIdentity,
)

OQ_COMPLETION_INTENT_RELPATH: str = "governance/v2c/oq_completion_intent.json"
OQ_COMPLETION_INTENT_SCHEMA_VERSION: int = 1

_COMPLETED_VERDICTS: frozenset[str] = frozenset({OQ_VERDICT_QUALIFIED, OQ_VERDICT_NOT_QUALIFIED})
_TERMINAL_HASH_FIELDS: tuple[str, ...] = (
    "result_sha256",
    "report_sha256",
    "evidence_sha256",
    "archive_manifest_sha256",
    "result_bundle_sha256",
)
_INTENT_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "qualification_id",
        "identity",
        "event_time_utc",
        "reason",
        "verdict",
        "prev_hash",
        "artifacts",
        *_TERMINAL_HASH_FIELDS,
    }
)

#: The exact set of relpaths a completion intent may name -- the three published archive artifacts
#: and nothing else. Binding to the known relpaths (not a ``startswith`` prefix) makes a ``..``
#: traversal or any out-of-archive path structurally impossible: the finalizer reads only these.
_ALLOWED_ARTIFACT_RELPATHS: frozenset[str] = frozenset(
    archive_relpath(relname)
    for relname in (
        OQ_ARCHIVE_RESULT_RELNAME,
        OQ_ARCHIVE_REPORT_RELNAME,
        OQ_ARCHIVE_MANIFEST_RELNAME,
    )
)


class OQCompletionIntentError(V2ValidationError):
    """The OQ completion intent is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class OQCompletionIntent:
    """The durable record that lets a crashed-but-published OQ run be finalized calculation-free."""

    qualification_id: str
    identity: QualificationIdentity
    event_time_utc: str
    reason: str
    verdict: str
    result_sha256: str
    report_sha256: str
    evidence_sha256: str
    archive_manifest_sha256: str
    result_bundle_sha256: str
    prev_hash: str
    artifacts: tuple[tuple[str, str], ...]  # (relpath, sha256), sorted

    def terminal_hashes(self) -> dict[str, str]:
        return {field: getattr(self, field) for field in _TERMINAL_HASH_FIELDS}

    def to_json_bytes(self) -> bytes:
        payload: dict[str, Any] = {
            "schema_version": OQ_COMPLETION_INTENT_SCHEMA_VERSION,
            "qualification_id": self.qualification_id,
            "identity": self.identity.as_map(),
            "event_time_utc": self.event_time_utc,
            "reason": self.reason,
            "verdict": self.verdict,
            "prev_hash": self.prev_hash,
            "artifacts": [list(pair) for pair in self.artifacts],
            **self.terminal_hashes(),
        }
        return canonical_json_bytes(payload)

    @classmethod
    def from_json_bytes(cls, data: bytes) -> OQCompletionIntent:
        try:
            payload = require_mapping("oq_completion_intent", strict_json_loads(data))
        except (V2ValidationError, M3DValidationError) as exc:
            # strict_json_loads raises StrictJSONError (the M3D ValueError tree), not
            # V2ValidationError -- catch both so a dup-key/NaN/bad-UTF-8 intent surfaces as the
            # advertised OQCompletionIntentError, never a raw StrictJSONError.
            raise OQCompletionIntentError(str(exc)) from exc
        require_exact_keys("oq_completion_intent", payload, _INTENT_KEYS)
        if payload["schema_version"] != OQ_COMPLETION_INTENT_SCHEMA_VERSION:
            raise OQCompletionIntentError("unsupported oq completion intent schema_version")
        verdict = require_nonempty_str("verdict", payload["verdict"])
        if verdict not in _COMPLETED_VERDICTS:
            raise OQCompletionIntentError(f"unknown completion verdict {verdict!r}")
        raw_artifacts = payload["artifacts"]
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise OQCompletionIntentError("artifacts must be a non-empty list")
        artifacts: list[tuple[str, str]] = []
        for item in raw_artifacts:
            if not isinstance(item, list) or len(item) != 2:
                raise OQCompletionIntentError("each artifact must be a [relpath, sha256] pair")
            relpath = require_nonempty_str("artifact.relpath", item[0])
            if relpath not in _ALLOWED_ARTIFACT_RELPATHS:
                raise OQCompletionIntentError(
                    f"artifact {relpath!r} is not one of the published archive artifacts "
                    "(a path-traversal or out-of-archive relpath is refused)"
                )
            artifacts.append((relpath, require_hex64("artifact.sha256", item[1])))
        return cls(
            qualification_id=require_nonempty_str("qualification_id", payload["qualification_id"]),
            identity=QualificationIdentity.parse(
                "identity", require_mapping("identity", payload["identity"])
            ),
            event_time_utc=require_nonempty_str("event_time_utc", payload["event_time_utc"]),
            reason=require_nonempty_str("reason", payload["reason"]),
            verdict=verdict,
            result_sha256=require_hex64("result_sha256", payload["result_sha256"]),
            report_sha256=require_hex64("report_sha256", payload["report_sha256"]),
            evidence_sha256=require_hex64("evidence_sha256", payload["evidence_sha256"]),
            archive_manifest_sha256=require_hex64(
                "archive_manifest_sha256", payload["archive_manifest_sha256"]
            ),
            result_bundle_sha256=require_hex64(
                "result_bundle_sha256", payload["result_bundle_sha256"]
            ),
            prev_hash=require_hex64("prev_hash", payload["prev_hash"]),
            artifacts=tuple(sorted(artifacts)),
        )


def build_completion_intent(
    archive: OQArchive,
    *,
    identity: QualificationIdentity,
    event_time_utc: str,
    reason: str,
    prev_hash: str,
) -> OQCompletionIntent:
    """Build the completion intent from a published archive and the started event's hash chain.

    Cross-binds the recorded artifact digests to the archive's terminal hashes so a hand-crafted
    intent cannot pair on-disk artifacts with a mismatched completed event.
    """
    if archive.qualification_id != identity.qualification_id:
        raise OQCompletionIntentError("archive qualification id disagrees with the identity")
    digests = archive_artifact_digests(archive)
    return OQCompletionIntent(
        qualification_id=identity.qualification_id,
        identity=identity,
        event_time_utc=event_time_utc,
        reason=reason,
        verdict=archive.verdict,
        result_sha256=archive.result_sha256,
        report_sha256=archive.report_sha256,
        evidence_sha256=archive.evidence_sha256,
        archive_manifest_sha256=archive.archive_manifest_sha256,
        result_bundle_sha256=archive.result_bundle_sha256,
        prev_hash=require_hex64("prev_hash", prev_hash),
        artifacts=tuple(sorted(digests.items())),
    )


def write_completion_intent(repo_root: str | Path, intent: OQCompletionIntent) -> None:
    """Durably write the completion intent to its canonical governance path."""
    durable_write_bytes(Path(repo_root) / OQ_COMPLETION_INTENT_RELPATH, intent.to_json_bytes())


def read_completion_intent(repo_root: str | Path) -> OQCompletionIntent | None:
    """Read and strictly parse the completion intent, or ``None`` if absent."""
    path = Path(repo_root) / OQ_COMPLETION_INTENT_RELPATH
    if path.is_symlink():
        raise OQCompletionIntentError("completion intent must not be a symlink")
    if not path.exists():
        return None
    if not path.is_file():
        raise OQCompletionIntentError("completion intent must be a real regular file")
    return OQCompletionIntent.from_json_bytes(path.read_bytes())


def clear_completion_intent(repo_root: str | Path) -> None:
    """Durably remove the completion intent (idempotent)."""
    durable_remove(Path(repo_root) / OQ_COMPLETION_INTENT_RELPATH)


__all__ = [
    "OQ_COMPLETION_INTENT_RELPATH",
    "OQCompletionIntent",
    "OQCompletionIntentError",
    "build_completion_intent",
    "clear_completion_intent",
    "read_completion_intent",
    "write_completion_intent",
]
