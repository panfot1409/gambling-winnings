"""Execute the shipped example configs and the quickstart script, offline, in a temp dir."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from eth_research.cli.app import main

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("config", ["synthetic_binary.toml", "synthetic_fractional.json"])
def test_example_config_runs(
    config: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = REPO / "examples" / "configs" / config
    out = tmp_path / "out"
    code = main(["backtest", "run", "--config", str(cfg), "--output", str(out)])
    capsys.readouterr()
    assert code == 0
    for name in ("result.json", "report.md", "receipt.json", "manifest.json"):
        assert (out / name).exists()


def test_quickstart_api_example_runs(tmp_path: Path) -> None:
    script = REPO / "examples" / "quickstart_api.py"
    proc = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert "terminal equity" in proc.stdout
    assert "result sha256" in proc.stdout
