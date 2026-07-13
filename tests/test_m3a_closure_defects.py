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
    """The results parser accepts forged nested values and schema versions."""

    def test_forged_results_are_accepted(self) -> None:
        from typing import Any

        from eth_research.development_evaluation import (
            _TOP_LEVEL_KEYS,
            load_development_results_payload,
        )

        forged: dict[str, Any] = dict.fromkeys(_TOP_LEVEL_KEYS, "x")
        forged["development_results_schema_version"] = 999
        forged["fold_results"] = "not-a-list-at-all"
        forged["bootstrap_cells"] = [{"forged": True}]
        forged["development_gate_event_count"] = 0
        forged["final_holdout_event_count"] = 0
        forged["data_access_declaration"] = {"x": "y"}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            p.write_bytes(json.dumps(forged).encode("utf-8"))
            out = load_development_results_payload(p)
        # R3 reproduced: forged schema version and non-list fold_results accepted.
        assert out["development_results_schema_version"] == 999
        assert out["fold_results"] == "not-a-list-at-all"


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
        assert crossing == 116  # R4 reproduced: 116/1097 starts cross a reset seam


class TestR5MissingRunIdentity:
    """The committed results cannot identify their own run."""

    def test_results_have_family_but_no_experiment_id(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "research/m3a/development_results.json").read_bytes()
        )
        assert "experiment_family_id" in payload
        assert "experiment_id" not in payload  # R5 reproduced


class TestR6HistoricalBodiesNotRetained:
    """Only the latest run's bodies exist at HEAD."""

    def test_no_per_experiment_archive_exists_yet(self) -> None:
        assert not (REPO_ROOT / "research/m3a/experiments").exists()  # R6 reproduced


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
