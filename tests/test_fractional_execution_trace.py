"""The committed execution-trace commitments bind the run and replay exactly."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.data.provenance import sha256_bytes
from eth_research.fractional.execution_trace import (
    EXECUTION_TRACE_COMMITMENTS_RELPATH,
    ExecutionTraceError,
    verify_execution_trace_commitments,
)
from eth_research.fractional.results import FRACTIONAL_RESULTS_RELPATH

REPO = Path(eth_research.__file__).resolve().parents[2]
_STRATEGIES = (
    "cash",
    "buy_and_hold",
    "donchian_55_20",
    "vol_target_buy_and_hold_30d_50pct",
    "vol_target_donchian_55_20_30d_50pct",
)
_SCENARIOS = ("compatibility_v1", "causal_proxy_base", "causal_proxy_stressed")


def _committed() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((REPO / EXECUTION_TRACE_COMMITMENTS_RELPATH).read_bytes())
    return payload


def test_commitments_are_canonical_and_bind_the_committed_results() -> None:
    payload = _committed()
    assert payload["execution_trace_commitments_schema_version"] == 1
    assert payload["cell_count"] == 75
    assert len(payload["cells"]) == 75
    results_sha = sha256_bytes((REPO / FRACTIONAL_RESULTS_RELPATH).read_bytes())
    assert payload["fractional_results_sha256"] == results_sha


def test_commitments_cover_the_exact_grid() -> None:
    cells = _committed()["cells"]
    seen = {(c["strategy"], c["cost_scenario"], c["fold_index"]) for c in cells}
    expected = {
        (strategy, scenario, fold)
        for strategy in _STRATEGIES
        for scenario in _SCENARIOS
        for fold in range(5)
    }
    assert seen == expected
    for cell in cells:
        assert cell["bar_count"] > 0
        assert len(cell["trace_sha256"]) == 64


def test_tampered_results_binding_is_rejected_without_replay(tmp_path: Path) -> None:
    # The results-binding check precedes the (slow) grid replay, so a broken bind
    # is caught cheaply.
    shutil.copytree(REPO / "research" / "m3b", tmp_path / "research" / "m3b")
    path = tmp_path / EXECUTION_TRACE_COMMITMENTS_RELPATH
    payload = json.loads(path.read_bytes())
    good = payload["fractional_results_sha256"]
    payload["fractional_results_sha256"] = good.replace(good[0], "0" if good[0] != "0" else "1", 1)
    path.write_bytes(
        (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )
    with pytest.raises(ExecutionTraceError, match="bind the committed results"):
        verify_execution_trace_commitments(tmp_path)


@pytest.mark.slow
def test_commitments_replay_byte_for_byte() -> None:
    assert verify_execution_trace_commitments(REPO) == (
        "trace_commitments_canonical",
        "trace_commitments_bind_results",
        "trace_commitments_replay_byte_for_byte",
    )
