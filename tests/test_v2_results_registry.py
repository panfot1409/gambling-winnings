"""Tests for the V2A results artifact and the one-shot hash-chained registry (§19-20)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eth_research.v2.candidates import V2A_CANDIDATES
from eth_research.v2.decision import decide
from eth_research.v2.evaluator import ProgramEvaluation, summarize_candidate
from eth_research.v2.protocol import ResearchProtocol
from eth_research.v2.registry import (
    RegistryError,
    append_event,
    read_events,
    started_run_ids,
    verify_registry,
)
from eth_research.v2.results import ResultsError, build_results, parse_results

_PROTOCOL = ResearchProtocol.current()
_FP = _PROTOCOL.fingerprint()
_RT_FP = "sha256:60aa988e9db786db5723c925abc794463c23ff701791173b745196c7a8b12033"


def _bench(seed: int = 1, per_fold: int = 40, folds: int = 5) -> dict[int, pd.Series]:
    rng = np.random.default_rng(seed)
    out: dict[int, pd.Series] = {}
    for f in range(folds):
        start = pd.Timestamp("2020-01-01", tz="UTC") + pd.Timedelta(days=f * per_fold)
        idx = pd.date_range(start, periods=per_fold, freq="D", name="timestamp")
        out[f] = pd.Series(rng.normal(0.0, 0.01, per_fold), index=idx)
    return out


def _shift(bench: dict[int, pd.Series], drift: float) -> dict[int, pd.Series]:
    return {f: (s + drift) for f, s in bench.items()}


def _real_program() -> ProgramEvaluation:
    bench = _bench()
    ids = [s.candidate_id for s in V2A_CANDIDATES]
    drifts = [0.02, -0.02, -0.03]  # first one wins, others lose
    evals = [
        summarize_candidate(
            cid,
            primary_candidate_by_fold=_shift(bench, d),
            primary_benchmark_by_fold=bench,
            stressed_candidate_by_fold=_shift(bench, d),
            stressed_benchmark_by_fold=bench,
            periods_per_year=365.25,
            protocol=_PROTOCOL,
        )
        for cid, d in zip(ids, drifts, strict=True)
    ]
    return ProgramEvaluation(
        protocol_fingerprint=_FP, periods_per_year=365.25, evaluations=tuple(evals)
    )


# --------------------------------------------------------------------------- #
# results                                                                      #
# --------------------------------------------------------------------------- #
def test_results_build_and_roundtrip() -> None:
    program = _real_program()
    decision = decide(program, _PROTOCOL)
    results = build_results(
        "run_001",
        program,
        decision,
        research_train_fingerprint=_RT_FP,
        package_version="2.0.0.dev0",
    )
    assert results.nominated_candidate_id == V2A_CANDIDATES[0].candidate_id
    assert parse_results(results.to_canonical()).fingerprint() == results.fingerprint()


def test_results_reject_unregistered_candidate() -> None:
    # A decision over ids outside the registered candidate set is rejected.
    bench = _bench()
    ev = summarize_candidate(
        "not_a_registered_candidate",
        primary_candidate_by_fold=_shift(bench, 0.02),
        primary_benchmark_by_fold=bench,
        stressed_candidate_by_fold=_shift(bench, 0.02),
        stressed_benchmark_by_fold=bench,
        periods_per_year=365.25,
        protocol=_PROTOCOL,
    )
    program = ProgramEvaluation(
        protocol_fingerprint=_FP, periods_per_year=365.25, evaluations=(ev,)
    )
    decision = decide(program, _PROTOCOL)
    with pytest.raises(ResultsError):
        build_results(
            "run_x",
            program,
            decision,
            research_train_fingerprint=_RT_FP,
            package_version="2.0.0.dev0",
        )


# --------------------------------------------------------------------------- #
# registry                                                                     #
# --------------------------------------------------------------------------- #
def test_registry_started_completed_chain(tmp_path: Path) -> None:
    reg = tmp_path / "research_registry.jsonl"
    e0 = append_event(
        reg, "started", "run_001", protocol_fingerprint=_FP, timestamp="2026-07-19T00:00:00Z"
    )
    e1 = append_event(
        reg,
        "completed",
        "run_001",
        protocol_fingerprint=_FP,
        timestamp="2026-07-19T00:05:00Z",
        payload={"results_fingerprint": "a" * 64},
    )
    events = read_events(reg)
    assert len(events) == 2
    assert events[0].entry_hash == e0.entry_hash
    assert events[1].prev_entry_hash == e0.entry_hash == e1.prev_entry_hash
    assert verify_registry(reg) == []
    assert started_run_ids(reg) == ("run_001",)


def test_registry_second_started_is_refused(tmp_path: Path) -> None:
    reg = tmp_path / "r.jsonl"
    append_event(
        reg, "started", "run_001", protocol_fingerprint=_FP, timestamp="2026-07-19T00:00:00Z"
    )
    # Even after a failure, the budget stays consumed — no second started.
    append_event(
        reg, "failed", "run_001", protocol_fingerprint=_FP, timestamp="2026-07-19T00:01:00Z"
    )
    with pytest.raises(RegistryError):
        append_event(
            reg, "started", "run_002", protocol_fingerprint=_FP, timestamp="2026-07-19T00:02:00Z"
        )


def test_registry_completed_without_started_is_refused(tmp_path: Path) -> None:
    reg = tmp_path / "r.jsonl"
    with pytest.raises(RegistryError):
        append_event(
            reg, "completed", "run_001", protocol_fingerprint=_FP, timestamp="2026-07-19T00:00:00Z"
        )


def test_registry_tamper_breaks_the_chain(tmp_path: Path) -> None:
    reg = tmp_path / "r.jsonl"
    append_event(
        reg, "started", "run_001", protocol_fingerprint=_FP, timestamp="2026-07-19T00:00:00Z"
    )
    append_event(
        reg, "completed", "run_001", protocol_fingerprint=_FP, timestamp="2026-07-19T00:05:00Z"
    )
    lines = reg.read_bytes().splitlines()
    # Tamper with the first entry's timestamp; the recorded entry_hash no longer matches.
    lines[0] = lines[0].replace(b"00:00:00Z", b"09:09:09Z")
    reg.write_bytes(b"\n".join(lines) + b"\n")
    assert verify_registry(reg) != []
    with pytest.raises(RegistryError):
        read_events(reg)
