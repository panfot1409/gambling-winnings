"""Independent semantic oracles over the accepted stack (commit: oracle)."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.m3f.oracle import OracleReport, run_oracles
from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def _repo_copy(tmp_path: Path) -> Path:
    shutil.copytree(REPO_ROOT / "research", tmp_path / "research")
    return tmp_path


def _rewrite_json(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    obj = load_canonical_json(path.read_bytes(), path.name)
    mutate(obj)
    path.write_bytes(canonical_json_bytes(obj))


def test_oracles_pass_on_real_repo() -> None:
    report = run_oracles(REPO_ROOT)
    assert report.ok, report.failures
    names = set(report.checks)
    for expected in (
        "m3c_decision_coherent",
        "m3e_base_binds_upstream",
        "m3e_cohort_window",
        "m3e_registry_chain",
        "sealed_ledgers_triple",
        "matches_honest_state",
    ):
        assert expected in names


def test_oracle_detects_incoherent_rejection(tmp_path: Path) -> None:
    root = _repo_copy(tmp_path)

    def flip_all_pass(decision: dict[str, Any]) -> None:
        for criterion in decision["criteria"]:
            criterion["passed"] = True

    _rewrite_json(root / "research/m3c/candidate_decision.json", flip_all_pass)
    report = run_oracles(root)
    assert not report.ok
    assert any(f.startswith("m3c_decision_coherent") for f in report.failures)


def test_oracle_detects_provenance_mismatch(tmp_path: Path) -> None:
    root = _repo_copy(tmp_path)
    target = root / "research/m3d/prospective_manifest.json"
    target.write_bytes(target.read_bytes() + b" ")  # any byte change breaks the hash binding
    report = run_oracles(root)
    assert not report.ok
    assert any(f.startswith("m3e_base_binds_upstream") for f in report.failures)


def test_oracle_detects_cohort_window_mismatch(tmp_path: Path) -> None:
    root = _repo_copy(tmp_path)

    def bump_rows(base: dict[str, Any]) -> None:
        base["row_count"] = base["row_count"] + 1

    _rewrite_json(root / "research/m3e/accepted_base.json", bump_rows)
    report = run_oracles(root)
    assert not report.ok
    assert any(f.startswith("m3e_cohort_window") for f in report.failures)


def test_oracle_detects_broken_registry_chain(tmp_path: Path) -> None:
    root = _repo_copy(tmp_path)
    registry = root / "research/m3e/proposal_registry.jsonl"
    lines = registry.read_text(encoding="utf-8").splitlines()
    # Corrupt the second line's back-pointer (flip one hex digit) without breaking JSON.
    lines[1] = lines[1].replace('"previous_line_sha256":"7c14', '"previous_line_sha256":"0c14')
    registry.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = run_oracles(root)
    assert not report.ok
    assert any(f.startswith("m3e_registry_chain") for f in report.failures)


def test_oracle_report_raise_for_status(tmp_path: Path) -> None:
    root = _repo_copy(tmp_path)
    (root / "research/m2b/test_evaluations.jsonl").write_text("x\n", encoding="utf-8")
    report = run_oracles(root)
    assert not report.ok
    with pytest.raises(M3FValidationError, match="semantic oracle failures"):
        report.raise_for_status()


def test_empty_report_is_ok() -> None:
    assert OracleReport().ok is True
