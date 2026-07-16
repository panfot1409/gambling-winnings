"""Deterministic proposal-branch naming and the concurrency lease (commit 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.m3e.accepted_base import AcceptedProspectiveBase, verify_accepted_base
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.lease import (
    PROPOSAL_BRANCH_PREFIX,
    acquire_proposal_lease,
    assert_publishable_proposal_branch,
    proposal_branch_name,
)
from eth_research.m3e.update_plan import ProspectiveUpdatePlan, build_update_plan
from eth_research.m3e.validation import M3EValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
_KEY = "a" * 64
_KEY2 = "b" * 64


def _real_plan() -> tuple[AcceptedProspectiveBase, ProspectiveUpdatePlan]:
    base = verify_accepted_base(REPO_ROOT)
    return base, build_update_plan(base, plan_update_window(base, "2026-07-22T02:17:00Z"))


def test_branch_name_is_deterministic_and_prefixed() -> None:
    name1 = proposal_branch_name(
        idempotency_key=_KEY,
        first_missing_open="2026-07-15T00:00:00Z",
        completed_day_exclusive_end="2026-07-22T00:00:00Z",
    )
    name2 = proposal_branch_name(
        idempotency_key=_KEY,
        first_missing_open="2026-07-15T00:00:00Z",
        completed_day_exclusive_end="2026-07-22T00:00:00Z",
    )
    assert name1 == name2
    assert name1 == PROPOSAL_BRANCH_PREFIX + "20260715-20260722-" + _KEY[:16]
    assert_publishable_proposal_branch(name1)


def test_distinct_keys_yield_distinct_branches() -> None:
    a = proposal_branch_name(
        idempotency_key=_KEY,
        first_missing_open="2026-07-15T00:00:00Z",
        completed_day_exclusive_end="2026-07-22T00:00:00Z",
    )
    b = proposal_branch_name(
        idempotency_key=_KEY2,
        first_missing_open="2026-07-15T00:00:00Z",
        completed_day_exclusive_end="2026-07-22T00:00:00Z",
    )
    assert a != b


@pytest.mark.parametrize(
    "bad",
    [
        "main",
        "master",
        "claude/m3d-prospective-evidence-governance",
        "claude/m3e-review-only-prospective-updates",
        "claude/anything",
        "bot/m3e-prospective-update/refs/heads/main",
        "feature/x",
        "bot/m3e-prospective-update/../main",
        PROPOSAL_BRANCH_PREFIX + "not-the-right-shape",
    ],
)
def test_protected_or_malformed_branches_are_refused(bad: str) -> None:
    with pytest.raises(M3EValidationError):
        assert_publishable_proposal_branch(bad)


def test_lease_proceeds_when_nothing_exists() -> None:
    _base, plan = _real_plan()
    lease = acquire_proposal_lease(
        idempotency_key=plan.idempotency_key,
        plan_sha256=plan.plan_sha256,
        first_missing_open=plan.first_missing_open,
        completed_day_exclusive_end=plan.completed_day_exclusive_end,
    )
    assert lease.should_proceed is True
    assert lease.branch_name.startswith(PROPOSAL_BRANCH_PREFIX)
    assert_publishable_proposal_branch(lease.branch_name)


def test_lease_skips_when_the_branch_already_exists() -> None:
    _base, plan = _real_plan()
    branch = proposal_branch_name(
        idempotency_key=plan.idempotency_key,
        first_missing_open=plan.first_missing_open,
        completed_day_exclusive_end=plan.completed_day_exclusive_end,
    )
    lease = acquire_proposal_lease(
        idempotency_key=plan.idempotency_key,
        plan_sha256=plan.plan_sha256,
        first_missing_open=plan.first_missing_open,
        completed_day_exclusive_end=plan.completed_day_exclusive_end,
        existing_branch_names={branch},
    )
    assert lease.should_proceed is False
    assert "already exists" in lease.reason


def test_lease_skips_when_an_open_proposal_key_exists() -> None:
    _base, plan = _real_plan()
    lease = acquire_proposal_lease(
        idempotency_key=plan.idempotency_key,
        plan_sha256=plan.plan_sha256,
        first_missing_open=plan.first_missing_open,
        completed_day_exclusive_end=plan.completed_day_exclusive_end,
        existing_open_proposal_keys={plan.idempotency_key},
    )
    assert lease.should_proceed is False


def test_lease_id_is_deterministic() -> None:
    _base, plan = _real_plan()
    first = acquire_proposal_lease(
        idempotency_key=plan.idempotency_key,
        plan_sha256=plan.plan_sha256,
        first_missing_open=plan.first_missing_open,
        completed_day_exclusive_end=plan.completed_day_exclusive_end,
    )
    second = acquire_proposal_lease(
        idempotency_key=plan.idempotency_key,
        plan_sha256=plan.plan_sha256,
        first_missing_open=plan.first_missing_open,
        completed_day_exclusive_end=plan.completed_day_exclusive_end,
    )
    assert first.lease_id == second.lease_id


def test_a_non_hex_idempotency_key_is_rejected() -> None:
    with pytest.raises(M3EValidationError):
        proposal_branch_name(
            idempotency_key="not-hex",
            first_missing_open="2026-07-15T00:00:00Z",
            completed_day_exclusive_end="2026-07-22T00:00:00Z",
        )
