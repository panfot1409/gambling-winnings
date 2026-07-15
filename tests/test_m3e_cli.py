"""Data-only status CLI + byte-exact offline replay CLI (commit 20)."""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.m3e.replay import replay
from eth_research.m3e.status import _assert_no_forbidden_keys, build_status
from eth_research.m3e.validation import M3EValidationError

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def test_status_reports_only_safe_governance_facts() -> None:
    status = build_status(REPO_ROOT)
    assert status["kind"] == "m3e_review_only_update_status"
    assert status["accepted_base"]["row_count"] == 3
    assert status["accepted_base"]["maturity_state"] == "immature"
    assert status["accepted_base"]["evaluation_authorized"] is False
    assert status["registry"]["proposals_recorded"] == 0
    assert status["workflow_posture"]["active"] is False
    assert all(v == 0 for v in status["ledgers"].values())
    # No OHLCV / return / metric value anywhere (recursive self-check already ran).
    _assert_no_forbidden_keys(status)


def test_status_self_check_catches_a_leak() -> None:
    with pytest.raises(M3EValidationError, match="could leak"):
        _assert_no_forbidden_keys({"accepted_base": {"close_price": 1805.51}})
    with pytest.raises(M3EValidationError):
        _assert_no_forbidden_keys({"return_pct": 0.42})
    # A negative boolean governance flag is honest, not a leak.
    _assert_no_forbidden_keys({"performance_metrics_computed": False})


def test_replay_check_verifies_the_m3e_artifacts() -> None:
    result = replay(REPO_ROOT, deep=False)
    assert result["m3e_artifacts_verified"] == 2
    assert result["deep"] is False


def test_replay_deep_rebuilds_byte_exact() -> None:
    result = replay(REPO_ROOT, deep=True)
    assert result["deep"] is True
    assert result["rebuilt_artifacts"] == 2


def test_replay_hard_stops_on_a_nonempty_ledger(tmp_path: Path) -> None:
    # Stage a tree whose prospective evaluation ledger is contaminated.
    import shutil

    (tmp_path / "research").mkdir()
    for sub in ("m2b", "m3a", "m3d", "m3c", "m3e"):
        shutil.copytree(REPO_ROOT / "research" / sub, tmp_path / "research" / sub)
    (tmp_path / "research/m3d/prospective_evaluations.jsonl").write_bytes(b'{"evaluated": 1}\n')
    with pytest.raises(M3EValidationError, match="byte-empty"):
        replay(tmp_path, deep=False)
