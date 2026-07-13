"""Fold-aware bootstraps: no block crosses a reset seam; deterministic; strict."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.bootstrap import BootstrapError
from eth_research.bootstrap_v2 import (
    FOLD_STRATIFIED_ALGORITHM,
    HIERARCHICAL_ALGORITHM,
    FoldAwareBootstrapConfig,
    _resample_within,
    fold_aware_bootstrap_bytes,
    fold_stratified_moving_block_bootstrap,
    hierarchical_fold_block_bootstrap,
)


def _series(values: list[float], start: str = "2020-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.Series([float(v) for v in values], index=idx)


def _five_folds(seed: int = 3) -> tuple[pd.Series, ...]:
    rng = np.random.default_rng(seed)
    sizes = [226, 225, 225, 225, 225]
    return tuple(_series(list(rng.normal(0.0, 0.02, s))) for s in sizes)


class TestConfig:
    def test_defaults_are_pinned(self) -> None:
        cfg = FoldAwareBootstrapConfig()
        assert cfg.primary_algorithm == FOLD_STRATIFIED_ALGORITHM
        assert cfg.sensitivity_algorithm == HIERARCHICAL_ALGORITHM
        assert cfg.seed == 20260713
        assert cfg.hierarchical_seed == 20260714  # domain-separated
        assert cfg.block_length == 30
        assert cfg.resamples == 5000
        assert cfg.confidence == 0.95

    def test_off_spec_algorithm_refused(self) -> None:
        with pytest.raises(ValueError, match="primary_algorithm is pinned"):
            FoldAwareBootstrapConfig(primary_algorithm="iid")


class TestNoSeamCrossing:
    def test_resample_within_stays_inside_the_fold(self) -> None:
        values = np.arange(100.0, 200.0)  # a fold whose values are all in [100,200)
        rng = np.random.Generator(np.random.PCG64(7))
        out = _resample_within(values, 30, rng)
        assert len(out) == 100
        assert set(out.tolist()) <= set(values.tolist())

    def test_constant_folds_collapse_to_the_weighted_mean(self) -> None:
        # Each fold is a distinct constant; a within-fold resample of a constant
        # fold is that constant, so every bootstrap resample equals the
        # observation-weighted mean and the interval collapses to it. Any block
        # crossing a seam would mix constants and widen the interval.
        sizes = [40, 41, 42, 43, 44]
        folds = tuple(_series([float(i)] * s) for i, s in enumerate(sizes, start=1))
        iv = fold_stratified_moving_block_bootstrap(folds)
        weighted = sum(i * s for i, s in enumerate(sizes, start=1)) / sum(sizes)
        assert iv.point_estimate == pytest.approx(weighted)
        assert iv.ci_lower == pytest.approx(weighted)
        assert iv.ci_upper == pytest.approx(weighted)
        assert iv.observation_count == sum(sizes)
        assert iv.fold_observation_counts == tuple(sizes)

    def test_block_longer_than_smallest_fold_refused(self) -> None:
        folds = (_series([0.01] * 40), _series([0.02] * 20))  # smallest fold is 20
        with pytest.raises(BootstrapError, match="exceeds the smallest fold length"):
            fold_stratified_moving_block_bootstrap(folds, FoldAwareBootstrapConfig(block_length=30))


class TestDeterminismAndStrictness:
    def test_repeated_bytes_identical(self) -> None:
        folds = _five_folds()
        a = fold_stratified_moving_block_bootstrap(folds)
        b = fold_stratified_moving_block_bootstrap(folds)
        assert fold_aware_bootstrap_bytes(a) == fold_aware_bootstrap_bytes(b)
        assert a.algorithm == FOLD_STRATIFIED_ALGORITHM

    def test_ordered_bounds_and_point_is_pooled_mean(self) -> None:
        folds = _five_folds(9)
        iv = fold_stratified_moving_block_bootstrap(folds)
        assert iv.ci_lower <= iv.ci_median <= iv.ci_upper
        pooled = np.concatenate([f.to_numpy(dtype=float) for f in folds])
        assert iv.point_estimate == pytest.approx(float(pooled.mean()))

    def test_empty_and_non_finite_and_non_tuple_refused(self) -> None:
        with pytest.raises(BootstrapError, match="non-empty tuple"):
            fold_stratified_moving_block_bootstrap(())
        with pytest.raises(BootstrapError, match="is empty"):
            fold_stratified_moving_block_bootstrap((_series([]),))
        with pytest.raises(BootstrapError, match="non-finite"):
            fold_stratified_moving_block_bootstrap((_series([0.01, np.nan] * 30),))


class TestHierarchicalSensitivity:
    def test_hierarchical_is_distinct_and_domain_separated(self) -> None:
        folds = _five_folds(11)
        primary = fold_stratified_moving_block_bootstrap(folds)
        sensitivity = hierarchical_fold_block_bootstrap(folds)
        assert sensitivity.algorithm == HIERARCHICAL_ALGORITHM
        # Same point estimate (both weight observations equally) but different
        # interval width, on a separate RNG stream.
        assert sensitivity.point_estimate == pytest.approx(primary.point_estimate)
        assert (sensitivity.ci_lower, sensitivity.ci_upper) != (primary.ci_lower, primary.ci_upper)
        assert sensitivity.ci_lower <= sensitivity.ci_median <= sensitivity.ci_upper

    def test_hierarchical_deterministic(self) -> None:
        folds = _five_folds(5)
        a = hierarchical_fold_block_bootstrap(folds)
        b = hierarchical_fold_block_bootstrap(folds)
        assert fold_aware_bootstrap_bytes(a) == fold_aware_bootstrap_bytes(b)
