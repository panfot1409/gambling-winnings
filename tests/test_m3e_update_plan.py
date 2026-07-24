"""Deterministic, append-only update plan + idempotency key (commit 5).

Every due window here is derived from the committed accepted base's ``last_open``
(never hard-coded), so the plan semantics are checked against whatever cohort
state governance has accepted.
"""

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
_DAY = pd.Timedelta(days=1)


def _z(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def base() -> AcceptedProspectiveBase:
    return verify_accepted_base(REPO_ROOT)


@pytest.fixture(scope="module")
def last_open(base: AcceptedProspectiveBase) -> pd.Timestamp:
    return pd.Timestamp(base.last_open)


def _plan_at(base: AcceptedProspectiveBase, as_of: pd.Timestamp | str) -> ProspectiveUpdatePlan:
    return build_update_plan(base, plan_update_window(base, as_of))


def _week_as_of(last_open: pd.Timestamp) -> pd.Timestamp:
    """An as_of whose settled due window spans exactly 7 days after last_open."""
    return last_open + pd.Timedelta(days=8, hours=2, minutes=17)


def test_build_tiles_a_multi_day_due_window(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    plan = _plan_at(base, _week_as_of(last_open))  # 7 settled days → 7 buckets
    first_missing = last_open + _DAY
    end = last_open + 8 * _DAY
    assert plan.expected_total_buckets == 7
    assert plan.first_missing_open == _z(first_missing)
    assert plan.completed_day_exclusive_end == _z(end)
    assert len(plan.windows) == 1  # 7 << 299, one window
    w = plan.windows[0]
    assert w["window_start"] == _z(first_missing)
    assert w["window_end"] == _z(end)
    # Coinbase inclusive-end: end_param is the last completed bucket open.
    assert w["end_param"] == _z(end - _DAY)


def test_build_is_deterministic(base: AcceptedProspectiveBase, last_open: pd.Timestamp) -> None:
    a = _plan_at(base, _week_as_of(last_open))
    b = _plan_at(base, last_open + pd.Timedelta(days=8, hours=23, minutes=59))  # same cutoff
    assert a.to_json_bytes() == b.to_json_bytes()
    assert a.idempotency_key == b.idempotency_key
    assert a.plan_sha256 == b.plan_sha256


def test_idempotency_key_changes_with_the_due_window(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    a = _plan_at(base, _week_as_of(last_open))  # 7 buckets
    b = _plan_at(base, last_open + pd.Timedelta(days=9, hours=2, minutes=17))  # 8 buckets
    assert a.idempotency_key != b.idempotency_key


def test_a_large_window_tiles_into_multiple_windows(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    # More than 299 settled daily buckets due → at least two windows.
    plan = _plan_at(base, last_open + pd.Timedelta(days=MAX_BUCKETS_PER_REQUEST + 4, hours=2))
    assert plan.expected_total_buckets > MAX_BUCKETS_PER_REQUEST
    assert len(plan.windows) >= 2
    assert all(w["expected_bucket_count"] <= MAX_BUCKETS_PER_REQUEST for w in plan.windows)
    # Contiguous tiling with no gap/overlap.
    for earlier, later in zip(plan.windows, plan.windows[1:], strict=False):
        assert earlier["window_end"] == later["window_start"]


def test_a_noop_decision_has_no_plan(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    noop = plan_update_window(base, last_open + _DAY + pd.Timedelta(hours=9))
    assert noop.is_noop is True
    with pytest.raises(M3EValidationError, match="no-op"):
        build_update_plan(base, noop)


def test_round_trips_through_from_mapping(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    plan = _plan_at(base, _week_as_of(last_open))
    again = ProspectiveUpdatePlan.from_mapping(json.loads(plan.to_json_bytes()))
    assert again.to_json_bytes() == plan.to_json_bytes()


def test_load_from_a_committed_path(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp, tmp_path: Path
) -> None:
    plan = _plan_at(base, _week_as_of(last_open))
    path = tmp_path / "update_plan.json"
    path.write_bytes(plan.to_json_bytes())
    assert load_update_plan(path).plan_sha256 == plan.plan_sha256


def test_a_forged_idempotency_key_is_rejected(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    doc = json.loads(_plan_at(base, _week_as_of(last_open)).to_json_bytes())
    doc["idempotency_key"] = "0" * 64
    with pytest.raises(M3EValidationError, match="idempotency_key does not match"):
        ProspectiveUpdatePlan.from_mapping(doc)


def test_a_forged_plan_hash_is_rejected(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    doc = json.loads(_plan_at(base, _week_as_of(last_open)).to_json_bytes())
    doc["plan_sha256"] = "0" * 64
    with pytest.raises(M3EValidationError, match="plan_sha256 does not match"):
        ProspectiveUpdatePlan.from_mapping(doc)


def test_first_missing_must_be_one_day_after_last_open(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    doc = json.loads(_plan_at(base, _week_as_of(last_open)).to_json_bytes())
    # Shift first_missing to two days after the accepted last open (a gap).
    doc["first_missing_open"] = _z(last_open + 2 * _DAY)
    with pytest.raises(M3EValidationError):
        ProspectiveUpdatePlan.from_mapping(doc)


def test_non_canonical_plan_bytes_are_rejected(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp, tmp_path: Path
) -> None:
    doc = json.loads(_plan_at(base, _week_as_of(last_open)).to_json_bytes())
    path = tmp_path / "update_plan.json"
    path.write_text(json.dumps(doc))  # compact, non-canonical
    with pytest.raises(M3EValidationError):
        load_update_plan(path)


def test_the_plan_never_reaches_the_forming_candle(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    # as_of mid-day: the as_of day's candle is forming; the plan must end at its
    # own midnight, exclusive.
    plan = _plan_at(base, last_open + pd.Timedelta(days=8, hours=14))
    assert pd.Timestamp(plan.completed_day_exclusive_end) == last_open + 8 * _DAY
