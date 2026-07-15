"""Status + replay CLI tests (M3D sections 20-22)."""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.m3d.replay import _assert_ledgers_byte_empty, replay
from eth_research.m3d.status import (
    FORBIDDEN_STATUS_KEY_SUBSTRINGS,
    _assert_no_forbidden_keys,
    build_status,
)
from eth_research.m3d.validation import M3DValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

_LEDGERS = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)


# --------------------------------------------------------------------------- #
# status                                                                      #
# --------------------------------------------------------------------------- #
def test_status_reports_the_honest_data_only_state() -> None:
    status = build_status(REPO_ROOT)
    assert status["maturity_state"] == "immature"
    assert status["evaluation_authorized"] is False
    assert status["row_count"] == 3
    assert status["remaining_rows"] == 362
    assert status["evaluation_ledger_byte_count"] == 0


def test_status_carries_no_price_or_performance_value() -> None:
    status = build_status(REPO_ROOT)
    for key, value in status.items():
        # Only booleans (the negative governance flags) may use a forbidden word.
        if any(sub in key.lower() for sub in FORBIDDEN_STATUS_KEY_SUBSTRINGS):
            assert isinstance(value, bool)
            assert value is False
    # No float leaks a price/return anywhere in the payload.
    assert not any(isinstance(v, float) for v in status.values())


def test_status_guard_rejects_a_value_bearing_forbidden_key() -> None:
    with pytest.raises(M3DValidationError, match="could leak"):
        _assert_no_forbidden_keys({"row_count": 3, "sharpe_ratio": 1.2})


# --------------------------------------------------------------------------- #
# replay                                                                      #
# --------------------------------------------------------------------------- #
def test_replay_check_runs_the_full_graph() -> None:
    result = replay(REPO_ROOT, deep=False)
    assert result["checks"] == 25
    assert result["deep"] is False


def test_replay_deep_proves_byte_exact_republish() -> None:
    result = replay(REPO_ROOT, deep=True)
    assert result["checks"] == 25
    assert result["republished_artifacts"] == 5


def test_replay_hard_stops_on_a_contaminated_ledger(tmp_path: Path) -> None:
    for relpath in _LEDGERS:
        (tmp_path / relpath).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relpath).write_bytes(b"")
    (tmp_path / _LEDGERS[2]).write_bytes(b'{"evaluated": true}\n')  # contaminate
    with pytest.raises(M3DValidationError, match="byte-empty"):
        _assert_ledgers_byte_empty(tmp_path, "before")
