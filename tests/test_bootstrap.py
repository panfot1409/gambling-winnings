"""Deterministic moving-block bootstrap: reproducible, pinned, strict inputs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.bootstrap import (
    BootstrapConfig,
    BootstrapError,
    bootstrap_bytes,
    moving_block_bootstrap,
    paired_excess_returns,
)


def _series(values: list[float], start: str = "2020-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.Series([float(v) for v in values], index=idx)


class TestConfig:
    def test_defaults_are_pinned(self) -> None:
        cfg = BootstrapConfig()
        assert cfg.algorithm == "moving-block-bootstrap-v1"
        assert cfg.seed == 20260713
        assert cfg.block_length == 30
        assert cfg.resamples == 5000
        assert cfg.confidence == 0.95

    def test_off_spec_algorithm_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="algorithm is pinned"):
            BootstrapConfig(algorithm="iid")


class TestDeterminism:
    def test_repeated_bytes_identical(self) -> None:
        rng = np.random.default_rng(3)
        series = _series(list(rng.normal(0.001, 0.02, 300)))
        a = moving_block_bootstrap(series)
        b = moving_block_bootstrap(series)
        assert bootstrap_bytes(a) == bootstrap_bytes(b)

    def test_seed_mutation_changes_result(self) -> None:
        rng = np.random.default_rng(3)
        series = _series(list(rng.normal(0.001, 0.02, 300)))
        a = moving_block_bootstrap(series, BootstrapConfig())
        b = moving_block_bootstrap(series, BootstrapConfig(seed=1))
        assert a.ci_lower != b.ci_lower or a.ci_upper != b.ci_upper

    def test_ordered_confidence_bounds(self) -> None:
        rng = np.random.default_rng(9)
        series = _series(list(rng.normal(0, 0.03, 400)))
        result = moving_block_bootstrap(series)
        assert result.ci_lower <= result.ci_median <= result.ci_upper


class TestKnownInputs:
    def test_constant_series_collapses_to_the_constant(self) -> None:
        result = moving_block_bootstrap(_series([0.004] * 100))
        assert result.point_estimate == pytest.approx(0.004)
        assert result.ci_lower == pytest.approx(0.004)
        assert result.ci_upper == pytest.approx(0.004)

    def test_point_estimate_is_the_sample_mean(self) -> None:
        series = _series([0.01, -0.02, 0.03, 0.00, 0.05] * 20)
        result = moving_block_bootstrap(series)
        assert result.point_estimate == pytest.approx(float(series.mean()))

    def test_small_seeded_oracle(self) -> None:
        # Reproduce the algorithm by hand for a tiny series/config.
        values = np.array([0.1, -0.2, 0.3, -0.4, 0.5, -0.6], dtype=float)
        series = _series(list(values))
        cfg = BootstrapConfig(block_length=2, resamples=7)
        rng = np.random.Generator(np.random.PCG64(cfg.seed))
        n = len(values)
        max_start = n - cfg.block_length + 1
        blocks_needed = (n + cfg.block_length - 1) // cfg.block_length
        offsets = np.arange(cfg.block_length)
        means = []
        for _ in range(cfg.resamples):
            starts = rng.integers(0, max_start, size=blocks_needed)
            pos = (starts[:, None] + offsets[None, :]).reshape(-1)[:n]
            means.append(float(values[pos].mean()))
        expected_lower = float(np.percentile(means, 2.5, method="linear"))
        result = moving_block_bootstrap(series, cfg)
        assert result.ci_lower == pytest.approx(expected_lower)


class TestStrictInputs:
    def test_block_longer_than_sample_is_rejected(self) -> None:
        with pytest.raises(BootstrapError, match="exceeds the sample size"):
            moving_block_bootstrap(_series([0.01] * 10), BootstrapConfig())  # block 30 > 10

    def test_block_length_one_is_allowed(self) -> None:
        result = moving_block_bootstrap(_series([0.01] * 40), BootstrapConfig(block_length=1))
        assert result.observation_count == 40

    def test_empty_series_is_rejected(self) -> None:
        with pytest.raises(BootstrapError, match="empty"):
            moving_block_bootstrap(_series([]))

    def test_non_finite_is_rejected(self) -> None:
        series = _series([0.01, np.nan, 0.02] * 20)
        with pytest.raises(BootstrapError, match="non-finite"):
            moving_block_bootstrap(series)


class TestPairing:
    def test_misaligned_pairs_are_rejected(self) -> None:
        cand = _series([0.01] * 50)
        bnh = _series([0.0] * 49)
        with pytest.raises(BootstrapError, match="not aligned"):
            paired_excess_returns(cand, bnh)

    def test_duplicate_timestamps_are_rejected(self) -> None:
        idx = pd.DatetimeIndex(["2020-01-01", "2020-01-01"], tz="UTC")
        cand = pd.Series([0.01, 0.02], index=idx)
        bnh = pd.Series([0.0, 0.0], index=idx)
        with pytest.raises(BootstrapError, match="duplicate timestamps"):
            paired_excess_returns(cand, bnh)

    def test_shifted_timestamps_are_rejected(self) -> None:
        cand = _series([0.01] * 50, start="2020-01-01")
        bnh = _series([0.0] * 50, start="2020-01-02")
        with pytest.raises(BootstrapError, match="not aligned"):
            paired_excess_returns(cand, bnh)

    def test_excess_is_the_difference(self) -> None:
        cand = _series([0.03, 0.01, -0.02])
        bnh = _series([0.01, 0.02, -0.01])
        excess = paired_excess_returns(cand, bnh)
        assert list(excess.round(6)) == [0.02, -0.01, -0.01]
