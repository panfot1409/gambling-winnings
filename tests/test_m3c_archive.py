"""M3C manifest model + bundle digest + deterministic trace commitment."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from eth_research.data.schema import validate_ohlcv
from eth_research.fractional.cost_model import COMPATIBILITY_V1
from eth_research.fractional.engine import run_fractional_backtest
from eth_research.fractional.strategies import STRATEGIES_BY_NAME
from eth_research.m3c.archive import (
    M3C_MANIFEST_RELPATH,
    M3C_MANIFEST_SCHEMA_VERSION,
    M3CArchiveError,
    M3CArtifactManifest,
    bundle_sha256,
)
from eth_research.m3c.decision import M3C_DECISION_RELPATH
from eth_research.m3c.pipeline import cell_trace_commitment
from eth_research.m3c.results import M3C_REPORT_RELPATH, M3C_RESULTS_RELPATH

_REJECT = (ValueError, TypeError, M3CArchiveError)
_HEX64 = "a" * 64


def _manifest() -> M3CArtifactManifest:
    return M3CArtifactManifest(
        manifest_schema_version=M3C_MANIFEST_SCHEMA_VERSION,
        experiment_id="m3c-dual-horizon-trend-v1-run-001",
        experiment_family="m3c-dual-horizon-trend-v1",
        package_version="0.6.0",
        results_path=M3C_RESULTS_RELPATH,
        results_sha256="1" * 64,
        report_path=M3C_REPORT_RELPATH,
        report_sha256="2" * 64,
        decision_path=M3C_DECISION_RELPATH,
        decision_sha256="3" * 64,
        bundle_sha256="4" * 64,
        promotion_status="rejected_for_development_gate_promotion",
        registered_event_sha256="5" * 64,
        started_event_sha256="6" * 64,
    )


def test_manifest_round_trips() -> None:
    m = _manifest()
    assert M3CArtifactManifest.from_json_bytes(m.to_json_bytes()) == m
    assert m.to_json_bytes().endswith(b"\n")  # canonical trailing newline


def test_manifest_rejects_wrong_artifact_paths() -> None:
    with pytest.raises(_REJECT):
        dataclasses.replace(_manifest(), results_path="research/m3c/somewhere_else.json")
    with pytest.raises(_REJECT):
        dataclasses.replace(_manifest(), decision_path="research/m3c/not_the_decision.json")


def test_manifest_rejects_non_hex_digest() -> None:
    with pytest.raises(_REJECT):
        dataclasses.replace(_manifest(), results_sha256="nope")
    with pytest.raises(_REJECT):
        dataclasses.replace(_manifest(), manifest_schema_version=2)


def test_manifest_relpath_is_under_the_run_directory() -> None:
    assert M3C_MANIFEST_RELPATH == "research/m3c/experiments/run-001/manifest.json"


def test_bundle_is_order_sensitive_concatenation() -> None:
    a, b, c = b"results", b"report", b"decision"
    assert bundle_sha256(a, b, c) != bundle_sha256(a, c, b)
    # Deterministic and equal to a manual concatenation digest.
    from eth_research.data.provenance import sha256_bytes

    assert bundle_sha256(a, b, c) == sha256_bytes(a + b + c)


def _tiny_result():
    n = 320
    close = 100.0 * (1.001 ** np.arange(n))
    idx = pd.date_range("2016-01-01", periods=n, freq="D", tz="UTC")
    frame = validate_ohlcv(
        pd.DataFrame(
            {
                "open": close,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": np.full(n, 1000.0),
            },
            index=idx,
        ),
        expected_interval="1D",
    )
    context, oos = frame.iloc[:260], frame.iloc[260:]
    return run_fractional_backtest(
        oos, STRATEGIES_BY_NAME["buy_and_hold"], COMPATIBILITY_V1, context=context
    )


def test_trace_commitment_is_deterministic_and_hex64() -> None:
    result = _tiny_result()
    a = cell_trace_commitment("buy_and_hold", "compatibility_v1", 0, result)
    b = cell_trace_commitment("buy_and_hold", "compatibility_v1", 0, result)
    assert a == b
    assert len(a) == 64
    assert all(ch in "0123456789abcdef" for ch in a)
    # The digest binds the (strategy, scenario, fold) label, so a different fold index differs.
    assert cell_trace_commitment("buy_and_hold", "compatibility_v1", 1, result) != a
