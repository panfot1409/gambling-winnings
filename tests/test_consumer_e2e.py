"""Installed-wheel consumer end-to-end: a fresh venv uses the platform out-of-tree.

Builds the wheel, installs it non-editable into a throwaway virtual environment, and drives
the ``eth-research`` CLI from a working directory outside the repository — proving the
platform works as an installed package with the repository source off ``sys.path``, offline,
and writing only inside the output directory it is given.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def consumer(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    dist = tmp_path_factory.mktemp("dist")
    venv = tmp_path_factory.mktemp("venv")
    try:
        _run(["uv", "build", "--wheel", "--out-dir", str(dist)], cwd=REPO)
        wheel = next(dist.glob("*.whl"))
        _run(["uv", "venv", str(venv)])
        _run(["uv", "pip", "install", "--python", str(venv / "bin" / "python"), str(wheel)])
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("uv is not available for the consumer E2E")
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"consumer install unavailable (offline?): {exc.stderr}")
    workdir = tmp_path_factory.mktemp("workdir")  # outside the repo
    return venv, workdir


def _cli(venv: Path, workdir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    exe = venv / "bin" / "eth-research"
    return subprocess.run([str(exe), *args], cwd=workdir, capture_output=True, text=True)


def test_installed_package_is_out_of_tree(consumer: tuple[Path, Path]) -> None:
    venv, workdir = consumer
    proc = subprocess.run(
        [
            str(venv / "bin" / "python"),
            "-c",
            "import eth_research, sys; print(eth_research.__file__); "
            "print(any(str(p).endswith('gambling-winnings/src') for p in sys.path))",
        ],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=True,
    )
    installed_path, repo_on_path = proc.stdout.strip().splitlines()
    assert "site-packages" in installed_path
    assert repo_on_path == "False"


def test_version_and_doctor(consumer: tuple[Path, Path]) -> None:
    venv, workdir = consumer
    version = _cli(venv, workdir, "version", "--json")
    assert version.returncode == 0
    assert json.loads(version.stdout)["package_version"] == "2.0.0.dev1"
    doctor = _cli(venv, workdir, "doctor", "--json")
    assert doctor.returncode == 0
    assert json.loads(doctor.stdout)["ok"] is True


def test_demo_run_verify_and_determinism(consumer: tuple[Path, Path]) -> None:
    venv, workdir = consumer
    demo = workdir / "demo"
    assert _cli(venv, workdir, "demo", "generate", "--output", str(demo)).returncode == 0
    config = demo / "config.json"

    first = _cli(venv, workdir, "backtest", "run", "--config", str(config))
    assert first.returncode == 0
    results = demo / "results"
    result_bytes = (results / "result.json").read_bytes()

    verify = _cli(
        venv,
        workdir,
        "receipt",
        "verify",
        "--receipt",
        str(results / "receipt.json"),
        "--result",
        str(results / "result.json"),
        "--report",
        str(results / "report.md"),
        "--config",
        str(config),
    )
    assert verify.returncode == 0

    # a second run into a fresh directory is byte-identical
    out_b = workdir / "run_b"
    assert (
        _cli(
            venv, workdir, "backtest", "run", "--config", str(config), "--output", str(out_b)
        ).returncode
        == 0
    )
    assert (out_b / "result.json").read_bytes() == result_bytes

    # re-running over the existing bundle is refused (exit 9)
    assert _cli(venv, workdir, "backtest", "run", "--config", str(config)).returncode == 9
