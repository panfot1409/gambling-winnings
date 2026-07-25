"""The immutable root of authority for prospective-cohort proposal acceptance.

WHY THIS MODULE EXISTS
======================

The acceptance chain used to root itself in two ordinary committed files — the
two "byte-frozen" stack freeze tables — cross-checked only against *each other*
and against the chain's own genesis line. An independent audit (Auditor B,
finding A-1) demonstrated the consequence: rewriting all three co-located files
together sets every pre-acceptance pin to a state that never existed, and all
three readers report a full green board. Agreement among N files that one actor
can rewrite is a *consistency* check, not an *authority*. It is the same
"consistency is not truth" failure the acceptance record itself was written to
close, one level further down.

Duplicating the mutable root more times does not fix this; it manufactures an
illusion of independence. The root has to live somewhere the data-plane attacker
does not reach. This module puts it in two places at once:

1. **Committed source constants** below, protected by the source freeze
   (:data:`SOURCE_FREEZE_RELPATH`) and by code review.
2. **Historical Git objects**, read out of a pinned ancestor commit through Git
   object access — never from the mutable working-tree copies.

An attacker who rewrites today's working tree changes neither. Re-rooting now
requires rewriting committed source, the source freeze, *and* trusted Git
history together.

WHAT THIS DOES NOT CLAIM
========================

This is **operationally tamper-evident under trusted Git ancestry, committed-source
binding, source-freeze verification and protected review** — not cryptographically
tamper-proof. An actor able to rewrite trusted Git history, this module's source,
the source-freeze authority and the branch-protection evidence *together* is
outside the in-repository trust boundary, and nothing inside the repository can
detect them. That limit is stated here rather than papered over, and the word
"tamper-proof" is deliberately not used anywhere in this package.

This module is a LEAF: it imports only the standard library, so any layer may
depend on it without creating a cycle. It lives in ``m3e`` because that package
owns the acceptance chain, and the M3E architecture guard forbids M3E importing
upward into V2E.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

AUTHORITY_SCHEMA_VERSION = 1

#: Domain separator for the genesis root. Domain separation keeps this digest from
#: ever colliding with a record/completion/ledger hash computed over similar bytes.
GENESIS_ROOT_DOMAIN = b"m3e/proposal_authority/genesis_root\n"

#: The trusted pre-proposal baseline. This commit is the sole parent of the bot
#: proposal head and the last state in which the cohort was 3 accepted rows.
TRUSTED_BASELINE_COMMIT = "ba2dcc1d63f29a009d3660be2d960388a9615da0"
TRUSTED_BASELINE_TREE = "35ed0d5b157047a63e04d91f8e1a4bfc64c9e127"

#: Authority tables, pinned to the SHA-256 of their bytes **as stored at**
#: :data:`TRUSTED_BASELINE_COMMIT`. The verifier reads them from that commit's
#: objects; the working-tree copies are treated as derived caches with no authority.
AUTHORITY_TABLES: dict[str, str] = {
    "docs/M3C_M3E_STACK_FREEZE_TABLE.json": (
        "d6805af08c7f68bcbf5a50038dc9eac5b7be389ac205e43c0eaab6cc5f3d5e53"
    ),
    "research/v2ab/stack_freeze_table.json": (
        "f0c6899b822c864a15914fce75a6e20b3d9aa7adccd6030750313b9a6dc82f69"
    ),
}

#: The accepted cohort manifest at the trusted baseline, and the accepted state it
#: describes. These are the values the chain must replay *from*.
ACCEPTED_MANIFEST_PATH = "research/m3d/prospective_manifest.json"
ACCEPTED_MANIFEST_SHA256 = "24457fb92a300b28cf5343283be9d39772cd599ec16e641235fd9cc0bc1be4b4"
ACCEPTED_ROW_COUNT = 3
ACCEPTED_LAST_OPEN = "2026-07-14T00:00:00Z"
ACCEPTED_BASE_SHA256 = "c7af0ecc3c3e2f3b838a405e1bc017e7e0b183639302d2eb7654d4299426373f"
ACCEPTED_FINGERPRINT = "bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507"

#: This acceptance is intentionally single-proposal-specific: the mechanism is new
#: and one landed proposal is the entire scope. A second proposal must extend these
#: pins deliberately, in source, under review — it cannot arrive as data.
EXPECTED_PROPOSAL_PARENT = TRUSTED_BASELINE_COMMIT
EXPECTED_PROPOSAL_HEAD = "779df6bb6c7ab4ac312e9d8fe7028392581db237"
EXPECTED_PROPOSAL_TREE = "ef26510e41ac1f3727abce2e1f9bd5fe2e69edfe"

#: The source freeze that protects these constants. Rewriting the pins above
#: without also defeating this artifact is detected by the Fable 5 freeze verifier.
SOURCE_FREEZE_RELPATH = "governance/v2/fable5_source_freeze.json"

_SHA1_RE = re.compile(r"\A[0-9a-f]{40}\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

#: Bound on any git plumbing read. The largest object read here is a freeze table
#: (tens of KiB); anything approaching this is pathological and fails closed.
_MAX_GIT_BYTES = 8 * 1024 * 1024


class ProposalAuthorityError(RuntimeError):
    """A violated root-authority invariant. Always fail closed; never repair."""


def require_sha1(value: object, label: str) -> str:
    """A full lowercase 40-hex object id.

    Rejects uppercase, abbreviations, and anything carrying revision syntax
    (``^``, ``~``, ``:``, ``@{...}``): ``git`` would happily resolve ``<sha>^`` or
    ``<sha>:path`` to a *different* object, so accepting them would let a pinned
    identity silently designate something else.
    """
    if not isinstance(value, str) or not _SHA1_RE.match(value):
        raise ProposalAuthorityError(
            f"{label}: expected a full lowercase 40-hex object id, got {value!r}"
        )
    return value


def require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise ProposalAuthorityError(f"{label}: expected a lowercase 64-hex digest, got {value!r}")
    return value


def _git(root: Path, *args: str) -> bytes:
    """Run one git plumbing command with a fixed argv (never a shell string).

    ``args`` are passed as a list, so no value can inject a flag or a shell
    metacharacter. Output is bounded.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git absent
        raise ProposalAuthorityError("git is not available; cannot verify root authority") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProposalAuthorityError(f"git {args[0]} timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace").strip()[:400]
        raise ProposalAuthorityError(f"git {' '.join(args)} failed: {detail}") from exc
    out: bytes = completed.stdout
    if len(out) > _MAX_GIT_BYTES:
        raise ProposalAuthorityError(f"git {args[0]} returned an implausibly large object")
    return out


def require_commit_object(root: Path, sha: str, label: str) -> str:
    """The id must name an existing object of type ``commit`` in this repository.

    A pinned id that is merely well-formed proves nothing: an audit showed
    ``ffffffff…`` and blob/tree ids passing a format-only check. Missing objects
    (a shallow clone) fail loudly here rather than silently weakening ancestry.
    """
    require_sha1(sha, label)
    try:
        kind = _git(root, "cat-file", "-t", sha).decode("ascii").strip()
    except ProposalAuthorityError as exc:
        raise ProposalAuthorityError(
            f"{label}: object {sha[:12]}… is not present in this repository "
            "(a shallow clone must fetch it explicitly rather than skip this check)"
        ) from exc
    if kind != "commit":
        raise ProposalAuthorityError(f"{label}: object {sha[:12]}… is a {kind}, not a commit")
    return sha


def require_tree_of(root: Path, commit: str, expected_tree: str, label: str) -> None:
    require_sha1(expected_tree, f"{label}.tree")
    actual = _git(root, "rev-parse", f"{commit}^{{tree}}").decode("ascii").strip()
    if actual != expected_tree:
        raise ProposalAuthorityError(
            f"{label}: commit {commit[:12]}… has tree {actual[:12]}…, expected "
            f"{expected_tree[:12]}… (right commit id, wrong content)"
        )


def commit_parents(root: Path, commit: str) -> tuple[str, ...]:
    line = _git(root, "rev-list", "--parents", "-n", "1", commit).decode("ascii").strip()
    parts = line.split()
    if not parts or parts[0] != commit:
        raise ProposalAuthorityError(f"could not resolve parents of {commit[:12]}…")
    return tuple(parts[1:])


def require_parents(root: Path, commit: str, expected: tuple[str, ...], label: str) -> None:
    """The exact parent set, in order. Guards both extra and reordered parents."""
    actual = commit_parents(root, commit)
    if actual != expected:
        raise ProposalAuthorityError(
            f"{label}: commit {commit[:12]}… has parents "
            f"{[p[:12] for p in actual]}, expected {[p[:12] for p in expected]}"
        )


def require_ancestor(root: Path, ancestor: str, descendant: str, label: str) -> None:
    """``ancestor`` must be reachable from ``descendant`` — direction matters.

    Reversing the arguments is a real forgery (an audit passed a descendant where
    an ancestor was required), so the direction is asserted, not assumed.
    """
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise ProposalAuthorityError(
            f"{label}: {ancestor[:12]}… is not an ancestor of {descendant[:12]}…"
        )


def read_blob_at(root: Path, commit: str, relpath: str) -> bytes:
    """Read a path's bytes **out of a commit's objects**, not the working tree.

    This is the whole point of the module: the historical bytes cannot be changed
    by editing files today.
    """
    if relpath.startswith("/") or ".." in Path(relpath).parts:
        raise ProposalAuthorityError(f"authority path escapes the repository: {relpath!r}")
    try:
        return _git(root, "cat-file", "-p", f"{commit}:{relpath}")
    except ProposalAuthorityError as exc:
        raise ProposalAuthorityError(
            f"authority table {relpath!r} is missing at trusted commit {commit[:12]}…"
        ) from exc


def historical_authority_digests(root: Path) -> dict[str, str]:
    """SHA-256 of each authority table as stored at the trusted baseline commit."""
    digests: dict[str, str] = {}
    for relpath in sorted(AUTHORITY_TABLES):
        blob = read_blob_at(root, TRUSTED_BASELINE_COMMIT, relpath)
        digests[relpath] = hashlib.sha256(blob).hexdigest()
    return digests


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def derive_genesis_root(root: Path) -> str:
    """The chain's root of authority, derived from history — never read from data.

    Every input is either a source constant in this module or a byte read out of a
    pinned historical commit. Nothing in today's working tree can move this value.
    """
    historical = historical_authority_digests(root)
    for relpath, pinned in AUTHORITY_TABLES.items():
        got = historical.get(relpath)
        if got != pinned:
            raise ProposalAuthorityError(
                f"authority table {relpath!r} at trusted commit "
                f"{TRUSTED_BASELINE_COMMIT[:12]}… hashes {got}, but source pins {pinned} "
                "(trusted history and committed source disagree)"
            )
    manifest = read_blob_at(root, TRUSTED_BASELINE_COMMIT, ACCEPTED_MANIFEST_PATH)
    manifest_digest = hashlib.sha256(manifest).hexdigest()
    if manifest_digest != ACCEPTED_MANIFEST_SHA256:
        raise ProposalAuthorityError(
            f"accepted manifest at trusted commit hashes {manifest_digest}, "
            f"source pins {ACCEPTED_MANIFEST_SHA256}"
        )
    body = {
        "authority_schema_version": AUTHORITY_SCHEMA_VERSION,
        "trusted_commit": TRUSTED_BASELINE_COMMIT,
        "trusted_tree": TRUSTED_BASELINE_TREE,
        "authority_tables": historical,
        "accepted_manifest_sha256": ACCEPTED_MANIFEST_SHA256,
        "accepted_row_count": ACCEPTED_ROW_COUNT,
        "accepted_last_open": ACCEPTED_LAST_OPEN,
    }
    return hashlib.sha256(GENESIS_ROOT_DOMAIN + _canonical(body)).hexdigest()


def verify_root_authority(
    repo_root: str | Path, *, verification_commit: str | None = None
) -> dict[str, Any]:
    """Prove the trusted root exists, is an ancestor, and matches committed source.

    Returns the derived facts (including the genesis root) so callers bind them
    rather than recomputing a second, divergent opinion.
    """
    root = Path(repo_root)
    require_commit_object(root, TRUSTED_BASELINE_COMMIT, "trusted_baseline_commit")
    require_tree_of(root, TRUSTED_BASELINE_COMMIT, TRUSTED_BASELINE_TREE, "trusted_baseline")

    head = verification_commit or _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    require_commit_object(root, head, "verification_commit")
    # The trusted root must be behind the tree being verified. A repository that
    # does not contain it is not a repository this acceptance applies to.
    require_ancestor(root, TRUSTED_BASELINE_COMMIT, head, "trusted baseline vs verification commit")

    require_commit_object(root, EXPECTED_PROPOSAL_HEAD, "expected_proposal_head")
    require_tree_of(root, EXPECTED_PROPOSAL_HEAD, EXPECTED_PROPOSAL_TREE, "expected_proposal_head")
    # Exactly one parent, and exactly the pinned one: an extra parent would let a
    # proposal quietly carry unrelated history into the accepted set.
    require_parents(
        root, EXPECTED_PROPOSAL_HEAD, (EXPECTED_PROPOSAL_PARENT,), "expected_proposal_head"
    )
    require_ancestor(root, EXPECTED_PROPOSAL_HEAD, head, "proposal head vs verification commit")

    return {
        "authority_schema_version": AUTHORITY_SCHEMA_VERSION,
        "trusted_commit": TRUSTED_BASELINE_COMMIT,
        "trusted_tree": TRUSTED_BASELINE_TREE,
        "verification_commit": head,
        "authority_tables": historical_authority_digests(root),
        "accepted_manifest_sha256": ACCEPTED_MANIFEST_SHA256,
        "accepted_row_count": ACCEPTED_ROW_COUNT,
        "accepted_last_open": ACCEPTED_LAST_OPEN,
        "accepted_base_sha256": ACCEPTED_BASE_SHA256,
        "accepted_fingerprint": ACCEPTED_FINGERPRINT,
        "proposal_parent": EXPECTED_PROPOSAL_PARENT,
        "proposal_head": EXPECTED_PROPOSAL_HEAD,
        "genesis_root": derive_genesis_root(root),
    }


def require_derived_cache_matches(
    root: Path, relpath: str, expected_sha256: str, label: str
) -> None:
    """A working-tree summary table is a derived cache, verified against authority.

    It is never consulted *as* authority: the comparison runs one way, from the
    historically-derived value to the file on disk.
    """
    path = root / relpath
    if path.is_symlink():
        raise ProposalAuthorityError(f"{label}: {relpath} is a symlink; refusing")
    if not path.is_file():
        raise ProposalAuthorityError(f"{label}: {relpath} is missing")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ProposalAuthorityError(
            f"{label}: working-tree {relpath} hashes {digest[:16]}…, but trusted history "
            f"says {expected_sha256[:16]}… (the derived cache disagrees with authority)"
        )
