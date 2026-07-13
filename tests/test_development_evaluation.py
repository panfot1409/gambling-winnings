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
    load_development_results_payload,
    longest_drawdown_duration,
    render_development_report,
)
from eth_research.replay_m2b import reconstruct_dataset

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"
BOUNDARY = pd.Timestamp("2022-06-21", tz="UTC")
FAMILY = "m3a-fixed-baseline-comparison-v1"
# The v1 evaluator reproduces the v1 experiment run-002; its provenance is read
# from run-002's immutable archive (the compatibility alias migrates to schema
# v2 once run-003 completes, so it is no longer a v1 provenance source).
RUN002_RESULTS = (
    REPO_ROOT
    / "research/m3a/experiments/m3a-fixed-baseline-comparison-v1-run-002/development_results.json"
)

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "research/m2b/raw/coinbase" / ATTEMPT).is_dir(),
    reason="real committed acquisition not present",
)


@pytest.fixture(scope="module")
def real_manifest() -> Path:
    work = Path(tempfile.mkdtemp())
    return reconstruct_dataset(REPO_ROOT, ATTEMPT, work).build.manifest_path


def _evaluate(manifest: Path) -> Any:
    # Phase 13 discipline: real research-train data is evaluated here only to
    # reproduce the *registered* experiment, so the provenance is the committed
    # experiment's own (never fabricated `"a"*40`/`"b"*40` commits). Synthetic
    # fixtures cover the pure unit diagnostics; the firewall spies below assert
    # no forbidden row reaches the engine.
    payload = load_development_results_payload(RUN002_RESULTS)
    return evaluate_development(
        REPO_ROOT,
        manifest,
        execution_code_commit_sha=payload["execution_code_commit_sha"],
        registered_code_commit_sha=payload["registered_code_commit_sha"],
        experiment_family_id=payload["experiment_family_id"],
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

    def test_fold_table_reports_fold_context_not_cash(self, real_manifest: Path) -> None:
        # Regression: the fold table must show the fold's available warm-up
        # context (55), not the cash strategy's zero. Sampling strategies[0]
        # (cash) once printed 0 for every fold, contradicting the protocol.
        md = render_development_report(_evaluate(real_manifest))
        section5 = md.split("## 5. Fold table")[1].split("## 6.")[0]
        data_rows = [ln for ln in section5.splitlines() if ln.startswith("| 0 |")]
        assert data_rows, "fold 0 data row missing"
        # columns: | fold | training rows | context rows | OOS rows | window |
        context_cell = data_rows[0].split("|")[3].strip()
        assert context_cell == "55", f"fold context column is {context_cell!r}, expected 55"

    def test_report_documents_the_donchian_warmup(self, real_manifest: Path) -> None:
        # Regression: the conservative one-bar Donchian warm-up must be disclosed.
        md = render_development_report(_evaluate(real_manifest))
        assert "first OOS bar flat" in md
        assert "not look-ahead" in md


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
        from eth_research.walkforward import build_fold_frames as real_build

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


class TestFrozenDossierReVerificationDisclosure:
    """Pin the one disclosed exception to the firewall (see ``development.py``).

    Loading the dataset first re-verifies the frozen M2B dossier, which recomputes
    M2B's already-published train+validation benchmark. That re-simulation runs the
    M2 validation segment — the M3A development gate — through the engine. This is
    benign (public M2B numbers, hash-compared and discarded, no gate-ledger event,
    run-003 financials unchanged) but it is real, so it is disclosed and pinned
    here: the re-derivation must never reach the final holdout, and both sealed
    ledgers must stay byte-empty. The M3A walk-forward's own surfaces are proven
    clean by :class:`TestFirewallSpies` above (which patches the evaluator binding).
    """

    GATE_END = pd.Timestamp("2024-06-30", tz="UTC")
    HOLDOUT_START = pd.Timestamp("2024-07-01", tz="UTC")
    _GATE_LEDGER = REPO_ROOT / "research/m3a/development_gate_access.jsonl"
    _HOLDOUT_LEDGER = REPO_ROOT / "research/m2b/test_evaluations.jsonl"

    def test_dossier_reverification_touches_validation_but_never_the_holdout(
        self, real_manifest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from eth_research import evaluation as ev
        from eth_research.development import load_development_dataset

        assert self._GATE_LEDGER.read_bytes() == b""
        assert self._HOLDOUT_LEDGER.read_bytes() == b""

        seen: list[pd.Timestamp] = []
        original = ev.run_backtest

        def spy(data: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
            seen.append(data.index.max())
            return original(data, *args, **kwargs)

        monkeypatch.setattr(ev, "run_backtest", spy)
        dataset = load_development_dataset(REPO_ROOT, real_manifest)

        # The dossier re-derivation exercised the engine over the M2 validation
        # (== development-gate) segment, but never the final holdout.
        assert seen, "the frozen-dossier verification must exercise the engine"
        assert max(seen) == self.GATE_END
        assert all(ts < self.HOLDOUT_START for ts in seen)
        # The frame M3A actually evaluates is research-train only.
        assert dataset.frame.index.max() == BOUNDARY
        assert len(dataset.frame) == 2221
        # No development-gate or final-holdout access was recorded.
        assert self._GATE_LEDGER.read_bytes() == b""
        assert self._HOLDOUT_LEDGER.read_bytes() == b""
