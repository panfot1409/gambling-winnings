"""M3C hash-chained registry: append-chain, single-use ids, lifecycle, identity."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd
import pytest

from eth_research.data.provenance import sha256_bytes
from eth_research.m3c.registry import (
    EMPTY_CONTENT_SHA256,
    EVENT_COMPLETED,
    EVENT_FAILED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3C_REGISTRY_SCHEMA_VERSION,
    PROMOTION_ELIGIBLE,
    M3CRegistryError,
    M3CRegistryEvent,
    append_registry_event,
    latest_registry_line_sha256,
    read_registry,
)

_REJECT = (ValueError, TypeError, M3CRegistryError)
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


def _registered(previous: str, *, when: pd.Timestamp = _T0) -> M3CRegistryEvent:
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
        protocol_path="research/m3c/protocol.json",
        protocol_sha256=_HEX64,
        lineage_path="research/m3c/research_lineage.json",
        lineage_sha256=_HEX64,
        research_budget_path="research/m3c/research_budget.json",
        research_budget_sha256=_HEX64,
        development_partition_sha256=_HEX64,
        frozen_m2_dossier_sha256=_HEX64,
        research_train_content_fingerprint=f"sha256:{_HEX64}",
        package_version="0.6.0",
        registered_code_commit_sha=_COMMIT,
        execution_code_commit_sha=_COMMIT,
        execution_source_tree_fingerprint=_HEX64,
        event_time_utc=when,
        immutable_results_path="research/m3c/experiments/run-001/results.json",
        immutable_report_path="research/m3c/experiments/run-001/report.md",
        immutable_decision_path="research/m3c/experiments/run-001/decision.json",
        artifact_manifest_path="research/m3c/experiments/run-001/manifest.json",
        results_json_sha256=None,
        report_markdown_sha256=None,
        decision_json_sha256=None,
        result_bundle_sha256=None,
        promotion_status=None,
        failure_description=None,
        previous_event_sha256=previous,
    )


def _pristine(tmp_path: Path) -> Path:
    path = tmp_path / "experiment_registry.jsonl"
    path.write_bytes(b"")
    return path


def test_round_trip_json_line_is_stable() -> None:
    ev = _registered(EMPTY_CONTENT_SHA256)
    parsed = M3CRegistryEvent.from_json_line(ev.to_json_line())
    assert parsed == ev
    assert ev.to_json_line().endswith(b"\n")


def test_empty_registry_is_pristine(tmp_path: Path) -> None:
    path = _pristine(tmp_path)
    assert read_registry(path) == ()
    assert latest_registry_line_sha256(path) == EMPTY_CONTENT_SHA256


def test_full_lifecycle_appends_and_chains(tmp_path: Path) -> None:
    path = _pristine(tmp_path)
    reg = _registered(latest_registry_line_sha256(path))
    append_registry_event(path, reg)

    started = dataclasses.replace(
        reg,
        event=EVENT_STARTED,
        event_time_utc=_T0 + pd.Timedelta(minutes=1),
        previous_event_sha256=latest_registry_line_sha256(path),
    )
    append_registry_event(path, started)

    completed = dataclasses.replace(
        started,
        event=EVENT_COMPLETED,
        event_time_utc=_T0 + pd.Timedelta(minutes=2),
        results_json_sha256="c" * 64,
        report_markdown_sha256="d" * 64,
        decision_json_sha256="e" * 64,
        result_bundle_sha256="f" * 64,
        promotion_status=PROMOTION_ELIGIBLE,
        previous_event_sha256=latest_registry_line_sha256(path),
    )
    append_registry_event(path, completed)

    events = read_registry(path)
    assert [e.event for e in events] == [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]
    assert events[-1].promotion_status == PROMOTION_ELIGIBLE
    # The chain is intact: each line names its predecessor's exact byte digest.
    raw = path.read_bytes().split(b"\n")[:-1]
    assert events[1].previous_event_sha256 == sha256_bytes(raw[0])
    assert events[2].previous_event_sha256 == sha256_bytes(raw[1])


def test_broken_chain_is_rejected(tmp_path: Path) -> None:
    path = _pristine(tmp_path)
    append_registry_event(path, _registered(latest_registry_line_sha256(path)))
    # A started event that chains onto the wrong previous hash must be refused.
    bad = dataclasses.replace(
        _registered(EMPTY_CONTENT_SHA256),  # wrong: should chain onto the registered line
        event=EVENT_STARTED,
        event_time_utc=_T0 + pd.Timedelta(minutes=1),
    )
    with pytest.raises(_REJECT):
        append_registry_event(path, bad)


def test_duplicate_registered_is_rejected(tmp_path: Path) -> None:
    path = _pristine(tmp_path)
    append_registry_event(path, _registered(latest_registry_line_sha256(path)))
    dup = _registered(latest_registry_line_sha256(path), when=_T0 + pd.Timedelta(minutes=1))
    with pytest.raises(_REJECT):
        append_registry_event(path, dup)


def test_started_without_registered_is_rejected(tmp_path: Path) -> None:
    path = _pristine(tmp_path)
    started = dataclasses.replace(_registered(EMPTY_CONTENT_SHA256), event=EVENT_STARTED)
    with pytest.raises(_REJECT):
        append_registry_event(path, started)


def test_lifecycle_identity_drift_is_rejected(tmp_path: Path) -> None:
    path = _pristine(tmp_path)
    reg = _registered(latest_registry_line_sha256(path))
    append_registry_event(path, reg)
    # A started event that mutates a frozen shared field (the protocol digest)
    # must be refused even though it chains correctly.
    drifted = dataclasses.replace(
        reg,
        event=EVENT_STARTED,
        protocol_sha256="9" * 64,
        event_time_utc=_T0 + pd.Timedelta(minutes=1),
        previous_event_sha256=latest_registry_line_sha256(path),
    )
    with pytest.raises(_REJECT):
        append_registry_event(path, drifted)


def test_timestamps_must_not_regress(tmp_path: Path) -> None:
    path = _pristine(tmp_path)
    reg = _registered(latest_registry_line_sha256(path), when=_T0)
    append_registry_event(path, reg)
    backwards = dataclasses.replace(
        reg,
        event=EVENT_STARTED,
        event_time_utc=_T0 - pd.Timedelta(minutes=1),
        previous_event_sha256=latest_registry_line_sha256(path),
    )
    with pytest.raises(_REJECT):
        append_registry_event(path, backwards)


def test_completed_requires_all_digests_and_a_valid_promotion_status() -> None:
    reg = _registered(EMPTY_CONTENT_SHA256)
    with pytest.raises(_REJECT):  # completed but missing the four digests + status
        dataclasses.replace(reg, event=EVENT_COMPLETED)
    with pytest.raises(_REJECT):  # all digests present but an invalid promotion status
        dataclasses.replace(
            reg,
            event=EVENT_COMPLETED,
            results_json_sha256="c" * 64,
            report_markdown_sha256="d" * 64,
            decision_json_sha256="e" * 64,
            result_bundle_sha256="f" * 64,
            promotion_status="promoted",
        )


def test_non_completed_events_reject_result_fields() -> None:
    with pytest.raises(_REJECT):
        dataclasses.replace(_registered(EMPTY_CONTENT_SHA256), results_json_sha256="c" * 64)
    with pytest.raises(_REJECT):
        dataclasses.replace(_registered(EMPTY_CONTENT_SHA256), promotion_status=PROMOTION_ELIGIBLE)


def test_failed_requires_a_description() -> None:
    with pytest.raises(_REJECT):
        dataclasses.replace(_registered(EMPTY_CONTENT_SHA256), event=EVENT_FAILED)
    ok = dataclasses.replace(
        _registered(EMPTY_CONTENT_SHA256),
        event=EVENT_FAILED,
        failure_description="execution failed: boom",
    )
    assert ok.event == EVENT_FAILED


def test_candidate_id_must_be_one_of_the_strategies() -> None:
    with pytest.raises(_REJECT):
        dataclasses.replace(_registered(EMPTY_CONTENT_SHA256), candidate_id="not_a_strategy")


def test_paths_must_live_under_the_m3c_prefix() -> None:
    with pytest.raises(_REJECT):
        dataclasses.replace(
            _registered(EMPTY_CONTENT_SHA256), protocol_path="research/m3b/protocol.json"
        )
    with pytest.raises(_REJECT):
        dataclasses.replace(
            _registered(EMPTY_CONTENT_SHA256),
            immutable_results_path="research/m3c/../m3b/results.json",
        )


def test_unknown_or_missing_keys_are_rejected() -> None:
    line = _registered(EMPTY_CONTENT_SHA256).to_json_line()
    payload = line.decode("utf-8").rstrip("\n")
    with pytest.raises(_REJECT):
        M3CRegistryEvent.from_json_line((payload[:-1] + ', "extra": 1}\n').encode("utf-8"))
