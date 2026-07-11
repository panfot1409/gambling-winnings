"""Read-only git checks binding an evaluation to a real, clean revision.

Milestone 2B's one-time test evaluation must run from a specific,
already-committed revision with a clean tracked working tree, so the
pre-registered ``code_commit_sha`` cannot be a fabricated string and the
protocol / dataset lock / acquisition evidence / ledger bytes cannot have
been edited after pre-registration. These helpers shell out to the local
``git`` binary (no networking) and never mutate the repository.

Scope and honesty: this is a **single-repository, single-researcher**
operational control. It proves the working files equal a real local
commit's blobs and that the tree is tracked-clean; it cannot prove
anything about a remote, about GitHub CI status, or prevent a concurrent
clone or a deliberate history rewrite. Those require external
coordination and are out of scope.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """A git check failed or the path is not inside a usable repository."""


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError) as exc:
        raise GitError(f"could not run git {' '.join(args)}: {exc}") from exc


def resolve_repo_root(start: str | Path) -> Path:
    """The top level of the git working tree containing ``start``.

    ``start`` may be a file or directory. Symlinks are resolved first so a
    symlinked path cannot masquerade as being inside the repository.
    """
    path = Path(start).resolve()
    search_dir = path if path.is_dir() else path.parent
    result = _run_git(search_dir, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise GitError(f"{start} is not inside a git repository: {result.stderr.strip()}")
    return Path(result.stdout.strip()).resolve()


def head_commit(repo_root: Path) -> str:
    """The full 40-hex SHA of ``HEAD``."""
    result = _run_git(repo_root, "rev-parse", "HEAD")
    if result.returncode != 0:
        raise GitError(f"could not resolve HEAD in {repo_root}: {result.stderr.strip()}")
    return result.stdout.strip()


def is_commit_object(repo_root: Path, sha: str) -> bool:
    """True only when ``sha`` names an existing commit object."""
    result = _run_git(repo_root, "cat-file", "-t", sha)
    return result.returncode == 0 and result.stdout.strip() == "commit"


def tracked_tree_is_clean(repo_root: Path) -> bool:
    """True when no tracked file has staged or unstaged modifications.

    Untracked and git-ignored files (e.g. raw/canonical market data under
    ``data/``) are deliberately ignored: only tracked modifications matter.
    """
    result = _run_git(repo_root, "status", "--porcelain", "--untracked-files=no")
    if result.returncode != 0:
        raise GitError(f"could not read git status in {repo_root}: {result.stderr.strip()}")
    return result.stdout.strip() == ""


def file_bytes_at_commit(repo_root: Path, commit: str, relpath: str) -> bytes:
    """The exact blob bytes of ``relpath`` at ``commit``.

    Raises :class:`GitError` if the path does not exist at that commit.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{commit}:{relpath}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitError(
            f"{relpath!r} does not exist at commit {commit[:12]} in {repo_root}: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    return result.stdout


def relative_to_repo(repo_root: Path, target: str | Path) -> str:
    """The repo-relative POSIX path of ``target``; rejects paths outside.

    Symlinks are resolved, so a symlink pointing outside the repository is
    rejected rather than silently followed.
    """
    resolved = Path(target).resolve()
    try:
        relative = resolved.relative_to(repo_root)
    except ValueError as exc:
        raise GitError(f"{target} is outside the repository {repo_root}") from exc
    return relative.as_posix()
