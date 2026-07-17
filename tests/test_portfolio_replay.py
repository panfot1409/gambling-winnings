"""The offline replay verifier: all reproducibility checks pass on the reference universe."""

from __future__ import annotations

from pathlib import Path

from eth_research.portfolio.replay import main, run_checks

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_replay_runs_every_check() -> None:
    passed = run_checks(_REPO_ROOT)
    names = [name for name, _detail in passed]
    assert names == ["determinism", "streaming", "resume", "result", "public_api"]


def test_replay_main_exits_zero() -> None:
    assert main(["--check", "--repo-root", str(_REPO_ROOT)]) == 0
