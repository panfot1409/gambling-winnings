"""V2B §21 — the corrected-alpha bootstrap reconciles with the accepted one and adds the tail."""

from __future__ import annotations

import numpy as np

from eth_research.m3c.statistics import FoldPaired, fold_stratified_block_bootstrap
from eth_research.v2b import statistics as st


def _folds(
    mean: float, sd: float, seed: int, n: int = 300, count: int = 6
) -> tuple[FoldPaired, ...]:
    rng = np.random.default_rng(seed)
    return tuple(FoldPaired(fold_index=i, log_excess=rng.normal(mean, sd, n)) for i in range(count))


def test_corrected_bootstrap_reproduces_the_accepted_95pct_bounds_exactly() -> None:
    folds = _folds(0.001, 0.02, seed=7)
    accepted = fold_stratified_block_bootstrap(folds)
    mine = st.corrected_bootstrap(folds, corrected_alpha=0.005)
    # Same RNG call sequence -> identical resample distribution -> identical percentiles.
    assert mine.ci95_lower == accepted.ci_lower
    assert mine.ci95_upper == accepted.ci_upper
    assert mine.point_estimate == accepted.point_estimate


def test_corrected_tail_is_more_extreme_than_the_95pct_lower() -> None:
    folds = _folds(0.001, 0.02, seed=8)
    mine = st.corrected_bootstrap(folds, corrected_alpha=0.005)
    # A one-sided 0.5% lower bound is below the two-sided 95% (2.5%) lower bound.
    assert mine.corrected_one_sided_lower <= mine.ci95_lower


def test_corrected_lower_above_zero_flags_a_strong_positive_edge() -> None:
    strong = _folds(0.02, 0.005, seed=9)  # mean >> noise
    weak = _folds(0.0, 0.02, seed=9)  # mean-zero
    assert st.corrected_bootstrap(strong, corrected_alpha=0.005).corrected_lower_above_zero
    assert not st.corrected_bootstrap(weak, corrected_alpha=0.005).corrected_lower_above_zero


def test_mc_sign_flip_p_value_is_small_for_a_strong_edge_and_midrange_for_null() -> None:
    strong = _folds(0.05, 0.005, seed=10)
    null = _folds(0.0, 0.02, seed=11)
    p_strong = st.mc_sign_flip_p_value(strong)
    p_null = st.mc_sign_flip_p_value(null)
    assert 0.0 < p_strong <= 0.05
    assert 0.1 < p_null < 0.9  # a mean-zero series is not significant


def test_to_fold_paired_round_trips() -> None:
    arrays = {0: np.array([0.1, 0.2]), 1: np.array([0.3, -0.1, 0.05])}
    folds = st.to_fold_paired(arrays)
    assert tuple(f.fold_index for f in folds) == (0, 1)
    assert folds[1].log_excess.shape == (3,)


def test_corrected_bootstrap_is_deterministic() -> None:
    folds = _folds(0.001, 0.02, seed=12)
    a = st.corrected_bootstrap(folds, corrected_alpha=0.01)
    b = st.corrected_bootstrap(folds, corrected_alpha=0.01)
    assert a.to_canonical() == b.to_canonical()


# --------------------------------------------------------------------------- #
# §26 pre-registration red-team regressions (Auditor C findings)               #
# --------------------------------------------------------------------------- #
def test_observed_configuration_counts_in_its_own_tail_no_ulp_dropout() -> None:
    # Regression for the anti-conservative ULP bug (Finding 1): the observed statistic must be
    # produced by the SAME reduction as the permuted ones, so the all-+1 draws are counted rather
    # than dropped by a Python-``sum`` vs numpy-``.sum`` last-ULP mismatch. Two size-1 folds give a
    # two-block space whose all-+1 config is the unique maximum, reached by ~1/4 of draws, so the
    # correct p is ~0.25 — never the ~1/(resamples+1) ≈ 5e-5 collapse the bug produced.
    folds = (
        FoldPaired(fold_index=0, log_excess=np.array([0.02])),
        FoldPaired(fold_index=1, log_excess=np.array([0.015])),
    )
    p = st.mc_sign_flip_p_value(folds)
    assert 0.2 < p < 0.3


def test_mc_gate_is_crossable_at_six_folds_and_still_discriminates() -> None:
    # Regression for the resolution floor (Finding 2): a whole-fold flip over six folds resolves no
    # finer than 1/2**6 = 0.0156 > the corrected alpha 0.005, so the gate would be structurally
    # impossible to satisfy. The block-level flip has full-sample resolution: a strong edge clears
    # 0.005 and a mean-zero null does not.
    corrected_alpha = 0.005
    assert corrected_alpha > 1.0 / (st.MC_SIGN_FLIP_RESAMPLES + 1.0)
    strong = _folds(0.05, 0.005, seed=31)
    null = _folds(0.0, 0.02, seed=32)
    assert st.mc_sign_flip_p_value(strong) <= corrected_alpha
    assert st.mc_sign_flip_p_value(null) > corrected_alpha


def test_block_partition_sums_reconstruct_the_fold_total() -> None:
    # The flip acts on a partition, so every observation is in exactly one block and the block sums
    # add back to the fold total (Finding 3 — order/partition consistency).
    x = np.arange(1.0, 11.0)  # ten observations
    sums = st._block_partition_sums(x, 3)  # blocks [0:3], [3:6], [6:9], [9:10]
    assert sums.size == 4
    assert np.isclose(float(sums.sum()), float(x.sum()))


def test_real_mc_p_value_feeds_the_nomination_gate_at_six_folds() -> None:
    # Closes the CI blind spot Auditor C flagged: no test fed a *real* mc_sign_flip_p_value at the
    # real fold count into build_gates (the nomination tests hardcoded p-values the function could
    # not emit). A strong six-fold edge now clears gate 6; a mean-zero null does not.
    from eth_research.v2b.nomination import CandidateGates, build_gates

    corrected_alpha = 0.005
    strong_p = st.mc_sign_flip_p_value(_folds(0.05, 0.005, seed=41))
    null_p = st.mc_sign_flip_p_value(_folds(0.0, 0.02, seed=42))

    def _gate(mc_p: float) -> CandidateGates:
        return build_gates(
            "cand",
            primary_lower_above_zero=True,
            stressed_lower_above_zero=True,
            latency_lower_above_zero=True,
            folds_beating=6,
            fold_count=6,
            corrected_lower_above_zero=True,
            mc_p_value=mc_p,
            corrected_alpha=corrected_alpha,
            sensitivity_all_above_zero=True,
            primary_point_estimate=0.05,
        )

    assert _gate(strong_p).mc_supports is True
    assert _gate(strong_p).eligible is True
    assert _gate(null_p).mc_supports is False
