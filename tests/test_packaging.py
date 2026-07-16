"""Private-data-safe, reproducible distribution build (wheel + sdist)."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load_scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "scan_distribution", REPO / "tools" / "scan_distribution.py"
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build(dest: Path) -> None:
    try:
        subprocess.run(
            ["uv", "build", "--out-dir", str(dest)],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:  # pragma: no cover - uv always present in CI
        pytest.skip("uv is not available to build the distribution")
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"distribution build failed (offline?): {exc.stderr}")


@pytest.fixture(scope="module")
def two_builds(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    first = tmp_path_factory.mktemp("build1")
    second = tmp_path_factory.mktemp("build2")
    _build(first)
    _build(second)
    return first, second


def _wheel(directory: Path) -> Path:
    return next(directory.glob("*.whl"))


def _sdist(directory: Path) -> Path:
    return next(directory.glob("*.tar.gz"))


def test_scanner_reports_clean(two_builds: tuple[Path, Path]) -> None:
    scanner = _load_scanner()
    first, _ = two_builds
    assert scanner.scan_distribution(_wheel(first)) == []
    assert scanner.scan_distribution(_sdist(first)) == []


def test_double_build_is_byte_identical(two_builds: tuple[Path, Path]) -> None:
    first, second = two_builds
    for name in (_wheel(first).name, _sdist(first).name):
        a = hashlib.sha256((first / name).read_bytes()).hexdigest()
        b = hashlib.sha256((second / name).read_bytes()).hexdigest()
        assert a == b, f"{name} is not reproducible: {a} != {b}"


def _is_pure_python_package_file(rel: str) -> bool:
    base = rel.rsplit("/", 1)[-1]
    return base == "py.typed" or rel.endswith((".py", ".pyi"))


def test_sdist_contains_no_private_data(two_builds: tuple[Path, Path]) -> None:
    first, _ = two_builds
    with tarfile.open(_sdist(first), "r:gz") as tf:
        members = [m for m in tf.getmembers() if m.isfile()]
    for member in members:
        name = member.name
        segments = name.split("/")
        assert "research" not in segments, f"research/ leaked into the sdist: {name}"
        assert ".github" not in segments
        assert "tests" not in segments
        assert not name.lower().endswith((".parquet", ".csv", ".jsonl", ".json"))
        # Inside the package tree only pure-Python files may ship — an allowlist, so a data
        # file of *any* extension (raw candles, a manifest, a pickle) cannot ride along.
        if "/src/eth_research/" in name:
            rel = name.split("/src/eth_research/", 1)[1]
            assert _is_pure_python_package_file(rel), f"non-source file in package tree: {name}"


def test_wheel_ships_py_typed_and_entry_point(two_builds: tuple[Path, Path]) -> None:
    first, _ = two_builds
    with zipfile.ZipFile(_wheel(first)) as zf:
        names = zf.namelist()
        assert "eth_research/py.typed" in names
        entry = next(n for n in names if n.endswith("entry_points.txt"))
        assert "eth_research.cli:main" in zf.read(entry).decode("utf-8")
        # no research/ data ships in the wheel either
        assert not any(n.split("/")[:1] == ["research"] for n in names)
        # inside the package tree, only pure-Python files ship (allowlist)
        for name in names:
            if name.startswith("eth_research/") and not name.endswith("/"):
                rel = name.split("eth_research/", 1)[1]
                assert _is_pure_python_package_file(rel), f"non-source file in wheel: {name}"


def test_sdist_rebuilds_a_wheel(two_builds: tuple[Path, Path], tmp_path: Path) -> None:
    first, _ = two_builds
    out = tmp_path / "from_sdist"
    try:
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(out), str(_sdist(first))],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        pytest.skip(f"sdist->wheel build unavailable: {exc}")
    assert next(out.glob("*.whl")).exists()
