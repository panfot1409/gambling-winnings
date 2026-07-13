"""Focused checks on the v2 replay dispatch (the full State-B byte reproduction
runs end-to-end in test_m3a_orchestrator_e2e)."""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.replay_m3a_v2 import ReplayV2Error, latest_completed_is_v2, verify_v2_replay

_REPO = Path(eth_research.__file__).resolve().parents[2]


class TestV2Dispatch:
    def test_current_repo_latest_completed_is_v1(self) -> None:
        # Before run-003, the latest completed experiment is v1 run-002.
        assert latest_completed_is_v2(_REPO) is False

    def test_v2_replay_refuses_when_latest_is_v1(self) -> None:
        # verify_v2_replay must refuse (before any reconstruction) when the latest
        # completed experiment is not v2 — the caller dispatches to the v1 path.
        with pytest.raises(ReplayV2Error, match="not schema v2"):
            verify_v2_replay(_REPO)
