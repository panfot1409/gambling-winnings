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
    """FIXED: the only real-data publication path is the registry-gated orchestrator."""

    def test_no_unregistered_write_path_and_orchestrator_is_used(self) -> None:
        # R1 fixed: the unregistered --write publisher is gone, and real-data
        # publication routes through the fail-closed orchestrator, which
        # consults the experiment registry before any real calculation.
        src = _module_source("src/eth_research/develop_m3a.py")
        assert "--write" not in src
        assert "_atomic_write" not in src
        assert "run_registered_development_experiment" in src
        orchestrator = _module_source("src/eth_research/development_orchestrator.py")
        assert "read_registry" in orchestrator
        assert "append_registry_event" in orchestrator


class TestR2NonTransactionalPublish:
    """FIXED: publication is a durable rollback-safe batch transaction."""

    def test_publisher_uses_the_durable_batch_transaction(self) -> None:
        # R2 fixed: develop_m3a no longer defines the per-file, no-fsync writer.
        dev = _module_source("src/eth_research/develop_m3a.py")
        assert "def _atomic_write" not in dev
        # Publication now runs through the durable, fsynced, rollback-safe batch.
        pub = _module_source("src/eth_research/development_publication.py")
        assert "publish_batch" in pub
        from eth_research import publication

        assert hasattr(publication, "publish_batch")


class TestNoUnregisteredRealDataWritePath:
    """Phase 13: the public CLI exposes no unregistered real-data write path."""

    def test_develop_m3a_main_has_no_write_flag(self) -> None:
        tree = ast.parse(_module_source("src/eth_research/develop_m3a.py"))
        offenders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and node.value == "--write"
        ]
        assert not offenders, "develop_m3a still defines a --write flag"

    def test_publish_batch_is_called_only_from_the_orchestrator_path(self) -> None:
        # The durable publisher is invoked only by the orchestrator's publication
        # module — never from an unguarded CLI path.
        callers = []
        for rel in (
            "src/eth_research/develop_m3a.py",
            "src/eth_research/development_publication.py",
            "src/eth_research/replay_m2b.py",
        ):
            if "publish_batch(" in _module_source(rel):
                callers.append(rel)
        assert callers == ["src/eth_research/development_publication.py"]


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
        payload = json.loads((REPO_ROOT / "research/m3a/development_results.json").read_bytes())
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
    """FIXED (N10): no workflow pipes an unverified installer into a shell."""

    def test_no_workflow_pipes_curl_into_sh(self) -> None:
        # R7/N10 fixed: uv is installed from the hash-pinned PyPI wheel.
        for wf in ("ci.yml", "m2b-replay.yml", "m3a-replay.yml"):
            text = _module_source(f".github/workflows/{wf}")
            assert "install.sh | sh" not in text
            assert "curl -LsSf https://astral.sh/uv" not in text
        pin = (REPO_ROOT / "ci/uv-requirements.txt").read_text("utf-8")
        assert pin.count("--hash=sha256:") >= 1


class TestR8MisleadingTrainingTerminology:
    """The report calls expanding information sets 'training' rows."""

    def test_report_uses_training_terminology(self) -> None:
        report = (REPO_ROOT / "research/m3a/development_report.md").read_text("utf-8")
        assert "training rows" in report  # R8 reproduced
