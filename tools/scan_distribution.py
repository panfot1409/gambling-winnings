#!/usr/bin/env python3
"""Private-data-safe distribution scanner for the eth-research wheel and sdist.

Opens a built ``.whl`` (zip) or ``.tar.gz`` (sdist) and fails closed unless every member
is on a strict allowlist and the artifact is a clean, pure-Python distribution:

* every path is relative and traversal-free (no absolute path, no ``..``, no leading ``/``);
* no member is a symlink or a hardlink;
* no path segment names a private or governance root (``research``, ``.git``, ``.github``,
  ``tests``, ``tools``, ``docs``, ``__pycache__``, ``.env``);
* no member carries a data / secret / binary extension (``.parquet``/``.csv``/``.jsonl``
  research data, ``.env``/``.pem``/``.key`` secrets, ``.so``/``.pyd``/``.dll`` binaries);
* **inside the package tree** (``eth_research/…`` in the wheel, ``…/src/eth_research/…`` in
  the sdist) every member is a *pure-Python* file — only ``.py`` / ``.pyi`` sources and the
  ``py.typed`` marker are admitted, so a data file of **any** extension (a raw Coinbase
  ``.json`` candle bundle, a ``.pkl`` / ``.npy`` / ``.arrow`` blob, a manifest ``.json``)
  dropped under the package can never ride along undetected;
* the wheel contains only that package tree plus its ``.dist-info``; the sdist contains only
  that package tree plus ``pyproject.toml`` / ``README.md`` / ``PKG-INFO`` (and hatchling's
  ``.gitignore``);
* there are no case-colliding member paths;
* the wheel ships ``eth_research/py.typed``, declares the ``eth-research`` console entry
  point, and is tagged pure-python (``py3-none-any``).

This is a supply-chain integrity gate, not a proof of provenance; it verifies the
*inclusion allowlist held*, so a raw Coinbase byte or a sealed ledger can never be shipped.
"""

from __future__ import annotations

import argparse
import posixpath
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path

_FORBIDDEN_SEGMENTS = frozenset(
    {"research", ".git", ".github", "tests", "tools", "docs", "__pycache__", ".env"}
)
_FORBIDDEN_SUFFIXES = (
    ".parquet",
    ".pq",
    ".csv",
    ".jsonl",
    ".env",
    ".pem",
    ".key",
    ".p12",
    ".so",
    ".pyd",
    ".dll",
    ".dylib",
)


def _path_failures(name: str) -> list[str]:
    failures: list[str] = []
    if name.startswith("/") or posixpath.isabs(name) or ":" in name.split("/", 1)[0]:
        failures.append(f"absolute path: {name}")
    parts = name.split("/")
    if ".." in parts:
        failures.append(f"path traversal: {name}")
    forbidden = _FORBIDDEN_SEGMENTS.intersection(parts)
    if forbidden:
        failures.append(f"forbidden path segment {sorted(forbidden)}: {name}")
    if name.lower().endswith(_FORBIDDEN_SUFFIXES):
        failures.append(f"forbidden file type: {name}")
    return failures


def _case_collisions(names: Iterable[str]) -> list[str]:
    seen: dict[str, str] = {}
    failures: list[str] = []
    for name in names:
        key = name.lower()
        if key in seen and seen[key] != name:
            failures.append(f"case-colliding paths: {seen[key]!r} vs {name!r}")
        seen.setdefault(key, name)
    return failures


# Inside the package tree, only these are admitted — a strict pure-Python allowlist, so a
# non-source file of any extension cannot be shipped inside the package.
_PACKAGE_FILE_SUFFIXES = (".py", ".pyi")
_PACKAGE_FILE_BASENAMES = frozenset({"py.typed"})


def _is_pure_python_package_file(name: str) -> bool:
    basename = name.rsplit("/", 1)[-1]
    return basename in _PACKAGE_FILE_BASENAMES or name.endswith(_PACKAGE_FILE_SUFFIXES)


def _wheel_member_allowed(name: str) -> bool:
    if name.startswith("eth_research-") and ".dist-info/" in name:
        return True
    if name.startswith("eth_research/"):
        return _is_pure_python_package_file(name)
    return False


def _sdist_member_allowed(relpath: str) -> bool:
    if relpath.startswith("src/eth_research/"):
        return _is_pure_python_package_file(relpath)
    # hatchling always ships .gitignore in an sdist; it is a benign ignore-pattern file.
    return relpath in {"pyproject.toml", "README.md", "PKG-INFO", ".gitignore"}


def _scan_wheel(path: Path) -> list[str]:
    failures: list[str] = []
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        for info in zf.infolist():
            name = info.filename
            failures.extend(_path_failures(name))
            # Unix mode is stored in the top 16 bits of external_attr; 0o120000 == symlink.
            mode = info.external_attr >> 16
            if mode and (mode & 0o170000) == 0o120000:
                failures.append(f"symlink in wheel: {name}")
            if not name.endswith("/") and not _wheel_member_allowed(name):
                failures.append(f"unexpected wheel member: {name}")
        failures.extend(_case_collisions(names))
        if not any(n == "eth_research/py.typed" for n in names):
            failures.append("wheel is missing eth_research/py.typed")
        entry_points = [n for n in names if n.endswith(".dist-info/entry_points.txt")]
        if not entry_points:
            failures.append("wheel is missing an entry_points.txt")
        else:
            text = zf.read(entry_points[0]).decode("utf-8", errors="replace")
            if "eth-research" not in text or "eth_research.cli:main" not in text:
                failures.append(
                    "wheel entry point does not declare eth-research = eth_research.cli:main"
                )
        wheel_meta = [n for n in names if n.endswith(".dist-info/WHEEL")]
        if wheel_meta:
            wheel_text = zf.read(wheel_meta[0]).decode("utf-8", errors="replace")
            if "py3-none-any" not in wheel_text:
                failures.append("wheel is not tagged pure-python py3-none-any")
    return failures


def _scan_sdist(path: Path) -> list[str]:
    failures: list[str] = []
    with tarfile.open(path, "r:gz") as tf:
        members = tf.getmembers()
        names = [m.name for m in members]
        # every member shares a single top-level directory (eth_research-<version>/)
        roots = {n.split("/", 1)[0] for n in names}
        if len(roots) != 1:
            failures.append(f"sdist has multiple top-level roots: {sorted(roots)}")
        for member in members:
            name = member.name
            failures.extend(_path_failures(name))
            if member.issym() or member.islnk():
                failures.append(f"link in sdist: {name}")
            if member.isdir():
                continue
            relpath = name.split("/", 1)[1] if "/" in name else name
            if not _sdist_member_allowed(relpath):
                failures.append(f"unexpected sdist member: {relpath}")
        failures.extend(_case_collisions(names))
        if not any(n.endswith("/src/eth_research/py.typed") for n in names):
            failures.append("sdist is missing src/eth_research/py.typed")
    return failures


def scan_distribution(path: str | Path) -> list[str]:
    """Return the list of allowlist violations for one distribution file (empty == clean)."""
    file_path = Path(path)
    if file_path.suffix == ".whl":
        return _scan_wheel(file_path)
    if file_path.name.endswith(".tar.gz"):
        return _scan_sdist(file_path)
    return [f"unrecognized distribution file: {file_path.name}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan an eth-research wheel/sdist for safety.")
    parser.add_argument("paths", nargs="+", help="paths to .whl and/or .tar.gz files")
    args = parser.parse_args(argv)
    all_failures: dict[str, list[str]] = {}
    for path in args.paths:
        failures = scan_distribution(path)
        if failures:
            all_failures[path] = failures
    if all_failures:
        for path, failures in all_failures.items():
            for failure in failures:
                sys.stderr.write(f"{path}: {failure}\n")
        return 1
    for path in args.paths:
        sys.stdout.write(f"{path}: clean\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
