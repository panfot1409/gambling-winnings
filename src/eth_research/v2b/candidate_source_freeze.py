"""Candidate SOURCE FREEZE — the pre-registration checkpoint that fixes the two V2B
cross-asset candidate families, their primary parameters, and the governing source
BEFORE the first real BTC byte enters the branch (Milestone V2B sections 7-9).

The freeze binds two independent things:

* the **semantic pre-registration** — each candidate's ``ResearchFamilyIdentity``
  fingerprint, its fixed primary parameters, and the whole-set fingerprint (the
  scientific claim of *what* is being tested); and
* the **source provenance** — the SHA-256 of the candidate/eligibility/identity source
  modules and the frozen hypothesis review (the *how*), so a later reader can prove the
  candidate logic and parameters were fixed on synthetic-only reasoning, before any real
  BTC price was acquired.

``verify_candidate_source_freeze`` re-derives both from the live tree and refuses any
drift. It is committed *before* the acquisition commit, so git history alone witnesses
that the candidates predate the data; this artifact makes that binding explicit and
machine-checkable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    sha256_bytes,
)
from eth_research.v2b.candidates import V2B_CANDIDATES

CANDIDATE_SOURCE_FREEZE_RELPATH = "research/v2b/candidate_source_freeze.json"
CANDIDATE_SOURCE_FREEZE_SCHEMA_VERSION = 1

# The exact source that defines the candidate logic, its eligibility (new-information)
# gate, and the family identity — hashed so a reader can prove the logic was fixed first.
_FROZEN_SOURCE_RELPATHS: tuple[str, ...] = (
    "src/eth_research/v2b/candidates.py",
    "src/eth_research/v2b/multiplicity.py",
    "src/eth_research/v2b/research_memory.py",
)
_HYPOTHESIS_REVIEW_RELPATH = "docs/V2B_HYPOTHESIS_REVIEW.md"

_FREEZE_STATEMENT = (
    "The two V2B cross-asset candidate families, their primary parameters, and the "
    "candidate/eligibility/identity source were fixed on synthetic-only reasoning and the "
    "frozen hypothesis review before the first real BTC observation was acquired. No real "
    "BTC price informed the candidate logic or parameters."
)


class CandidateSourceFreezeError(V2ValidationError):
    """The committed candidate source freeze drifted from the live candidate source."""


def _read_bytes(repo_root: Path, relpath: str) -> bytes:
    raw = repo_root / relpath
    if raw.is_symlink():
        raise CandidateSourceFreezeError(f"{relpath} is a symlink")
    path = raw.resolve()
    if not path.is_relative_to(repo_root.resolve()):
        raise CandidateSourceFreezeError(f"{relpath} escapes the repository root")
    return path.read_bytes()


def build_candidate_source_freeze(repo_root: str | Path) -> dict[str, Any]:
    """Derive the candidate source freeze dict from the live candidate set + source."""
    root = Path(repo_root)
    candidates = [
        {
            "candidate_id": spec.candidate_id,
            "identity_fingerprint": spec.identity.fingerprint(),
            "fixed_parameters": dict(sorted(spec.fixed_parameters.items())),
            "spec_fingerprint": spec.fingerprint(),
        }
        for spec in V2B_CANDIDATES
    ]
    candidate_set_fingerprint = canonical_sha256([c["spec_fingerprint"] for c in candidates])
    source_files = {
        rel: sha256_bytes(_read_bytes(root, rel)) for rel in sorted(_FROZEN_SOURCE_RELPATHS)
    }
    return {
        "schema_version": CANDIDATE_SOURCE_FREEZE_SCHEMA_VERSION,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "candidate_set_fingerprint": candidate_set_fingerprint,
        "frozen_source_sha256": source_files,
        "hypothesis_review_sha256": sha256_bytes(_read_bytes(root, _HYPOTHESIS_REVIEW_RELPATH)),
        "frozen_before_real_btc": True,
        "statement": _FREEZE_STATEMENT,
    }


def render_candidate_source_freeze_bytes(freeze: dict[str, Any]) -> bytes:
    return canonical_json_bytes(freeze)


def verify_candidate_source_freeze(repo_root: str | Path) -> None:
    """The committed freeze reproduces byte-for-byte from the live candidate source."""
    root = Path(repo_root)
    committed = (root / CANDIDATE_SOURCE_FREEZE_RELPATH).read_bytes()
    fresh = render_candidate_source_freeze_bytes(build_candidate_source_freeze(root))
    if committed != fresh:
        raise CandidateSourceFreezeError(
            "committed candidate_source_freeze.json does not reproduce from the live candidate "
            "source (candidate logic or parameters changed after the freeze)"
        )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="V2B candidate source freeze (read-only)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--emit", action="store_true", help="print the derived freeze JSON")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    if args.emit:
        print(render_candidate_source_freeze_bytes(build_candidate_source_freeze(root)).decode())
        return 0
    try:
        verify_candidate_source_freeze(root)
    except (OSError, V2ValidationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
