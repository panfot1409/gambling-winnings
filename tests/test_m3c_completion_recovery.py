"""M3C completion intent + calculation-free recovery of a crashed publication."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd
import pytest

from eth_research.data.provenance import sha256_bytes
from eth_research.m3c.completion import (
    CompletionArtifact,
    CompletionIntent,
    CompletionIntentError,
    clear_completion_intent,
    read_completion_intent,
    write_completion_intent,
)
from eth_research.m3c.recovery import (
    STATE_ALREADY_FINALIZED,
    STATE_FINALIZABLE,
    STATE_FINALIZED,
    STATE_NO_INTENT,
    STATE_NOT_FINALIZABLE,
    assess,
    finalize,
)
from eth_research.m3c.registry import (
    EVENT_COMPLETED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3C_REGISTRY_RELPATH,
    M3C_REGISTRY_SCHEMA_VERSION,
    PROMOTION_ELIGIBLE,
    M3CRegistryEvent,
    append_registry_event,
    latest_registry_line_sha256,
    read_registry,
)

_REJECT = (ValueError, TypeError, CompletionIntentError)
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

_RUN = "research/m3c/experiments/run-001"
_RESULTS = f"{_RUN}/results.json"
_REPORT = f"{_RUN}/report.md"
_DECISION = f"{_RUN}/decision.json"
_MANIFEST = f"{_RUN}/manifest.json"


def _registered(previous: str) -> M3CRegistryEvent:
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
        event_time_utc=_T0,
        immutable_results_path=_RESULTS,
        immutable_report_path=_REPORT,
        immutable_decision_path=_DECISION,
        artifact_manifest_path=_MANIFEST,
        results_json_sha256=None,
        report_markdown_sha256=None,
        decision_json_sha256=None,
        result_bundle_sha256=None,
        promotion_status=None,
        failure_description=None,
        previous_event_sha256=previous,
    )


def _publish_artifacts(root: Path) -> dict[str, str]:
    """Write the four artifact files; return relpath -> sha256."""
    bodies = {
        _RESULTS: b'{"results": 1}\n',
        _REPORT: b"# report\n",
        _DECISION: b'{"decision": "eligible"}\n',
        _MANIFEST: b'{"manifest": 1}\n',
    }
    digests: dict[str, str] = {}
    for relpath, body in bodies.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        digests[relpath] = sha256_bytes(body)
    return digests


def _seed_registered_started(root: Path) -> str:
    """Write registered + started; return the started line's sha256 digest."""
    registry = root / M3C_REGISTRY_RELPATH
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_bytes(b"")
    reg = _registered(latest_registry_line_sha256(registry))
    append_registry_event(registry, reg)
    started = dataclasses.replace(
        reg,
        event=EVENT_STARTED,
        event_time_utc=_T0 + pd.Timedelta(minutes=1),
        previous_event_sha256=latest_registry_line_sha256(registry),
    )
    append_registry_event(registry, started)
    return latest_registry_line_sha256(registry)


def _completed_event(root: Path, digests: dict[str, str], started_sha: str) -> M3CRegistryEvent:
    reg = _registered(_HEX64)  # previous is overwritten below; only shared fields matter
    return dataclasses.replace(
        reg,
        event=EVENT_COMPLETED,
        event_time_utc=_T0 + pd.Timedelta(minutes=2),
        results_json_sha256=digests[_RESULTS],
        report_markdown_sha256=digests[_REPORT],
        decision_json_sha256=digests[_DECISION],
        result_bundle_sha256=_HEX64,
        promotion_status=PROMOTION_ELIGIBLE,
        previous_event_sha256=started_sha,
    )


def _intent(root: Path, digests: dict[str, str], started_sha: str) -> CompletionIntent:
    completed = _completed_event(root, digests, started_sha)
    return CompletionIntent(
        experiment_id=completed.experiment_id,
        completed_event_line=completed.to_json_line()[:-1],
        previous_event_sha256=started_sha,
        artifacts=tuple(CompletionArtifact(rel, digests[rel]) for rel in digests),
    )


def test_intent_round_trips(tmp_path: Path) -> None:
    started_sha = _seed_registered_started(tmp_path)
    digests = _publish_artifacts(tmp_path)
    intent = _intent(tmp_path, digests, started_sha)
    assert CompletionIntent.from_json_bytes(intent.to_json_bytes()) == intent


def test_intent_rejects_a_digest_that_disagrees_with_the_event(tmp_path: Path) -> None:
    started_sha = _seed_registered_started(tmp_path)
    digests = _publish_artifacts(tmp_path)
    completed = _completed_event(tmp_path, digests, started_sha)
    # Record a results digest that does not match what the completed event certifies.
    with pytest.raises(_REJECT):
        CompletionIntent(
            experiment_id=completed.experiment_id,
            completed_event_line=completed.to_json_line()[:-1],
            previous_event_sha256=started_sha,
            artifacts=(
                CompletionArtifact(_RESULTS, "c" * 64),  # wrong
                CompletionArtifact(_REPORT, digests[_REPORT]),
                CompletionArtifact(_DECISION, digests[_DECISION]),
            ),
        )


def test_no_intent_is_a_clean_state(tmp_path: Path) -> None:
    _seed_registered_started(tmp_path)
    status = assess(tmp_path)
    assert status.state == STATE_NO_INTENT
    # finalize is safe to call unconditionally on a clean tree.
    assert finalize(tmp_path).state == STATE_NO_INTENT


def test_crashed_but_published_run_is_finalized_calculation_free(tmp_path: Path) -> None:
    started_sha = _seed_registered_started(tmp_path)
    digests = _publish_artifacts(tmp_path)
    intent = _intent(tmp_path, digests, started_sha)
    write_completion_intent(tmp_path, intent)

    assert assess(tmp_path).state == STATE_FINALIZABLE
    result = finalize(tmp_path)
    assert result.state == STATE_FINALIZED
    events = read_registry(tmp_path / M3C_REGISTRY_RELPATH)
    assert [e.event for e in events] == [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]
    assert events[-1].promotion_status == PROMOTION_ELIGIBLE
    assert read_completion_intent(tmp_path) is None  # intent cleared after finalize
    # Idempotent: a second finalize on the now-completed run is a clean no-op.
    assert finalize(tmp_path).state in (STATE_NO_INTENT, STATE_ALREADY_FINALIZED)


def test_already_finalized_run_just_clears_the_intent(tmp_path: Path) -> None:
    started_sha = _seed_registered_started(tmp_path)
    digests = _publish_artifacts(tmp_path)
    intent = _intent(tmp_path, digests, started_sha)
    # Append the completed event first, then leave the (now stale) intent behind.
    append_registry_event(tmp_path / M3C_REGISTRY_RELPATH, intent.completed_event)
    write_completion_intent(tmp_path, intent)
    assert assess(tmp_path).state == STATE_ALREADY_FINALIZED
    assert finalize(tmp_path).state == STATE_ALREADY_FINALIZED
    assert read_completion_intent(tmp_path) is None


def test_incomplete_publication_is_not_finalizable(tmp_path: Path) -> None:
    started_sha = _seed_registered_started(tmp_path)
    digests = _publish_artifacts(tmp_path)
    intent = _intent(tmp_path, digests, started_sha)
    write_completion_intent(tmp_path, intent)
    # Simulate a crash mid-publication: one artifact never landed on disk.
    (tmp_path / _DECISION).unlink()
    assert assess(tmp_path).state == STATE_NOT_FINALIZABLE
    assert finalize(tmp_path).state == STATE_NOT_FINALIZABLE
    # Nothing was appended: the run is still stuck at started.
    events = read_registry(tmp_path / M3C_REGISTRY_RELPATH)
    assert [e.event for e in events] == [EVENT_REGISTERED, EVENT_STARTED]
    clear_completion_intent(tmp_path)
