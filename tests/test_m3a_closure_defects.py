"""Executable reproductions of the Milestone 3A closure defects (R1-R8).

Each test documents a defect exactly as it exists on the starting HEAD. As a
defect is corrected, its reproduction here is inverted (or removed) and a
regression test asserting the fixed behavior is added in the corresponding
module test file; see docs/M3A_BUG_LOG.md.

These are pinned to the *current* behavior so the branch stays green while the
remediation is built incrementally; the point is a permanent, reviewable record
that the defect was real and reproduced before the fix.
"""

from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path

import pytest

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def _module_source(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text("utf-8")


class TestR1RegistryBypass:
    """The public publisher can publish without consulting the registry."""

    def test_publisher_does_not_reference_the_experiment_registry(self) -> None:
        # R1: develop_m3a imports no registry module, so --write cannot enforce
        # that a registered/started experiment exists before publishing.
        tree = ast.parse(_module_source("src/eth_research/develop_m3a.py"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        assert not any("experiment_registry" in m for m in imported), (
            "R1 reproduced only while develop_m3a does not consult the registry; "
            "once the orchestrator enforces registration, invert this test"
        )


class TestR2NonTransactionalPublish:
    """The results+report batch is not atomic and never fsyncs."""

    def test_atomic_write_is_per_file_and_never_fsyncs(self) -> None:
        src = _module_source("src/eth_research/develop_m3a.py")
        assert "def _atomic_write" in src
        # R2: no fsync anywhere in the publisher, and results/report are two
        # independent replaces (a crash between leaves a mixed pair).
        assert "fsync" not in src
        assert src.count("_atomic_write(") >= 2


class TestR3LooseResultsParsing:
    """FIXED: the results parser refuses forged schema versions and containers."""

    def _forged(self, **mut: object) -> Path:
        from eth_research.development_evaluation import _TOP_LEVEL_KEYS

        forged: dict[str, object] = dict.fromkeys(_TOP_LEVEL_KEYS, "x")
        forged["development_gate_event_count"] = 0
        forged["final_holdout_event_count"] = 0
        forged.update(mut)
        p = Path(tempfile.mkdtemp()) / "r.json"
        p.write_bytes(json.dumps(forged).encode("utf-8"))
        return p

    def test_forged_results_are_now_rejected(self) -> None:
        from eth_research.development_evaluation import (
            DevelopmentEvaluationError,
            load_development_results_payload,
        )

        # R3 fixed: schema version, container types, and grid counts are enforced.
        for mut in (
            {"development_results_schema_version": 999},
            {"fold_results": "not-a-list-at-all"},
            {"bootstrap_cells": [{"forged": True}]},
        ):
            with pytest.raises(DevelopmentEvaluationError):
                load_development_results_payload(self._forged(**mut))


class TestR4SeamCrossingBootstrap:
    """v1 moving blocks cross independent-reset fold seams."""

    def test_flat_concatenation_crosses_reset_seams(self) -> None:
        fold_sizes = [226, 225, 225, 225, 225]
        n = sum(fold_sizes)
        block = 30
        # Reset seams are the cumulative fold boundaries (interior only).
        seams = []
        acc = 0
        for s in fold_sizes[:-1]:
            acc += s
            seams.append(acc)
        max_start = n - block + 1
        crossing = 0
        for start in range(max_start):
            end = start + block  # exclusive
            if any(start < seam < end for seam in seams):
                crossing += 1
        assert n == 1126
        assert max_start == 1097
        assert crossing == 116  # R4 reproduced: 116/1097 v1 starts cross a reset seam

    def test_v2_is_fold_stratified_and_cannot_cross_a_seam(self) -> None:
        # R4 fixed: the v2 primary bootstrap draws blocks strictly within a fold
        # and refuses a block longer than the smallest fold.
        import pandas as pd

        from eth_research.bootstrap import BootstrapError
        from eth_research.bootstrap_v2 import (
            FoldAwareBootstrapConfig,
            fold_stratified_moving_block_bootstrap,
        )

        def s(vals: list[float]) -> pd.Series:
            idx = pd.date_range("2020-01-01", periods=len(vals), freq="D", tz="UTC")
            return pd.Series(vals, index=idx)

        with pytest.raises(BootstrapError, match="exceeds the smallest fold length"):
            fold_stratified_moving_block_bootstrap(
                (s([0.01] * 40), s([0.02] * 20)),
                FoldAwareBootstrapConfig(block_length=30),
            )


class TestR5MissingRunIdentity:
    """The committed results cannot identify their own run."""

    def test_results_have_family_but_no_experiment_id(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "research/m3a/development_results.json").read_bytes()
        )
        assert "experiment_family_id" in payload
        assert "experiment_id" not in payload  # R5 reproduced


class TestR6HistoricalBodiesNotRetained:
    """FIXED: every completed experiment now has directly verifiable bytes."""

    def test_per_experiment_archive_exists_and_verifies(self) -> None:
        from eth_research.experiment_archive import verify_experiment_archive

        # R6 fixed: run-001 and run-002 bodies are archived and verified at HEAD,
        # not only recoverable from Git history.
        ids = verify_experiment_archive(REPO_ROOT)
        assert "m3a-fixed-baseline-comparison-v1-run-001" in ids
        assert "m3a-fixed-baseline-comparison-v1-run-002" in ids


class TestR7UnverifiedInstaller:
    """Workflows pipe an unverified installer into a shell."""

    def test_workflows_pipe_curl_into_sh(self) -> None:
        offenders = []
        for wf in ("ci.yml", "m2b-replay.yml", "m3a-replay.yml"):
            text = _module_source(f".github/workflows/{wf}")
            if "curl -LsSf https://astral.sh/uv" in text and "| sh" in text:
                offenders.append(wf)
        assert set(offenders) == {"ci.yml", "m2b-replay.yml", "m3a-replay.yml"}  # R7


class TestR8MisleadingTrainingTerminology:
    """The report calls expanding information sets 'training' rows."""

    def test_report_uses_training_terminology(self) -> None:
        report = (REPO_ROOT / "research/m3a/development_report.md").read_text("utf-8")
        assert "training rows" in report  # R8 reproduced
