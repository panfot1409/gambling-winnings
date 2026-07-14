"""The append-only, hash-chained Milestone 3B experiment registry."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from eth_research.fractional.registry import (
    EMPTY_CONTENT_SHA256,
    EVENT_COMPLETED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3B_REGISTRY_SCHEMA_VERSION,
    FractionalRegistryEvent,
    RegistryError,
    append_registry_event,
    latest_registry_line_sha256,
    read_registry,
)

_ID = "m3b-fractional-execution-risk-v1-run-001"
_FAMILY = "m3b-fractional-execution-risk-v1"


def _event(
    event: str,
    previous: str,
    *,
    time: str = "2026-07-14T00:00:00+00:00",
    results: str | None = None,
    report: str | None = None,
    bundle: str | None = None,
    failure: str | None = None,
    hypothesis: str = "Characterize fractional execution and cost overlays; no alpha claim.",
) -> FractionalRegistryEvent:
    return FractionalRegistryEvent(
        registry_schema_version=M3B_REGISTRY_SCHEMA_VERSION,
        event=event,
        experiment_id=_ID,
        experiment_family=_FAMILY,
        hypothesis=hypothesis,
        strategies=("cash", "buy_and_hold", "donchian_55_20", "vt_bh", "vt_don"),
        cost_scenarios=("compatibility_v1", "causal_proxy_base", "causal_proxy_stressed"),
        fractional_protocol_path="research/m3b/fractional_protocol.json",
        fractional_protocol_sha256="a" * 64,
        development_partition_sha256="b" * 64,
        frozen_m2_dossier_sha256="c" * 64,
        package_version="0.5.0",
        registered_code_commit_sha="d" * 40,
        execution_code_commit_sha="d" * 40,
        execution_source_tree_fingerprint="e" * 64,
        event_time_utc=pd.Timestamp(time),
        immutable_results_path="research/m3b/fractional_results.json",
        immutable_report_path="research/m3b/fractional_report.md",
        artifact_manifest_path="research/m3b/experiments/run-001/manifest.json",
        results_json_sha256=results,
        report_markdown_sha256=report,
        result_bundle_sha256=bundle,
        failure_description=failure,
        previous_event_sha256=previous,
    )


def _completed(previous: str) -> FractionalRegistryEvent:
    return _event(
        EVENT_COMPLETED, previous, time="2026-07-14T01:00:00+00:00",
        results="1" * 64, report="2" * 64, bundle="3" * 64,
    )


@pytest.fixture
def registry(tmp_path: Path) -> Path:
    path = tmp_path / "experiment_registry.jsonl"
    path.write_bytes(b"")
    return path


class TestLifecycle:
    def test_empty_registry_is_pristine(self, registry: Path) -> None:
        assert read_registry(registry) == ()
        assert latest_registry_line_sha256(registry) == EMPTY_CONTENT_SHA256

    def test_full_chained_lifecycle(self, registry: Path) -> None:
        append_registry_event(registry, _event(EVENT_REGISTERED, EMPTY_CONTENT_SHA256))
        append_registry_event(
            registry, _event(EVENT_STARTED, latest_registry_line_sha256(registry))
        )
        append_registry_event(registry, _completed(latest_registry_line_sha256(registry)))
        events = read_registry(registry)
        assert [e.event for e in events] == [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]

    def test_round_trips_byte_stably(self, registry: Path) -> None:
        append_registry_event(registry, _event(EVENT_REGISTERED, EMPTY_CONTENT_SHA256))
        (event,) = read_registry(registry)
        assert FractionalRegistryEvent.from_json_line(event.to_json_line()) == event


class TestChain:
    def test_first_line_must_chain_onto_empty_sentinel(self, registry: Path) -> None:
        with pytest.raises(RegistryError, match="append-chain is broken"):
            append_registry_event(registry, _event(EVENT_REGISTERED, "f" * 64))

    def test_broken_chain_is_detected_on_read(self, registry: Path) -> None:
        append_registry_event(registry, _event(EVENT_REGISTERED, EMPTY_CONTENT_SHA256))
        append_registry_event(
            registry, _event(EVENT_STARTED, latest_registry_line_sha256(registry))
        )
        # Corrupt the first line's bytes: the second line's stored previous hash
        # no longer matches, so the chain is broken.
        raw = registry.read_bytes().split(b"\n")
        raw[0] = raw[0].replace(b'"package_version":"0.5.0"', b'"package_version":"9.9.9"')
        registry.write_bytes(b"\n".join(raw))
        with pytest.raises(RegistryError, match=r"append-chain is broken|disagrees"):
            read_registry(registry)

    def test_partial_final_line_is_rejected(self, registry: Path) -> None:
        append_registry_event(registry, _event(EVENT_REGISTERED, EMPTY_CONTENT_SHA256))
        registry.write_bytes(registry.read_bytes().rstrip(b"\n"))  # drop the trailing newline
        with pytest.raises(RegistryError, match="does not end with a newline"):
            read_registry(registry)


class TestSequencing:
    def test_single_use_experiment_id(self, registry: Path) -> None:
        append_registry_event(registry, _event(EVENT_REGISTERED, EMPTY_CONTENT_SHA256))
        with pytest.raises(RegistryError, match="single-use"):
            append_registry_event(
                registry, _event(EVENT_REGISTERED, latest_registry_line_sha256(registry))
            )

    def test_started_must_follow_registered(self, registry: Path) -> None:
        with pytest.raises(RegistryError, match="must follow exactly one 'registered'"):
            append_registry_event(registry, _event(EVENT_STARTED, EMPTY_CONTENT_SHA256))

    def test_shared_identity_must_stay_constant(self, registry: Path) -> None:
        append_registry_event(registry, _event(EVENT_REGISTERED, EMPTY_CONTENT_SHA256))
        drift = _event(
            EVENT_STARTED, latest_registry_line_sha256(registry), hypothesis="a different story"
        )
        with pytest.raises(RegistryError, match="disagrees with the 'registered' event"):
            append_registry_event(registry, drift)

    def test_timestamps_must_not_regress(self, registry: Path) -> None:
        append_registry_event(
            registry,
            _event(EVENT_REGISTERED, EMPTY_CONTENT_SHA256, time="2026-07-14T05:00:00+00:00"),
        )
        earlier = _event(
            EVENT_STARTED, latest_registry_line_sha256(registry), time="2026-07-14T04:00:00+00:00"
        )
        with pytest.raises(RegistryError, match="event time precedes"):
            append_registry_event(registry, earlier)


class TestEventValidation:
    def test_completed_requires_result_hashes(self) -> None:
        with pytest.raises(ValueError, match="results_json_sha256"):
            _event(EVENT_COMPLETED, EMPTY_CONTENT_SHA256)

    def test_result_hashes_forbidden_on_registered(self) -> None:
        with pytest.raises(ValueError, match="must be null on a 'registered'"):
            _event(EVENT_REGISTERED, EMPTY_CONTENT_SHA256, results="1" * 64)

    def test_failure_description_required_on_failed(self) -> None:
        with pytest.raises(ValueError, match="failure_description"):
            _event("failed", EMPTY_CONTENT_SHA256)

    def test_experiment_id_must_belong_to_family(self) -> None:
        with pytest.raises(ValueError, match="belong to the experiment_family"):
            FractionalRegistryEvent.from_json_line(
                _event(EVENT_REGISTERED, EMPTY_CONTENT_SHA256)
                .to_json_line()
                .replace(b'"experiment_id":"' + _ID.encode(), b'"experiment_id":"other-run-0001')
            )

    def test_unknown_key_is_rejected(self) -> None:
        line = _event(EVENT_REGISTERED, EMPTY_CONTENT_SHA256).to_json_line()
        tampered = line[:-2] + b',"surprise":1}\n'
        with pytest.raises(ValueError, match="keys do not match"):
            FractionalRegistryEvent.from_json_line(tampered)
