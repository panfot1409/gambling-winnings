"""Focused checks on the v2 replay dispatch (the full State-B byte reproduction
runs end-to-end in test_m3a_orchestrator_e2e)."""

from __future__ import annotations

from pathlib import Path

import eth_research
from eth_research.replay_m3a_v2 import latest_completed_is_v2, verify_v2_replay

_REPO = Path(eth_research.__file__).resolve().parents[2]


class TestV2Dispatch:
    def test_current_repo_latest_completed_is_v2(self) -> None:
        # run-003 (v2) is the latest completed experiment.
        assert latest_completed_is_v2(_REPO) is True

    def test_v2_replay_reproduces_the_committed_run003(self) -> None:
        # verify_v2_replay regenerates the v2 archive from the committed raw bytes
        # and the recorded commit identities, and byte-compares to the committed
        # aliases + immutable archive; it returns the reproduced experiment id.
        assert verify_v2_replay(_REPO) == "m3a-fixed-baseline-comparison-v2-run-003"
