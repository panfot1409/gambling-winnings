"""Reproductions for the M3B trust-boundary closure defects (R1-R11).

Each ``xfail(strict=True)`` test asserts the *desired* strict behaviour, so it
xfails against the current code (documenting the live defect) and will xpass once
the fix lands — at which point the marker is removed in the fixing commit, per
the closure plan. The un-marked tests are passing *evidence* of a fact the
closure documents (equal lifecycle timestamps, the cellwise cost-monotonicity
counterexample, the single-file archive body, the aggregate-only evidence).

None of these tests evaluate the development gate or final holdout, and none
mutate a committed artifact.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import eth_research
from eth_research.data.schema import validate_ohlcv
from eth_research.fractional.accounting import (
    DEFAULT_TOLERANCES,
    AccountingError,
    PortfolioState,
    equity_at,
)
from eth_research.fractional.cost_model import COMPATIBILITY_V1
from eth_research.fractional.engine import EngineError, run_fractional_backtest
from eth_research.fractional.liquidity import LiquidityError, estimate_liquidity
from eth_research.fractional.registry import read_registry
from eth_research.fractional.results import FractionalResults
from eth_research.fractional.strategies import FractionalStrategy, RiskConfig
from eth_research.strategies.base import Strategy

REPO = Path(eth_research.__file__).resolve().parents[2]
_RESULTS = REPO / "research/m3b/fractional_results.json"
_REGISTRY = REPO / "research/m3b/experiment_registry.jsonl"

# The strict rejections raise one of these domain / value errors (never a blind
# Exception, and never a silent coercion).
_REJECT = (ValueError, TypeError, AccountingError, EngineError, LiquidityError)


def _tiny_frame(n: int = 8) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    close = 100.0 + np.arange(n, dtype="float64")
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    vol = np.full(n, 1_000.0)
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx
    )
    return validate_ohlcv(frame, expected_interval="1D")


class _ConstSignal(Strategy):
    """A fixed target; optionally returns a shuffled / mis-valued signal index."""

    def __init__(self, *, shuffle: bool = False, value: float = 1.0) -> None:
        self._shuffle = shuffle
        self._value = value

    @property
    def name(self) -> str:
        return "const"

    def target_positions(self, data: pd.DataFrame) -> pd.Series:
        index = data.index[::-1] if self._shuffle else data.index
        return pd.Series(np.full(len(data), self._value), index=index, name="t")


def _strategy(signal: Strategy) -> FractionalStrategy:
    return FractionalStrategy(signal.name, signal, RiskConfig(max_exposure=1.0), warmup_bars=0)


def _mutated_results(**overrides: object) -> bytes:
    payload = json.loads(_RESULTS.read_bytes())
    payload.update(overrides)
    return json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")


# ---------------------------------------------------------------------------
# R4 — results parser must not repair malformed input
# ---------------------------------------------------------------------------
class TestR4ResultsParserStrictness:
    @pytest.mark.xfail(reason="R4: int(True) coerces bool to schema version", strict=True)
    def test_bool_schema_version_is_rejected(self) -> None:
        with pytest.raises(_REJECT):
            FractionalResults.from_json_bytes(_mutated_results(fractional_results_schema_version=True))

    @pytest.mark.xfail(reason="R4: int(False) coerces bool to a zero event count", strict=True)
    def test_bool_event_count_is_rejected(self) -> None:
        with pytest.raises(_REJECT):
            FractionalResults.from_json_bytes(_mutated_results(development_gate_event_count=False))

    @pytest.mark.xfail(reason="R4: float(str) repairs a numeric string", strict=True)
    def test_numeric_string_real_is_rejected(self) -> None:
        # initial_cash is per-cell and not cross-checked by aggregate re-derivation,
        # so this isolates the float(str) coercion rather than a grid mismatch.
        payload = json.loads(_RESULTS.read_bytes())
        payload["fold_cells"][0]["initial_cash"] = "10000.0"
        raw = json.dumps(payload, sort_keys=True, indent=2).encode()
        with pytest.raises(_REJECT):
            FractionalResults.from_json_bytes(raw)


# ---------------------------------------------------------------------------
# R5 — invalid accounting values must not cross the domain boundary
# ---------------------------------------------------------------------------
class TestR5AccountingStrictness:
    def test_nan_cash_state_is_rejected(self) -> None:
        with pytest.raises(_REJECT):
            PortfolioState(cash=float("nan"), quantity=0.0)

    def test_inf_quantity_state_is_rejected(self) -> None:
        with pytest.raises(_REJECT):
            PortfolioState(cash=0.0, quantity=float("inf"))

    def test_equity_at_nan_close_is_rejected(self) -> None:
        with pytest.raises(_REJECT):
            equity_at(PortfolioState(cash=100.0, quantity=1.0), float("nan"))

    def test_nan_tolerance_is_rejected(self) -> None:
        with pytest.raises(_REJECT):
            dataclasses.replace(DEFAULT_TOLERANCES, cash_tolerance=float("nan"))


# ---------------------------------------------------------------------------
# R6 — invalid liquidity configuration/history must be refused
# ---------------------------------------------------------------------------
class TestR6LiquidityStrictness:
    def test_naive_as_of_is_rejected_explicitly(self) -> None:
        # It is currently rejected only incidentally (pandas tz-compare TypeError);
        # the closure requires an explicit LiquidityError.
        frame = _tiny_frame()
        with pytest.raises(LiquidityError):
            estimate_liquidity(frame, pd.Timestamp("2020-01-05"), lookback=3, min_observations=2)

    def test_duplicate_history_is_rejected(self) -> None:
        frame = _tiny_frame()
        dup = pd.concat([frame.iloc[:3], frame.iloc[2:3]])
        with pytest.raises(_REJECT):
            estimate_liquidity(dup, frame.index[5], lookback=3, min_observations=2)


# ---------------------------------------------------------------------------
# R7 — the public engine must strictly validate its signal + frame
# ---------------------------------------------------------------------------
class TestR7EngineBoundaryStrictness:
    @pytest.mark.xfail(reason="R7: a shuffled-index signal is applied positionally", strict=True)
    def test_shuffled_signal_index_is_rejected(self) -> None:
        frame = _tiny_frame()
        strat = _strategy(_ConstSignal(shuffle=True))
        with pytest.raises(_REJECT):
            run_fractional_backtest(frame, strat, COMPATIBILITY_V1, initial_cash=10_000.0)

    @pytest.mark.xfail(reason="R7: a signal value outside [0,1] is not refused", strict=True)
    def test_out_of_range_signal_is_rejected(self) -> None:
        frame = _tiny_frame()
        strat = _strategy(_ConstSignal(value=1.5))
        with pytest.raises(_REJECT):
            run_fractional_backtest(frame, strat, COMPATIBILITY_V1, initial_cash=10_000.0)

    @pytest.mark.xfail(reason="R7: a non-finite signal value is not refused", strict=True)
    def test_non_finite_signal_is_rejected(self) -> None:
        frame = _tiny_frame()
        strat = _strategy(_ConstSignal(value=float("nan")))
        with pytest.raises(_REJECT):
            run_fractional_backtest(frame, strat, COMPATIBILITY_V1, initial_cash=10_000.0)

    def test_duplicate_timestamp_frame_is_rejected(self) -> None:
        frame = _tiny_frame()
        dup = pd.concat([frame.iloc[:1], frame])  # duplicate first timestamp
        strat = _strategy(_ConstSignal())
        with pytest.raises(_REJECT):
            run_fractional_backtest(dup, strat, COMPATIBILITY_V1, initial_cash=10_000.0)


# ---------------------------------------------------------------------------
# R2 / R9 / R10 / R11 — passing evidence the closure documents
# ---------------------------------------------------------------------------
class TestClosureEvidence:
    def test_r2_archive_body_is_only_a_manifest(self) -> None:
        entries = sorted(p.name for p in (REPO / "research/m3b/experiments/run-001").iterdir())
        assert entries == ["manifest.json"], entries  # no independent immutable body yet

    def test_r9_started_and_completed_share_one_timestamp(self) -> None:
        events = read_registry(_REGISTRY)
        started = next(e for e in events if e.event == "started")
        completed = next(e for e in events if e.event == "completed")
        assert started.event_time_utc == completed.event_time_utc  # legacy limitation

    def test_r10_cost_monotonicity_has_a_cellwise_counterexample(self) -> None:
        payload = json.loads(_RESULTS.read_bytes())
        cells = {
            (c["strategy"], c["cost_scenario"], c["fold_index"]): c["marked_total_return"]
            for c in payload["fold_cells"]
        }
        base = cells[("donchian_55_20", "causal_proxy_base", 1)]
        stressed = cells[("donchian_55_20", "causal_proxy_stressed", 1)]
        # cellwise monotonic-decline would require stressed <= base; it does NOT hold
        assert stressed > base, (base, stressed)

    def test_r11_only_aggregate_evidence_exists(self) -> None:
        # No per-cell execution trace is retained beside the aggregate results.
        assert not (REPO / "research/m3b/experiments/run-001/immutable-v2").exists()
        assert _RESULTS.exists()
        # a reviewer has only 75 aggregate cells, not the per-bar fill/cost path
        payload = json.loads(_RESULTS.read_bytes())
        assert len(payload["fold_cells"]) == 75
        assert all("execution_trace" not in c for c in payload["fold_cells"])


def test_repro_module_does_not_touch_sealed_ledgers() -> None:
    from eth_research.data.provenance import sha256_file

    empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ledgers = (
        "research/m3a/development_gate_access.jsonl",
        "research/m2b/test_evaluations.jsonl",
    )
    for rel in ledgers:
        assert sha256_file(REPO / rel) == empty
        assert (REPO / rel).stat().st_size == 0

