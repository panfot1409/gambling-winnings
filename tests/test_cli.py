"""The offline eth-research CLI: commands, exit codes, and determinism."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eth_research.cli.app import main


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_version_and_doctor(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["version", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["api_version"]

    code, out, _ = _run(["doctor", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["ok"] is True


def test_no_subcommand_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert main(["dataset"]) == 2


def test_demo_run_and_verify_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = tmp_path / "demo"
    assert _run(["demo", "generate", "--output", str(demo)], capsys)[0] == 0
    config = demo / "config.json"
    assert config.exists()
    assert (demo / "synthetic_eth.csv").exists()

    assert _run(["backtest", "run", "--config", str(config)], capsys)[0] == 0
    results = demo / "results"
    for name in ("result.json", "report.md", "receipt.json", "manifest.json"):
        assert (results / name).exists()

    # the receipt verifies against the published artifacts
    code, _, _ = _run(
        [
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
        ],
        capsys,
    )
    assert code == 0

    # the result validates
    assert _run(["result", "verify", "--result", str(results / "result.json")], capsys)[0] == 0


def test_backtest_run_is_deterministic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = tmp_path / "demo"
    _run(["demo", "generate", "--output", str(demo)], capsys)
    config = demo / "config.json"
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    _run(["backtest", "run", "--config", str(config), "--output", str(out_a)], capsys)
    _run(["backtest", "run", "--config", str(config), "--output", str(out_b)], capsys)
    assert (out_a / "result.json").read_bytes() == (out_b / "result.json").read_bytes()
    assert (out_a / "receipt.json").read_bytes() == (out_b / "receipt.json").read_bytes()


def test_overwrite_refusal_and_force(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = tmp_path / "demo"
    _run(["demo", "generate", "--output", str(demo)], capsys)
    config = demo / "config.json"
    assert _run(["backtest", "run", "--config", str(config)], capsys)[0] == 0
    # a second run refuses to clobber the existing bundle
    assert _run(["backtest", "run", "--config", str(config)], capsys)[0] == 9
    # ...unless --overwrite is given
    assert _run(["backtest", "run", "--config", str(config), "--overwrite"], capsys)[0] == 0


def test_result_and_receipt_tamper_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = tmp_path / "demo"
    _run(["demo", "generate", "--output", str(demo)], capsys)
    _run(["backtest", "run", "--config", str(demo / "config.json")], capsys)
    results = demo / "results"

    tampered = tmp_path / "tampered_result.json"
    tampered.write_bytes((results / "result.json").read_bytes()[:-2] + b"9\n")
    assert _run(["result", "verify", "--result", str(tampered)], capsys)[0] == 7

    assert (
        _run(
            [
                "receipt",
                "verify",
                "--receipt",
                str(results / "receipt.json"),
                "--result",
                str(tampered),
            ],
            capsys,
        )[0]
        == 8
    )


def test_config_with_governed_path_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "bad.json"
    config.write_text(
        json.dumps(
            {
                "config_schema_version": 1,
                "dataset": {"source": "synthetic", "synthetic": {"n_periods": 40}},
                "engine": "binary",
                "strategy": {"kind": "buy_and_hold", "params": {}},
                "costs": {"scenario": "base"},
                "output": {"directory": "research/m2b/leak"},
            }
        ),
        encoding="utf-8",
    )
    assert _run(["backtest", "run", "--config", str(config)], capsys)[0] == 3
