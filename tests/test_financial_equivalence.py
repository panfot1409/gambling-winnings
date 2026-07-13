"""Section 16: the financial-equivalence verifier catches any financial drift."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.financial_equivalence import (
    FinancialEquivalenceError,
    assert_financial_equivalence,
)

_REPO = Path(eth_research.__file__).resolve().parents[2]
_RUN002 = (
    _REPO
    / "research/m3a/experiments/m3a-fixed-baseline-comparison-v1-run-002"
    / "development_results.json"
)


def _payload() -> dict[str, Any]:
    payload = json.loads(_RUN002.read_bytes())
    assert isinstance(payload, dict)
    return payload


def _write(tmp_path: Path, name: str, payload: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_bytes(json.dumps(payload).encode("utf-8"))
    return path


class TestFinancialEquivalence:
    def test_identical_financials_pass(self, tmp_path: Path) -> None:
        # A copy with different identity/bootstrap fields but identical financials.
        run003 = _payload()
        run003["execution_code_commit_sha"] = "f" * 40
        run003["bootstrap_cells"] = []  # bootstrap is a permitted difference
        left = _write(tmp_path, "run002.json", _payload())
        right = _write(tmp_path, "run003.json", run003)
        summary = assert_financial_equivalence(left, right)
        assert summary.fold_cells == 60
        assert summary.independent_fold_summaries == 12
        assert summary.pooled_reset_oos == 12
        assert summary.full_train_exploratory == 12

    def test_mutated_fold_metric_is_caught(self, tmp_path: Path) -> None:
        run003 = _payload()
        # marked_total_return is a real float on every cell; perturb one.
        run003["fold_results"][0]["marked_total_return"] = -12345.678
        left = _write(tmp_path, "run002.json", _payload())
        right = _write(tmp_path, "run003.json", run003)
        with pytest.raises(FinancialEquivalenceError, match=r"field 'marked_total_return' differs"):
            assert_financial_equivalence(left, right)

    def test_missing_fold_cell_is_caught(self, tmp_path: Path) -> None:
        run003 = _payload()
        run003["fold_results"] = run003["fold_results"][:-1]
        left = _write(tmp_path, "run002.json", _payload())
        right = _write(tmp_path, "run003.json", run003)
        with pytest.raises(FinancialEquivalenceError, match="cell sets differ"):
            assert_financial_equivalence(left, right)

    def test_differing_data_fingerprint_is_caught(self, tmp_path: Path) -> None:
        run003 = _payload()
        run003["dataset_content_fingerprint"] = "sha256:" + "0" * 64
        left = _write(tmp_path, "run002.json", _payload())
        right = _write(tmp_path, "run003.json", run003)
        with pytest.raises(FinancialEquivalenceError, match="dataset_content_fingerprint"):
            assert_financial_equivalence(left, right)

    def test_int_to_float_type_change_is_caught(self, tmp_path: Path) -> None:
        run003 = _payload()
        # num_fills is an integer count; the same value as a float is still a drift.
        cell = next(
            c
            for c in run003["fold_results"]
            if isinstance(c["num_fills"], int) and not isinstance(c["num_fills"], bool)
        )
        cell["num_fills"] = float(cell["num_fills"])
        left = _write(tmp_path, "run002.json", _payload())
        right = _write(tmp_path, "run003.json", run003)
        with pytest.raises(FinancialEquivalenceError, match=r"field 'num_fills' differs"):
            assert_financial_equivalence(left, right)

    def test_run002_is_trivially_equivalent_to_itself(self, tmp_path: Path) -> None:
        summary = assert_financial_equivalence(_RUN002, _RUN002)
        assert summary.fold_cells == 60
