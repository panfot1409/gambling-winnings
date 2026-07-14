"""M3C tri/quad-state replay: input re-binding (M1) and the green failed state (M3)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd
import pytest

from eth_research.data.provenance import sha256_file
from eth_research.m3c.registry import (
    EVENT_FAILED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3C_REGISTRY_RELPATH,
    M3C_REGISTRY_SCHEMA_VERSION,
    M3CRegistryEvent,
    append_registry_event,
    latest_registry_line_sha256,
)
from eth_research.m3c.replay import M3CReplayError, check_replay

_HEX64 = "a" * 64
_COMMIT = "b" * 40
_CANDIDATE = "dual_horizon_trend_63_252_vol_target_30d_50pct"
_STRATEGIES = (
    "cash",
    "buy_and_hold",
    "donchian_55_20",
    "vol_target_donchian_55_20_30d_50pct",
    _CANDIDATE,
)
_SCENARIOS = ("compatibility_v1", "causal_proxy_base", "causal_proxy_stressed")
_T0 = pd.Timestamp("2026-07-14T00:00:00Z")

_PROTOCOL = "research/m3c/protocol.json"
_LINEAGE = "research/m3c/research_lineage.json"
_BUDGET = "research/m3c/research_budget.json"
_PARTITION = "research/m3a/development_partition.json"
_DOSSIER = "research/m2b/frozen_dossier.json"
_GATE = "research/m3a/development_gate_access.jsonl"
_HOLDOUT = "research/m2b/test_evaluations.jsonl"


def _write_inputs(root: Path) -> dict[str, str]:
    bodies = {
        _PROTOCOL: b'{"protocol": 1}\n',
        _LINEAGE: b'{"lineage": 1}\n',
        _BUDGET: b'{"budget": 1}\n',
        _PARTITION: b'{"partition": 1}\n',
        _DOSSIER: b'{"dossier": 1}\n',
    }
    digests: dict[str, str] = {}
    for relpath, body in bodies.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        digests[relpath] = sha256_file(path)
    for ledger in (_GATE, _HOLDOUT):
        p = root / ledger
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    (root / M3C_REGISTRY_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    (root / M3C_REGISTRY_RELPATH).write_bytes(b"")
    return digests


def _registered(root: Path, digests: dict[str, str], previous: str) -> M3CRegistryEvent:
    return M3CRegistryEvent(
        registry_schema_version=M3C_REGISTRY_SCHEMA_VERSION,
        event=EVENT_REGISTERED,
        experiment_id="m3c-dual-horizon-trend-v1-run-001",
        experiment_family="m3c-dual-horizon-trend-v1",
        hypothesis="Characterize the dual-horizon trend candidate vs buy-and-hold.",
        candidate_id=_CANDIDATE,
        candidate_fingerprint=_HEX64,
        strategies=_STRATEGIES,
        cost_scenarios=_SCENARIOS,
        protocol_path=_PROTOCOL,
        protocol_sha256=digests[_PROTOCOL],
        lineage_path=_LINEAGE,
        lineage_sha256=digests[_LINEAGE],
        research_budget_path=_BUDGET,
        research_budget_sha256=digests[_BUDGET],
        development_partition_sha256=digests[_PARTITION],
        frozen_m2_dossier_sha256=digests[_DOSSIER],
        research_train_content_fingerprint=f"sha256:{_HEX64}",
        package_version="0.6.0",
        registered_code_commit_sha=_COMMIT,
        execution_code_commit_sha=_COMMIT,
        execution_source_tree_fingerprint=_HEX64,
        event_time_utc=_T0,
        immutable_results_path="research/m3c/candidate_results.json",
        immutable_report_path="research/m3c/candidate_report.md",
        immutable_decision_path="research/m3c/candidate_decision.json",
        artifact_manifest_path="research/m3c/experiments/run-001/manifest.json",
        results_json_sha256=None,
        report_markdown_sha256=None,
        decision_json_sha256=None,
        result_bundle_sha256=None,
        promotion_status=None,
        failure_description=None,
        previous_event_sha256=previous,
    )


def test_pristine_is_green(tmp_path: Path) -> None:
    _write_inputs(tmp_path)
    state, *_ = check_replay(tmp_path)
    assert state == "pristine"


def test_registered_is_green_and_binds_every_input(tmp_path: Path) -> None:
    digests = _write_inputs(tmp_path)
    reg_path = tmp_path / M3C_REGISTRY_RELPATH
    append_registry_event(
        reg_path, _registered(tmp_path, digests, latest_registry_line_sha256(reg_path))
    )
    assert check_replay(tmp_path)[0] == "registered"
    # Tampering ANY of the five recorded inputs flips the registered checkpoint red —
    # including the development partition, which the old check silently ignored (M1).
    (tmp_path / _PARTITION).write_bytes(b'{"partition": 999}\n')
    with pytest.raises(M3CReplayError):
        check_replay(tmp_path)


def test_failed_is_a_green_committed_checkpoint(tmp_path: Path) -> None:
    digests = _write_inputs(tmp_path)
    reg_path = tmp_path / M3C_REGISTRY_RELPATH
    reg = _registered(tmp_path, digests, latest_registry_line_sha256(reg_path))
    append_registry_event(reg_path, reg)
    started = dataclasses.replace(
        reg,
        event=EVENT_STARTED,
        event_time_utc=_T0 + pd.Timedelta(minutes=1),
        previous_event_sha256=latest_registry_line_sha256(reg_path),
    )
    append_registry_event(reg_path, started)
    failed = dataclasses.replace(
        started,
        event=EVENT_FAILED,
        event_time_utc=_T0 + pd.Timedelta(minutes=2),
        failure_description="execution failed: injected fault",
        previous_event_sha256=latest_registry_line_sha256(reg_path),
    )
    append_registry_event(reg_path, failed)
    # An honest one-shot failure is a real committed state, not a bricked CI (M3).
    assert check_replay(tmp_path)[0] == "failed"


def test_started_only_mid_lifecycle_is_rejected(tmp_path: Path) -> None:
    digests = _write_inputs(tmp_path)
    reg_path = tmp_path / M3C_REGISTRY_RELPATH
    reg = _registered(tmp_path, digests, latest_registry_line_sha256(reg_path))
    append_registry_event(reg_path, reg)
    started = dataclasses.replace(
        reg,
        event=EVENT_STARTED,
        event_time_utc=_T0 + pd.Timedelta(minutes=1),
        previous_event_sha256=latest_registry_line_sha256(reg_path),
    )
    append_registry_event(reg_path, started)
    with pytest.raises(M3CReplayError):
        check_replay(tmp_path)  # [registered, started] is never a committed state


# --------------------------------------------------------------------------- reproduction
# The completed-state reproduction compares the raw-data rebuild against the committed
# results field by field: byte-for-byte everywhere except a named set of secondary
# statistical scalars (bootstrap interval, per-fold paired log-excess, PSR), which are
# outputs of non-correctly-rounded transcendentals (np.log1p, integer powers, math.erf)
# and may differ by a last ULP across machines. Everything else fails closed.


def test_reproduction_tolerates_only_named_transcendental_last_ulp_drift() -> None:
    from eth_research.m3c.replay import _classify_json_reproduction

    committed = {
        "bootstrap": {"ci_lower": -0.002305602394720637, "resamples": 20000},
        "psr_diagnostic": {"psr": 0.4579391619967602, "sample_size": 1126},
        "paired_comparisons": [
            {"fold_index": 0, "mean_daily_paired_log_excess": 0.0019397907812665118}
        ],
        "aggregates": [{"median_marked_return": 1.8482029745405835}],
    }
    reproduced = {
        "bootstrap": {"ci_lower": -0.002305602394720637 * (1 + 4e-13), "resamples": 20000},
        "psr_diagnostic": {"psr": 0.4579391619967602 * (1 - 3e-13), "sample_size": 1126},
        "paired_comparisons": [
            {"fold_index": 0, "mean_daily_paired_log_excess": 0.0019397907812665118 * (1 + 5e-13)}
        ],
        "aggregates": [{"median_marked_return": 1.8482029745405835}],
    }
    tolerated, hard = _classify_json_reproduction(committed, reproduced)
    assert not hard
    assert {".".join(str(part) for part in path) for path, _, _ in tolerated} == {
        "bootstrap.ci_lower",
        "psr_diagnostic.psr",
        "paired_comparisons.0.mean_daily_paired_log_excess",
    }


def test_reproduction_rejects_financial_drift_even_when_tiny() -> None:
    from eth_research.m3c.replay import _classify_json_reproduction

    committed = {"aggregates": [{"median_marked_return": 1.8482029745405835}]}
    reproduced = {"aggregates": [{"median_marked_return": 1.8482029745405835 * (1 + 1e-13)}]}
    tolerated, hard = _classify_json_reproduction(committed, reproduced)
    assert not tolerated  # a financial field is never tolerant, however small the drift
    assert [path for path, _, _ in hard] == [("aggregates", 0, "median_marked_return")]


def test_reproduction_rejects_out_of_tolerance_statistical_drift() -> None:
    from eth_research.m3c.replay import _classify_json_reproduction

    committed = {"bootstrap": {"ci_lower": -0.002305602394720637}}
    reproduced = {"bootstrap": {"ci_lower": -0.002305602394720637 * (1 + 1e-6)}}
    tolerated, hard = _classify_json_reproduction(committed, reproduced)
    assert not tolerated  # 1e-6 relative is far above transcendental last-ULP noise
    assert [path for path, _, _ in hard] == [("bootstrap", "ci_lower")]


def test_reproduction_rejects_structural_and_non_float_drift() -> None:
    from eth_research.m3c.replay import _classify_json_reproduction, _is_transcendental_leaf

    committed = {
        "bootstrap": {"resamples": 20000, "block_lengths": [6, 6, 6, 6, 6]},
        "paired_comparisons": [{"fold_index": 0, "candidate_beats_bnh": True}],
    }
    reproduced = {
        "bootstrap": {"resamples": 20001, "block_lengths": [6, 6, 6, 6]},
        "paired_comparisons": [{"fold_index": 0, "candidate_beats_bnh": False}],
    }
    tolerated, hard = _classify_json_reproduction(committed, reproduced)
    assert not tolerated
    hard_paths = {path for path, _, _ in hard}
    assert ("bootstrap", "resamples") in hard_paths  # integer difference
    assert ("bootstrap", "block_lengths") in hard_paths  # list length differs
    assert ("paired_comparisons", 0, "candidate_beats_bnh") in hard_paths  # boolean
    # The path predicate: only the three named statistical leaf families are tolerant.
    assert _is_transcendental_leaf(("bootstrap", "ci_lower"))
    assert _is_transcendental_leaf(("paired_comparisons", 3, "mean_daily_paired_log_excess"))
    assert not _is_transcendental_leaf(("paired_comparisons", 3, "candidate_marked_return"))
    assert not _is_transcendental_leaf(("aggregates", 0, "median_marked_return"))
