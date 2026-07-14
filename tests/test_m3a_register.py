"""Focused refusals for the run-003 registration CLI.

The successful --append path, the registry-only R commit, and the E..R diff are
exercised end-to-end in test_m3a_orchestrator_e2e; these are the cheap,
tree-independent guards that this tool registers *only* run-003 correcting
run-002 and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.m3a_register import (
    RUN_003_CORRECTS,
    RUN_003_EXPERIMENT_ID,
    RegistrationError,
    build_run003_registration,
)

_REPO = Path(eth_research.__file__).resolve().parents[2]


class TestRegistrationRefusals:
    def test_refuses_a_foreign_experiment_id(self) -> None:
        with pytest.raises(RegistrationError, match="registers only"):
            build_run003_registration(_REPO, experiment_id="m3a-some-other-experiment-001")

    def test_refuses_a_foreign_correction_parent(self) -> None:
        with pytest.raises(RegistrationError, match="corrects only"):
            build_run003_registration(_REPO, corrects="m3a-some-other-experiment-001")

    def test_constants_match_the_milestone(self) -> None:
        assert RUN_003_EXPERIMENT_ID == "m3a-fixed-baseline-comparison-v2-run-003"
        assert RUN_003_CORRECTS == "m3a-fixed-baseline-comparison-v1-run-002"
