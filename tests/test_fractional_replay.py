"""Dual-state replay verifier: fail-closed on any inconsistent committed state.

The pristine and completed happy paths are exercised end-to-end in
``test_fractional_orchestrator.py`` (a real disposable clone). These are the
cheap negative paths on a synthetic minimal tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eth_research.fractional.replay import ReplayError, check_replay
from eth_research.fractional.results import FRACTIONAL_RESULTS_RELPATH

_GATE = "research/m3a/development_gate_access.jsonl"
_HOLDOUT = "research/m2b/test_evaluations.jsonl"
_REGISTRY = "research/m3b/experiment_registry.jsonl"


def _pristine_tree(root: Path) -> None:
    for rel in (_GATE, _HOLDOUT, _REGISTRY):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


class TestReplayNegativePaths:
    def test_minimal_pristine_tree_is_pristine(self, tmp_path: Path) -> None:
        _pristine_tree(tmp_path)
        state, *_ = check_replay(tmp_path)
        assert state == "pristine"

    def test_nonempty_gate_ledger_is_caught(self, tmp_path: Path) -> None:
        _pristine_tree(tmp_path)
        (tmp_path / _GATE).write_text('{"x": 1}\n')
        with pytest.raises(ReplayError, match="not byte-empty"):
            check_replay(tmp_path)

    def test_artifact_without_registry_is_caught(self, tmp_path: Path) -> None:
        _pristine_tree(tmp_path)
        results = tmp_path / FRACTIONAL_RESULTS_RELPATH
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_bytes(b"{}\n")
        with pytest.raises(ReplayError, match="no run-001 event but artifacts exist"):
            check_replay(tmp_path)
