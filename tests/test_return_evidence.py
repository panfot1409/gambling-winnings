"""Strict, symmetric per-run OOS return evidence (Phase 9)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from eth_research.return_evidence import (
    DEVELOPMENT_GATE_FIRST_DAY,
    FoldReturnAxis,
    ReturnEvidence,
    build_return_evidence,
)

_STRATEGIES = ("cash", "buy_and_hold", "sma_20_50", "donchian_55_20")
_SCENARIOS = ("base", "stressed", "severe")


def _fold_series(fold: int, n: int, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2016-06-01", tz="UTC") + pd.Timedelta(days=fold * 400)
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    return pd.Series(rng.normal(0.0, 0.01, size=n), index=idx, dtype=float)


def _build(folds: int = 5) -> ReturnEvidence:
    fr: dict[tuple[str, str], list[pd.Series]] = {}
    seed = 0
    for st in _STRATEGIES:
        for sc in _SCENARIOS:
            fr[(st, sc)] = [_fold_series(f, 4 + f, seed := seed + 1) for f in range(folds)]
    return build_return_evidence(
        experiment_id="m3a-fixed-baseline-comparison-v2-run-003",
        periods_per_year=365.25,
        research_train_last_open_time=pd.Timestamp("2022-06-21T00:00:00+00:00"),
        strategies=_STRATEGIES,
        cost_scenarios=_SCENARIOS,
        fold_returns=fr,
    )


class TestSymmetry:
    def test_round_trip(self) -> None:
        ev = _build()
        assert ReturnEvidence.from_json_bytes(ev.to_json_bytes()) == ev

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(_build().to_json_bytes())
        payload["surprise"] = 1
        with pytest.raises(ValueError, match="keys do not match"):
            ReturnEvidence.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_content_hash_is_stable(self) -> None:
        assert _build().content_sha256() == _build().content_sha256()


class TestReDerivation:
    def test_pooled_returns_match_manual_concatenation(self) -> None:
        ev = _build()
        pooled = ev.pooled_returns("sma_20_50", "stressed")
        manual = np.concatenate(
            [
                s.net_returns
                for s in ev.series
                if s.strategy == "sma_20_50" and s.cost_scenario == "stressed"
            ]
        )
        assert np.array_equal(pooled, np.asarray(manual, dtype=float))

    def test_pooled_series_is_timestamp_indexed_and_ordered(self) -> None:
        ev = _build()
        s = ev.pooled_series("cash", "base")
        assert s.index.is_monotonic_increasing
        assert (s.index < DEVELOPMENT_GATE_FIRST_DAY).all()


class TestFirewall:
    def test_observation_on_or_after_gate_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="forbidden observation"):
            FoldReturnAxis(
                fold_index=0,
                oos_open_times=(pd.Timestamp("2022-06-22T00:00:00+00:00"),),
            )

    def test_boundary_after_gate_is_rejected(self) -> None:
        fr = {
            (st, sc): [_fold_series(f, 4 + f, 1) for f in range(5)]
            for st in _STRATEGIES
            for sc in _SCENARIOS
        }
        with pytest.raises(ValueError, match="precede the development gate"):
            build_return_evidence(
                experiment_id="m3a-x-001",
                periods_per_year=365.25,
                research_train_last_open_time=pd.Timestamp("2022-06-22T00:00:00+00:00"),
                strategies=_STRATEGIES,
                cost_scenarios=_SCENARIOS,
                fold_returns=fr,
            )


class TestGrid:
    def test_incomplete_grid_is_rejected(self) -> None:
        ev = _build()
        payload = json.loads(ev.to_json_bytes())
        payload["series"] = payload["series"][:-1]  # drop one cell
        with pytest.raises(ValueError, match="canonical"):
            ReturnEvidence.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_length_mismatch_is_rejected(self) -> None:
        ev = _build()
        payload = json.loads(ev.to_json_bytes())
        payload["series"][0]["net_returns"].append(0.0)  # too many returns for its axis
        with pytest.raises(ValueError, match="fold axis has"):
            ReturnEvidence.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_nan_return_is_rejected(self) -> None:
        ev = _build()
        payload = json.loads(ev.to_json_bytes())
        raw = json.dumps(payload).replace("0.0", "NaN", 1).encode("utf-8")
        with pytest.raises(ValueError):
            ReturnEvidence.from_json_bytes(raw)
