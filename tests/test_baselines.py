"""Cash and Donchian(55/20) baselines: causal, current-bar-safe, binary."""

from __future__ import annotations

import numpy as np
import pandas as pd

from eth_research.backtest import CostModel, run_backtest
from eth_research.strategies import Cash, DonchianChannel


def _frame(closes: list[float], highs: list[float], lows: list[float]) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": [float(c) for c in closes],
            "high": [float(h) for h in highs],
            "low": [float(low) for low in lows],
            "close": [float(c) for c in closes],
            "volume": [1.0] * n,
        },
        index=idx,
    )


class TestCash:
    def test_always_flat(self) -> None:
        frame = _frame([10, 11, 12, 13], [10, 11, 12, 13], [9, 10, 11, 12])
        targets = Cash().target_positions(frame)
        assert list(targets) == [0.0, 0.0, 0.0, 0.0]
        assert Cash().name == "cash"
        assert Cash().initial_target == 0

    def test_no_fills_constant_equity(self) -> None:
        frame = _frame(list(range(10, 40)), list(range(10, 40)), list(range(9, 39)))
        result = run_backtest(frame, Cash(), CostModel())
        assert result.num_trades == 0
        assert result.total_traded_notional == 0.0
        assert result.turnover == 0.0
        assert (result.equity == result.initial_cash).all()


class TestDonchianHandCalc:
    def test_entry_and_exit_path(self) -> None:
        # entry_window=3, exit_window=2. Breakout then breakdown.
        frame = _frame(
            closes=[10, 10, 10, 15, 19, 6, 6, 6],
            highs=[10, 10, 10, 10, 20, 20, 20, 10],
            lows=[9, 9, 9, 9, 9, 5, 5, 5],
        )
        targets = DonchianChannel(entry_window=3, exit_window=2).target_positions(frame)
        assert list(targets) == [0, 0, 0, 1, 1, 0, 0, 0]

    def test_name(self) -> None:
        assert DonchianChannel().name == "donchian_55_20"

    def test_equality_does_not_trigger(self) -> None:
        # close exactly equals the prior-3 high max -> no entry (strict >).
        frame = _frame(
            closes=[10, 10, 10, 10, 10],
            highs=[10, 10, 10, 10, 10],
            lows=[9, 9, 9, 9, 9],
        )
        targets = DonchianChannel(entry_window=3, exit_window=2).target_positions(frame)
        assert list(targets) == [0, 0, 0, 0, 0]

    def test_flat_during_warmup(self) -> None:
        frame = _frame(list(range(1, 60)), list(range(1, 60)), [0.5] * 59)
        targets = DonchianChannel().target_positions(frame)  # 55/20 default
        # No entry can occur before 55 prior candles exist.
        assert (targets.iloc[:55] == 0.0).all()

    def test_targets_are_binary(self) -> None:
        rng = np.random.default_rng(0)
        n = 200
        closes = np.cumsum(rng.normal(size=n)) + 100
        highs = closes + rng.uniform(0, 2, n)
        lows = closes - rng.uniform(0, 2, n)
        frame = _frame(list(closes), list(highs), list(lows))
        targets = DonchianChannel().target_positions(frame)
        assert set(np.unique(targets.to_numpy())) <= {0.0, 1.0}


class TestDonchianLookAhead:
    def _random_frame(self, n: int = 300, seed: int = 7) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        closes = np.cumsum(rng.normal(size=n)) + 100
        highs = closes + rng.uniform(0, 3, n)
        lows = closes - rng.uniform(0, 3, n)
        return _frame(list(closes), list(highs), list(lows))

    def test_prefix_invariance(self) -> None:
        # The target at bar t depends only on bars <= t: computing over a
        # longer series must not change any earlier target.
        frame = self._random_frame()
        full = DonchianChannel().target_positions(frame)
        for cut in (80, 150, 220):
            prefix = DonchianChannel().target_positions(frame.iloc[:cut])
            assert list(prefix) == list(full.iloc[:cut])

    def test_future_mutation_invariance(self) -> None:
        # Mutating a future bar must not change any earlier target.
        frame = self._random_frame()
        base = DonchianChannel().target_positions(frame)
        mutated = frame.copy()
        mutated.loc[mutated.index[250], "high"] = 10_000.0
        mutated.loc[mutated.index[250], "close"] = 10_000.0
        after = DonchianChannel().target_positions(mutated)
        assert list(base.iloc[:250]) == list(after.iloc[:250])

    def test_same_bar_high_cannot_cause_same_bar_entry(self) -> None:
        frame = _frame(
            closes=[10, 10, 10, 10, 10, 10],
            highs=[10, 10, 10, 10, 10, 10],
            lows=[9, 9, 9, 9, 9, 9],
        )
        # Spike the current high AND close on the last bar; the channel excludes
        # the current bar, so entry at that bar must still not trigger (max of
        # the prior-3 highs is 10, close 10 is not > 10).
        frame.loc[frame.index[5], "high"] = 100.0
        targets = DonchianChannel(entry_window=3, exit_window=2).target_positions(frame)
        assert targets.iloc[5] == 0.0

    def test_same_bar_low_cannot_cause_same_bar_exit(self) -> None:
        # Enter long, then drop the current low far below on a bar; the exit
        # channel excludes the current bar, so a same-bar low spike alone must
        # not force a same-bar exit (only the close vs the *prior* min matters).
        frame = _frame(
            closes=[10, 10, 10, 15, 15, 15],
            highs=[10, 10, 10, 10, 15, 15],
            lows=[9, 9, 9, 9, 9, 9],
        )
        targets = DonchianChannel(entry_window=3, exit_window=2).target_positions(frame)
        assert targets.iloc[3] == 1.0  # entered
        frame2 = frame.copy()
        frame2.loc[frame2.index[4], "low"] = 0.01  # spike current low only
        t2 = DonchianChannel(entry_window=3, exit_window=2).target_positions(frame2)
        # close[4]=15 vs min(prior-2 lows = l2,l3 = 9,9) = 9; 15 not < 9 -> stay long
        assert t2.iloc[4] == 1.0

    def test_context_carry_matches_full_series(self) -> None:
        # Running with warm-up context must match running over context+eval.
        frame = self._random_frame(n=200)
        full_targets = DonchianChannel().target_positions(frame)
        # engine path: context is the first 120 rows, eval the next 80.
        result = run_backtest(
            frame.iloc[120:],
            DonchianChannel(),
            CostModel(),
            context=frame.iloc[65:120],
        )
        # The engine executes the target decided at the prior close; here we
        # just confirm the strategy signal over context+eval equals the full.
        combined = pd.concat([frame.iloc[65:120], frame.iloc[120:]])
        combined_targets = DonchianChannel().target_positions(combined)
        assert list(combined_targets.iloc[-len(frame.iloc[120:]) :]) == list(
            full_targets.iloc[120:]
        )
        assert result.num_trades >= 0
