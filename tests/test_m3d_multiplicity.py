"""Tests for the M3D append-only chain helper and the multiplicity ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eth_research.m3d import chain
from eth_research.m3d.multiplicity import (
    LEDGER_PATH,
    _reject_duplicate_identities,
    build_multiplicity_ledger_bytes,
    verify_research_multiplicity,
)
from eth_research.m3d.validation import canonical_jsonl_line

_REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# chain helper                                                                 #
# --------------------------------------------------------------------------- #
def test_chain_round_trips() -> None:
    records: list[dict[str, Any]] = [
        {"entry_kind": "genesis"},
        {"entry_kind": "x", "i": 1},
        {"entry_kind": "x", "i": 2},
    ]
    lines = chain.chained_line_bytes(records)
    decoded = chain.verify_chain(lines)
    assert [r["entry_kind"] for r in decoded] == ["genesis", "x", "x"]
    assert decoded[0][chain.PREVIOUS_FIELD] == chain.GENESIS_PREVIOUS


def test_chain_rejects_preset_previous_field() -> None:
    with pytest.raises(ValueError, match="must not pre-set"):
        chain.chained_line_bytes([{"entry_kind": "genesis", chain.PREVIOUS_FIELD: "x"}])


def test_chain_detects_broken_link() -> None:
    lines = chain.chained_line_bytes([{"a": 1}, {"a": 2}, {"a": 3}])
    lines[2] = canonical_jsonl_line({"a": 3, chain.PREVIOUS_FIELD: "0" * 64})
    with pytest.raises(ValueError, match="breaks the hash chain"):
        chain.verify_chain(lines)


def test_split_rejects_blank_line_and_missing_newline() -> None:
    with pytest.raises(ValueError, match="trailing newline"):
        chain.split_ledger_lines(b'{"a":1}')
    with pytest.raises(ValueError, match="blank line"):
        chain.split_ledger_lines(b'{"a":1}\n\n{"a":2}\n')


# --------------------------------------------------------------------------- #
# multiplicity ledger                                                          #
# --------------------------------------------------------------------------- #
def test_build_is_deterministic_and_committed_matches() -> None:
    a = build_multiplicity_ledger_bytes(_REPO)
    b = build_multiplicity_ledger_bytes(_REPO)
    assert a == b
    assert (_REPO / LEDGER_PATH).read_bytes() == a
    verify_research_multiplicity(_REPO)


def test_ledger_has_genesis_and_all_strategies_and_experiments() -> None:
    records = verify_research_multiplicity(_REPO)
    assert records[0]["entry_kind"] == "genesis"
    strategies = {r["identity"] for r in records if r.get("dimension") == "strategy_specification"}
    assert len(strategies) == 8
    experiments = {r["identity"] for r in records if r.get("dimension") == "experiment"}
    assert "m3c-dual-horizon-trend-v1-run-001" in experiments
    assert "m3a-fixed-baseline-comparison-v2-run-003" in experiments


def test_candidate_recorded_as_candidate_not_benchmark() -> None:
    records = verify_research_multiplicity(_REPO)
    cand = next(
        r for r in records if r.get("identity") == "dual_horizon_trend_63_252_vol_target_30d_50pct"
    )
    assert cand["role"] == "candidate"
    assert cand["status"] == "rejected_for_development_gate_promotion"


def test_reject_duplicate_identities() -> None:
    with pytest.raises(ValueError, match="duplicate multiplicity identity"):
        _reject_duplicate_identities(
            [
                {"dimension": "experiment", "identity": "x"},
                {"dimension": "experiment", "identity": "x"},
            ]
        )


def _records_without_previous() -> list[dict[str, Any]]:
    raw = (_REPO / LEDGER_PATH).read_bytes()
    records = chain.verify_chain(chain.split_ledger_lines(raw))
    stripped: list[dict[str, Any]] = []
    for record in records:
        copy = dict(record)
        copy.pop(chain.PREVIOUS_FIELD)
        stripped.append(copy)
    return stripped


def test_verify_fails_when_an_experiment_is_dropped(tmp_path: Path) -> None:
    records = _records_without_previous()
    kept = [r for r in records if r.get("identity") != "m3b-fractional-execution-risk-v1-run-001"]
    tampered = chain.render_ledger_bytes(chain.chained_line_bytes(kept))
    path = _REPO / LEDGER_PATH
    original = path.read_bytes()
    try:
        path.write_bytes(tampered)
        with pytest.raises(ValueError, match="missing experiment entries"):
            verify_research_multiplicity(_REPO)
    finally:
        path.write_bytes(original)


def test_verify_fails_on_value_tamper(tmp_path: Path) -> None:
    records = _records_without_previous()
    for record in records:
        if record.get("dimension") == "strategy_specification" and record["identity"] == "cash":
            record["status"] = "tampered_status"
    tampered = chain.render_ledger_bytes(chain.chained_line_bytes(records))
    path = _REPO / LEDGER_PATH
    original = path.read_bytes()
    try:
        path.write_bytes(tampered)
        with pytest.raises(ValueError, match="does not match the rebuilt"):
            verify_research_multiplicity(_REPO)
    finally:
        path.write_bytes(original)
