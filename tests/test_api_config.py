"""Strict run-configuration parsing (JSON + TOML)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from eth_research import api
from eth_research.api.config import load_config, load_config_file


def _valid_synthetic() -> dict[str, Any]:
    return {
        "config_schema_version": 1,
        "dataset": {"source": "synthetic", "synthetic": {"n_periods": 100, "seed": 1}},
        "engine": "binary",
        "strategy": {"kind": "buy_and_hold", "params": {}},
        "costs": {"scenario": "base"},
        "split": {"enabled": False},
        "run": {"initial_cash": 10000.0},
        "output": {"directory": "out"},
    }


def _load(cfg: dict[str, Any]) -> api.RunConfig:
    return load_config(json.dumps(cfg).encode("utf-8"), fmt="json")


def test_valid_synthetic_config_parses() -> None:
    cfg = _load(_valid_synthetic())
    assert cfg.config_schema_version == 1
    assert cfg.engine == "binary"
    assert cfg.dataset.source == "synthetic"
    assert cfg.dataset.synthetic is not None
    assert cfg.dataset.synthetic.n_periods == 100
    assert cfg.strategy.kind == "buy_and_hold"
    assert cfg.costs.scenario == "base"
    assert cfg.output.directory == "out"
    assert cfg.output.overwrite is False


def test_valid_file_config_parses() -> None:
    cfg = _valid_synthetic()
    cfg["dataset"] = {
        "source": "file",
        "file": {"path": "data/eth.csv", "interval_seconds": 86400},
    }
    parsed = _load(cfg)
    assert parsed.dataset.source == "file"
    assert parsed.dataset.file is not None
    assert parsed.dataset.file.path == "data/eth.csv"
    assert parsed.dataset.file.interval_seconds == 86400


def test_toml_config_parses() -> None:
    toml = b"""
config_schema_version = 1
engine = "fractional"

[dataset]
source = "synthetic"
[dataset.synthetic]
n_periods = 80

[strategy]
kind = "donchian_55_20"
params = {}

[costs]
scenario = "causal_proxy_base"

[output]
directory = "results"
"""
    cfg = load_config(toml, fmt="toml")
    assert cfg.engine == "fractional"
    assert cfg.costs.scenario == "causal_proxy_base"
    assert cfg.output.directory == "results"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.__setitem__("unexpected", 1),
        lambda c: c["dataset"].__setitem__("unexpected", 1),
        lambda c: c.__setitem__("config_schema_version", 2),
        lambda c: c.__setitem__("engine", "quantum"),
        lambda c: c["run"].__setitem__("initial_cash", "10000"),  # string not repaired
        lambda c: c["run"].__setitem__("initial_cash", -5),  # non-positive
        lambda c: c["strategy"]["params"].__setitem__("fast_window", True),  # bool != int
        lambda c: c["costs"].__setitem__("scenario", "compatibility_v1"),  # wrong engine
        lambda c: c["output"].__setitem__("directory", "/abs/path"),
        lambda c: c["output"].__setitem__("directory", "../escape"),
        lambda c: c["output"].__setitem__("directory", "research/m2b/x"),
        lambda c: c["output"].__setitem__("directory", "http://x/y"),
    ],
)
def test_strict_rejections(mutate: Any) -> None:
    cfg = _valid_synthetic()
    cfg["strategy"] = {"kind": "moving_average_crossover", "params": {"fast_window": 5}}
    mutate(cfg)
    with pytest.raises(api.ConfigurationError):
        _load(cfg)


def test_non_finite_number_rejected() -> None:
    # inf cannot appear in strict JSON; assert the strict decoder rejects it.
    raw = b'{"config_schema_version": 1e999}'
    with pytest.raises(api.ConfigurationError):
        load_config(raw, fmt="json")


def test_load_config_file_by_extension(tmp_path: Any) -> None:
    path = tmp_path / "run.json"
    path.write_bytes(json.dumps(_valid_synthetic()).encode("utf-8"))
    assert load_config_file(path).engine == "binary"
    bad = tmp_path / "run.yaml"
    bad.write_bytes(b"x: 1\n")
    with pytest.raises(api.ConfigurationError):
        load_config_file(bad)
