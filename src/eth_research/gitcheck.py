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

import hashlib
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


def list_tree_files(repo_root: Path, commit: str, relpath: str) -> set[str]:
    """Repo-relative POSIX paths of the files under ``relpath`` at ``commit``."""
    result = _run_git(repo_root, "ls-tree", "-r", "--name-only", commit, "--", relpath)
    if result.returncode != 0:
        raise GitError(
            f"could not list {relpath!r} at {commit[:12]} in {repo_root}: {result.stderr.strip()}"
        )
    return {line for line in result.stdout.splitlines() if line}


PACKAGE_RELPATH: str = "src/eth_research"
"""The src-layout location of the package inside the repository."""


def verify_package_source(repo_root: Path, head: str, package_root: Path) -> None:
    """Prove the running package is the source committed at ``head``.

    ``package_root`` is the filesystem directory the ``eth_research`` package
    was actually imported from. This is a fail-closed, single-repository
    control (see the module docstring): it establishes that the code
    executing the evaluation is exactly the ``src/eth_research`` tree
    committed at the authorized ``HEAD`` — not a foreign clone, a
    site-packages install, an untracked shadow module, or a modified working
    copy. It cannot attest a remote or a cryptographic identity.

    Rejects, via :class:`GitError`:

    * a package imported from anywhere other than
      ``<repo_root>/src/eth_research``;
    * a repository with no committed package source at ``head``;
    * a symlinked package directory or symlinked source file;
    * an untracked shadow ``*.py`` file under the package;
    * a tracked source file missing at ``head`` or whose working bytes
      differ from the ``head`` blob.
    """
    src_dir = repo_root / PACKAGE_RELPATH
    if src_dir.is_symlink():
        raise GitError(f"package directory {src_dir} is a symlink; refusing to follow it")
    if not src_dir.is_dir():
        raise GitError(
            f"the authorized repository has no {PACKAGE_RELPATH} directory — it carries "
            "metadata but not the package source"
        )
    if package_root.resolve() != src_dir.resolve():
        raise GitError(
            f"the running eth_research package is imported from {package_root}, not the "
            f"authorized repository's {PACKAGE_RELPATH} ({src_dir}); execution and the "
            "authorized commit are different checkouts"
        )

    head_py = {
        rel for rel in list_tree_files(repo_root, head, PACKAGE_RELPATH) if rel.endswith(".py")
    }
    if not head_py:
        raise GitError(
            f"no committed {PACKAGE_RELPATH} source at {head[:12]} — the running code is not "
            "the code committed at the authorized revision"
        )

    working_py: set[str] = set()
    for path in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise GitError(f"package source file {path} is a symlink; refusing to follow it")
        working_py.add(relative_to_repo(repo_root, path))

    shadow = sorted(working_py - head_py)
    if shadow:
        raise GitError(
            f"untracked package source not committed at {head[:12]}: {shadow} — a shadow "
            "module could change behaviour"
        )
    missing = sorted(head_py - working_py)
    if missing:
        raise GitError(f"committed package source missing from the working tree: {missing}")

    for rel in sorted(head_py):
        working_bytes = (repo_root / rel).read_bytes()
        if working_bytes != file_bytes_at_commit(repo_root, head, rel):
            raise GitError(
                f"package source {rel} differs from its bytes committed at {head[:12]} — "
                "the running code was modified after the authorized commit"
            )


_SOURCE_TREE_FP_HEADER: bytes = b"eth-research source-tree-fp-v1\n"


def source_tree_fingerprint(repo_root: Path, commit: str) -> str:
    """Deterministic digest of the committed package source at ``commit``.

    A single stable identity for the exact ``src/eth_research`` ``*.py`` tree
    committed at ``commit`` (``__pycache__`` excluded), independent of the
    commit SHA itself: two commits with byte-identical package source share
    the fingerprint, and any source change alters it. Computed purely from
    the committed blobs, so a replay from git history reproduces it exactly.

    The digest is the SHA-256 of the domain-separated header
    ``b"eth-research source-tree-fp-v1\\n"`` followed, for every ``*.py`` path
    under :data:`PACKAGE_RELPATH` in ascending path order, by one line::

        <repo-relative posix path>\\x00<lowercase sha256 of the blob bytes>\\n

    :func:`verify_package_source` proves the running tree equals ``commit``'s
    blobs, so the fingerprint recorded by the orchestrator binds the exact
    code that produced a result.
    """
    paths = sorted(
        rel
        for rel in list_tree_files(repo_root, commit, PACKAGE_RELPATH)
        if rel.endswith(".py") and "__pycache__" not in rel.split("/")
    )
    if not paths:
        raise GitError(
            f"no committed {PACKAGE_RELPATH} source at {commit[:12]} — cannot fingerprint an "
            "empty source tree"
        )
    digest = hashlib.sha256()
    digest.update(_SOURCE_TREE_FP_HEADER)
    for rel in paths:
        blob = file_bytes_at_commit(repo_root, commit, rel)
        line = rel.encode("utf-8") + b"\x00" + hashlib.sha256(blob).hexdigest().encode("ascii")
        digest.update(line + b"\n")
    return digest.hexdigest()
