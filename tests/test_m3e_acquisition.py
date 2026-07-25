"""Per-runner strict acquisition validators for the update window (commit 7).

All boundary instants are derived from the committed accepted base's ``last_open``
(never hard-coded), so the same boundary semantics are checked against whatever
cohort state governance has accepted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

import eth_research
from conftest import M3E_DEFAULT_NEW_DAYS, m3e_as_of_for_new_days, m3e_zulu
from eth_research.m3d.receipt import ProspectiveAttemptReceipt
from eth_research.m3e.accepted_base import AcceptedProspectiveBase, verify_accepted_base
from eth_research.m3e.acquisition import (
    build_runner_bundles,
    new_window_canonical_rows,
    new_window_fingerprint,
)
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.update_plan import ProspectiveUpdatePlan, build_update_plan
from eth_research.m3e.validation import M3EValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
_DAY = pd.Timedelta(days=1)

_Mutate = Callable[[int, list[list[float | int]]], list[list[float | int]]]


@pytest.fixture(scope="module")
def base() -> AcceptedProspectiveBase:
    return verify_accepted_base(REPO_ROOT)


@pytest.fixture
def plan(base: AcceptedProspectiveBase) -> ProspectiveUpdatePlan:
    return build_update_plan(base, plan_update_window(base, m3e_as_of_for_new_days(base)))


def _runner(
    m3e_write_runner: Callable[..., ProspectiveAttemptReceipt],
    tmp_path: Path,
    plan: ProspectiveUpdatePlan,
    name: str,
    *,
    mutate: _Mutate | None = None,
) -> tuple[Path, ProspectiveAttemptReceipt]:
    raw_dir = tmp_path / name
    receipt = m3e_write_runner(
        raw_dir,
        plan,
        attempt_id=f"coinbase-eth-usd-prospective-update-runner-{name}",
        source_commit=("a" if name == "a" else "b") * 40,
        workflow_run_id=f"run-{name}",
        runner_identity=f"ubuntu-x64-{name}",
        mutate=mutate,
    )
    return raw_dir, receipt


def test_a_runner_produces_the_seven_new_completed_days(
    m3e_write_runner: Callable[..., ProspectiveAttemptReceipt],
    tmp_path: Path,
    plan: ProspectiveUpdatePlan,
    base: AcceptedProspectiveBase,
) -> None:
    raw_dir, receipt = _runner(m3e_write_runner, tmp_path, plan, "a")
    bundles = build_runner_bundles(raw_dir=raw_dir, update_plan=plan, receipt=receipt)
    rows = new_window_canonical_rows(bundles)
    assert len(rows) == M3E_DEFAULT_NEW_DAYS
    # A contiguous run of completed days starting the day after the accepted base ends.
    last_open = pd.Timestamp(base.last_open)
    assert rows[0][0] == m3e_zulu(last_open + _DAY)
    assert rows[-1][0] == m3e_zulu(last_open + M3E_DEFAULT_NEW_DAYS * _DAY)


def test_two_independent_runners_agree_byte_for_byte(
    m3e_write_runner: Callable[..., ProspectiveAttemptReceipt],
    tmp_path: Path,
    plan: ProspectiveUpdatePlan,
) -> None:
    dir_a, rec_a = _runner(m3e_write_runner, tmp_path, plan, "a")
    dir_b, rec_b = _runner(m3e_write_runner, tmp_path, plan, "b")
    fp_a = new_window_fingerprint(
        build_runner_bundles(raw_dir=dir_a, update_plan=plan, receipt=rec_a)
    )
    fp_b = new_window_fingerprint(
        build_runner_bundles(raw_dir=dir_b, update_plan=plan, receipt=rec_b)
    )
    assert fp_a == fp_b


def test_a_perturbed_runner_yields_a_different_fingerprint(
    m3e_write_runner: Callable[..., ProspectiveAttemptReceipt],
    tmp_path: Path,
    plan: ProspectiveUpdatePlan,
) -> None:
    def bump_close(_ordinal: int, rows: list[list[float | int]]) -> list[list[float | int]]:
        rows[0][4] = rows[0][4] + 1.0  # nudge one close price
        return rows

    dir_a, rec_a = _runner(m3e_write_runner, tmp_path, plan, "a")
    dir_b, rec_b = _runner(m3e_write_runner, tmp_path, plan, "b", mutate=bump_close)
    fp_a = new_window_fingerprint(
        build_runner_bundles(raw_dir=dir_a, update_plan=plan, receipt=rec_a)
    )
    fp_b = new_window_fingerprint(
        build_runner_bundles(raw_dir=dir_b, update_plan=plan, receipt=rec_b)
    )
    assert fp_a != fp_b


def test_a_tampered_raw_byte_breaks_the_receipt_binding(
    m3e_write_runner: Callable[..., ProspectiveAttemptReceipt],
    tmp_path: Path,
    plan: ProspectiveUpdatePlan,
) -> None:
    raw_dir, receipt = _runner(m3e_write_runner, tmp_path, plan, "a")
    # Overwrite the raw file after the receipt is sealed → SHA-256 mismatch.
    target = raw_dir / str(plan.windows[0]["raw_filename"])
    rows = json.loads(target.read_text())
    rows[0][4] = rows[0][4] + 5.0
    target.write_text(json.dumps(rows))
    with pytest.raises(M3EValidationError, match="SHA-256 does not match the receipt"):
        build_runner_bundles(raw_dir=raw_dir, update_plan=plan, receipt=receipt)


def test_a_truncated_tail_is_rejected(
    m3e_write_runner: Callable[..., ProspectiveAttemptReceipt],
    tmp_path: Path,
    plan: ProspectiveUpdatePlan,
) -> None:
    def drop_newest(_ordinal: int, rows: list[list[float | int]]) -> list[list[float | int]]:
        return rows[1:]  # rows are descending; drop the newest completed day

    raw_dir, receipt = _runner(m3e_write_runner, tmp_path, plan, "a", mutate=drop_newest)
    with pytest.raises(M3EValidationError, match=r"planned|reach the plan window end"):
        build_runner_bundles(raw_dir=raw_dir, update_plan=plan, receipt=receipt)


def test_a_receipt_for_a_different_plan_is_rejected(
    m3e_write_runner: Callable[..., ProspectiveAttemptReceipt],
    tmp_path: Path,
    plan: ProspectiveUpdatePlan,
    base: AcceptedProspectiveBase,
) -> None:
    # A strictly wider window than ``plan``: a genuinely different update plan.
    other = build_update_plan(
        base, plan_update_window(base, m3e_as_of_for_new_days(base, M3E_DEFAULT_NEW_DAYS + 1))
    )
    assert other.plan_sha256 != plan.plan_sha256
    raw_dir, receipt = _runner(m3e_write_runner, tmp_path, other, "a")
    with pytest.raises(M3EValidationError, match="plan hash does not match"):
        build_runner_bundles(raw_dir=raw_dir, update_plan=plan, receipt=receipt)


def test_a_symlinked_raw_file_is_refused(
    m3e_write_runner: Callable[..., ProspectiveAttemptReceipt],
    tmp_path: Path,
    plan: ProspectiveUpdatePlan,
) -> None:
    raw_dir, receipt = _runner(m3e_write_runner, tmp_path, plan, "a")
    target = raw_dir / str(plan.windows[0]["raw_filename"])
    real = target.read_bytes()
    target.unlink()
    (tmp_path / "elsewhere.json").write_bytes(real)
    target.symlink_to(tmp_path / "elsewhere.json")
    with pytest.raises(M3EValidationError, match="not a regular file"):
        build_runner_bundles(raw_dir=raw_dir, update_plan=plan, receipt=receipt)
