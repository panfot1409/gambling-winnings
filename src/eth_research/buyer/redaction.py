"""The redaction policy and scanner: the buyer boundary's fail-closed safety gate.

Nothing reaches a buyer without passing this scanner. It rejects, by content, three classes of
leakage that must never appear in a diligence bundle:

* **secrets** — private-key blocks, cloud access keys, bearer tokens, ``key=value`` credential
  assignments;
* **embedded source** — a diligence artifact that contains program source (multiple Python source
  tokens), because the buyer boundary is deliberately source-free;
* **raw or sealed data** — embedded tabular market data or a sealed evaluation-ledger dump (an OHLCV
  header, a long numeric CSV row, or a large JSON array of numbers). Governance prose may *name* the
  sealed partitions; it may never carry their *data*.

The scanner is a pure function of the text it is given, so its verdicts are deterministic and
independently reproducible. A bundle is served only if the scan returns zero violations — the gate
is closed by default, opened only by an empty finding list.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from eth_research.v2.strict import V2ValidationError

# Only these artifact kinds may ever appear in a diligence bundle (structural allowlist).
ALLOWED_ARTIFACT_KINDS: frozenset[str] = frozenset(
    {"contract", "claims_catalog", "factsheet", "readiness_scorecard", "diligence_manifest"}
)

# The private-key header is written with ``-{5}`` (not five literal dashes) so this detector source
# does not itself trip the repo's private-key hygiene scan; it still matches a real PEM header.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key_block", re.compile(r"-{5}BEGIN [A-Z ]*PRIVATE KEY-{5}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("bearer_token", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}")),
    (
        "credential_assignment",
        re.compile(
            r"(?i)(api[_-]?key|secret|password|passwd|access[_-]?token|private[_-]?key"
            r"|credential|auth[_-]?token|session[_-]?token|passphrase)"
            r"\s*[:=]\s*['\"]?[A-Za-z0-9/+_\-]{12,}"
        ),
    ),
)

# Python source markers. Beyond keyword-lead lines (import/from/def/class/@), a bare assignment,
# ``return``, or ``lambda`` also indicates source — so an expression-only strategy formula trips.
# A SINGLE marker is enough (embedded source is never expected in a redacted artifact).
_SOURCE_TOKENS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^\s*import\s+\w"),
    re.compile(r"(?m)^\s*from\s+\w[\w.]*\s+import\s"),
    re.compile(r"(?m)^\s*def\s+\w+\s*\("),
    re.compile(r"(?m)^\s*class\s+\w+\s*[:(]"),
    re.compile(r"(?m)^\s*@\w+"),
    re.compile(r"(?m)^\s*[A-Za-z_]\w*\s*=[^=]"),
    re.compile(r"(?m)^\s*return\b"),
    re.compile(r"\blambda\b\s*[\w,\s]*:"),
)
_SOURCE_TOKEN_THRESHOLD: int = 1

# Raw/sealed tabular data: an OHLCV header, a long numeric CSV row, or a big JSON number array.
_RAW_DATA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ohlcv_header", re.compile(r"(?i)open\s*,\s*high\s*,\s*low\s*,\s*close")),
    (
        "numeric_csv_row",
        re.compile(r"(?m)^\s*[-+]?\d[\d.eE+\-]*(?:\s*,\s*[-+]?\d[\d.eE+\-]*){5,}\s*$"),
    ),
    ("numeric_json_array", re.compile(r"\[\s*[-+]?\d[\d.eE+\-]*(?:\s*,\s*[-+]?\d[\d.eE+\-]*){9,}")),
)


class RedactionError(V2ValidationError):
    """A redaction-policy value was malformed."""


@dataclass(frozen=True, slots=True)
class RedactionViolation:
    """One reason a piece of content may not cross the buyer boundary."""

    artifact: str
    category: str
    detail: str

    def to_canonical(self) -> dict[str, object]:
        return {"artifact": self.artifact, "category": self.category, "detail": self.detail}


def scan_text(artifact: str, text: str) -> list[RedactionViolation]:
    """Return every redaction violation in ``text`` (empty list == safe to disclose)."""
    violations: list[RedactionViolation] = []

    for name, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            violations.append(RedactionViolation(artifact=artifact, category="secret", detail=name))

    source_hits = sum(1 for token in _SOURCE_TOKENS if token.search(text))
    if source_hits >= _SOURCE_TOKEN_THRESHOLD:
        violations.append(
            RedactionViolation(
                artifact=artifact,
                category="embedded_source",
                detail=f"{source_hits} source tokens present",
            )
        )

    for name, pattern in _RAW_DATA_PATTERNS:
        if pattern.search(text):
            violations.append(
                RedactionViolation(artifact=artifact, category="raw_data", detail=name)
            )

    return violations


def _scan_json_string_values(artifact: str, text: str) -> list[RedactionViolation]:
    """Also scan the decoded string *values* of a JSON artifact (B1/B3).

    Canonical JSON places each string value on one physical line, so a line-anchored detector (an
    assignment-style source line, a numeric CSV row) can be evaded by smuggling content *inside* a
    string. Decoding and scanning every string value standalone closes that gap. Non-JSON text is
    left to the raw scan above.
    """
    try:
        decoded = json.loads(text)
    except (ValueError, TypeError):
        return []
    violations: list[RedactionViolation] = []
    stack: list[object] = [decoded]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            violations.extend(scan_text(artifact, node))
        elif isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return violations


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    """The kinds a bundle may contain and the scan every artifact must pass."""

    allowed_kinds: frozenset[str]

    @staticmethod
    def current() -> RedactionPolicy:
        return RedactionPolicy(allowed_kinds=ALLOWED_ARTIFACT_KINDS)

    def check_kind(self, artifact: str, kind: str) -> list[RedactionViolation]:
        if kind not in self.allowed_kinds:
            return [
                RedactionViolation(
                    artifact=artifact,
                    category="forbidden_kind",
                    detail=f"{kind!r} is not an allowed diligence kind",
                )
            ]
        return []

    def scan_artifact(self, artifact: str, kind: str, text: str) -> list[RedactionViolation]:
        """Kind-allowlist check + raw content scan + decoded-JSON-value scan for one artifact."""
        return [
            *self.check_kind(artifact, kind),
            *scan_text(artifact, text),
            *_scan_json_string_values(artifact, text),
        ]
