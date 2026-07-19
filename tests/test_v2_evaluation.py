"""Tests for the V2A evaluation stack: protocol, candidate summarization, and the nomination rule.

The real research-train run happens exactly once (the registered one-shot). Here the pure decision
math is exercised on synthetic per-fold returns: a candidate that consistently beats the benchmark
after costs is supported and (if uniquely best) nominated; one that does not is rejected; ties and
failed robustness nominate nobody. Every emitted status is within the constitution's vocabulary.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.v2.constitution import V2A_EMITTABLE_STATUSES
from eth_research.v2.decision import DecisionError, decide, parse_decision
from eth_research.v2.evaluator import CandidateEvaluation, ProgramEvaluation, summarize_candidate
from eth_research.v2.protocol import ProtocolError, ResearchProtocol, parse_protocol

_PROTOCOL = ResearchProtocol.current()
_PPY = 365.25


def _benchmark(seed: int = 1, per_fold: int = 40, folds: int = 5) -> dict[int, pd.Series]:
    rng = np.random.default_rng(seed)
    out: dict[int, pd.Series] = {}
    for f in range(folds):
        start = pd.Timestamp("2020-01-01", tz="UTC") + pd.Timedelta(days=f * per_fold)
        idx = pd.date_range(start, periods=per_fold, freq="D", name="timestamp")
        out[f] = pd.Series(rng.normal(0.0, 0.01, per_fold), index=idx)
    return out


def _shift(bench: dict[int, pd.Series], drift: float) -> dict[int, pd.Series]:
    return {f: (s + drift) for f, s in bench.items()}


def _summ(
    cid: str,
    cand: dict[int, pd.Series],
    bench: dict[int, pd.Series],
    *,
    stressed: dict[int, pd.Series] | None = None,
) -> CandidateEvaluation:
    return summarize_candidate(
        cid,
        primary_candidate_by_fold=cand,
        primary_benchmark_by_fold=bench,
        stressed_candidate_by_fold=stressed if stressed is not None else cand,
        stressed_benchmark_by_fold=bench,
        periods_per_year=_PPY,
        protocol=_PROTOCOL,
    )


def _program(evals: list[CandidateEvaluation]) -> ProgramEvaluation:
    return ProgramEvaluation(
        protocol_fingerprint=_PROTOCOL.fingerprint(),
        periods_per_year=_PPY,
        evaluations=tuple(evals),
    )


# --------------------------------------------------------------------------- #
# protocol                                                                     #
# --------------------------------------------------------------------------- #
def test_protocol_roundtrips_and_pins() -> None:
    p = ResearchProtocol.current()
    assert p.research_train_rows == 2221
    assert p.oos_fold_count == 5
    assert p.criteria.min_folds_beating_benchmark == 3
    assert parse_protocol(p.to_canonical()).fingerprint() == p.fingerprint()
    bad = p.to_canonical()
    bad["bootstrap_seed"] = 1
    with pytest.raises(ProtocolError):
        parse_protocol(bad)


# --------------------------------------------------------------------------- #
# summarization                                                                #
# --------------------------------------------------------------------------- #
def test_winning_candidate_summary_beats_benchmark() -> None:
    bench = _benchmark()
    winner = _summ("winner", _shift(bench, 0.02), bench)
    assert winner.folds_beating_benchmark == 5
    assert winner.primary_lower_above_zero is True
    assert winner.stressed_lower_above_zero is True
    assert winner.aggregate_sharpe > 0.0


def test_losing_candidate_summary_trails_benchmark() -> None:
    bench = _benchmark()
    loser = _summ("loser", _shift(bench, -0.02), bench)
    assert loser.folds_beating_benchmark == 0
    assert loser.primary_lower_above_zero is False


# --------------------------------------------------------------------------- #
# decision rule                                                                #
# --------------------------------------------------------------------------- #
def test_unique_winner_is_supported_and_nominated() -> None:
    bench = _benchmark()
    winner = _summ("winner", _shift(bench, 0.02), bench)
    loser = _summ("loser", _shift(bench, -0.02), bench)
    decision = decide(_program([winner, loser]), _PROTOCOL)
    assert decision.nominated_candidate_id == "winner"
    by_id = {o.candidate_id: o for o in decision.outcomes}
    assert by_id["winner"].status == "eligible_for_development_gate_review"
    assert by_id["winner"].nominated is True
    assert by_id["loser"].status == "research_stage_rejected"
    # No reserved status anywhere.
    assert all(o.status in V2A_EMITTABLE_STATUSES for o in decision.outcomes)


def test_no_candidate_supported_nominates_none() -> None:
    bench = _benchmark()
    a = _summ("a", _shift(bench, -0.02), bench)
    b = _summ("b", _shift(bench, -0.03), bench)
    decision = decide(_program([a, b]), _PROTOCOL)
    assert decision.nominated_candidate_id is None
    assert all(o.status == "research_stage_rejected" for o in decision.outcomes)


def test_tie_for_top_nominates_none_but_both_supported() -> None:
    bench = _benchmark()
    cand = _shift(bench, 0.02)
    a = _summ("a", cand, bench)
    b = _summ("b", cand, bench)  # identical evidence => identical point estimate => tie
    decision = decide(_program([a, b]), _PROTOCOL)
    assert decision.nominated_candidate_id is None
    assert all(o.status == "research_stage_supported" for o in decision.outcomes)
    assert not any(o.nominated for o in decision.outcomes)


def test_failed_stressed_robustness_rejects() -> None:
    bench = _benchmark()
    # Wins the primary read but fails under the stressed scenario (trails there).
    cand = _summ("fragile", _shift(bench, 0.02), bench, stressed=_shift(bench, -0.02))
    decision = decide(_program([cand]), _PROTOCOL)
    assert decision.nominated_candidate_id is None
    outcome = decision.outcomes[0]
    assert outcome.status == "research_stage_rejected"
    assert outcome.criteria["stressed_robustness"] is False


def test_decision_roundtrips_and_rejects_double_nomination() -> None:
    bench = _benchmark()
    winner = _summ("winner", _shift(bench, 0.02), bench)
    loser = _summ("loser", _shift(bench, -0.02), bench)
    decision = decide(_program([winner, loser]), _PROTOCOL)
    assert parse_decision(decision.to_canonical()).fingerprint() == decision.fingerprint()
    # A tampered artifact with two nominations is rejected.
    bad = decision.to_canonical()
    outcomes = bad["outcomes"]
    assert isinstance(outcomes, list)
    for o in outcomes:
        assert isinstance(o, dict)
        o["nominated"] = True
        o["status"] = "eligible_for_development_gate_review"
    bad["nominated_candidate_id"] = "winner"
    with pytest.raises(DecisionError):
        parse_decision(bad)
