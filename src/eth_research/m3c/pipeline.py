"""The one deterministic build pipeline shared by execution and replay.

The orchestrator (single real execution) and the fresh-clone replay must run the
*identical* reduction, so the mapping from the 75 reconciled cell runs to the
strict :class:`M3CResults` lives here once and is called by both — any difference
is then purely runtime, never logic. It is a pure function of the frozen engine +
committed data:

* per-cell **trace commitment** — the SHA-256 of the full canonical bar-record
  sequence of that cell, so tampering with any single bar is detectable and the
  published summary is anchored to the exact per-bar execution that produced it;
* the frozen **primary inference** — the fold-seam-aware moving-block bootstrap of
  the candidate-vs-buy-and-hold mean paired daily log-excess under
  ``causal_proxy_base``, plus the fragile secondary Probabilistic Sharpe;
* the assembled :class:`M3CResults`.

Nothing here fits a parameter, reads a sealed row, or touches the network.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from eth_research.data.provenance import sha256_bytes
from eth_research.fractional.dataset import verify_dataset_integrity_only
from eth_research.fractional.engine import BarRecord, FractionalBacktestResult
from eth_research.m3c.candidate import M3C_CANDIDATE_ID
from eth_research.m3c.experiment import M3CCellRun, compute_m3c_cell_runs
from eth_research.m3c.protocol import load_m3c_protocol
from eth_research.m3c.registry import M3CRegistryEvent
from eth_research.m3c.results import (
    M3C_PROTOCOL_RELPATH,
    PRIMARY_SCENARIO,
    M3CResults,
    build_m3c_results,
)
from eth_research.m3c.statistics import (
    BootstrapResult,
    ProbabilisticSharpe,
    align_paired_by_fold,
    fold_stratified_block_bootstrap,
    probabilistic_sharpe_ratio,
)
from eth_research.walkforward import (
    WALK_FORWARD_PROTOCOL_RELPATH,
    WalkForwardProtocol,
    load_walk_forward_protocol,
)

_BUY_AND_HOLD: str = "buy_and_hold"


def _canon(value: object) -> object:
    """Map a non-finite float to a stable token; pass everything else through."""
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "nan"
        return "inf" if value > 0.0 else "-inf"
    return value


def _bar_dict(bar: BarRecord) -> dict[str, object]:
    """The full canonical per-bar record committed to by a cell's trace digest."""
    return {
        "timestamp": bar.timestamp.isoformat(),
        "reference_open": _canon(bar.reference_open),
        "close": _canon(bar.close),
        "raw_target": _canon(bar.raw_target),
        "executable_target": _canon(bar.executable_target),
        "volatility_scale": _canon(bar.volatility_scale),
        "drawdown_tripped": bar.drawdown_tripped,
        "prior_achieved_exposure": _canon(bar.prior_achieved_exposure),
        "lagged_dollar_volume": _canon(bar.lagged_dollar_volume),
        "participation_cap": _canon(bar.participation_cap),
        "side": bar.side,
        "executed_quantity": _canon(bar.executed_quantity),
        "fill_price": _canon(bar.fill_price),
        "fee": _canon(bar.fee),
        "partial": bar.partial,
        "reason": bar.reason,
        "cash_after": _canon(bar.cash_after),
        "quantity_after": _canon(bar.quantity_after),
        "achieved_exposure": _canon(bar.achieved_exposure),
        "equity": _canon(bar.equity),
    }


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def cell_trace_commitment(
    strategy: str, cost_scenario: str, fold_index: int, result: FractionalBacktestResult
) -> str:
    """SHA-256 of one cell's full canonical bar-record sequence (deterministic)."""
    payload = {
        "strategy": strategy,
        "cost_scenario": cost_scenario,
        "fold_index": fold_index,
        "bars": [_bar_dict(b) for b in result.bars],
    }
    return sha256_bytes(_canonical_bytes(payload))


def build_trace_commitments(
    cell_runs: tuple[M3CCellRun, ...],
) -> dict[tuple[str, str, int], str]:
    """Per-cell trace digest for every reconciled cell run."""
    commitments: dict[tuple[str, str, int], str] = {}
    for run in cell_runs:
        key = (run.strategy, run.cost_scenario, run.fold_index)
        if key in commitments:
            raise ValueError(f"duplicate cell {key} in cell runs")
        commitments[key] = cell_trace_commitment(
            run.strategy, run.cost_scenario, run.fold_index, run.result
        )
    return commitments


def compute_primary_inference(
    cell_runs: tuple[M3CCellRun, ...],
) -> tuple[BootstrapResult, ProbabilisticSharpe]:
    """The frozen primary bootstrap interval + the secondary PSR diagnostic.

    Pairs the candidate against buy-and-hold under ``causal_proxy_base`` fold by
    fold on the exact OOS index, runs the fold-seam-aware moving-block bootstrap of
    the pooled mean paired daily log-excess, and computes the fragile secondary
    Probabilistic Sharpe on the pooled per-day paired log-excess series.
    """
    runs_by = {(r.strategy, r.cost_scenario, r.fold_index): r for r in cell_runs}
    folds = sorted({r.fold_index for r in cell_runs if r.cost_scenario == PRIMARY_SCENARIO})
    candidate_by_fold: dict[int, pd.Series] = {}
    bnh_by_fold: dict[int, pd.Series] = {}
    for fold in folds:
        candidate_by_fold[fold] = runs_by[
            (M3C_CANDIDATE_ID, PRIMARY_SCENARIO, fold)
        ].marked_daily_returns
        bnh_by_fold[fold] = runs_by[(_BUY_AND_HOLD, PRIMARY_SCENARIO, fold)].marked_daily_returns
    paired = align_paired_by_fold(candidate_by_fold, bnh_by_fold)
    bootstrap = fold_stratified_block_bootstrap(paired)
    pooled = np.concatenate([fold.log_excess for fold in paired])
    psr = probabilistic_sharpe_ratio(pooled)
    return bootstrap, psr


def assemble_m3c_results(
    cell_runs: tuple[M3CCellRun, ...],
    *,
    wf_protocol: WalkForwardProtocol,
    research_train: pd.DataFrame,
    package_version: str,
    execution_code_commit_sha: str,
    registered_code_commit_sha: str,
    execution_source_tree_fingerprint: str,
    protocol_sha256: str,
    lineage_sha256: str,
    budget_sha256: str,
    frozen_m2_dossier_sha256: str,
    development_partition_sha256: str,
) -> M3CResults:
    """Reduce the reconciled cell runs to the strict, byte-stable results model.

    Called identically by the single real execution and by the fresh-clone replay.
    On the execution host the two rebuilds are byte-identical (the P6 determinism
    gate); across hosts every financial field still reproduces byte-for-byte, while
    the secondary statistical scalars (bootstrap interval, paired log-excess, PSR)
    may differ by a transcendental last ULP — see :mod:`eth_research.m3c.replay`.
    """
    trace_commitments = build_trace_commitments(cell_runs)
    bootstrap, psr = compute_primary_inference(cell_runs)
    return build_m3c_results(
        cell_runs=cell_runs,
        wf_protocol=wf_protocol,
        package_version=package_version,
        execution_code_commit_sha=execution_code_commit_sha,
        registered_code_commit_sha=registered_code_commit_sha,
        execution_source_tree_fingerprint=execution_source_tree_fingerprint,
        protocol_sha256=protocol_sha256,
        lineage_sha256=lineage_sha256,
        budget_sha256=budget_sha256,
        frozen_m2_dossier_sha256=frozen_m2_dossier_sha256,
        development_partition_sha256=development_partition_sha256,
        research_train=research_train,
        primary_bootstrap=bootstrap,
        psr=psr,
        trace_commitments=trace_commitments,
    )


def reproduce_results(repo_root: str | Path, registered: M3CRegistryEvent) -> M3CResults:
    """Rebuild the strict results from committed inputs alone (research-train only).

    Binds the *recorded* provenance from the ``registered`` event so the rebuild is
    version-independent: the committed bytes reproduce even after a later
    package-version bump. Loads the research-train partition integrity-only (no
    sealed row is ever touched), re-runs the 75-cell grid, and reduces it through
    the one shared pipeline. This is exactly the computation the single real
    execution performed, re-expressed for verification and fresh-clone replay.
    """
    root = Path(repo_root)
    protocol = load_m3c_protocol(root / M3C_PROTOCOL_RELPATH)
    wf_protocol = load_walk_forward_protocol(root / WALK_FORWARD_PROTOCOL_RELPATH)
    research_train = verify_dataset_integrity_only(root).research_train
    cell_runs = compute_m3c_cell_runs(
        research_train, wf_protocol, initial_cash=protocol.initial_cash
    )
    return assemble_m3c_results(
        cell_runs,
        wf_protocol=wf_protocol,
        research_train=research_train,
        package_version=registered.package_version,
        execution_code_commit_sha=registered.execution_code_commit_sha,
        registered_code_commit_sha=registered.registered_code_commit_sha,
        execution_source_tree_fingerprint=registered.execution_source_tree_fingerprint,
        protocol_sha256=registered.protocol_sha256,
        lineage_sha256=registered.lineage_sha256,
        budget_sha256=registered.research_budget_sha256,
        frozen_m2_dossier_sha256=registered.frozen_m2_dossier_sha256,
        development_partition_sha256=registered.development_partition_sha256,
    )
