"""Standing hygiene gates for the Milestone 3B fractional laboratory.

Enforces, as a permanent test, the M3B scope boundaries: the fractional package
imports only an allowlist (no ML, optimizer, network, wallet, or exchange code);
both sealed access ledgers stay byte-empty; only the expected M3B artifacts are
tracked (no stray data or results); and the published run is long-only, declares
zero forbidden access, and its report discloses the sealed partitions.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from eth_research.data.provenance import sha256_file
from eth_research.fractional.archive import FRACTIONAL_MANIFEST_RELPATH, verify_published_run
from eth_research.fractional.archive_v2 import FRACTIONAL_ARCHIVE_V2_TRACKED
from eth_research.fractional.artifact_annotations import ARTIFACT_ANNOTATIONS_RELPATH
from eth_research.fractional.execution_trace import EXECUTION_TRACE_COMMITMENTS_RELPATH
from eth_research.fractional.legacy_completion_audit import FRACTIONAL_LEGACY_AUDIT_RELPATH
from eth_research.fractional.protocol import FRACTIONAL_PROTOCOL_RELPATH
from eth_research.fractional.report_erratum import FRACTIONAL_ERRATA_TRACKED
from eth_research.fractional.registry import M3B_REGISTRY_RELPATH, read_registry
from eth_research.fractional.results import (
    FRACTIONAL_REPORT_RELPATH,
    FRACTIONAL_RESULTS_RELPATH,
    load_fractional_results,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
_FRACTIONAL_DIR = REPO_ROOT / "src" / "eth_research" / "fractional"
_EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_GATE_LEDGER = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER = "research/m2b/test_evaluations.jsonl"

# The fractional package may import only these roots: stdlib, the numeric stack,
# and the package itself. Anything else — an ML library, an optimizer, a network
# or exchange client — is a scope violation and fails this gate.
_ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "__future__",
        "argparse",
        "base64",
        "binascii",
        "collections",
        "dataclasses",
        "itertools",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "statistics",
        "sys",
        "tempfile",
        "typing",
        "numpy",
        "pandas",
        "pyarrow",
        "eth_research",
    }
)

_ALLOWED_M3B_TRACKED: frozenset[str] = frozenset(
    {
        FRACTIONAL_PROTOCOL_RELPATH,
        FRACTIONAL_RESULTS_RELPATH,
        FRACTIONAL_REPORT_RELPATH,
        FRACTIONAL_MANIFEST_RELPATH,
        M3B_REGISTRY_RELPATH,
        FRACTIONAL_LEGACY_AUDIT_RELPATH,
        EXECUTION_TRACE_COMMITMENTS_RELPATH,
        ARTIFACT_ANNOTATIONS_RELPATH,
        *FRACTIONAL_ARCHIVE_V2_TRACKED,
        *FRACTIONAL_ERRATA_TRACKED,
    }
)


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _tracked(prefix: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", prefix],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


class TestPackageHygiene:
    def test_fractional_imports_are_allowlisted(self) -> None:
        offenders: dict[str, set[str]] = {}
        for path in sorted(_FRACTIONAL_DIR.glob("*.py")):
            extra = _import_roots(path) - _ALLOWED_IMPORT_ROOTS
            if extra:
                offenders[path.name] = extra
        assert offenders == {}, f"non-allowlisted imports in the fractional package: {offenders}"


class TestSealedLedgers:
    @pytest.mark.parametrize("ledger", [_GATE_LEDGER, _HOLDOUT_LEDGER])
    def test_sealed_ledger_is_byte_empty(self, ledger: str) -> None:
        assert sha256_file(REPO_ROOT / ledger) == _EMPTY_SHA


class TestTrackedArtifacts:
    def test_only_allowlisted_m3b_files_are_tracked(self) -> None:
        tracked = set(_tracked("research/m3b"))
        unexpected = tracked - _ALLOWED_M3B_TRACKED
        assert unexpected == set(), f"unexpected tracked M3B files: {sorted(unexpected)}"

    def test_no_data_files_under_m3b(self) -> None:
        data = [f for f in _tracked("research/m3b") if f.endswith((".csv", ".parquet", ".feather"))]
        assert data == [], f"market-data files tracked under research/m3b: {data}"


class TestPublishedRun:
    def test_results_declare_zero_forbidden_access(self) -> None:
        results = load_fractional_results(str(REPO_ROOT / FRACTIONAL_RESULTS_RELPATH))
        assert results.development_gate_event_count == 0
        assert results.final_holdout_event_count == 0

    def test_published_run_is_long_only(self) -> None:
        results = load_fractional_results(str(REPO_ROOT / FRACTIONAL_RESULTS_RELPATH))
        for cell in results.fold_cells:
            assert -1e-9 <= cell.average_achieved_exposure <= 1.0 + 1e-9
            assert cell.max_drawdown >= -1.0
            assert cell.marked_terminal_equity > 0.0

    def test_report_discloses_the_sealed_partitions(self) -> None:
        report = (REPO_ROOT / FRACTIONAL_REPORT_RELPATH).read_text(encoding="utf-8")
        assert "**not evaluated (forbidden)**" in report
        assert "2024-07-01" in report  # the final-holdout boundary, disclosed

    def test_registry_lifecycle_and_archive_verify(self) -> None:
        events = read_registry(REPO_ROOT / M3B_REGISTRY_RELPATH)
        assert [e.event for e in events] == ["registered", "started", "completed"]
        checks = verify_published_run(REPO_ROOT)
        assert "registry_lifecycle_complete" in checks
        assert "manifest_binds_artifacts_and_registry" in checks
