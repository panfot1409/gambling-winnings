"""Lexical honesty guards over the trust-boundary claim.

Two obligations, both mechanical so neither can quietly rot:

* the exact trust-boundary sentence must be present verbatim, and every
  qualification it depends on must be stated alongside it. A claim whose caveats
  drift away from it stops being the claim that was reviewed;
* the forbidden absolutes must not appear as assertions anywhere in the tree.

The second check needs care, because the same words legitimately appear in three
places: negations ("tamper-evident, not tamper-proof"), errata that exist
precisely to retract an earlier overclaim, and append-only historical records
whose whole purpose is to preserve what was wrongly said at the time. Those are
allowlisted individually with a reason, never by pattern — an allowlist that
matched on wildcards would let a genuinely new overclaim in through the same
door.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = REPO_ROOT / "src/eth_research/m3e/proposal_authority.py"

#: The claim, verbatim. Whitespace-normalised before comparison because the
#: source wraps it across lines, but not otherwise relaxed.
REQUIRED_CLAIM = (
    "Operationally tamper-evident relative to pinned historical Git objects, "
    "committed verifier source, source-freeze enforcement, exact closed-file-set "
    "policy and protected review."
)

#: Every qualification the claim depends on. Dropping any one of them turns the
#: sentence into an overclaim by omission.
REQUIRED_QUALIFICATIONS = (
    "not cryptographic remote attestation",
    "not tamper-proof",
    "rewrite trusted history, verifier source, freeze authority and review controls together",
    "do not constitute three external trust anchors",
    "implementation diversity",
    "mutable-data editing",
    "reviewed source or history modification",
)

FORBIDDEN = (
    "tamper-proof",
    "unforgeable",
    "impossible to alter",
    "cryptographically guaranteed",
    "independently anchored",
)

#: (relpath, reason). Each entry is a specific file whose use of a forbidden word
#: is a negation, a retraction, or an append-only historical record. Adding to
#: this list requires stating which of those three it is.
ALLOWLIST: dict[str, str] = {
    "docs/M3F_THREAT_MODEL.md": "negation: 'tamper-evident, not tamper-proof'",
    "docs/V2E_STACK_ACCEPTANCE_AUDIT.md": (
        "negation: records that the word is NOT used about this system"
    ),
    "docs/V2AB_STACK_ACCEPTANCE_ERRATA.md": (
        "retraction: erratum E-4 exists to withdraw the 'unforgeable' overclaim"
    ),
    "docs/M3A_RUN003_TERMINAL_PLAN.md": (
        "retraction: defect N1 records that the 'unforgeable' authorization is forgeable"
    ),
    "docs/M3A_CLOSURE_REMEDIATION.md": "append-only historical record, superseded by N1",
    "docs/M3A_BUG_LOG.md": "append-only historical record, superseded by N1",
    "docs/M3A_CLOSURE_AUDIT.md": "append-only historical record, superseded by N1",
    "docs/V2AB_STACK_ACCEPTANCE_PLAN.md": "append-only historical record, corrected by E-4",
    "src/eth_research/development_orchestrator.py": (
        "negation: 'NOT an unforgeable capability', with the reason it is not"
    ),
    "src/eth_research/m3e/proposal_authority.py": (
        "negation: states the forbidden words in order to disclaim them"
    ),
    "tests/test_v2e_trust_boundary_language.py": "this file defines the forbidden list",
}

SEARCHED_SUFFIXES = {".py", ".md", ".json", ".yml", ".yaml", ".toml", ".cff"}
SKIPPED_DIRS = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _tracked_files() -> list[Path]:
    found: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SEARCHED_SUFFIXES:
            continue
        if any(part in SKIPPED_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        found.append(path)
    return found


def test_the_trust_boundary_claim_is_present_verbatim() -> None:
    assert _normalise(REQUIRED_CLAIM) in _normalise(AUTHORITY.read_text())


def test_every_qualification_accompanies_the_claim() -> None:
    body = _normalise(AUTHORITY.read_text())
    missing = [q for q in REQUIRED_QUALIFICATIONS if _normalise(q) not in body]
    assert not missing, (
        "the trust-boundary claim is stated without its qualifications: " + ", ".join(missing)
    )


def test_no_file_asserts_a_forbidden_absolute() -> None:
    offenders: list[str] = []
    for path in _tracked_files():
        relpath = path.relative_to(REPO_ROOT).as_posix()
        if relpath in ALLOWLIST:
            continue
        lowered = path.read_text(errors="replace").lower()
        for word in FORBIDDEN:
            if word in lowered:
                offenders.append(f"{relpath}: {word!r}")
    assert not offenders, "forbidden absolute claim(s) outside the allowlist:\n  " + "\n  ".join(
        offenders
    )


def test_every_allowlist_entry_is_real_and_still_needed() -> None:
    """An allowlist that outlives its reason is a hole with a comment on it."""
    stale: list[str] = []
    for relpath, reason in ALLOWLIST.items():
        path = REPO_ROOT / relpath
        if not path.is_file():
            stale.append(f"{relpath}: allowlisted but does not exist")
            continue
        lowered = path.read_text(errors="replace").lower()
        if not any(word in lowered for word in FORBIDDEN):
            stale.append(f"{relpath}: allowlisted ({reason}) but contains no forbidden word")
    assert not stale, "stale allowlist entries:\n  " + "\n  ".join(stale)
