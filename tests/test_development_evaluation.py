"""Walk-forward evaluator: diagnostics, determinism, and firewall spies.

The security-critical proof: no development-gate or final-holdout timestamp
(anything after 2022-06-21 UTC) ever reaches a strategy or the backtest
engine.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

import eth_research
from eth_research import development_evaluation
from eth_research.backtest import run_backtest as real_run_backtest
from eth_research.development_evaluation import (
    evaluate_development,
    expected_shortfall,
    exposure_fraction,
    longest_drawdown_duration,
    render_development_report,
)
from eth_research.replay_m2b import reconstruct_dataset

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"
BOUNDARY = pd.Timestamp("2022-06-21", tz="UTC")
FAMILY = "m3a-fixed-baseline-comparison-v1"

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "research/m2b/raw/coinbase" / ATTEMPT).is_dir(),
    reason="real committed acquisition not present",
)


@pytest.fixture(scope="module")
def real_manifest() -> Path:
    work = Path(tempfile.mkdtemp())
    return reconstruct_dataset(REPO_ROOT, ATTEMPT, work).build.manifest_path


def _evaluate(manifest: Path) -> Any:
    return evaluate_development(
        REPO_ROOT,
        manifest,
        execution_code_commit_sha="a" * 40,
        registered_code_commit_sha="b" * 40,
        experiment_family_id=FAMILY,
    )


class TestDiagnostics:
    def test_longest_drawdown_duration_hand_calc(self) -> None:
        # initial 100; equity 90,80,120,110,100: underwater until it exceeds 100.
        equity = pd.Series([90.0, 80.0, 120.0, 110.0, 100.0])
        # path=[100,90,80,120,110,100]; peaks=[100,100,100,120,120,120]
        # underwater=[F,T,T,F,T,T] -> longest run = 2 (last two) and (idx1-2)=2
        assert longest_drawdown_duration(equity, 100.0) == 2

    def test_longest_drawdown_terminal_unrecovered(self) -> None:
        equity = pd.Series([90.0, 80.0, 70.0])  # never recovers
        assert longest_drawdown_duration(equity, 100.0) == 3

    def test_expected_shortfall_mean_of_left_tail(self) -> None:
        returns = np.array([-0.10, -0.05, 0.0, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08])
        # 5th percentile (linear) cutoff, mean of obs <= cutoff.
        cutoff = float(np.percentile(returns, 5.0, method="linear"))
        expected = float(returns[returns <= cutoff].mean())
        assert expected_shortfall(returns) == pytest.approx(expected)

    def test_exposure_fraction_counts_positive_quantity_bars(self) -> None:
        # A short synthetic run through the engine.
        idx = pd.date_range("2020-01-01", periods=10, freq="D", tz="UTC")
        frame = pd.DataFrame(
            {
                "open": [10.0] * 10,
                "high": [11.0] * 10,
                "low": [9.0] * 10,
                "close": [10.0] * 10,
                "volume": [1.0] * 10,
            },
            index=idx,
        )
        from eth_research.strategies import BuyAndHold

        result = real_run_backtest(frame, BuyAndHold())
        assert exposure_fraction(result) == 1.0  # held the whole time


class TestEvaluatorShape:
    def test_produces_the_full_grid_deterministically(self, real_manifest: Path) -> None:
        res = _evaluate(real_manifest)
        assert len(res.fold_results) == 60  # 5 folds x 4 strategies x 3 costs
        assert len(res.independent_fold_summaries) == 12
        assert len(res.pooled_reset_oos) == 12
        assert len(res.full_train_exploratory) == 12
        assert len(res.bootstrap_cells) == 9  # 3 non-B&H strategies x 3 scenarios
        assert res.development_gate_event_count == 0
        assert res.final_holdout_event_count == 0
        assert _evaluate(real_manifest).to_json_bytes() == res.to_json_bytes()

    def test_report_has_all_sections(self, real_manifest: Path) -> None:
        import re

        md = render_development_report(_evaluate(real_manifest))
        sections = re.findall(r"^## (\d+)\.", md, re.MULTILINE)
        assert sections == [str(i) for i in range(1, 22)]


class TestFirewallSpies:
    def test_no_forbidden_timestamp_reaches_the_engine(
        self, real_manifest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[pd.Timestamp] = []

        def spy(data: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
            seen.append(data.index.max())
            context = kwargs.get("context")
            if context is not None and len(context) > 0:
                seen.append(context.index.max())
            return real_run_backtest(data, *args, **kwargs)

        monkeypatch.setattr(development_evaluation, "run_backtest", spy)
        _evaluate(real_manifest)
        assert seen, "the evaluator must have exercised the engine"
        assert max(seen) <= BOUNDARY
        # No development-gate (>= 2022-06-22) or final-holdout (>= 2024-07-01) row.
        assert max(seen) < pd.Timestamp("2022-06-22", tz="UTC")

    def test_strategy_generation_sees_no_forbidden_row(
        self, real_manifest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[pd.Timestamp] = []
        from eth_research.strategies.donchian import DonchianChannel

        original = DonchianChannel.target_positions

        def spy(self: DonchianChannel, data: pd.DataFrame) -> Any:
            seen.append(data.index.max())
            return original(self, data)

        monkeypatch.setattr(DonchianChannel, "target_positions", spy)
        _evaluate(real_manifest)
        assert seen
        assert max(seen) <= BOUNDARY

    def test_forbidden_row_injection_fails_before_strategy(
        self, real_manifest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force a fold's OOS frame to include a forbidden timestamp: the
        # firewall must reject it before any engine call.
        from eth_research import development_evaluation as de
        from eth_research.development import DevelopmentAccessError

        real_build = de.build_fold_frames

        def poisoned(research_train: pd.DataFrame, protocol: Any) -> Any:
            frames = real_build(research_train, protocol)
            last = frames[-1]  # its OOS ends exactly at the 2022-06-21 boundary
            # Append the *contiguous* next day — a development-gate row — so the
            # frame stays regular and the boundary check (not a gap check) fires.
            bad_idx = pd.Timestamp("2022-06-22", tz="UTC")
            bad = last.oos.iloc[[-1]].copy()
            bad.index = pd.DatetimeIndex([bad_idx])
            poisoned_oos = pd.concat([last.oos, bad])
            from dataclasses import replace

            return (*frames[:-1], replace(last, oos=poisoned_oos))

        monkeypatch.setattr(de, "build_fold_frames", poisoned)
        with pytest.raises(DevelopmentAccessError, match="forbidden partition access"):
            _evaluate(real_manifest)
