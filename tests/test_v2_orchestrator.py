"""Tests for the V2A one-shot orchestrator (§21): full-pipeline rehearsal + registry-mediated flow.

The ``@slow`` rehearsal runs the entire deterministic evaluation path (reused engine + folds +
bootstrap + decision) on a synthetic 2221-row frame that carries the *real* research-train dates but
*synthetic* prices — so no real price is ever evaluated, yet the whole engine mechanism is exercised
before the eventual registered run. The flow tests monkeypatch the data + evaluation to prove the
registry lifecycle (started -> completed, started -> failed, budget-consumed-on-start) without
touching the real partition.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eth_research.v2 import orchestrator
from eth_research.v2.candidates import V2A_CANDIDATES
from eth_research.v2.decision import ProgramDecision, decide
from eth_research.v2.evaluator import ProgramEvaluation, summarize_candidate
from eth_research.v2.partitions import ResearchTrainView
from eth_research.v2.protocol import ResearchProtocol
from eth_research.v2.registry import RegistryError, read_events
from eth_research.walkforward import WalkForwardProtocol, load_walk_forward_protocol

REPO = Path(__file__).resolve().parents[1]
_PROTOCOL = ResearchProtocol.current()
_RT_FP = "sha256:60aa988e9db786db5723c925abc794463c23ff701791173b745196c7a8b12033"


def _wf() -> WalkForwardProtocol:
    return load_walk_forward_protocol(REPO / orchestrator.WALK_FORWARD_RELPATH)


def _synthetic_research_train() -> pd.DataFrame:
    # Real research-train dates (public partition boundaries), synthetic prices (no peeking).
    index = pd.date_range("2016-05-23", periods=2221, freq="D", tz="UTC", name="timestamp")
    rng = np.random.default_rng(20260719)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, index.size)))
    openp = np.empty_like(close)
    openp[0] = close[0]
    openp[1:] = close[:-1]
    high = np.maximum(openp, close) * (1.0 + np.abs(rng.normal(0.0, 0.005, index.size)))
    low = np.minimum(openp, close) * (1.0 - np.abs(rng.normal(0.0, 0.005, index.size)))
    volume = rng.uniform(1_000.0, 5_000.0, index.size)
    return pd.DataFrame(
        {"open": openp, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )


@pytest.mark.slow
def test_execute_evaluation_full_pipeline_rehearsal() -> None:
    frame = _synthetic_research_train()
    wf = load_walk_forward_protocol(REPO / orchestrator.WALK_FORWARD_RELPATH)
    evaluation, decision = orchestrator.execute_evaluation(frame, wf, _PROTOCOL)
    ids = {s.candidate_id for s in V2A_CANDIDATES}
    assert {e.candidate_id for e in evaluation.evaluations} == ids
    assert {o.candidate_id for o in decision.outcomes} == ids
    assert sum(1 for o in decision.outcomes if o.nominated) <= 1
    assert all(
        o.status
        in {
            "research_stage_supported",
            "research_stage_rejected",
            "eligible_for_development_gate_review",
        }
        for o in decision.outcomes
    )


def _canned_eval_and_decision() -> tuple[ProgramEvaluation, ProgramDecision]:
    rng = np.random.default_rng(3)
    bench = {
        f: pd.Series(
            rng.normal(0.0, 0.01, 40),
            index=pd.date_range("2020-01-01", periods=40, freq="D", tz="UTC")
            + pd.Timedelta(days=f * 40),
        )
        for f in range(5)
    }
    evals = tuple(
        summarize_candidate(
            s.candidate_id,
            primary_candidate_by_fold={f: v - 0.01 for f, v in bench.items()},
            primary_benchmark_by_fold=bench,
            stressed_candidate_by_fold={f: v - 0.01 for f, v in bench.items()},
            stressed_benchmark_by_fold=bench,
            periods_per_year=365.25,
            protocol=_PROTOCOL,
        )
        for s in V2A_CANDIDATES
    )
    program = ProgramEvaluation(
        protocol_fingerprint=_PROTOCOL.fingerprint(), periods_per_year=365.25, evaluations=evals
    )
    return program, decide(program, _PROTOCOL)


def _fake_view() -> ResearchTrainView:
    idx = pd.date_range("2016-05-23", periods=3, freq="D", tz="UTC", name="timestamp")
    frame = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx
    )
    return ResearchTrainView(
        frame=frame,
        first_open_time=idx[0],
        last_open_time=idx[-1],
        row_count=3,
        content_fingerprint=_RT_FP,
    )


def test_run_one_shot_flow_started_then_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program, decision = _canned_eval_and_decision()
    monkeypatch.setattr(orchestrator, "load_research_train_only", lambda root: _fake_view())
    monkeypatch.setattr(orchestrator, "execute_evaluation", lambda f, wf, p: (program, decision))
    reg = tmp_path / "reg.jsonl"
    results = orchestrator.run_one_shot(
        tmp_path,
        "run_001",
        started_at="2026-07-19T00:00:00Z",
        completed_at="2026-07-19T00:05:00Z",
        registry_path=reg,
        wf_protocol=_wf(),  # unused (execute_evaluation is patched), but correctly typed
    )
    events = read_events(reg)
    assert [e.event for e in events] == ["started", "completed"]
    assert events[1].payload["results_fingerprint"] == results.fingerprint()
    assert (tmp_path / "research/v2a/results.json").exists()


def test_run_one_shot_failure_records_failed_and_consumes_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(
        frame: pd.DataFrame, wf: WalkForwardProtocol, protocol: ResearchProtocol
    ) -> tuple[ProgramEvaluation, ProgramDecision]:
        raise RuntimeError("engine blew up")

    monkeypatch.setattr(orchestrator, "load_research_train_only", lambda root: _fake_view())
    monkeypatch.setattr(orchestrator, "execute_evaluation", _boom)
    reg = tmp_path / "reg.jsonl"
    with pytest.raises(RuntimeError):
        orchestrator.run_one_shot(
            tmp_path,
            "run_001",
            started_at="2026-07-19T00:00:00Z",
            completed_at="2026-07-19T00:05:00Z",
            registry_path=reg,
            wf_protocol=_wf(),
        )
    events = read_events(reg)
    assert [e.event for e in events] == ["started", "failed"]
    # The budget is consumed even on failure: a second run cannot start.
    monkeypatch.setattr(
        orchestrator, "execute_evaluation", lambda f, wf, p: _canned_eval_and_decision()
    )
    with pytest.raises(RegistryError):
        orchestrator.run_one_shot(
            tmp_path,
            "run_002",
            started_at="2026-07-19T01:00:00Z",
            completed_at="2026-07-19T01:05:00Z",
            registry_path=reg,
            wf_protocol=_wf(),
        )
