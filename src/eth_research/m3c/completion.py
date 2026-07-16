"""Crash-recoverable completion intent for the M3C run publication.

The orchestrator publishes the four immutable artifacts (results JSON, report
Markdown, decision JSON, manifest) as one durable transaction, then appends the
``completed`` registry event. A crash in the narrow window *after* publication
but *before* that append would leave the registry stuck at ``started`` with a
fully published, verified archive on disk and no way to finalize without
re-running the whole experiment — and, worse, the orchestrator's blanket failure
handler would record an honest-looking ``failed`` event that *mislabels a
published success*.

To make that window recoverable without any recomputation, the orchestrator
writes this completion intent durably *before* it publishes: it records the exact
``completed`` event bytes it will append and the SHA-256 of every file the
publication writes. The calculation-free finalizer (:mod:`eth_research.m3c.recovery`)
can then verify that every recorded artifact is present on disk with the recorded
bytes and that the registry is still exactly ``registered`` → ``started`` for this
id (with the started line the intent chains onto), and append the recorded
``completed`` event. On a clean run the orchestrator clears the intent immediately
after the append, so its mere presence signals an unfinalized run.

The recorded ``completed`` line is validated on both write and read: it must parse
as a ``completed`` :class:`M3CRegistryEvent` for the recorded experiment id whose
``previous_event_sha256`` equals the recorded chain value, and the recorded
artifact digests must agree with the results / report / decision digests the event
itself certifies (cross-bound through the event's own immutable artifact paths), so
the intent can never name one run and carry another's completion.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.provenance import sha256_bytes
from eth_research.m3c.registry import EVENT_COMPLETED, M3CRegistryEvent
from eth_research.m3c.validation import require_hex64, require_int, require_nonempty_str
from eth_research.publication import durable_remove, durable_write_bytes

M3C_COMPLETION_INTENT_RELPATH: str = "research/m3c/completion_intent.json"
M3C_COMPLETION_INTENT_SCHEMA_VERSION: int = 1

_INTENT_KEYS: frozenset[str] = frozenset(
    {
        "completion_intent_schema_version",
        "experiment_id",
        "completed_event_line_b64",
        "completed_event_sha256",
        "previous_event_sha256",
        "artifacts",
    }
)
_ARTIFACT_KEYS: frozenset[str] = frozenset({"relpath", "sha256"})


class CompletionIntentError(RuntimeError):
    """The completion intent is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class CompletionArtifact:
    """One published file the finalizer must find on disk with these bytes."""

    relpath: str
    sha256: str

    def __post_init__(self) -> None:
        require_nonempty_str("relpath", self.relpath)
        require_hex64("sha256", self.sha256)


@dataclass(frozen=True)
class CompletionIntent:
    """The durable record that lets a crashed run be finalized calculation-free."""

    experiment_id: str
    completed_event_line: bytes  # exact registry-line JSON bytes, no trailing newline
    previous_event_sha256: str
    artifacts: tuple[CompletionArtifact, ...]

    def __post_init__(self) -> None:
        require_nonempty_str("experiment_id", self.experiment_id)
        require_hex64("previous_event_sha256", self.previous_event_sha256)
        if not isinstance(self.completed_event_line, bytes) or not self.completed_event_line:
            raise CompletionIntentError("completed_event_line must be non-empty bytes")
        try:
            event = M3CRegistryEvent.from_json_line(self.completed_event_line + b"\n")
        except ValueError as exc:
            raise CompletionIntentError(
                f"completed_event_line is not a valid registry event: {exc}"
            ) from exc
        if event.event != EVENT_COMPLETED:
            raise CompletionIntentError("completed_event_line is not a 'completed' event")
        if event.experiment_id != self.experiment_id:
            raise CompletionIntentError(
                "completed_event_line experiment id disagrees with the intent"
            )
        if event.previous_event_sha256 != self.previous_event_sha256:
            raise CompletionIntentError(
                "completed_event_line previous_event_sha256 disagrees with the intent"
            )
        if not self.artifacts:
            raise CompletionIntentError("a completion intent must record at least one artifact")
        # Cross-bind the recorded artifact digests to the ones the 'completed' event
        # itself certifies, keyed by the event's OWN immutable artifact paths, so a
        # hand-crafted intent cannot pair on-disk artifacts with an event carrying
        # different result digests and be finalized.
        by_relpath = {a.relpath: a.sha256 for a in self.artifacts}
        for path, certified, label in (
            (event.immutable_results_path, event.results_json_sha256, "results"),
            (event.immutable_report_path, event.report_markdown_sha256, "report"),
            (event.immutable_decision_path, event.decision_json_sha256, "decision"),
        ):
            if by_relpath.get(path) != certified:
                raise CompletionIntentError(
                    f"recorded {label} digest disagrees with the completed event"
                )

    @property
    def completed_event(self) -> M3CRegistryEvent:
        """Re-parse the recorded ``completed`` event (validated on construction)."""
        return M3CRegistryEvent.from_json_line(self.completed_event_line + b"\n")

    @property
    def completed_event_sha256(self) -> str:
        return sha256_bytes(self.completed_event_line)

    def to_json_bytes(self) -> bytes:
        payload = {
            "completion_intent_schema_version": M3C_COMPLETION_INTENT_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "completed_event_line_b64": base64.b64encode(self.completed_event_line).decode("ascii"),
            "completed_event_sha256": self.completed_event_sha256,
            "previous_event_sha256": self.previous_event_sha256,
            "artifacts": [{"relpath": a.relpath, "sha256": a.sha256} for a in self.artifacts],
        }
        text = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, data: bytes) -> CompletionIntent:
        try:
            payload: Any = strict_json_loads(data)
        except StrictJSONError as exc:
            raise CompletionIntentError(f"completion intent is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict) or set(payload) != _INTENT_KEYS:
            raise CompletionIntentError("completion intent keys do not match the schema")
        version = require_int(
            "completion_intent_schema_version", payload["completion_intent_schema_version"]
        )
        if version != M3C_COMPLETION_INTENT_SCHEMA_VERSION:
            raise CompletionIntentError(f"unsupported completion intent version {version!r}")
        encoded = require_nonempty_str(
            "completed_event_line_b64", payload["completed_event_line_b64"]
        )
        try:
            line = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CompletionIntentError(
                f"completed_event_line_b64 is not valid base64: {exc}"
            ) from exc
        recorded_sha = require_hex64("completed_event_sha256", payload["completed_event_sha256"])
        if sha256_bytes(line) != recorded_sha:
            raise CompletionIntentError(
                "completed_event_sha256 does not match the recorded completed_event_line"
            )
        raw_artifacts = payload["artifacts"]
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise CompletionIntentError("artifacts must be a non-empty list")
        artifacts: list[CompletionArtifact] = []
        for item in raw_artifacts:
            if not isinstance(item, dict) or set(item) != _ARTIFACT_KEYS:
                raise CompletionIntentError("each artifact must have exactly relpath and sha256")
            artifacts.append(
                CompletionArtifact(
                    relpath=require_nonempty_str("relpath", item["relpath"]),
                    sha256=require_hex64("sha256", item["sha256"]),
                )
            )
        return cls(
            experiment_id=require_nonempty_str("experiment_id", payload["experiment_id"]),
            completed_event_line=line,
            previous_event_sha256=require_hex64(
                "previous_event_sha256", payload["previous_event_sha256"]
            ),
            artifacts=tuple(artifacts),
        )


def write_completion_intent(repo_root: str | Path, intent: CompletionIntent) -> None:
    """Durably write the completion intent to its canonical path."""
    durable_write_bytes(Path(repo_root) / M3C_COMPLETION_INTENT_RELPATH, intent.to_json_bytes())


def read_completion_intent(repo_root: str | Path) -> CompletionIntent | None:
    """Read and strictly parse the completion intent, or ``None`` if absent."""
    path = Path(repo_root) / M3C_COMPLETION_INTENT_RELPATH
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise CompletionIntentError("completion intent must be a real regular file")
    return CompletionIntent.from_json_bytes(path.read_bytes())


def clear_completion_intent(repo_root: str | Path) -> None:
    """Durably remove the completion intent (idempotent)."""
    durable_remove(Path(repo_root) / M3C_COMPLETION_INTENT_RELPATH)
