"""Lifecycle-v2 fixtures: the registry supports distinct per-event timestamps (R9).

run-001 was published with a single ``event_time_utc`` for its ``started`` and
``completed`` events, so their timestamps are identical (defect R9, documented as a
legacy limitation by the closure-evidence test). These fixtures prove the
limitation is *run-001-specific*, not systemic: the existing registry schema
accepts and validates a lifecycle whose events carry strictly increasing
timestamps, and rejects one whose timestamps go backwards. No committed artifact is
touched — every registry here is synthesized in a temp directory from the real
events, re-timestamped and re-chained.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd
import pytest

import eth_research
from eth_research.data.provenance import sha256_bytes
from eth_research.fractional.registry import (
    M3B_REGISTRY_RELPATH,
    FractionalRegistryEvent,
    RegistryError,
    read_registry,
)

REPO = Path(eth_research.__file__).resolve().parents[2]


def _real_lifecycle() -> tuple[FractionalRegistryEvent, ...]:
    return read_registry(REPO / M3B_REGISTRY_RELPATH)


def _rechain(events: list[FractionalRegistryEvent]) -> bytes:
    """Serialize a re-chained lifecycle: each line points at the prior line's bytes."""
    from eth_research.fractional.registry import EMPTY_CONTENT_SHA256

    out = b""
    previous = EMPTY_CONTENT_SHA256
    for event in events:
        line = dataclasses.replace(event, previous_event_sha256=previous).to_json_line()
        out += line
        previous = sha256_bytes(line[:-1])
    return out


def test_run001_has_the_legacy_identical_timestamps() -> None:
    registered, started, completed = _real_lifecycle()
    assert registered.event == "registered"
    assert started.event_time_utc == completed.event_time_utc  # the R9 legacy limitation


def test_distinct_increasing_timestamps_validate(tmp_path: Path) -> None:
    registered, started, completed = _real_lifecycle()
    base = registered.event_time_utc
    started_v2 = dataclasses.replace(started, event_time_utc=base + pd.Timedelta(minutes=1))
    completed_v2 = dataclasses.replace(completed, event_time_utc=base + pd.Timedelta(minutes=2))
    registry = tmp_path / "registry.jsonl"
    registry.write_bytes(_rechain([registered, started_v2, completed_v2]))

    events = read_registry(registry)
    assert [e.event for e in events] == ["registered", "started", "completed"]
    # a genuine v2 lifecycle: three strictly increasing, distinct timestamps
    times = [e.event_time_utc for e in events]
    assert times[0] < times[1] < times[2]
    assert len({t.isoformat() for t in times}) == 3


def test_backwards_timestamp_is_rejected(tmp_path: Path) -> None:
    registered, started, completed = _real_lifecycle()
    base = registered.event_time_utc
    started_v2 = dataclasses.replace(started, event_time_utc=base + pd.Timedelta(minutes=5))
    completed_v2 = dataclasses.replace(completed, event_time_utc=base + pd.Timedelta(minutes=1))
    registry = tmp_path / "registry.jsonl"
    registry.write_bytes(_rechain([registered, started_v2, completed_v2]))
    with pytest.raises(RegistryError, match="event time precedes"):
        read_registry(registry)
