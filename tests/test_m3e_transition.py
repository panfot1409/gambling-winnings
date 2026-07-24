"""Old → new append-only prospective cohort transition (commit 10).

The old-cohort expectations and every synthetic new-window open are derived from
the committed accepted base (never hard-coded), so the append-only boundary
semantics are checked against whatever cohort state governance has accepted.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import eth_research
from eth_research.m3e.accepted_base import AcceptedProspectiveBase, verify_accepted_base
from eth_research.m3e.acquisition import fingerprint_new_window_rows
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.runner_boundary import load_and_verify_runner
from eth_research.m3e.transition import build_update_transition
from eth_research.m3e.update_plan import build_update_plan
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


def _canon_rows(first_open: str, count: int) -> list[list[Any]]:
    rows: list[list[Any]] = []
    t = pd.Timestamp(first_open)
    for _ in range(count):
        rows.append([t.strftime("%Y-%m-%dT%H:%M:%SZ"), 1700.0, 1705.0, 1698.0, 1702.0, 40_000.0])
        t += pd.Timedelta(days=1)
    return rows


def _runner_rows(
    m3e_write_runner: Callable[..., object], tmp_path: Path, base: AcceptedProspectiveBase
) -> tuple[list[list[Any]], str]:
    # A due window derived from the committed base: 7 settled days past last_open.
    as_of = pd.Timestamp(base.last_open) + pd.Timedelta(days=8, hours=2, minutes=17)
    plan = build_update_plan(base, plan_update_window(base, as_of))
    raw_dir = tmp_path / "runner_a"
    m3e_write_runner(
        raw_dir,
        plan,
        attempt_id="coinbase-eth-usd-prospective-update-runner-a",
        source_commit="a" * 40,
        workflow_run_id="run-a",
        runner_identity="ubuntu-x64-a",
    )
    runner = load_and_verify_runner(raw_dir, runner_label="a")
    return runner.canonical_rows, runner.new_window_fingerprint


def test_a_valid_append_only_extension(
    m3e_write_runner: Callable[..., object],
    tmp_path: Path,
    base: AcceptedProspectiveBase,
    last_open: pd.Timestamp,
) -> None:
    rows, fp = _runner_rows(m3e_write_runner, tmp_path, base)
    t = build_update_transition(REPO_ROOT, base, new_window_rows=rows, new_window_fingerprint=fp)
    assert t.is_append_only is True
    assert t.old_row_count == base.row_count
    assert t.old_last_open == base.last_open
    assert t.new_window_row_count == len(rows) == 7  # the planned 7-day due window
    assert t.new_window_first_open == _z(last_open + _DAY)
    assert t.proposed_row_count == base.row_count + len(rows)
    assert t.proposed_last_open == _z(last_open + 7 * _DAY)
    assert t.old_fingerprint == base.canonical_content_fingerprint
    assert len(t.proposed_cohort_fingerprint) == 64


def test_a_mismatched_new_window_fingerprint_is_rejected(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    rows = _canon_rows(_z(last_open + _DAY), 3)
    with pytest.raises(M3EValidationError, match="fingerprint does not match"):
        build_update_transition(
            REPO_ROOT, base, new_window_rows=rows, new_window_fingerprint="0" * 64
        )


def test_a_gap_after_the_accepted_cohort_is_rejected(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    rows = _canon_rows(_z(last_open + 2 * _DAY), 3)  # skips the first missing day → gap
    fp = fingerprint_new_window_rows(rows)
    with pytest.raises(M3EValidationError, match="one interval after"):
        build_update_transition(REPO_ROOT, base, new_window_rows=rows, new_window_fingerprint=fp)


def test_an_overlap_with_the_accepted_cohort_is_rejected(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    rows = _canon_rows(_z(last_open), 3)  # re-includes the accepted last open
    fp = fingerprint_new_window_rows(rows)
    with pytest.raises(M3EValidationError, match="overlaps or precedes"):
        build_update_transition(REPO_ROOT, base, new_window_rows=rows, new_window_fingerprint=fp)


def test_an_internally_discontiguous_new_window_is_rejected(
    base: AcceptedProspectiveBase, last_open: pd.Timestamp
) -> None:
    rows = _canon_rows(_z(last_open + _DAY), 3)
    # Punch a hole: shift the last row a day later so the window has a gap.
    rows[-1][0] = _z(last_open + 4 * _DAY)
    fp = fingerprint_new_window_rows(rows)
    with pytest.raises(M3EValidationError, match="not contiguous daily"):
        build_update_transition(REPO_ROOT, base, new_window_rows=rows, new_window_fingerprint=fp)


def test_transition_hash_is_deterministic(
    m3e_write_runner: Callable[..., object], tmp_path: Path, base: AcceptedProspectiveBase
) -> None:
    rows, fp = _runner_rows(m3e_write_runner, tmp_path, base)
    a = build_update_transition(REPO_ROOT, base, new_window_rows=rows, new_window_fingerprint=fp)
    b = build_update_transition(REPO_ROOT, base, new_window_rows=rows, new_window_fingerprint=fp)
    assert a.transition_sha256 == b.transition_sha256
