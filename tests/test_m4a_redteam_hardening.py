"""Regression tests for the Milestone 4A independent red-team findings (auditors A / B / C).

Each finding was reproduced by an independent auditor against the pre-hardening code with a
concrete exploit; the tests below lock in the fixes so the same defect cannot recur. They are
grouped by finding id:

* A1/A3 + split — the ``run_id`` binds the *entire* run identity (context fingerprint, split,
  dataset manifest digest), and a tampered manifest digest is detected on verify.
* A-C1 — dataset interval failures surface as the public ``DatasetError``.
* A-C2 — ``StrategySpec`` is an object-level canonical fixed point.
* B1 — the distribution scanner admits only pure-Python files inside the package tree.
* F1/F2 — a symlink cannot walk a dataset read or an output write outside its directory.
* F3 — an operator ``--output`` cannot write into the governed ``research/`` / ``.git`` roots.
* F4 — publishing over a non-regular-file target is a clean ``OutputCollisionError``.
* F7 — ``result``/``receipt verify`` use taxonomy exit codes for an unreadable input.
* F8 — ``doctor``'s offline check is a real, in-process check.
* F9 — the config path guard is case-insensitive.
* F10 — the run config is read exactly once and those bytes are what the receipt binds.
"""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest

from eth_research.api import (
    CostSpec,
    DatasetError,
    OutputCollisionError,
    ReceiptVerificationError,
    ResearchResult,
    RunReceipt,
    StrategySpec,
    chronological_split,
    generate_synthetic_dataset,
    publish_bundle,
    run_binary_backtest,
)
from eth_research.api.config import _safe_rel_path, load_config, load_config_source
from eth_research.api.errors import ConfigurationError
from eth_research.api.models import ChronologicalSplitSpec
from eth_research.api.orchestrate import execute_config
from eth_research.api.receipt import build_receipt, verify_run_receipt
from eth_research.api.serialization import CanonicalError, canonical_json_bytes
from eth_research.cli import app
from eth_research.cli.app import main

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #
def _base_result() -> ResearchResult:
    dataset = generate_synthetic_dataset(n_periods=120, seed=3)
    return run_binary_backtest(
        dataset,
        StrategySpec("buy_and_hold"),
        CostSpec("base"),
        split=ChronologicalSplitSpec(0.6, 0.2),
    )


def _canonical(mapping: dict[str, Any]) -> bytes:
    return canonical_json_bytes(mapping)


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


def _make_sdist(tmp_path: Path, extra: dict[str, str]) -> Path:
    tgz = tmp_path / "eth_research-1.0.0.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:

        def add(name: str, text: str) -> None:
            payload = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))

        add("eth_research-1.0.0/src/eth_research/__init__.py", "x = 1\n")
        add("eth_research-1.0.0/src/eth_research/py.typed", "")
        add("eth_research-1.0.0/pyproject.toml", "[project]\nname = 'eth-research'\n")
        add("eth_research-1.0.0/README.md", "# eth-research\n")
        add("eth_research-1.0.0/PKG-INFO", "Metadata-Version: 2.1\n")
        for name, data in extra.items():
            add(name, data)
    return tgz


_VALID_SYNTHETIC_CONFIG = {
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
    doc = copy.deepcopy(_VALID_SYNTHETIC_CONFIG)
    doc.update(overrides)
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# A1 / A3 / split — the run_id binds the whole identity                        #
# --------------------------------------------------------------------------- #
def test_run_id_binds_context_fingerprint() -> None:
    base = json.loads(_base_result().to_json_bytes())
    without = build_receipt(_canonical(base)).run_id
    changed = copy.deepcopy(base)
    changed["run_spec"]["context_fingerprint"] = "sha256:" + "a" * 64
    with_context = build_receipt(_canonical(changed)).run_id
    assert without != with_context


def test_run_id_binds_split_fractions() -> None:
    base = json.loads(_base_result().to_json_bytes())
    original = build_receipt(_canonical(base)).run_id
    changed = copy.deepcopy(base)
    changed["run_spec"]["split"]["train_fraction"] = 0.7
    altered = build_receipt(_canonical(changed)).run_id
    assert original != altered


def test_run_id_binds_dataset_manifest_sha256() -> None:
    base = _base_result().to_json_bytes()
    without = build_receipt(base, dataset_manifest_sha256=None).run_id
    with_manifest = build_receipt(base, dataset_manifest_sha256="a" * 64).run_id
    assert without != with_manifest


def test_receipt_manifest_digest_tamper_is_detected() -> None:
    base = _base_result().to_json_bytes()
    receipt = build_receipt(base, dataset_manifest_sha256="a" * 64)
    verify_run_receipt(receipt, result_bytes=base)  # untampered verifies
    tampered = RunReceipt.from_dict({**receipt.to_dict(), "dataset_manifest_sha256": "b" * 64})
    with pytest.raises(ReceiptVerificationError):
        verify_run_receipt(tampered, result_bytes=base)


# --------------------------------------------------------------------------- #
# A-C1 — dataset interval failures are DatasetError, not a bare ValueError      #
# --------------------------------------------------------------------------- #
def test_generate_synthetic_single_period_raises_dataset_error() -> None:
    with pytest.raises(DatasetError):
        generate_synthetic_dataset(n_periods=1, seed=0)


class _OneRowHandle:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    @property
    def fingerprint(self) -> str:
        return "sha256:" + "0" * 64

    @property
    def interval_seconds(self) -> int:
        return 86_400

    @property
    def row_count(self) -> int:
        return len(self._frame)


def test_chronological_split_one_row_raises_dataset_error() -> None:
    frame = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
        index=pd.DatetimeIndex(["2020-01-01"], tz="UTC"),
    )
    with pytest.raises(DatasetError):
        chronological_split(_OneRowHandle(frame), ChronologicalSplitSpec(0.6, 0.2))


# --------------------------------------------------------------------------- #
# A-C2 — StrategySpec is an object-level canonical fixed point                  #
# --------------------------------------------------------------------------- #
def test_strategyspec_is_object_level_fixed_point() -> None:
    spec = StrategySpec("moving_average_crossover", (("slow_window", 50), ("fast_window", 20)))
    assert spec.params == (("fast_window", 20), ("slow_window", 50))
    assert spec == StrategySpec.from_dict(spec.to_dict())


# --------------------------------------------------------------------------- #
# B1 — the scanner admits only pure-Python files inside the package tree        #
# --------------------------------------------------------------------------- #
def test_scanner_accepts_a_clean_crafted_wheel(tmp_path: Path) -> None:
    scanner = _load_scanner()
    assert scanner.scan_distribution(_make_wheel(tmp_path, {})) == []


def test_scanner_flags_data_json_inside_wheel_package(tmp_path: Path) -> None:
    scanner = _load_scanner()
    whl = _make_wheel(tmp_path, {"eth_research/data/_candles.json": "[[1489708800, 35.04]]"})
    failures = scanner.scan_distribution(whl)
    assert any("_candles.json" in failure for failure in failures)


def test_scanner_flags_data_file_inside_sdist_package(tmp_path: Path) -> None:
    scanner = _load_scanner()
    tgz = _make_sdist(tmp_path, {"eth_research-1.0.0/src/eth_research/_lock.json": "{}"})
    failures = scanner.scan_distribution(tgz)
    assert any("_lock.json" in failure for failure in failures)


# --------------------------------------------------------------------------- #
# F1 / F2 — symlinks cannot escape the dataset dir or the output dir            #
# --------------------------------------------------------------------------- #
def test_dataset_file_symlink_escaping_base_dir_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    dataset = generate_synthetic_dataset(n_periods=60, seed=1)
    csv_bytes = dataset.frame.reset_index().to_csv(index=False).encode("utf-8")
    (outside / "secret.csv").write_bytes(csv_bytes)

    base = tmp_path / "cfg"
    base.mkdir()
    (base / "data.csv").symlink_to(outside / "secret.csv")

    raw = _config_bytes(
        {
            "dataset": {
                "source": "file",
                "file": {"path": "data.csv", "interval_seconds": dataset.interval_seconds},
            }
        }
    )
    config = load_config(raw, fmt="json")
    with pytest.raises(DatasetError):
        execute_config(config, config_bytes=raw, base_dir=base, output_dir=tmp_path / "out")


def test_publish_bundle_refuses_symlinked_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OutputCollisionError):
        publish_bundle(link / "bundle", {"a.json": b"{}\n"})
    assert not (outside / "bundle").exists()


def test_config_output_symlink_escaping_base_dir_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    base = tmp_path / "cfg"
    base.mkdir()
    (base / "link").symlink_to(outside, target_is_directory=True)
    raw = _config_bytes({"output": {"directory": "link/bundle"}})
    config = load_config(raw, fmt="json")
    with pytest.raises(ConfigurationError):
        execute_config(config, config_bytes=raw, base_dir=base, output_dir=None)
    assert not (outside / "bundle").exists()


# --------------------------------------------------------------------------- #
# F3 — an operator --output cannot target governed research / .git roots        #
# --------------------------------------------------------------------------- #
def test_reject_governed_output_refuses_research_and_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "research").mkdir()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(OutputCollisionError):
        app._reject_governed_output(tmp_path / "research" / "m4a" / "probe")
    with pytest.raises(OutputCollisionError):
        app._reject_governed_output(tmp_path / ".git" / "objects")
    # a non-governed sibling directory is allowed
    app._reject_governed_output(tmp_path / "results" / "run")


def test_cli_demo_output_into_git_component_is_refused(tmp_path: Path) -> None:
    assert main(["demo", "generate", "--output", str(tmp_path / ".git" / "x")]) == 9
    assert not (tmp_path / ".git").exists()


# --------------------------------------------------------------------------- #
# F4 — publishing over a non-regular-file target is a clean OutputCollisionError #
# --------------------------------------------------------------------------- #
def test_publish_bundle_refuses_overwriting_a_directory(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "result.json").mkdir()
    with pytest.raises(OutputCollisionError):
        publish_bundle(
            out,
            {"result.json": b"{}\n", "manifest.json": b"{}\n"},
            overwrite=True,
            completeness_marker="manifest.json",
        )


# --------------------------------------------------------------------------- #
# F7 — verify commands use taxonomy exit codes for an unreadable input          #
# --------------------------------------------------------------------------- #
def test_result_verify_missing_file_uses_taxonomy_exit_code(tmp_path: Path) -> None:
    assert main(["result", "verify", "--result", str(tmp_path / "nope.json")]) == 7


def test_receipt_verify_missing_file_uses_taxonomy_exit_code(tmp_path: Path) -> None:
    code = main(
        [
            "receipt",
            "verify",
            "--receipt",
            str(tmp_path / "a.json"),
            "--result",
            str(tmp_path / "b.json"),
        ]
    )
    assert code == 8


# --------------------------------------------------------------------------- #
# F8 — the doctor offline check is a real, in-process check                     #
# --------------------------------------------------------------------------- #
def test_doctor_offline_check_reports_the_real_state(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    offline = next(check for check in payload["checks"] if check["name"] == "offline")
    assert offline["ok"] is True
    assert offline["detail"] == "no network/exchange/wallet client is imported"
    assert code == 0


def test_offline_status_flips_when_a_network_client_is_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "requests", ModuleType("requests"))
    ok, detail = app._offline_capability_status()
    assert ok is False
    assert "requests" in detail


# --------------------------------------------------------------------------- #
# F9 — the config path guard is case-insensitive                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ["Research/x.csv", "RESEARCH/y.csv", ".GIT/config", ".Git/x"])
def test_config_rejects_governed_paths_case_insensitively(path: str) -> None:
    with pytest.raises(CanonicalError):
        _safe_rel_path(path, "dataset.file.path")


# --------------------------------------------------------------------------- #
# F10 — the run config is read exactly once; those bytes are what is bound       #
# --------------------------------------------------------------------------- #
def test_load_config_source_returns_the_exact_file_bytes(tmp_path: Path) -> None:
    raw = _config_bytes({})
    path = tmp_path / "config.json"
    path.write_bytes(raw)
    config, returned = load_config_source(path)
    assert returned == raw
    assert config.engine == "binary"
