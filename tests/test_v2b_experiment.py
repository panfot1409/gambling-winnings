"""V2B §28-29 — the R/P experiment drivers and the offline replay verifier.

The real :func:`run_one_shot` is monkeypatched in every driver test: calling it for real would
evaluate the true partition and consume the one-shot budget. The pristine real repo is checked
read-only.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import eth_research
from eth_research.v2b import experiment as exp
from eth_research.v2b import governance as gov
from eth_research.v2b import orchestrator as orch
from eth_research.v2b import replay as rp
from eth_research.v2b.folds import EXPECTED_ROWS, build_oos_folds
from eth_research.v2b.scenarios import COST_SCENARIOS, PRIMARY_COST, STRESSED_COST

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
TS = "2026-07-20T00:00:00Z"

_PROTOCOL_ARTIFACTS = (
    "v2b_one_shot_budget.json",
    "v2b_research_protocol.json",
    "candidate_source_freeze.json",
    "joint_partition_identity.json",
    "execution_scenarios.json",
    "research_multiplicity_state.json",
)
_SEALED_LEDGERS = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)


def _seed_v2b(dst: Path) -> None:
    """A tmp repo with just enough committed artifacts for the governance + replay verifiers."""
    (dst / "research" / "v2b").mkdir(parents=True, exist_ok=True)
    for name in _PROTOCOL_ARTIFACTS:
        shutil.copy(REPO_ROOT / "research" / "v2b" / name, dst / "research" / "v2b" / name)
    for rel in _SEALED_LEDGERS:
        path = dst / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


@pytest.fixture(scope="module")
def program_result() -> orch.ProgramResult:
    rng = np.random.default_rng(20260726)
    n = EXPECTED_ROWS
    idx = pd.date_range("2016-05-23", periods=n, freq="D", tz="UTC")
    eth = 10.0 * np.cumprod(1.0 + rng.normal(0.0008, 0.03, n))
    btc = 450.0 * np.cumprod(1.0 + rng.normal(0.0006, 0.025, n))
    frame: dict[str, np.ndarray] = {}
    for name, close in (("eth", eth), ("btc", btc)):
        frame[f"{name}_open"] = close * 0.999
        frame[f"{name}_high"] = close * 1.02
        frame[f"{name}_low"] = close * 0.98
        frame[f"{name}_close"] = close
        frame[f"{name}_volume"] = np.full(n, 1_000.0)
    panel = pd.DataFrame(frame, index=idx)
    folds = build_oos_folds(pd.DatetimeIndex(panel.index))
    return orch.evaluate_program(
        panel,
        folds,
        primary_cost=COST_SCENARIOS[PRIMARY_COST],
        stressed_cost=COST_SCENARIOS[STRESSED_COST],
        corrected_alpha=0.005,
    )


def _patch_run(monkeypatch: pytest.MonkeyPatch, root: Path, result: orch.ProgramResult) -> None:
    fingerprint = gov.protocol_fingerprint(root)
    outcome = orch.OneShotOutcome(protocol_fingerprint=fingerprint, result=result)
    monkeypatch.setattr(exp, "run_one_shot", lambda _root: outcome)


def test_register_appends_one_registered_event(tmp_path: Path) -> None:
    _seed_v2b(tmp_path)
    event = exp.register(tmp_path, timestamp=TS)
    assert event.event == "registered"
    events = gov.read_events(tmp_path / gov.V2B_REGISTRY_RELPATH)
    assert [e.event for e in events] == ["registered"]
    # A registered-but-not-run state replays cleanly.
    assert rp.verify_v2b(tmp_path) == []


def test_registration_is_single_use(tmp_path: Path) -> None:
    _seed_v2b(tmp_path)
    exp.register(tmp_path, timestamp=TS)
    with pytest.raises(exp.V2BExperimentError, match="single-use"):
        exp.register(tmp_path, timestamp=TS)


def test_execute_requires_a_prior_registration(
    tmp_path: Path, program_result: orch.ProgramResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_v2b(tmp_path)
    _patch_run(monkeypatch, tmp_path, program_result)
    with pytest.raises(gov.V2BGovernanceError, match="no prior registered"):
        exp.execute(tmp_path, started_at=TS, completed_at=TS)


def test_execute_completes_publishes_and_replays(
    tmp_path: Path, program_result: orch.ProgramResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_v2b(tmp_path)
    _patch_run(monkeypatch, tmp_path, program_result)
    exp.register(tmp_path, timestamp=TS)
    receipt = exp.execute(tmp_path, started_at=TS, completed_at=TS)

    events = gov.read_events(tmp_path / gov.V2B_REGISTRY_RELPATH)
    assert [e.event for e in events] == ["registered", "started", "completed"]
    assert events[-1].payload["results_fingerprint"] == receipt.results_fingerprint
    assert (tmp_path / rp.V2B_RESULTS_RELPATH).exists()
    # The whole published run replays cleanly.
    assert rp.verify_v2b(tmp_path) == []


def test_execute_failure_records_a_failed_terminal_and_no_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_v2b(tmp_path)

    def _boom(_root: Path) -> orch.OneShotOutcome:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(exp, "run_one_shot", _boom)
    exp.register(tmp_path, timestamp=TS)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        exp.execute(tmp_path, started_at=TS, completed_at=TS)

    events = gov.read_events(tmp_path / gov.V2B_REGISTRY_RELPATH)
    assert [e.event for e in events] == ["registered", "started", "failed"]
    assert events[-1].payload["reason"] == "RuntimeError"
    assert not (tmp_path / rp.V2B_RESULTS_RELPATH).exists()


def test_a_second_started_is_rejected_after_a_terminal(
    tmp_path: Path, program_result: orch.ProgramResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_v2b(tmp_path)
    _patch_run(monkeypatch, tmp_path, program_result)
    exp.register(tmp_path, timestamp=TS)
    exp.execute(tmp_path, started_at=TS, completed_at=TS)
    # The one-shot budget is spent; a second execution cannot begin.
    with pytest.raises(gov.V2BGovernanceError, match="one-shot budget"):
        exp.execute(tmp_path, started_at=TS, completed_at=TS)


def test_the_live_repo_replays_cleanly() -> None:
    # Read-only: the live repo replays cleanly in whatever governed state it is in (pristine now).
    assert rp.verify_v2b(REPO_ROOT) == []
