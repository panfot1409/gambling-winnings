"""Commit genealogy for the accepted proposal, with stable error codes.

Auditor B, finding A-4: the acceptance chain asserted that its pinned commits
were "ancestors of HEAD" and little else. That is close to vacuous — *every*
commit in a repository is an ancestor of HEAD — and it left a family of forgeries
undetected: an id that names a tree or a blob, an abbreviated or uppercase id, an
id carrying revision syntax that git resolves to something else entirely, a
commit with the right id but a different tree, an extra parent smuggling
unrelated history in, the ancestry relation asserted backwards, and a shallow
clone in which the pinned object is simply absent so the check never runs.

This module states the genealogy as fifteen numbered checks, each with a stable
``GEN-xx`` code. Codes matter because they are what a test, a runbook or an
operator can name: "GEN-11 failed" survives rewording of the message, and lets
the adversarial matrix assert *which* invariant caught a probe rather than
merely that something did.

Object-substitution defences
----------------------------
Three git mechanisms can make the same object id return different content:
``.git/shallow`` (truncated history, so ancestry answers are unreliable),
``.git/info/grafts`` (fabricated parentage) and ``refs/replace/*`` (wholesale
object substitution). Each gets its own check, and every git invocation here
passes ``--no-replace-objects`` so the checks themselves cannot be redirected by
the very mechanism they are testing.

What this does not claim
------------------------
This is operationally tamper-evident relative to pinned historical Git objects
and committed verifier source. It is not cryptographic remote attestation: an
actor who can rewrite trusted Git history together with this module's source and
the source-freeze authority is outside the in-repository trust boundary.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path
from typing import Final

from eth_research.m3e.proposal_authority import (
    EXPECTED_PROPOSAL_HEAD,
    EXPECTED_PROPOSAL_PARENT,
    EXPECTED_PROPOSAL_TREE,
    TRUSTED_BASELINE_COMMIT,
    TRUSTED_BASELINE_TREE,
    ProposalAuthorityError,
    require_sha1,
)

GENEALOGY_SCHEMA_VERSION: Final[int] = 1

_GIT_TIMEOUT: Final[int] = 120
_MAX_GIT_BYTES: Final[int] = 8 * 1024 * 1024

#: Every check, in evaluation order, with the invariant each one states.
CHECK_IDS: Final[tuple[tuple[str, str], ...]] = (
    ("GEN-01", "repo_root is a git repository with a readable object database"),
    ("GEN-02", "history is complete (not a shallow clone), so ancestry answers are total"),
    ("GEN-03", "no graft file fabricates parentage"),
    ("GEN-04", "no refs/replace/* entry substitutes a pinned object"),
    ("GEN-05", "the baseline id is a full lowercase 40-hex id with no revision syntax"),
    ("GEN-06", "the baseline object exists and its type is commit"),
    ("GEN-07", "the baseline commit's tree is exactly the pinned tree"),
    ("GEN-08", "the proposal head id is a full lowercase 40-hex id with no revision syntax"),
    ("GEN-09", "the proposal head object exists and its type is commit"),
    ("GEN-10", "the proposal head's tree is exactly the pinned tree"),
    ("GEN-11", "the baseline is an ancestor of the proposal head"),
    ("GEN-12", "the proposal head is NOT an ancestor of the baseline (direction is asserted)"),
    ("GEN-13", "the proposal head has exactly one parent"),
    ("GEN-14", "the proposal head's sole parent is exactly the pinned baseline"),
    ("GEN-15", "the verification commit is a commit and both pinned commits precede it"),
)

# Ordering note (and a correction). The direction checks GEN-11/GEN-12 are
# evaluated BEFORE the parentage checks GEN-13/GEN-14, and that is load-bearing
# rather than stylistic. In the first draft parentage came first, which made the
# direction check unreachable: once "head's parent is the baseline" holds, head
# is a child of the baseline, and a commit DAG has no cycles, so "head is an
# ancestor of the baseline" could never be true. It was a check that could not
# fail — the exact vacuous-assertion shape this work exists to remove. Evaluated
# first, GEN-12 is reachable and catches the real case it was written for: a
# self-referential pin where baseline == head, which makes "is an ancestor of"
# trivially true in both directions and so says nothing at all.

_CHECK_MEANING: Final[dict[str, str]] = dict(CHECK_IDS)


class CommitGenealogyError(ProposalAuthorityError):
    """A violated genealogy invariant, carrying the stable code that failed.

    Subclasses :class:`ProposalAuthorityError` so existing callers that fail
    closed on root-authority problems keep doing so without change.
    """

    def __init__(self, code: str, message: str) -> None:
        if code not in _CHECK_MEANING:
            raise ValueError(f"unknown genealogy check code: {code!r}")
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclasses.dataclass(frozen=True, slots=True)
class GenealogyCheck:
    """One passed check: its stable code and what was actually observed."""

    code: str
    detail: str

    @property
    def meaning(self) -> str:
        return _CHECK_MEANING[self.code]


def _git(root: Path, args: list[str], code: str) -> bytes:
    """One git plumbing read, with replacement objects disabled.

    ``--no-replace-objects`` is not optional: without it, ``refs/replace/*`` could
    silently redirect every read below — including the read that looks for
    replacement refs."""
    try:
        completed = subprocess.run(
            ["git", "--no-replace-objects", "-C", str(root), *args],
            check=True,
            capture_output=True,
            timeout=_GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git absent
        raise CommitGenealogyError(code, "git is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommitGenealogyError(code, f"git {args[0]} timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace").strip()[:300]
        raise CommitGenealogyError(code, f"git {' '.join(args)} failed: {detail}") from exc
    out: bytes = completed.stdout
    if len(out) > _MAX_GIT_BYTES:
        raise CommitGenealogyError(code, f"git {args[0]} returned an implausibly large object")
    return out


def _git_ok(root: Path, args: list[str]) -> bool:
    """A predicate git call: exit status only, never raising on a nonzero exit."""
    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    return completed.returncode == 0


def _require_id(value: str, label: str, code: str) -> str:
    try:
        return require_sha1(value, label)
    except ProposalAuthorityError as exc:
        raise CommitGenealogyError(code, str(exc)) from exc


def _object_type(root: Path, sha: str, label: str, code: str) -> str:
    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), "cat-file", "-t", sha],
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    if completed.returncode != 0:
        raise CommitGenealogyError(
            code,
            f"{label}: object {sha[:12]}… is absent from this repository. A shallow or "
            "partial clone must fetch it (git fetch origin <sha>) — the check is never "
            "skipped just because the object is missing.",
        )
    return completed.stdout.decode("ascii", "replace").strip()


def _parents(root: Path, commit: str, code: str) -> tuple[str, ...]:
    line = _git(root, ["rev-list", "--parents", "-n", "1", commit], code).decode("ascii").strip()
    parts = line.split()
    if not parts or parts[0] != commit:
        raise CommitGenealogyError(code, f"could not resolve the parents of {commit[:12]}…")
    return tuple(parts[1:])


def verify_commit_genealogy(
    repo_root: str | Path, *, verification_commit: str | None = None
) -> list[GenealogyCheck]:
    """Run all fifteen checks in order; raise on the first violation.

    Ordering is deliberate: the repository-integrity checks (GEN-01..04) run
    before any object is trusted, and identity/shape checks run before the
    relational ones, so a failure names the earliest broken assumption rather
    than a downstream symptom.
    """
    root = Path(repo_root)
    passed: list[GenealogyCheck] = []

    def ok(code: str, detail: str) -> None:
        passed.append(GenealogyCheck(code, detail))

    # --- repository integrity: nothing below is meaningful without these ---
    git_dir = _git(root, ["rev-parse", "--git-dir"], "GEN-01").decode("utf-8").strip()
    ok("GEN-01", f"git-dir={git_dir}")

    if _git(root, ["rev-parse", "--is-shallow-repository"], "GEN-02").decode().strip() == "true":
        raise CommitGenealogyError(
            "GEN-02",
            "this is a shallow clone: ancestry queries are answered against truncated "
            "history, so a 'not an ancestor' result would be unsound. Deepen it "
            "(git fetch --unshallow) before verifying.",
        )
    ok("GEN-02", "complete history")

    resolved_git_dir = (root / git_dir) if not Path(git_dir).is_absolute() else Path(git_dir)
    grafts = resolved_git_dir / "info" / "grafts"
    if grafts.exists():
        raise CommitGenealogyError(
            "GEN-03", f"{grafts} exists; grafted parentage is not trusted parentage"
        )
    ok("GEN-03", "no graft file")

    replaced = _git(root, ["replace", "--list"], "GEN-04").decode("utf-8", "replace").split()
    pinned_ids = {TRUSTED_BASELINE_COMMIT, EXPECTED_PROPOSAL_HEAD}
    hijacked = sorted(pinned_ids & set(replaced))
    if hijacked:
        raise CommitGenealogyError(
            "GEN-04", f"refs/replace/* substitutes pinned object(s): {hijacked}"
        )
    ok("GEN-04", f"replace refs={len(replaced)}, none pinned")

    # --- the baseline ---
    baseline = _require_id(TRUSTED_BASELINE_COMMIT, "trusted baseline", "GEN-05")
    ok("GEN-05", f"baseline={baseline[:12]}…")

    kind = _object_type(root, baseline, "trusted baseline", "GEN-06")
    if kind != "commit":
        raise CommitGenealogyError(
            "GEN-06", f"trusted baseline {baseline[:12]}… is a {kind}, not a commit"
        )
    ok("GEN-06", "type=commit")

    baseline_tree = _git(root, ["rev-parse", f"{baseline}^{{tree}}"], "GEN-07").decode().strip()
    if baseline_tree != TRUSTED_BASELINE_TREE:
        raise CommitGenealogyError(
            "GEN-07",
            f"trusted baseline has tree {baseline_tree[:12]}…, source pins "
            f"{TRUSTED_BASELINE_TREE[:12]}… (right commit id, wrong content)",
        )
    ok("GEN-07", f"tree={baseline_tree[:12]}…")

    # --- the proposal head ---
    head = _require_id(EXPECTED_PROPOSAL_HEAD, "proposal head", "GEN-08")
    ok("GEN-08", f"head={head[:12]}…")

    kind = _object_type(root, head, "proposal head", "GEN-09")
    if kind != "commit":
        raise CommitGenealogyError(
            "GEN-09", f"proposal head {head[:12]}… is a {kind}, not a commit"
        )
    ok("GEN-09", "type=commit")

    head_tree = _git(root, ["rev-parse", f"{head}^{{tree}}"], "GEN-10").decode().strip()
    if head_tree != EXPECTED_PROPOSAL_TREE:
        raise CommitGenealogyError(
            "GEN-10",
            f"proposal head has tree {head_tree[:12]}…, source pins "
            f"{EXPECTED_PROPOSAL_TREE[:12]}… (right commit id, wrong content)",
        )
    ok("GEN-10", f"tree={head_tree[:12]}…")

    # --- the relations, both directions asserted, BEFORE parentage (see the
    #     ordering note above: after parentage, GEN-12 could never fail) ---
    if not _git_ok(root, ["merge-base", "--is-ancestor", baseline, head]):
        raise CommitGenealogyError(
            "GEN-11", f"baseline {baseline[:12]}… is not an ancestor of head {head[:12]}…"
        )
    ok("GEN-11", "baseline precedes head")

    if _git_ok(root, ["merge-base", "--is-ancestor", head, baseline]):
        raise CommitGenealogyError(
            "GEN-12",
            f"head {head[:12]}… is also an ancestor of baseline {baseline[:12]}… — the "
            "relation is symmetric, so it says nothing about direction",
        )
    ok("GEN-12", "relation is strictly directed")

    parents = _parents(root, head, "GEN-13")
    if len(parents) != 1:
        raise CommitGenealogyError(
            "GEN-13",
            f"proposal head has {len(parents)} parent(s) {[p[:12] for p in parents]}; a data "
            "proposal is one commit on one parent, and a merge would carry unrelated "
            "history into the accepted set",
        )
    ok("GEN-13", "exactly one parent")

    if parents[0] != EXPECTED_PROPOSAL_PARENT:
        raise CommitGenealogyError(
            "GEN-14",
            f"proposal head's parent is {parents[0][:12]}…, source pins "
            f"{EXPECTED_PROPOSAL_PARENT[:12]}…",
        )
    ok("GEN-14", f"parent={parents[0][:12]}…")

    target = verification_commit or _git(root, ["rev-parse", "HEAD"], "GEN-15").decode().strip()
    target = _require_id(target, "verification commit", "GEN-15")
    kind = _object_type(root, target, "verification commit", "GEN-15")
    if kind != "commit":
        raise CommitGenealogyError(
            "GEN-15", f"verification commit {target[:12]}… is a {kind}, not a commit"
        )
    for label, pinned in (("baseline", baseline), ("proposal head", head)):
        if not _git_ok(root, ["merge-base", "--is-ancestor", pinned, target]):
            raise CommitGenealogyError(
                "GEN-15",
                f"{label} {pinned[:12]}… is not an ancestor of the verification commit "
                f"{target[:12]}… — this acceptance does not apply to this history",
            )
    ok("GEN-15", f"verification={target[:12]}…")

    return passed


__all__ = [
    "CHECK_IDS",
    "GENEALOGY_SCHEMA_VERSION",
    "CommitGenealogyError",
    "GenealogyCheck",
    "verify_commit_genealogy",
]
