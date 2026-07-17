"""Regression tests for the independent M4A acceptance audit (M4B §3, auditors A/B/C).

Each test encodes a reproduced Class B/C finding from the pre-M4B independent acceptance audit
and fails against the pre-fix code. Grouped by finding id (F-A/F-B/F-D/F-E from the CLI+governance
auditor, A-A1/A-A2/A-A3 from the API auditor, B-1/B-2 from the distribution auditor).
"""

from __future__ import annotations

import importlib.util
import json
import warnings
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from eth_research.api import (
    ConfigurationError,
    OutputCollisionError,
    generate_synthetic_dataset,
)
from eth_research.api.config import load_config
from eth_research.cli import app
from eth_research.cli.app import main

REPO = Path(__file__).resolve().parents[1]


def _load_scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "scan_distribution", REPO / "tools" / "scan_distribution.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_wheel(tmp_path: Path, extra: dict[str, str]) -> Path:
    whl = tmp_path / "eth_research-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("eth_research/__init__.py", "x = 1\n")
        zf.writestr("eth_research/py.typed", "")
        zf.writestr(
            "eth_research-1.0.0.dist-info/entry_points.txt",
            "[console_scripts]\neth-research = eth_research.cli:main\n",
        )
        zf.writestr(
            "eth_research-1.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        for name, data in extra.items():
            zf.writestr(name, data)
    return whl


_VALID_CONFIG: dict[str, Any] = {
    "config_schema_version": 1,
    "dataset": {"source": "synthetic", "synthetic": {"n_periods": 60}},
    "engine": "binary",
    "strategy": {"kind": "buy_and_hold"},
    "costs": {"scenario": "base"},
    "split": {"enabled": False},
    "run": {"initial_cash": 10_000.0},
    "output": {"directory": "results"},
}


def _config_bytes(overrides: dict[str, Any]) -> bytes:
    doc = json.loads(json.dumps(_VALID_CONFIG))
    doc.update(overrides)
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# F-A — governed-output guard anchors to the output, not the cwd               #
# --------------------------------------------------------------------------- #
def test_reject_governed_output_anchors_to_output_not_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "research").mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.chdir(outside)  # cwd OUTSIDE the target repo — the pre-fix bypass
    with pytest.raises(OutputCollisionError):
        app._reject_governed_output(repo / "research" / "m4a" / "probe")
    # a non-governed sibling under the same repo is still allowed
    app._reject_governed_output(repo / "results" / "run")


# --------------------------------------------------------------------------- #
# F-B — dataset build --output is governed-path guarded                        #
# --------------------------------------------------------------------------- #
def test_cli_dataset_build_into_governed_research_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "research" / "m2b").mkdir(parents=True)
    monkeypatch.chdir(repo)
    dataset = generate_synthetic_dataset(n_periods=40, seed=0)
    csv = repo / "in.csv"
    csv.write_bytes(dataset.frame.reset_index().to_csv(index=False).encode("utf-8"))
    code = main(
        [
            "dataset",
            "build",
            "--input",
            str(csv),
            "--output",
            str(repo / "research" / "m2b" / "smuggled"),
            "--symbol",
            "ETH-USD",
            "--venue",
            "test",
            "--quote-asset",
            "USD",
            "--interval-seconds",
            str(dataset.interval_seconds),
            "--source",
            "synthetic fixture",
        ]
    )
    assert code == 9  # OutputCollisionError
    assert not (repo / "research" / "m2b" / "smuggled").exists()


# --------------------------------------------------------------------------- #
# A-A1 — config costs/strategy objects reject unknown keys                      #
# --------------------------------------------------------------------------- #
def test_config_costs_rejects_unknown_key() -> None:
    raw = _config_bytes({"costs": {"scenario": "base", "fee_rate": 0.9}})
    with pytest.raises(ConfigurationError):
        load_config(raw, fmt="json")


def test_config_strategy_rejects_unknown_key() -> None:
    raw = _config_bytes({"strategy": {"kind": "buy_and_hold", "leverage": 3}})
    with pytest.raises(ConfigurationError):
        load_config(raw, fmt="json")


# --------------------------------------------------------------------------- #
# A-A2 — config errors use the taxonomy (exit 3/4), never internal exit 70      #
# --------------------------------------------------------------------------- #
def _write_config(tmp_path: Path, raw: bytes) -> Path:
    path = tmp_path / "config.json"
    path.write_bytes(raw)
    return path


def test_cli_bad_split_fractions_use_config_exit_code(tmp_path: Path) -> None:
    raw = _config_bytes(
        {"split": {"enabled": True, "train_fraction": 0.6, "validation_fraction": 0.5}}
    )
    cfg = _write_config(tmp_path, raw)
    assert main(["backtest", "run", "--config", str(cfg), "--output", str(tmp_path / "o")]) == 3


def test_cli_nonpositive_interval_uses_config_exit_code(tmp_path: Path) -> None:
    raw = _config_bytes(
        {"dataset": {"source": "file", "file": {"path": "x.csv", "interval_seconds": 0}}}
    )
    cfg = _write_config(tmp_path, raw)
    assert main(["backtest", "run", "--config", str(cfg), "--output", str(tmp_path / "o")]) == 3


def test_cli_oversized_context_bars_uses_dataset_exit_code(tmp_path: Path) -> None:
    raw = _config_bytes(
        {
            "dataset": {"source": "synthetic", "synthetic": {"n_periods": 40}},
            "split": {"enabled": True, "evaluate": "validation", "context_bars": 100_000},
        }
    )
    cfg = _write_config(tmp_path, raw)
    assert main(["backtest", "run", "--config", str(cfg), "--output", str(tmp_path / "o")]) == 4


# --------------------------------------------------------------------------- #
# A-A3 — receipt verify rejects a non-canonical receipt                         #
# --------------------------------------------------------------------------- #
def test_receipt_verify_rejects_noncanonical_receipt(tmp_path: Path) -> None:
    # Build a real bundle, then *re-indent* the receipt: identical content, keys, and trailing
    # newline (so strict parsing + digest binding both still accept it), but non-canonical bytes
    # (indent 4, not the canonical indent 2). Pre-fix, ``receipt verify`` — unlike ``result
    # verify`` — omitted the re-serialization fixed-point check, so this reformatted-but-valid
    # receipt verified clean (exit 0); the fix restores the symmetric canonical-form guard.
    out = tmp_path / "bundle"
    cfg = _write_config(tmp_path, _config_bytes({}))
    assert main(["backtest", "run", "--config", str(cfg), "--output", str(out)]) == 0
    receipt = json.loads((out / "receipt.json").read_bytes())
    tampered = tmp_path / "receipt_noncanon.json"
    tampered.write_bytes((json.dumps(receipt, indent=4, sort_keys=True) + "\n").encode("utf-8"))
    # Supply *every* bound artifact so the digest/identity checks all pass — the canonical-form
    # guard is then the sole reason a non-canonical receipt can be rejected.
    code = main(
        [
            "receipt",
            "verify",
            "--receipt",
            str(tampered),
            "--result",
            str(out / "result.json"),
            "--report",
            str(out / "report.md"),
            "--config",
            str(cfg),
        ]
    )
    assert code == 8  # ReceiptVerificationError: receipt is not in canonical form


# --------------------------------------------------------------------------- #
# B-1 / B-2 — scanner: dist-info allowlist + exact-duplicate detection          #
# --------------------------------------------------------------------------- #
def test_scanner_flags_data_file_smuggled_in_dist_info(tmp_path: Path) -> None:
    scanner = _load_scanner()
    whl = _make_wheel(
        tmp_path, {"eth_research-1.0.0.dist-info/licenses/candles.json": "[[1489708800, 35.04]]"}
    )
    failures = scanner.scan_distribution(whl)
    assert any("candles.json" in failure for failure in failures)


def test_scanner_flags_exact_duplicate_member(tmp_path: Path) -> None:
    scanner = _load_scanner()
    whl = tmp_path / "eth_research-1.0.0-py3-none-any.whl"
    # A crafted supply-chain wheel can carry two members with the identical name (the zip
    # format permits it); Python's writer warns when we build such a fixture, so suppress
    # that construction-time warning — the assertion is about the *scanner*, not the writer.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(whl, "w") as zf:
            zf.writestr("eth_research/__init__.py", "x = 1\n")
            zf.writestr("eth_research/__init__.py", "x = 2\n")  # exact duplicate name
            zf.writestr("eth_research/py.typed", "")
            zf.writestr(
                "eth_research-1.0.0.dist-info/entry_points.txt",
                "[console_scripts]\neth-research = eth_research.cli:main\n",
            )
            zf.writestr("eth_research-1.0.0.dist-info/WHEEL", "Tag: py3-none-any\n")
    failures = scanner.scan_distribution(whl)
    assert any("duplicate member" in failure for failure in failures)


# --------------------------------------------------------------------------- #
# F-E — firewall matcher catches dynamic-execution spellings                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "snippet",
    [
        "import runpy\nrunpy.run_path('x')\n",
        "import importlib.util\nimportlib.util.spec_from_file_location('m', 'x')\n",
        "import os\nos.execv('/bin/sh', ['sh'])\n",
        "from runpy import run_path\nrun_path('x')\n",
    ],
)
def test_firewall_matcher_catches_dynamic_execution(snippet: str, tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "test_m4a_security", REPO / "tests" / "test_m4a_security.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    probe = tmp_path / "probe.py"
    probe.write_text(snippet, encoding="utf-8")
    findings = module._scan_file(probe)
    assert findings, f"matcher missed: {snippet!r}"
