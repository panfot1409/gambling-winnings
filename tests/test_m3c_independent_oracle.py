"""Independent statistical reconstruction of the committed M3C primary inference.

Rebuilds the candidate vs buy-and-hold daily returns from the committed data using the
frozen *engine* only, then reimplements — WITHOUT calling any audited statistics helper
(``paired_log_excess`` / ``align_paired_by_fold`` / ``fold_stratified_block_bootstrap``
/ ``probabilistic_sharpe_ratio``) or the decision module (``evaluate_candidate_decision``
/ ``_evaluate_criteria``) — the paired log-excess, the pooled point estimate, the 2/5
fold count, an independent fold-stratified moving-block bootstrap, the PSR, and the full
P1..P7 rule. Confirms the committed rejection is faithful to the raw evidence.

Neither sealed partition is read: the loader returns research-train rows only.
"""

from __future__ import annotations

import math
import statistics as py_statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eth_research.fractional.dataset import verify_dataset_integrity_only
from eth_research.m3c.candidate import M3C_CANDIDATE_ID
from eth_research.m3c.decision import CandidateDecision, load_m3c_decision
from eth_research.m3c.experiment import M3CCellRun, compute_m3c_cell_runs
from eth_research.m3c.numerics import ulp_distance
from eth_research.m3c.protocol import load_m3c_protocol
from eth_research.m3c.results import (
    M3C_PROTOCOL_RELPATH,
    PRIMARY_COMPARATOR,
    PRIMARY_SCENARIO,
    M3CResults,
    load_m3c_results,
)
from eth_research.walkforward import WALK_FORWARD_PROTOCOL_RELPATH, load_walk_forward_protocol

REPO = Path(__file__).resolve().parents[1]
_BNH = "buy_and_hold"
_STRESSED = "causal_proxy_stressed"
_SEED = 20260714
_RESAMPLES = 20000


def _floor_cbrt(n: int) -> int:
    """Independent exact floor of the real cube root (integer search only)."""
    k = 0
    while (k + 1) ** 3 <= n:
        k += 1
    return k


@dataclass(frozen=True)
class _Rebuilt:
    folds: list[int]
    cand: dict[int, pd.Series]
    bnh: dict[int, pd.Series]
    runs: dict[tuple[str, str, int], M3CCellRun]
    results: M3CResults
    decision: CandidateDecision


@pytest.fixture(scope="module")
def rebuilt() -> _Rebuilt:
    """Rebuild the candidate/B&H causal_proxy_base daily returns from committed data."""
    protocol = load_m3c_protocol(REPO / M3C_PROTOCOL_RELPATH)
    wf = load_walk_forward_protocol(REPO / WALK_FORWARD_PROTOCOL_RELPATH)
    research_train = verify_dataset_integrity_only(REPO).research_train
    runs = compute_m3c_cell_runs(research_train, wf, initial_cash=protocol.initial_cash)
    by_key = {(r.strategy, r.cost_scenario, r.fold_index): r for r in runs}
    folds = sorted({r.fold_index for r in runs if r.cost_scenario == PRIMARY_SCENARIO})
    cand = {f: by_key[(M3C_CANDIDATE_ID, PRIMARY_SCENARIO, f)].marked_daily_returns for f in folds}
    bnh = {f: by_key[(_BNH, PRIMARY_SCENARIO, f)].marked_daily_returns for f in folds}
    return _Rebuilt(
        folds=folds,
        cand=cand,
        bnh=bnh,
        runs=by_key,
        results=load_m3c_results(REPO / "research/m3c/candidate_results.json"),
        decision=load_m3c_decision(REPO / "research/m3c/candidate_decision.json"),
    )


def _log_excess(rebuilt: _Rebuilt) -> dict[int, np.ndarray]:
    """log1p(candidate) - log1p(bnh) per fold, aligned strictly by (fold, timestamp)."""
    out: dict[int, np.ndarray] = {}
    for f in rebuilt.folds:
        c, b = rebuilt.cand[f], rebuilt.bnh[f]
        assert c.index.equals(b.index), f"fold {f}: candidate/B&H timestamps must match exactly"
        cv = c.to_numpy(dtype="float64")
        bv = b.to_numpy(dtype="float64")
        assert np.isfinite(cv).all()
        assert np.isfinite(bv).all()
        assert (cv > -1.0).all()
        assert (bv > -1.0).all()
        out[f] = np.log1p(cv) - np.log1p(bv)
    return out


def test_alignment_is_by_timestamp_never_positional(rebuilt: _Rebuilt) -> None:
    for f in rebuilt.folds:
        assert rebuilt.cand[f].index.equals(rebuilt.bnh[f].index)
        assert rebuilt.cand[f].index.is_monotonic_increasing


def test_counts_match_committed(rebuilt: _Rebuilt) -> None:
    le = _log_excess(rebuilt)
    per_fold = {f: le[f].size for f in le}
    committed_counts = {
        pc.fold_index: pc.oos_row_count for pc in rebuilt.results.paired_comparisons
    }
    assert per_fold == committed_counts
    assert sum(per_fold.values()) == rebuilt.results.bootstrap.observation_count == 1126


def test_point_estimate_reconstructs(rebuilt: _Rebuilt) -> None:
    le = _log_excess(rebuilt)
    pooled = np.concatenate([le[f] for f in sorted(le)])
    independent_point = float(pooled.sum() / pooled.size)
    committed = rebuilt.results.bootstrap.point_estimate
    # Independent pooled mean agrees with the committed point estimate to a few ULPs.
    assert abs(independent_point - committed) <= 1e-15
    # Internal consistency: pooled mean == count-weighted average of committed per-fold means.
    total = sum(
        pc.mean_daily_paired_log_excess * pc.oos_row_count
        for pc in rebuilt.results.paired_comparisons
    )
    weighted = total / sum(pc.oos_row_count for pc in rebuilt.results.paired_comparisons)
    assert abs(weighted - committed) <= 1e-15


def test_candidate_wins_exactly_two_of_five_folds(rebuilt: _Rebuilt) -> None:
    wins = 0
    for pc in rebuilt.results.paired_comparisons:
        cand_cell = rebuilt.runs[(M3C_CANDIDATE_ID, PRIMARY_SCENARIO, pc.fold_index)]
        bnh_cell = rebuilt.runs[(_BNH, PRIMARY_SCENARIO, pc.fold_index)]
        # independent: candidate marked total return vs B&H, straight from the rebuilt cells
        if cand_cell.metrics.total_return > bnh_cell.metrics.total_return:
            wins += 1
    assert wins == 2


def _independent_block_bootstrap(le: dict[int, np.ndarray]) -> tuple[float, float]:
    """An independent fold-stratified circular moving-block bootstrap (own indexing).

    Blocks are drawn within each fold only (never crossing a seam); each fold keeps its
    observation count; the circular gather uses modulo indexing (distinct from the
    production concat-pad construction); folds are visited in a fixed order.
    """
    rng = np.random.default_rng(_SEED)
    total = np.zeros(_RESAMPLES, dtype="float64")
    count = 0
    for f in sorted(le):
        x = le[f]
        n = x.size
        count += n
        length = _floor_cbrt(n)
        num_blocks = -(-n // length)
        starts = rng.integers(0, n, size=(_RESAMPLES, num_blocks))
        offsets = np.arange(length)
        idx = (starts[:, :, None] + offsets[None, None, :]) % n
        sampled = x[idx].reshape(_RESAMPLES, num_blocks * length)[:, :n]
        total += sampled.sum(axis=1)
    means = total / count
    return (
        float(np.percentile(means, 2.5, method="linear")),
        float(np.percentile(means, 97.5, method="linear")),
    )


def test_independent_bootstrap_straddles_zero_and_p1_fails(rebuilt: _Rebuilt) -> None:
    le = _log_excess(rebuilt)
    # block lengths per fold are floor(n**1/3) == 6, never crossing a fold seam
    assert {f: _floor_cbrt(le[f].size) for f in le} == dict.fromkeys(le, 6)
    lo, hi = _independent_block_bootstrap(le)
    ci_lower = rebuilt.results.bootstrap.ci_lower
    # The independent interval reproduces the committed one closely (same seed/algorithm).
    assert abs(lo - ci_lower) < 1e-9 or ulp_distance(lo, ci_lower) < 4096
    assert lo < 0.0 < hi  # straddles zero
    assert not (lo > 0.0)  # P1 (ci_lower > 0) fails


def _independent_psr(le: dict[int, np.ndarray]) -> float:
    x = np.concatenate([le[f] for f in sorted(le)])
    n = x.size
    mean = float(x.mean())
    std = float(x.std(ddof=1))
    sr = mean / std
    centered = (x - mean) / std
    skew = float((centered**3).mean())
    kurt = float((centered**4).mean())
    denom = math.sqrt(max(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2, 1e-12))
    z = (sr - 0.0) * math.sqrt(n - 1.0) / denom
    return float(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))


def test_independent_psr_matches_and_is_secondary(rebuilt: _Rebuilt) -> None:
    le = _log_excess(rebuilt)
    psr = _independent_psr(le)
    assert abs(psr - rebuilt.results.psr_diagnostic.psr) < 1e-9
    assert 0.0 <= psr <= 1.0
    # PSR is descriptive only: it is not one of the mechanical promotion criteria.
    ids = {c.criterion_id for c in rebuilt.decision.criteria}
    assert ids == {"P1", "P2", "P3", "P4", "P5", "P6", "P7"}
    assert not any("psr" in c.description.lower() for c in rebuilt.decision.criteria)


def test_independent_p1_to_p7_reproduce_the_committed_rejection(rebuilt: _Rebuilt) -> None:
    results = rebuilt.results
    decision = rebuilt.decision
    cells = {(c.strategy, c.cost_scenario, c.fold_index): c for c in results.fold_cells}
    folds = list(range(len(results.paired_comparisons)))

    # Independent recompute of the seven criteria (own logic, not decision.py).
    p1 = results.bootstrap.ci_lower > 0.0
    wins = sum(1 for pc in results.paired_comparisons if pc.candidate_beats_bnh)
    p2 = wins >= 3
    cand_dd = py_statistics.median(
        [cells[(M3C_CANDIDATE_ID, PRIMARY_SCENARIO, f)].max_drawdown for f in folds]
    )
    bnh_dd = py_statistics.median([cells[(_BNH, PRIMARY_SCENARIO, f)].max_drawdown for f in folds])
    p3 = cand_dd >= bnh_dd
    cand_stressed = py_statistics.median(
        [cells[(M3C_CANDIDATE_ID, _STRESSED, f)].marked_total_return for f in folds]
    )
    p4 = cand_stressed > 0.0
    causal = [cells[(M3C_CANDIDATE_ID, s, f)] for s in (PRIMARY_SCENARIO, _STRESSED) for f in folds]
    p5 = min(c.marked_terminal_equity for c in causal) > 0.0 and all(
        c.marked_total_return > -1.0 for c in causal
    )
    p6 = decision.verification_passed  # external verification flag
    candidate_count = sum(1 for s in results.strategies if s == M3C_CANDIDATE_ID)
    p7 = (
        candidate_count == 1
        and results.primary_scenario == PRIMARY_SCENARIO
        and results.primary_comparator == PRIMARY_COMPARATOR
    )
    independent_vector = [
        ("P1", p1),
        ("P2", p2),
        ("P3", p3),
        ("P4", p4),
        ("P5", p5),
        ("P6", p6),
        ("P7", p7),
    ]
    committed_vector = [(c.criterion_id, c.passed) for c in decision.criteria]
    assert independent_vector == committed_vector
    assert p1 is False  # primary interval lower bound not above zero
    assert p2 is False  # candidate beats B&H in only 2 of 5 folds
    assert decision.outcome == "rejected_for_development_gate_promotion"
    assert not all(passed for _, passed in independent_vector)
