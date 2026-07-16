"""Adversarial misuse of the public API and cross-platform path handling."""

from __future__ import annotations

import json

import pytest

from eth_research import api
from eth_research.api.config import load_config
from eth_research.api.serialization import CanonicalError


def test_engine_strategy_mismatch_is_rejected() -> None:
    ds = api.generate_synthetic_dataset(n_periods=80, seed=1)
    # a fractional-only strategy id on the binary engine
    with pytest.raises(api.StrategyError):
        api.run_binary_backtest(
            ds, api.StrategySpec("vol_target_buy_and_hold_30d_50pct"), api.CostSpec("base")
        )
    # a binary strategy on the fractional engine with an unknown fractional id
    with pytest.raises(api.StrategyError):
        api.run_fractional_backtest(
            ds, api.StrategySpec("moving_average_crossover"), api.CostSpec("compatibility_v1")
        )


def test_strategy_spec_rejects_non_integer_params() -> None:
    with pytest.raises(CanonicalError):
        api.StrategySpec(kind="moving_average_crossover", params=(("fast_window", "ten"),))  # type: ignore[arg-type]


def test_result_parsing_is_strict() -> None:
    ds = api.generate_synthetic_dataset(n_periods=80, seed=1)
    good = api.run_binary_backtest(
        ds, api.StrategySpec("buy_and_hold"), api.CostSpec("base")
    ).to_json_bytes()
    # missing trailing newline (non-canonical)
    with pytest.raises(api.ResultValidationError):
        api.ResearchResult.from_json_bytes(good.rstrip(b"\n"))
    # duplicate keys
    with pytest.raises(api.ResultValidationError):
        api.ResearchResult.from_json_bytes(b'{"a": 1, "a": 2}\n')


def test_receipt_parsing_is_strict() -> None:
    with pytest.raises(api.ReceiptVerificationError):
        api.RunReceipt.from_json_bytes(b'{"not": "a receipt"}\n')


def test_unknown_cost_scenario_is_configuration_error() -> None:
    ds = api.generate_synthetic_dataset(n_periods=60, seed=1)
    with pytest.raises(api.ConfigurationError):
        api.calculate_metrics(ds, api.StrategySpec("cash"), api.CostSpec("nonexistent"))


def test_dataset_and_split_specs_validate_bounds() -> None:
    with pytest.raises(CanonicalError):
        api.DatasetSpec(interval_seconds=0)
    with pytest.raises(CanonicalError):
        api.ChronologicalSplitSpec(0.8, 0.3)


@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",  # absolute
        "..\\escape",  # backslash (windows-style) traversal
        "a\\b.csv",  # backslash separator
        "../up",  # posix traversal
        "research/m3f/x",  # governed root
        "https://example.com/data.csv",  # url
        ".git/config",  # vcs
    ],
)
def test_config_rejects_unsafe_dataset_paths(bad_path: str) -> None:
    config = {
        "config_schema_version": 1,
        "dataset": {"source": "file", "file": {"path": bad_path, "interval_seconds": 86400}},
        "engine": "binary",
        "strategy": {"kind": "buy_and_hold", "params": {}},
        "costs": {"scenario": "base"},
        "output": {"directory": "out"},
    }
    with pytest.raises(api.ConfigurationError):
        load_config(json.dumps(config).encode("utf-8"), fmt="json")


def test_publish_rejects_windows_style_filenames(tmp_path: object) -> None:
    from pathlib import Path

    out = tmp_path if isinstance(tmp_path, Path) else Path(str(tmp_path))
    with pytest.raises(api.OutputCollisionError):
        api.publish_bundle(out / "bundle", {"a\\b.txt": b"x\n"})
