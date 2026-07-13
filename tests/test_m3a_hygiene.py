"""Milestone 3A repository hygiene and firewall-at-rest guarantees.

Committed-artifact checks that hold on every fresh clone: both access ledgers
are byte-empty, only the allowlisted M3A files are tracked, no committed number
comes from the development gate or the final holdout, the three honest
aggregation views are never conflated, and the registry's terminal event binds
the published bytes.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.data.provenance import sha256_bytes
from eth_research.develop_m3a import REPORT_RELPATH, RESULTS_RELPATH, result_bundle_sha256
from eth_research.development import DEVELOPMENT_PARTITION_RELPATH
from eth_research.experiment_registry import EXPERIMENT_REGISTRY_RELPATH, read_registry
from eth_research.walkforward import WALK_FORWARD_PROTOCOL_RELPATH

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_TRAIN_BOUNDARY = pd.Timestamp("2022-06-21", tz="UTC")
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _alias_results() -> dict[str, Any]:
    """The committed compatibility-alias results as a raw dict.

    The alias migrates from schema v1 (run-002) to v2 (run-003) when run-003
    completes; the fold-result / summary / view / declaration substructures keep
    the same JSON shape across versions, so these hygiene checks read the raw
    dict rather than a version-specific parser.
    """
    payload = json.loads((REPO_ROOT / RESULTS_RELPATH).read_bytes())
    assert isinstance(payload, dict)
    return payload


GATE_LEDGER_RELPATH = "research/m3a/development_gate_access.jsonl"
HOLDOUT_LEDGER_RELPATH = "research/m2b/test_evaluations.jsonl"

_ALLOWED_M3A_FILES: frozenset[str] = frozenset(
    {
        "research/m3a/development_partition.json",
        "research/m3a/walk_forward_protocol.json",
        "research/m3a/walk_forward_protocol_v2.json",
        "research/m3a/development_gate_access.jsonl",
        "research/m3a/experiment_registry.jsonl",
        "research/m3a/development_results.json",
        "research/m3a/development_report.md",
        "research/m3a/README.md",
    }
)


def _tracked(prefix: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", prefix],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


class TestAccessLedgersAtRest:
    def test_development_gate_ledger_is_byte_empty(self) -> None:
        path = REPO_ROOT / GATE_LEDGER_RELPATH
        assert path.is_file()
        assert path.read_bytes() == b""

    def test_final_holdout_ledger_is_byte_empty(self) -> None:
        path = REPO_ROOT / HOLDOUT_LEDGER_RELPATH
        assert path.is_file()
        assert path.read_bytes() == b""

    def test_both_ledgers_hash_to_the_empty_digest(self) -> None:
        for rel in (GATE_LEDGER_RELPATH, HOLDOUT_LEDGER_RELPATH):
            assert sha256_bytes((REPO_ROOT / rel).read_bytes()) == EMPTY_SHA


class TestTrackedArtifacts:
    def test_only_allowlisted_m3a_files_are_tracked(self) -> None:
        # Files under research/m3a/experiments/ are the immutable per-experiment
        # archive, verified byte-for-byte against the registry by
        # verify_experiment_archive; only their names/paths are checked here.
        tracked = {
            f for f in _tracked("research/m3a") if not f.startswith("research/m3a/experiments/")
        }
        assert tracked, "expected committed M3A artifacts"
        unexpected = tracked - _ALLOWED_M3A_FILES
        assert unexpected == set(), f"unexpected tracked M3A files: {sorted(unexpected)}"

    def test_archive_files_are_allowlisted_names_only(self) -> None:
        allowed_names = {
            "development_results.json",
            "development_report.md",
            "return_evidence.json",
            "artifact_manifest.json",
        }
        for rel in _tracked("research/m3a/experiments"):
            if rel == "research/m3a/experiments/experiment_index.json":
                continue
            name = rel.rsplit("/", 1)[-1]
            assert name in allowed_names, f"unexpected archive file: {rel}"
            assert ".." not in rel

    def test_no_data_files_under_m3a(self) -> None:
        for pattern in ("research/m3a/*.csv", "research/m3a/*.parquet", "research/m3a/*.pq"):
            assert _tracked(pattern) == [], f"tracked data file {pattern}"

    def test_no_results_files_outside_the_allowlist(self) -> None:
        # A stray second results/report (e.g. a gate or holdout evaluation) must
        # never appear.
        for name in ("gate_results.json", "holdout_results.json", "test_results.json"):
            assert _tracked(f"research/m3a/{name}") == []


class TestNoForbiddenPartitionInResults:
    def test_every_oos_window_ends_within_research_train(self) -> None:
        payload = _alias_results()
        for row in payload["fold_results"]:
            first = pd.Timestamp(row["oos_first_open_time"])
            last = pd.Timestamp(row["oos_last_open_time"])
            assert first <= RESEARCH_TRAIN_BOUNDARY, first
            assert last <= RESEARCH_TRAIN_BOUNDARY, last

    def test_full_train_row_count_is_the_research_train_size(self) -> None:
        payload = _alias_results()
        assert {row["row_count"] for row in payload["full_train_exploratory"]} == {2221}

    def test_results_declare_zero_forbidden_access(self) -> None:
        payload = _alias_results()
        assert payload["development_gate_event_count"] == 0
        assert payload["final_holdout_event_count"] == 0
        decl = payload["data_access_declaration"]
        assert decl["research_train"].startswith("evaluated")
        assert "not evaluated" in decl["development_gate"]
        assert "not evaluated" in decl["final_holdout"]

    def test_report_marks_gate_and_holdout_not_evaluated(self) -> None:
        report = (REPO_ROOT / REPORT_RELPATH).read_text("utf-8")
        assert "not evaluated (forbidden)" in report
        # The development-gate and final-holdout date ranges appear only in the
        # boundaries table, tagged not-evaluated — never as a performance row.
        assert "2024-07-01" in report  # holdout boundary, disclosed as forbidden
        assert "**not evaluated (forbidden)**" in report


class TestHonestViewsNeverConflated:
    def test_report_presents_diagnostics_with_honest_caveats(self) -> None:
        # The corrected v2 run-003 report presents the fold-aware bootstrap and
        # the pooled reset-OOS diagnostics as distinct sections and carries the
        # honest caveats; it claims no alpha and promotes no candidate.
        report = (REPO_ROOT / REPORT_RELPATH).read_text("utf-8")
        assert "Corrected fold-aware bootstrap (v2)" in report
        assert "Pooled reset-OOS diagnostics" in report
        assert "Honest finding" in report
        assert "in-sample" in report
        assert "No alpha is claimed" in report
        assert "No candidate is promoted" in report

    def test_results_keep_the_three_views_in_separate_arrays(self) -> None:
        payload = _alias_results()
        assert len(payload["independent_fold_summaries"]) == 12
        assert len(payload["pooled_reset_oos"]) == 12
        assert len(payload["full_train_exploratory"]) == 12


class TestRegistryBindsPublishedBytes:
    """The latest completed experiment binds the currently committed files.
    Earlier experiments (a superseded run whose report was later corrected)
    remain in the append-only registry as history."""

    def _latest_completed(self) -> tuple[Any, Any]:
        events = read_registry(REPO_ROOT / EXPERIMENT_REGISTRY_RELPATH)
        completed = [e for e in events if e.event == "completed"]
        assert completed, "no completed experiment in the registry"
        latest = completed[-1]
        registered = next(
            e for e in events if e.event == "registered" and e.experiment_id == latest.experiment_id
        )
        return latest, registered

    def test_completed_event_binds_the_committed_results_and_report(self) -> None:
        completed, _registered = self._latest_completed()
        results_bytes = (REPO_ROOT / RESULTS_RELPATH).read_bytes()
        report_text = (REPO_ROOT / REPORT_RELPATH).read_text("utf-8")
        assert completed.results_json_sha256 == sha256_bytes(results_bytes)
        assert completed.report_markdown_sha256 == sha256_bytes(report_text.encode("utf-8"))
        assert completed.result_bundle_sha256 == result_bundle_sha256(results_bytes, report_text)

    def test_results_provenance_agrees_with_registration(self) -> None:
        _completed, registered = self._latest_completed()
        payload = _alias_results()
        # v2 alias (run-003): distinct commit-identity fields (N8) — the
        # execution-source commit and methodology-freeze commit carried in the
        # results equal the registered event's execution and registered commits.
        assert payload["execution_source_commit_sha"] == registered.execution_code_commit_sha
        assert payload["methodology_freeze_commit_sha"] == registered.registered_code_commit_sha
        assert payload["experiment_family_id"] == registered.experiment_family
        assert payload["development_partition_sha256"] == registered.development_partition_sha256
        assert payload["methodology_id"] == registered.methodology_id


class TestPartitionProtocolCrossBinding:
    def test_protocol_binds_the_committed_partition(self) -> None:
        from eth_research.data.provenance import sha256_file
        from eth_research.walkforward import load_walk_forward_protocol

        protocol = load_walk_forward_protocol(REPO_ROOT / WALK_FORWARD_PROTOCOL_RELPATH)
        partition_sha = sha256_file(REPO_ROOT / DEVELOPMENT_PARTITION_RELPATH)
        assert protocol.development_partition_sha256 == partition_sha

    def test_partition_binds_the_frozen_m2_dossier(self) -> None:
        from eth_research.data.provenance import sha256_file
        from eth_research.development import load_development_partition

        partition = load_development_partition(REPO_ROOT / DEVELOPMENT_PARTITION_RELPATH)
        dossier_sha = sha256_file(REPO_ROOT / "research/m2b/frozen_dossier.json")
        assert partition.frozen_m2_dossier_sha256 == dossier_sha
