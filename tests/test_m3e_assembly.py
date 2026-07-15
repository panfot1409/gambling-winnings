"""Transactional offline proposal assembly with rollback (commit 12)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import eth_research
from eth_research._atomic import write_atomic
from eth_research.m3e.accepted_base import verify_accepted_base
from eth_research.m3e.assembly import assemble_update_proposal
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.proposal import (
    COMPARISON_NAME,
    PROPOSAL_MANIFEST_NAME,
    TRANSITION_NAME,
)
from eth_research.m3e.update_plan import build_update_plan
from eth_research.m3e.validation import M3EValidationError
from eth_research.m3e.verify_m3e_program import verify_update_proposal

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def _stage_runners(m3e_write_runner: Callable[..., object], proposal_dir: Path) -> None:
    base = verify_accepted_base(REPO_ROOT)
    plan = build_update_plan(base, plan_update_window(base, "2026-07-22T02:17:00Z"))
    m3e_write_runner(
        proposal_dir / "runner_a",
        plan,
        attempt_id="coinbase-eth-usd-prospective-update-runner-a",
        source_commit="a" * 40,
        workflow_run_id="run-99",
        runner_identity="ubuntu-x64-a",
    )
    m3e_write_runner(
        proposal_dir / "runner_b",
        plan,
        attempt_id="coinbase-eth-usd-prospective-update-runner-b",
        source_commit="b" * 40,
        workflow_run_id="run-99",
        runner_identity="ubuntu-x64-b",
    )


def test_assemble_writes_and_self_verifies(
    m3e_write_runner: Callable[..., object], tmp_path: Path
) -> None:
    prop = tmp_path / "prop"
    _stage_runners(m3e_write_runner, prop)
    assembled, digests = assemble_update_proposal(REPO_ROOT, prop)
    names = {rel for rel, _ in digests}
    assert names == {COMPARISON_NAME, TRANSITION_NAME, PROPOSAL_MANIFEST_NAME}
    for name in names:
        assert (prop / name).is_file()
    # The written proposal independently passes the 35-check graph.
    assert len(verify_update_proposal(REPO_ROOT, prop)) == 35
    assert assembled.proposal_branch.startswith("bot/m3e-prospective-update/")


def test_assembly_is_idempotent(m3e_write_runner: Callable[..., object], tmp_path: Path) -> None:
    prop = tmp_path / "prop"
    _stage_runners(m3e_write_runner, prop)
    assemble_update_proposal(REPO_ROOT, prop)
    first = {
        n: (prop / n).read_bytes()
        for n in (COMPARISON_NAME, TRANSITION_NAME, PROPOSAL_MANIFEST_NAME)
    }
    assemble_update_proposal(REPO_ROOT, prop)
    second = {
        n: (prop / n).read_bytes()
        for n in (COMPARISON_NAME, TRANSITION_NAME, PROPOSAL_MANIFEST_NAME)
    }
    assert first == second


def test_a_malformed_target_fails_closed(
    m3e_write_runner: Callable[..., object], tmp_path: Path
) -> None:
    prop = tmp_path / "prop"
    _stage_runners(m3e_write_runner, prop)
    # A non-regular-file where an evidence file must go is refused before any write.
    (prop / PROPOSAL_MANIFEST_NAME).mkdir()
    with pytest.raises(M3EValidationError, match="not a regular file"):
        assemble_update_proposal(REPO_ROOT, prop)
    assert not (prop / COMPARISON_NAME).exists()
    assert not (prop / TRANSITION_NAME).exists()


def test_an_injected_write_failure_rolls_back_the_batch(
    monkeypatch: pytest.MonkeyPatch,
    m3e_write_runner: Callable[..., object],
    tmp_path: Path,
) -> None:
    import eth_research.m3d.publication as pub

    prop = tmp_path / "prop"
    _stage_runners(m3e_write_runner, prop)

    def flaky(path: Path, data: bytes) -> None:
        if Path(path).name == PROPOSAL_MANIFEST_NAME:
            raise OSError("injected write failure on the final blob")
        write_atomic(path, data)

    monkeypatch.setattr(pub, "write_atomic", flaky)
    with pytest.raises(M3EValidationError):
        assemble_update_proposal(REPO_ROOT, prop)
    # The earlier blobs, written before the failure, are rolled back.
    assert not (prop / COMPARISON_NAME).exists()
    assert not (prop / TRANSITION_NAME).exists()
    assert not (prop / PROPOSAL_MANIFEST_NAME).exists()
