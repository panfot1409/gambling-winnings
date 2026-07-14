"""Size-bounded, replay-reconstructible execution-trace commitments (R11).

The published results retain only per-cell *summary* numbers; there is no evidence
tying each of the 75 (strategy, scenario, fold) cells to the specific per-bar
execution trace that produced it (defect R11 — insufficient per-run return
evidence). Retaining every bar of every cell would bloat the repository, so this
module commits to them instead: for each cell it hashes the full canonical
sequence of bar records (a deterministic function of the frozen engine + data) and
stores only that digest, the bar/fill counts, and a combined digest over all
cells. The committed record binds the exact published results digest.

Because the engine is deterministic, the commitment is *replay-reconstructible*:
:func:`verify_execution_trace_commitments` re-runs the identical 75-cell grid on
the integrity-verified research train, recomputes every trace digest, and requires
the committed record to re-derive byte-for-byte. It never fits a parameter, reads
a sealed row, or touches the network — it is the same computation the published
run performed, re-expressed as a hash so tampering with any bar is detectable.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from eth_research._json import require_canonical_file_bytes, strict_json_loads
from eth_research.data.provenance import sha256_bytes
from eth_research.fractional.accounting import DEFAULT_TOLERANCES, Tolerances
from eth_research.fractional.cost_model import SCENARIOS
from eth_research.fractional.dataset import verify_dataset_integrity_only
from eth_research.fractional.engine import (
    BarRecord,
    FractionalBacktestResult,
    run_fractional_backtest,
)
from eth_research.fractional.protocol import (
    EXPERIMENT_FAMILY,
    FRACTIONAL_PROTOCOL_RELPATH,
    RUN_001_EXPERIMENT_ID,
    load_fractional_protocol,
)
from eth_research.fractional.reconciliation import reconcile_result
from eth_research.fractional.results import FRACTIONAL_RESULTS_RELPATH, load_fractional_results
from eth_research.fractional.strategies import build_strategies
from eth_research.publication import durable_write_bytes
from eth_research.walkforward import (
    WALK_FORWARD_PROTOCOL_RELPATH,
    build_fold_frames,
    load_walk_forward_protocol,
)

EXECUTION_TRACE_COMMITMENTS_RELPATH: str = "research/m3b/execution_trace_commitments.json"
EXECUTION_TRACE_COMMITMENTS_SCHEMA_VERSION: int = 1
_TRACE_DIGEST_ALGORITHM: str = "sha256(canonical-json(bar-records))"


class ExecutionTraceError(RuntimeError):
    """The execution-trace commitments are missing, malformed, or do not replay."""


def _canon(value: object) -> object:
    """Map a non-finite float to a stable token; pass everything else through."""
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "nan"
        return "inf" if value > 0.0 else "-inf"
    return value


def _bar_dict(bar: BarRecord) -> dict[str, object]:
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


def _cell_commitment(
    strategy_name: str, scenario_name: str, fold_index: int, result: FractionalBacktestResult
) -> dict[str, Any]:
    trace_payload = {
        "strategy": strategy_name,
        "cost_scenario": scenario_name,
        "fold_index": fold_index,
        "bars": [_bar_dict(b) for b in result.bars],
    }
    return {
        "strategy": strategy_name,
        "cost_scenario": scenario_name,
        "fold_index": fold_index,
        "bar_count": len(result.bars),
        "fill_count": len(result.fills),
        "trace_sha256": sha256_bytes(_canonical_bytes(trace_payload)),
    }


def _grid_commitments(
    repo_root: Path, *, tol: Tolerances = DEFAULT_TOLERANCES
) -> list[dict[str, Any]]:
    """Re-run the identical 75-cell grid and return each cell's trace commitment.

    Mirrors ``compute_fractional_fold_cells`` iteration order (fold, scenario,
    strategy) so the ordered commitments line up with the published fold cells.
    Each result is reconciled before it is committed, exactly as at publication.
    """
    protocol = load_fractional_protocol(repo_root / FRACTIONAL_PROTOCOL_RELPATH)
    wf_protocol = load_walk_forward_protocol(repo_root / WALK_FORWARD_PROTOCOL_RELPATH)
    research_train = verify_dataset_integrity_only(repo_root).research_train
    fold_frames = build_fold_frames(research_train, wf_protocol)
    strategies = build_strategies()
    cells: list[dict[str, Any]] = []
    for fold in fold_frames:
        for scenario in SCENARIOS:
            for strategy in strategies:
                result = run_fractional_backtest(
                    fold.oos,
                    strategy,
                    scenario,
                    initial_cash=protocol.initial_cash,
                    context=fold.context,
                    tol=tol,
                )
                reconcile_result(result, scenario, tol=tol)
                cells.append(
                    _cell_commitment(strategy.name, scenario.name, fold.fold_index, result)
                )
    return cells


def build_execution_trace_commitments(repo_root: str | Path) -> dict[str, Any]:
    """Re-run the grid and derive the execution-trace commitment record.

    Read-only w.r.t. committed artifacts. Binds the exact published results digest
    and the protocol / research-train fingerprints so the commitment cannot be
    reattached to a different run.
    """
    root = Path(repo_root)
    results = load_fractional_results(str(root / FRACTIONAL_RESULTS_RELPATH))
    results_sha = sha256_bytes(
        require_canonical_file_bytes(
            (root / FRACTIONAL_RESULTS_RELPATH).read_bytes(), "fractional results"
        )
    )
    cells = _grid_commitments(root)
    return {
        "execution_trace_commitments_schema_version": EXECUTION_TRACE_COMMITMENTS_SCHEMA_VERSION,
        "experiment_id": RUN_001_EXPERIMENT_ID,
        "experiment_family": EXPERIMENT_FAMILY,
        "fractional_results_path": FRACTIONAL_RESULTS_RELPATH,
        "fractional_results_sha256": results_sha,
        "fractional_protocol_sha256": results.fractional_protocol_sha256,
        "research_train_content_fingerprint": results.research_train_content_fingerprint,
        "trace_digest_algorithm": _TRACE_DIGEST_ALGORITHM,
        "cell_count": len(cells),
        "combined_trace_sha256": sha256_bytes(_canonical_bytes(cells)),
        "cells": cells,
    }


def render_execution_trace_commitments(repo_root: str | Path) -> bytes:
    """Canonical JSON bytes of the derived execution-trace commitment record."""
    payload = build_execution_trace_commitments(repo_root)
    return (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def materialize_execution_trace_commitments(repo_root: str | Path) -> tuple[str, ...]:
    """Durably write the execution-trace commitments file; return verifier checks."""
    root = Path(repo_root)
    durable_write_bytes(
        root / EXECUTION_TRACE_COMMITMENTS_RELPATH, render_execution_trace_commitments(root)
    )
    return verify_execution_trace_commitments(root)


def verify_execution_trace_commitments(repo_root: str | Path) -> tuple[str, ...]:
    """Replay-verify the committed execution-trace commitments.

    Re-runs the identical 75-cell grid, recomputes every trace digest, and
    requires the committed record to re-derive byte-for-byte and to bind the exact
    committed results digest. Raises :class:`ExecutionTraceError` on the first
    violation. This re-runs the experiment and is therefore slow.
    """
    root = Path(repo_root)
    path = root / EXECUTION_TRACE_COMMITMENTS_RELPATH
    if not path.exists() or path.is_symlink() or not path.is_file():
        raise ExecutionTraceError(
            f"{EXECUTION_TRACE_COMMITMENTS_RELPATH} is missing or not a regular file"
        )
    committed = path.read_bytes()
    try:
        require_canonical_file_bytes(committed, "execution trace commitments")
        payload: Any = strict_json_loads(committed)
    except ValueError as exc:
        raise ExecutionTraceError(f"commitments file is not canonical JSON: {exc}") from exc
    results_sha = sha256_bytes(
        require_canonical_file_bytes(
            (root / FRACTIONAL_RESULTS_RELPATH).read_bytes(), "fractional results"
        )
    )
    if payload["fractional_results_sha256"] != results_sha:
        raise ExecutionTraceError("commitments do not bind the committed results digest")
    if committed != render_execution_trace_commitments(root):
        raise ExecutionTraceError(
            "execution-trace commitments do not replay byte-for-byte from the frozen engine + data"
        )
    return (
        "trace_commitments_canonical",
        "trace_commitments_bind_results",
        "trace_commitments_replay_byte_for_byte",
    )
