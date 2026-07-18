#!/usr/bin/env python3
"""Deterministic lexical + structural secret scanner (stdlib only, no network).

A supply-chain hygiene gate for the PRIVATE ``eth-research`` distribution: it reads bytes
(a repository file, or a wheel / sdist / payload member) and fails closed if a credential
material pattern appears. It is deliberately narrow and high-precision — it is one layer,
paired with ``tools/scan_distribution.py`` (member allowlist) and
``tests/test_public_publication_killswitch.py`` (publication-vector scan), not a proof that
no secret exists.

Detectors (each reports a REDACTED fingerprint only — never the raw match):

* ``pem_private_key`` — dash-wrapped ``BEGIN [RSA|EC|OPENSSH|DSA|ENCRYPTED] PRIVATE KEY`` headers.
* ``pgp_private_key`` — dash-wrapped ``BEGIN PGP PRIVATE KEY BLOCK`` headers.
* ``aws_access_key_id`` — ``AKIA``/``ASIA`` + 16 upper-alphanumeric.
* ``aws_secret_access_key`` — an exactly-40-char base64 run that is high-entropy AND mixes
  upper/lower/digit AND is not pure hex (so a 64-hex SHA-256 digest, a 40-hex git SHA, or a
  wheel ``RECORD`` url-safe-base64 hash — which is 43 chars and uses ``-``/``_`` — never trips).
* ``github_token`` — ``gh[pousr]_`` + 36+ base62.
* ``slack_token`` — ``xox[baprs]-`` tokens.
* ``secret_assignment`` — ``password``/``secret``/``api_key``/``token``-style assignments to a
  quoted, whitespace-free, non-placeholder, credential-shaped literal.

SELF-SCAN SAFETY. Every secret-shaped literal in this file is assembled from fragments, so
this source contains no contiguous string that any detector matches — scanning this very file
yields zero findings (``tests/test_secret_scanner.py`` asserts it). Redaction is structural:
a :class:`Finding` stores only ``<detector>:sha256:<12 hex>`` and never the raw secret, so no
output, log, or repr can leak the material it found.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------- #
# fragment assembly — keep this source free of any contiguous matchable secret #
# --------------------------------------------------------------------------- #
_D5 = "-" * 5
_BEGIN = _D5 + "BEGIN "
_PRIVATE_KEY = "PRIVATE" + " " + "KEY"
_AKIA = "A" + "KIA"
_ASIA = "A" + "SIA"

# --------------------------------------------------------------------------- #
# structural detector patterns                                                 #
# --------------------------------------------------------------------------- #
_PEM_RE = re.compile(_BEGIN + r"(?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?" + _PRIVATE_KEY + _D5)
_PGP_RE = re.compile(_BEGIN + "PGP " + _PRIVATE_KEY + " BLOCK" + _D5)
_AWS_KEY_ID_RE = re.compile(r"\b(?:" + _AKIA + "|" + _ASIA + r")[0-9A-Z]{16}\b")
_GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")
_SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")

# A *maximal* base64-family run (standard ``+/`` plus url-safe ``-_``), matched greedily so a
# longer blob is never sliced into a spurious 40-window. :func:`_is_aws_secret` then requires the
# whole run to be exactly 40 standard-base64 chars, so a 64-hex SHA-256 digest (64), a 40-hex git
# SHA (rejected by diversity/not-hex), and a wheel ``RECORD`` url-safe hash (43 chars, and carries
# ``-``/``_``) all fall out.
_B64_RUN_RE = re.compile(r"[A-Za-z0-9+/_-]{40,}")

# ``<optional_identifier_prefix><keyword> = "<value>"`` — the prefix lets ``client_secret`` /
# ``confirm_token`` match; ``(?i)`` makes the lowercase classes case-insensitive.
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)(?:^|[^0-9A-Za-z_])"
    r"(?:[0-9a-z_]*_)?"
    r"(?:password|passwd|pwd|secret|api[_-]?key|apikey|api[_-]?token|auth[_-]?token|"
    r"access[_-]?token|access[_-]?key|secret[_-]?key|client[_-]?secret|token)"
    r"\s*[:=]\s*"
    r"(?P<q>[\"'])(?P<val>[^\"'\s]{8,})(?P=q)"
)

# Substrings that mark an assignment value as an obvious placeholder rather than a live secret.
_PLACEHOLDER_SUBSTRINGS = (
    "example",
    "placeholder",
    "changeme",
    "change-me",
    "change_me",
    "your-",
    "your_",
    "yourtoken",
    "redact",
    "dummy",
    "fake",
    "sample",
    "xxxx",
    "todo",
    "insert",
    "replace",
    "<",
    ">",
    "{",
    "}",
    "...",
    "****",
    "password",
    "secret",
    "token",
    "apikey",
    "api_key",
    "0000",
)


@dataclass(frozen=True)
class Finding:
    """One detection. Carries a redacted fingerprint only — never the raw secret."""

    detector: str
    name: str
    line: int
    fingerprint: str

    def __str__(self) -> str:
        return f"{self.name}:{self.line}: [{self.detector}] {self.fingerprint}"


def _fingerprint(detector: str, match: str) -> str:
    """A stable, non-reversible label: detector id + a SHA-256 prefix of the raw match."""
    return f"{detector}:sha256:{hashlib.sha256(match.encode('utf-8')).hexdigest()[:12]}"


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


_HEX_CHARS = frozenset("0123456789abcdefABCDEF")
_SYMBOLS = frozenset("/+=._-")


def _is_aws_secret(match: str) -> bool:
    # An AWS secret access key is exactly 40 standard-base64 chars. A longer maximal run (a RECORD
    # hash, a SHA-256 digest, a file path) is therefore not one; url-safe ``-``/``_`` rules out a
    # wheel RECORD hash even at length 40.
    if len(match) != 40 or any(c in "-_" for c in match):
        return False
    has_lower = any(c.islower() for c in match)
    has_upper = any(c.isupper() for c in match)
    has_digit = any(c.isdigit() for c in match)
    if not (has_lower and has_upper and has_digit):
        return False
    if all(c in _HEX_CHARS for c in match):
        return False
    return _shannon_entropy(match) >= 4.0


def _is_placeholder(value: str) -> bool:
    low = value.lower()
    if len(set(value)) <= 2:
        return True
    return any(sub in low for sub in _PLACEHOLDER_SUBSTRINGS)


def _looks_credential(value: str) -> bool:
    has_digit = any(c.isdigit() for c in value)
    has_lower = any(c.islower() for c in value)
    has_upper = any(c.isupper() for c in value)
    has_symbol = any(c in _SYMBOLS for c in value)
    return has_digit or (has_lower and has_upper) or has_symbol or len(value) >= 20


def _valid_secret_assignment(value: str) -> bool:
    return not _is_placeholder(value) and _looks_credential(value)


# id, compiled pattern, optional validator over the matched text, group to fingerprint.
_STRUCTURAL: tuple[tuple[str, re.Pattern[str], Callable[[str], bool] | None], ...] = (
    ("pem_private_key", _PEM_RE, None),
    ("pgp_private_key", _PGP_RE, None),
    ("aws_access_key_id", _AWS_KEY_ID_RE, None),
    ("aws_secret_access_key", _B64_RUN_RE, _is_aws_secret),
    ("github_token", _GITHUB_TOKEN_RE, None),
    ("slack_token", _SLACK_TOKEN_RE, None),
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def scan_text(name: str, text: str) -> list[Finding]:
    """Scan already-decoded ``text``; return sorted, redacted findings."""
    findings: list[Finding] = []
    for detector, pattern, validator in _STRUCTURAL:
        for m in pattern.finditer(text):
            matched = m.group(0)
            if validator is not None and not validator(matched):
                continue
            findings.append(
                Finding(detector, name, _line_of(text, m.start()), _fingerprint(detector, matched))
            )
    for m in _SECRET_ASSIGN_RE.finditer(text):
        value = m.group("val")
        if not _valid_secret_assignment(value):
            continue
        findings.append(
            Finding(
                "secret_assignment",
                name,
                _line_of(text, m.start("val")),
                _fingerprint("secret_assignment", value),
            )
        )
    findings.sort(key=lambda f: (f.name, f.line, f.detector, f.fingerprint))
    return findings


def scan_bytes(name: str, data: bytes) -> list[Finding]:
    """Scan raw ``data`` under logical ``name``; return sorted, redacted findings.

    Decodes latin-1 (a total, lossless byte->codepoint map) so arbitrary binary never raises and
    every ASCII secret pattern is still visible.
    """
    return scan_text(name, data.decode("latin-1"))


# --------------------------------------------------------------------------- #
# filesystem traversal                                                         #
# --------------------------------------------------------------------------- #
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".idea",
        ".vscode",
        "dist_private",
        "build",
        "dist",
        ".eggs",
        ".tox",
        ".nox",
    }
)
_MAX_FILE_BYTES = 20 * 1024 * 1024


def _iter_files(path: Path) -> Iterator[Path]:
    if path.is_file():
        yield path
        return
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for filename in sorted(filenames):
            yield Path(dirpath) / filename


def scan_paths(paths: Iterable[str | os.PathLike[str]]) -> list[Finding]:
    """Scan every file under each path (directories walked, noise dirs pruned). Sorted findings."""
    findings: list[Finding] = []
    for raw in paths:
        base = Path(raw)
        for file_path in _iter_files(base):
            try:
                if file_path.stat().st_size > _MAX_FILE_BYTES:
                    continue
                data = file_path.read_bytes()
            except OSError:
                continue
            name = file_path.as_posix()
            findings.extend(scan_bytes(name, data))
    findings.sort(key=lambda f: (f.name, f.line, f.detector, f.fingerprint))
    return findings


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic, redacting secret scanner (stdlib only)."
    )
    parser.add_argument("--repo-root", default=".", help="default target when none is given")
    parser.add_argument("targets", nargs="*", help="files or directories to scan")
    args = parser.parse_args(argv)

    targets: list[str] = list(args.targets) or [args.repo_root]
    findings = scan_paths(targets)
    for finding in findings:
        sys.stderr.write(f"{finding}\n")
    if findings:
        sys.stderr.write(f"secret scan FAILED: {len(findings)} finding(s)\n")
        return 1
    sys.stdout.write(f"secret scan clean: {', '.join(targets)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
