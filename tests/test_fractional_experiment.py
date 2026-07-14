"""The 75-cell fractional experiment runner over a synthetic research-train frame.

Real research-train execution is the preregistered orchestrated run only; these
tests drive the deterministic runner on a synthetic 2221-row frame so the grid
coverage, causal warm-up, reconciliation gate, and provenance assembly are all
exercised without touching a committed artifact or a sealed row.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import eth_research
from eth_research.data.provenance import content_fingerprint
from eth_research.data.schema import validate_ohlcv
from eth_research.fractional.cost_model import SCENARIOS
from eth_research.fractional.experiment import (
    ExperimentError,
    build_fractional_results,
    compute_fractional_fold_cells,
)
from eth_research.fractional.protocol import (
    FRACTIONAL_PROTOCOL_RELPATH,
    FractionalProtocol,
    load_fractional_protocol,
)
from eth_research.fractional.results import FractionalFoldCell, FractionalResults
from eth_research.fractional.strategies import STRATEGY_NAMES
from eth_research.walkforward import (
    RESEARCH_TRAIN_ROWS,
    WalkForwardProtocol,
    build_walk_forward_protocol,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
PROTOCOL_PATH = REPO_ROOT / FRACTIONAL_PROTOCOL_RELPATH
_SCEN = tuple(s.name for s in SCENARIOS)


def _synthetic_research_train() -> pd.DataFrame:
    # A deterministic cyclic-plus-trend path with a tight OHLC band, so the
    # 55/20 Donchian channel is actually broken (a wide band would inflate the
    # entry level above every close and the breakout would never trigger).
    n = RESEARCH_TRAIN_ROWS
    index = pd.date_range("2016-05-23", periods=n, freq="D", tz="UTC")
    t = np.arange(n, dtype="float64")
    close = 350.0 + 180.0 * np.sin(t / 55.0) + 0.05 * t + 22.0 * np.sin(t / 9.0)
    open_ = np.empty(n, dtype="float64")
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) * 1.0008
    low = np.minimum(open_, close) * 0.9992
    volume = 5_000.0 + 20.0 * t + 500.0 * np.abs(np.sin(t / 7.0))
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
    return validate_ohlcv(frame, expected_interval="1D")


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return _synthetic_research_train()


@pytest.fixture(scope="module")
def wf_protocol(frame: pd.DataFrame) -> WalkForwardProtocol:
    return build_walk_forward_protocol(frame, development_partition_sha256="a" * 64)


@pytest.fixture(scope="module")
def cells(frame: pd.DataFrame, wf_protocol: WalkForwardProtocol) -> tuple[FractionalFoldCell, ...]:
    return compute_fractional_fold_cells(frame, wf_protocol, initial_cash=10_000.0)


class TestGrid:
    def test_produces_the_full_75_cell_grid(self, cells: tuple[FractionalFoldCell, ...]) -> None:
        assert len(cells) == 75
        grid = {(c.strategy, c.cost_scenario, c.fold_index) for c in cells}
        assert grid == {
            (strategy, scenario, fold)
            for strategy in STRATEGY_NAMES
            for scenario in _SCEN
            for fold in range(5)
        }

    def test_is_deterministic(
        self,
        frame: pd.DataFrame,
        wf_protocol: WalkForwardProtocol,
        cells: tuple[FractionalFoldCell, ...],
    ) -> None:
        again = compute_fractional_fold_cells(frame, wf_protocol, initial_cash=10_000.0)
        assert again == cells

    def test_fold_windows_match_the_protocol(
        self, cells: tuple[FractionalFoldCell, ...], wf_protocol: WalkForwardProtocol
    ) -> None:
        by_fold = {f.fold_index: f for f in wf_protocol.folds}
        for cell in cells:
            fold = by_fold[cell.fold_index]
            assert cell.oos_first_open_time == fold.oos_first_open_time
            assert cell.oos_last_open_time == fold.oos_last_open_time
            assert cell.oos_row_count == fold.oos_row_count


class TestCells:
    def test_cash_is_flat_and_never_trades(self, cells: tuple[FractionalFoldCell, ...]) -> None:
        cash = [c for c in cells if c.strategy == "cash"]
        assert len(cash) == 15
        for c in cash:
            assert c.marked_total_return == pytest.approx(0.0, abs=1e-12)
            assert c.num_fills == 0
            assert c.total_fees == 0.0
            assert c.average_achieved_exposure == pytest.approx(0.0, abs=1e-12)

    def test_buy_and_hold_holds_from_entry(self, cells: tuple[FractionalFoldCell, ...]) -> None:
        bnh = [c for c in cells if c.strategy == "buy_and_hold"]
        assert len(bnh) == 15
        for c in bnh:
            # holds ETH from the first bar onward, even when a participation cap
            # spreads the entry over several bars.
            assert c.num_fills >= 1
            assert c.time_in_market == 1.0
        # the frictionless compatibility scenario is one clean, full fill.
        compat = [c for c in bnh if c.cost_scenario == "compatibility_v1"]
        assert len(compat) == 5
        for c in compat:
            assert c.num_fills == 1
            assert c.average_achieved_exposure > 0.99

    def test_liquidation_never_exceeds_marked(self, cells: tuple[FractionalFoldCell, ...]) -> None:
        for c in cells:
            assert c.terminal_liquidation_equity <= c.marked_terminal_equity + 1e-9
            assert c.marked_terminal_equity > 0.0

    def test_bounds_hold_for_every_cell(self, cells: tuple[FractionalFoldCell, ...]) -> None:
        for c in cells:
            assert -1.0 <= c.max_drawdown <= 0.0
            assert -1e-9 <= c.average_achieved_exposure <= 1.0 + 1e-9
            assert 0.0 <= c.time_in_market <= 1.0

    def test_active_strategies_actually_trade(self, cells: tuple[FractionalFoldCell, ...]) -> None:
        # Donchian and the vol-target strategies must trade at least once
        # somewhere on the synthetic frame (non-vacuous coverage).
        for strategy in STRATEGY_NAMES:
            if strategy in ("cash",):
                continue
            fills = sum(c.num_fills for c in cells if c.strategy == strategy)
            assert fills >= 1, strategy


class TestBuildResults:
    def _protocol(self, frame: pd.DataFrame) -> FractionalProtocol:
        committed = load_fractional_protocol(PROTOCOL_PATH)
        return dataclasses.replace(
            committed, research_train_content_fingerprint=content_fingerprint(frame)
        )

    def test_assembles_a_valid_results_model(
        self, frame: pd.DataFrame, cells: tuple[FractionalFoldCell, ...]
    ) -> None:
        results = build_fractional_results(
            fractional_protocol=self._protocol(frame),
            research_train=frame,
            fold_cells=cells,
            package_version="0.5.0",
            execution_code_commit_sha="b" * 40,
            registered_code_commit_sha="c" * 40,
            execution_source_tree_fingerprint="sha256:" + "d" * 64,
            fractional_protocol_sha256="e" * 64,
        )
        raw = results.to_json_bytes()
        assert FractionalResults.from_json_bytes(raw) == results
        assert results.development_gate_event_count == 0
        assert results.final_holdout_event_count == 0

    def test_fingerprint_mismatch_fails_closed(
        self, frame: pd.DataFrame, cells: tuple[FractionalFoldCell, ...]
    ) -> None:
        committed = load_fractional_protocol(PROTOCOL_PATH)
        with pytest.raises(ExperimentError, match="content fingerprint disagrees"):
            build_fractional_results(
                fractional_protocol=committed,  # binds the REAL research-train fingerprint
                research_train=frame,  # synthetic frame -> mismatch
                fold_cells=cells,
                package_version="0.5.0",
                execution_code_commit_sha="b" * 40,
                registered_code_commit_sha="c" * 40,
                execution_source_tree_fingerprint="sha256:" + "d" * 64,
                fractional_protocol_sha256="e" * 64,
            )
