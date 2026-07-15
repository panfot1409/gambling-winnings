"""Two-runner canonical-equality attestation (commit 9)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import eth_research
from eth_research.m3e.accepted_base import verify_accepted_base
from eth_research.m3e.comparison import compare_runners
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.runner_boundary import VerifiedRunner, load_and_verify_runner
from eth_research.m3e.update_plan import ProspectiveUpdatePlan, build_update_plan
from eth_research.m3e.validation import M3EValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
_AS_OF = "2026-07-22T02:17:00Z"

_Mutate = Callable[[int, list[list[float | int]]], list[list[float | int]]]


@pytest.fixture
def plan() -> ProspectiveUpdatePlan:
    base = verify_accepted_base(REPO_ROOT)
    return build_update_plan(base, plan_update_window(base, _AS_OF))


def _runner(
    m3e_write_runner: Callable[..., object],
    tmp_path: Path,
    plan: ProspectiveUpdatePlan,
    label: str,
    *,
    mutate: _Mutate | None = None,
    runner_identity: str | None = None,
) -> VerifiedRunner:
    raw_dir = tmp_path / f"runner_{label}"
    m3e_write_runner(
        raw_dir,
        plan,
        attempt_id=f"coinbase-eth-usd-prospective-update-runner-{label}",
        source_commit=(label * 40)[:40] if label in "ab" else "c" * 40,
        workflow_run_id="run-99",  # same workflow run; distinct runners
        runner_identity=runner_identity or f"ubuntu-x64-{label}",
        mutate=mutate,
    )
    return load_and_verify_runner(
        raw_dir, runner_label=label, expected_plan_sha256=plan.plan_sha256
    )


def test_two_isolated_runners_agree(
    m3e_write_runner: Callable[..., object], tmp_path: Path, plan: ProspectiveUpdatePlan
) -> None:
    a = _runner(m3e_write_runner, tmp_path, plan, "a")
    b = _runner(m3e_write_runner, tmp_path, plan, "b")
    result = compare_runners(a, b)
    assert result.canonical_content_match is True
    assert result.runners_isolated is True
    assert result.row_count == 7
    assert result.new_window_fingerprint == a.new_window_fingerprint
    assert result.first_open == "2026-07-15T00:00:00Z"


def test_disagreeing_runners_hard_stop(
    m3e_write_runner: Callable[..., object], tmp_path: Path, plan: ProspectiveUpdatePlan
) -> None:
    def bump(_ordinal: int, rows: list[list[float | int]]) -> list[list[float | int]]:
        rows[0][4] = rows[0][4] + 1.0
        return rows

    a = _runner(m3e_write_runner, tmp_path, plan, "a")
    b = _runner(m3e_write_runner, tmp_path, plan, "b", mutate=bump)
    with pytest.raises(M3EValidationError, match="different canonical content"):
        compare_runners(a, b)


def test_runners_on_different_plans_hard_stop(
    m3e_write_runner: Callable[..., object], tmp_path: Path, plan: ProspectiveUpdatePlan
) -> None:
    base = verify_accepted_base(REPO_ROOT)
    other = build_update_plan(base, plan_update_window(base, "2026-07-23T02:17:00Z"))
    a = _runner(m3e_write_runner, tmp_path, plan, "a")
    # Runner b fetched a different window entirely.
    raw_b = tmp_path / "runner_b"
    m3e_write_runner(
        raw_b,
        other,
        attempt_id="coinbase-eth-usd-prospective-update-runner-b",
        source_commit="b" * 40,
        workflow_run_id="run-99",
        runner_identity="ubuntu-x64-b",
    )
    b = load_and_verify_runner(raw_b, runner_label="b", expected_plan_sha256=other.plan_sha256)
    with pytest.raises(M3EValidationError, match="different update plans"):
        compare_runners(a, b)


def test_non_isolated_runners_hard_stop(
    m3e_write_runner: Callable[..., object], tmp_path: Path, plan: ProspectiveUpdatePlan
) -> None:
    # Same runner identity on both sides → not two isolated runners.
    a = _runner(m3e_write_runner, tmp_path, plan, "a", runner_identity="ubuntu-x64-same")
    b = _runner(m3e_write_runner, tmp_path, plan, "b", runner_identity="ubuntu-x64-same")
    with pytest.raises(M3EValidationError, match="not isolated"):
        compare_runners(a, b)


def test_comparison_hash_is_deterministic(
    m3e_write_runner: Callable[..., object], tmp_path: Path, plan: ProspectiveUpdatePlan
) -> None:
    a = _runner(m3e_write_runner, tmp_path, plan, "a")
    b = _runner(m3e_write_runner, tmp_path, plan, "b")
    assert compare_runners(a, b).comparison_sha256 == compare_runners(a, b).comparison_sha256
