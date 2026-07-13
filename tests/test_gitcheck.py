"""C1/C4: package-source binding — direct, fast unit tests on gitcheck."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from eth_research.gitcheck import GitError, verify_package_source


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def make_pkg_repo(root: Path, *, extra: dict[str, bytes] | None = None) -> tuple[Path, str]:
    """A minimal repo committing src/eth_research with a couple of modules."""
    repo = root / "repo"
    pkg = repo / "src" / "eth_research"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_bytes(b'__version__ = "0.3.0"\n')
    (pkg / "evaluation.py").write_bytes(b"# evaluation\n")
    sub = pkg / "data"
    sub.mkdir()
    (sub / "__init__.py").write_bytes(b"# data\n")
    for name, content in (extra or {}).items():
        target = pkg / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "package")
    return repo, _git(repo, "rev-parse", "HEAD")


class TestVerifyPackageSource:
    def test_matching_clean_checkout_passes(self, tmp_path: Path) -> None:
        repo, head = make_pkg_repo(tmp_path)
        verify_package_source(repo, head, repo / "src" / "eth_research")

    def test_foreign_package_root_is_rejected(self, tmp_path: Path) -> None:
        repo, head = make_pkg_repo(tmp_path)
        other, _ = make_pkg_repo(tmp_path / "b")
        with pytest.raises(GitError, match=r"different checkouts|imported from"):
            verify_package_source(repo, head, other / "src" / "eth_research")

    def test_no_source_directory_is_rejected(self, tmp_path: Path) -> None:
        # A repo with commits but no src/eth_research.
        bare = tmp_path / "meta"
        bare.mkdir()
        (bare / "readme.txt").write_text("meta only", encoding="utf-8")
        _git(bare, "init", "-q")
        _git(bare, "config", "user.email", "t@e.com")
        _git(bare, "config", "user.name", "T")
        _git(bare, "add", "-A")
        _git(bare, "commit", "-q", "-m", "meta")
        head = _git(bare, "rev-parse", "HEAD")
        with pytest.raises(GitError, match="metadata but not the package source"):
            verify_package_source(bare, head, bare / "src" / "eth_research")

    def test_symlinked_package_directory_is_rejected(self, tmp_path: Path) -> None:
        repo, head = make_pkg_repo(tmp_path)
        real = repo / "src" / "eth_research"
        elsewhere = tmp_path / "elsewhere"
        real.rename(elsewhere)
        real.symlink_to(elsewhere)
        with pytest.raises(GitError, match=r"package directory .* is a symlink"):
            verify_package_source(repo, head, real)

    def test_symlinked_source_file_is_rejected(self, tmp_path: Path) -> None:
        repo, head = make_pkg_repo(tmp_path)
        pkg = repo / "src" / "eth_research"
        target = pkg / "evaluation.py"
        external = tmp_path / "external.py"
        external.write_bytes(b"# external\n")
        target.unlink()
        target.symlink_to(external)
        with pytest.raises(GitError, match=r"source file .* is a symlink"):
            verify_package_source(repo, head, pkg)

    def test_untracked_shadow_module_is_rejected(self, tmp_path: Path) -> None:
        # An untracked .py in the package: git status --untracked=no is clean,
        # but the source-binding check must still reject it.
        repo, head = make_pkg_repo(tmp_path)
        pkg = repo / "src" / "eth_research"
        (pkg / "shadow.py").write_bytes(b"# shadow\n")
        assert (
            _git(repo, "status", "--porcelain", "--untracked-files=no") == ""
        )  # clean by that measure
        with pytest.raises(GitError, match="untracked package source"):
            verify_package_source(repo, head, pkg)

    def test_modified_tracked_source_is_rejected(self, tmp_path: Path) -> None:
        repo, head = make_pkg_repo(tmp_path)
        pkg = repo / "src" / "eth_research"
        target = pkg / "evaluation.py"
        target.write_bytes(target.read_bytes() + b"# tampered\n")
        with pytest.raises(GitError, match="differs from its bytes committed"):
            verify_package_source(repo, head, pkg)

    def test_missing_tracked_source_is_rejected(self, tmp_path: Path) -> None:
        repo, head = make_pkg_repo(tmp_path)
        pkg = repo / "src" / "eth_research"
        (pkg / "evaluation.py").unlink()
        with pytest.raises(GitError, match="missing from the working tree"):
            verify_package_source(repo, head, pkg)

    def test_runtime_code_from_a_different_commit_is_rejected(self, tmp_path: Path) -> None:
        # HEAD is valid, package_root is the repo's own src, but the working
        # bytes match an OLDER commit than HEAD (runtime != HEAD blob).
        repo, first = make_pkg_repo(tmp_path)
        pkg = repo / "src" / "eth_research"
        (pkg / "evaluation.py").write_bytes(b"# new content\n")
        _git(repo, "commit", "-q", "-am", "advance")
        head = _git(repo, "rev-parse", "HEAD")
        # Restore the OLD working bytes (matching `first`, not HEAD).
        (pkg / "evaluation.py").write_bytes(b"# evaluation\n")
        assert first != head
        with pytest.raises(GitError, match="differs from its bytes committed"):
            verify_package_source(repo, head, pkg)
