"""Deterministic, append-only update plan + idempotency key (commit 5)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import eth_research
from eth_research.m3d.acquisition_plan import MAX_BUCKETS_PER_REQUEST
from eth_research.m3e.accepted_base import AcceptedProspectiveBase, verify_accepted_base
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.update_plan import (
    ProspectiveUpdatePlan,
    build_update_plan,
    load_update_plan,
)
from eth_research.m3e.validation import M3EValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def base() -> AcceptedProspectiveBase:
    return verify_accepted_base(REPO_ROOT)


def _plan_at(base: AcceptedProspectiveBase, as_of: str) -> ProspectiveUpdatePlan:
    return build_update_plan(base, plan_update_window(base, as_of))


def test_build_tiles_a_multi_day_due_window(base: AcceptedProspectiveBase) -> None:
    plan = _plan_at(base, "2026-07-22T02:17:00Z")  # 07-15 .. 07-21 → 7 buckets
    assert plan.expected_total_buckets == 7
    assert plan.first_missing_open == "2026-07-15T00:00:00Z"
    assert plan.completed_day_exclusive_end == "2026-07-22T00:00:00Z"
    assert len(plan.windows) == 1  # 7 << 299, one window
    w = plan.windows[0]
    assert w["window_start"] == "2026-07-15T00:00:00Z"
    assert w["window_end"] == "2026-07-22T00:00:00Z"
    # Coinbase inclusive-end: end_param is the last completed bucket open.
    assert w["end_param"] == "2026-07-21T00:00:00Z"


def test_build_is_deterministic(base: AcceptedProspectiveBase) -> None:
    a = _plan_at(base, "2026-07-22T02:17:00Z")
    b = _plan_at(base, "2026-07-22T23:59:00Z")  # same completed-day cutoff
    assert a.to_json_bytes() == b.to_json_bytes()
    assert a.idempotency_key == b.idempotency_key
    assert a.plan_sha256 == b.plan_sha256


def test_idempotency_key_changes_with_the_due_window(base: AcceptedProspectiveBase) -> None:
    a = _plan_at(base, "2026-07-22T02:17:00Z")  # 7 buckets
    b = _plan_at(base, "2026-07-23T02:17:00Z")  # 8 buckets
    assert a.idempotency_key != b.idempotency_key


def test_a_large_window_tiles_into_multiple_windows(base: AcceptedProspectiveBase) -> None:
    # ~ one year later → more than 299 daily buckets → at least two windows.
    plan = _plan_at(base, "2027-08-01T00:00:00Z")
    assert plan.expected_total_buckets > MAX_BUCKETS_PER_REQUEST
    assert len(plan.windows) >= 2
    assert all(w["expected_bucket_count"] <= MAX_BUCKETS_PER_REQUEST for w in plan.windows)
    # Contiguous tiling with no gap/overlap.
    for earlier, later in zip(plan.windows, plan.windows[1:], strict=False):
        assert earlier["window_end"] == later["window_start"]


def test_a_noop_decision_has_no_plan(base: AcceptedProspectiveBase) -> None:
    noop = plan_update_window(base, "2026-07-15T09:00:00Z")
    assert noop.is_noop is True
    with pytest.raises(M3EValidationError, match="no-op"):
        build_update_plan(base, noop)


def test_round_trips_through_from_mapping(base: AcceptedProspectiveBase) -> None:
    plan = _plan_at(base, "2026-07-22T02:17:00Z")
    again = ProspectiveUpdatePlan.from_mapping(json.loads(plan.to_json_bytes()))
    assert again.to_json_bytes() == plan.to_json_bytes()


def test_load_from_a_committed_path(base: AcceptedProspectiveBase, tmp_path: Path) -> None:
    plan = _plan_at(base, "2026-07-22T02:17:00Z")
    path = tmp_path / "update_plan.json"
    path.write_bytes(plan.to_json_bytes())
    assert load_update_plan(path).plan_sha256 == plan.plan_sha256


def test_a_forged_idempotency_key_is_rejected(base: AcceptedProspectiveBase) -> None:
    doc = json.loads(_plan_at(base, "2026-07-22T02:17:00Z").to_json_bytes())
    doc["idempotency_key"] = "0" * 64
    with pytest.raises(M3EValidationError, match="idempotency_key does not match"):
        ProspectiveUpdatePlan.from_mapping(doc)


def test_a_forged_plan_hash_is_rejected(base: AcceptedProspectiveBase) -> None:
    doc = json.loads(_plan_at(base, "2026-07-22T02:17:00Z").to_json_bytes())
    doc["plan_sha256"] = "0" * 64
    with pytest.raises(M3EValidationError, match="plan_sha256 does not match"):
        ProspectiveUpdatePlan.from_mapping(doc)


def test_first_missing_must_be_one_day_after_last_open(base: AcceptedProspectiveBase) -> None:
    doc = json.loads(_plan_at(base, "2026-07-22T02:17:00Z").to_json_bytes())
    # Shift first_missing to two days after the accepted last open (a gap).
    doc["first_missing_open"] = "2026-07-16T00:00:00Z"
    with pytest.raises(M3EValidationError):
        ProspectiveUpdatePlan.from_mapping(doc)


def test_non_canonical_plan_bytes_are_rejected(
    base: AcceptedProspectiveBase, tmp_path: Path
) -> None:
    doc = json.loads(_plan_at(base, "2026-07-22T02:17:00Z").to_json_bytes())
    path = tmp_path / "update_plan.json"
    path.write_text(json.dumps(doc))  # compact, non-canonical
    with pytest.raises(M3EValidationError):
        load_update_plan(path)


def test_the_plan_never_reaches_the_forming_candle(base: AcceptedProspectiveBase) -> None:
    # as_of mid-day 2026-07-22: 07-22 is forming; the plan must end at 07-22 exclusive.
    plan = _plan_at(base, "2026-07-22T14:00:00Z")
    assert pd.Timestamp(plan.completed_day_exclusive_end) == pd.Timestamp("2026-07-22T00:00:00Z")
