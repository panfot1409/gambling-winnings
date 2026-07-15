"""Independent-acceptance hardening: governance-doc binding, strict timestamps,
ascending fold order, and the replay ledger symlink guard.

Covers the fixes reproduced from the three independent auditors (see
docs/M3C_BUG_LOG.md, "Independent acceptance"): the budget/lineage were bound by SHA
only; fold-cell / registry timestamps were parsed leniently; the numerics allowlist
keyed paired_comparisons by position while the model left the order unpinned; and the
replay ledger check lacked the orchestrator's symlink guard.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from eth_research.m3c.candidate import build_research_budget
from eth_research.m3c.lineage import build_m3c_lineage
from eth_research.m3c.replay import M3CReplayError, _require_ledgers_byte_empty
from eth_research.m3c.results import M3CFoldCell, M3CResults, M3CResultsError
from eth_research.m3c.validation import canonical_json_bytes

REPO = Path(__file__).resolve().parents[1]
_RESULTS = REPO / "research/m3c/candidate_results.json"


def test_committed_governance_docs_are_the_one_canonical_pair() -> None:
    # The committed budget/lineage must BE the canonical governance documents, not merely
    # hash to a registered digest (a lying-but-consistent file is otherwise invisible).
    budget = (REPO / "research/m3c/research_budget.json").read_bytes()
    lineage = (REPO / "research/m3c/research_lineage.json").read_bytes()
    assert canonical_json_bytes(build_research_budget().to_dict()) == budget
    assert canonical_json_bytes(build_m3c_lineage().to_dict()) == lineage


def _a_committed_fold_cell() -> dict[str, object]:
    return copy.deepcopy(json.loads(_RESULTS.read_bytes())["fold_cells"][0])


def test_fold_cell_rejects_naive_timestamp() -> None:
    cell = _a_committed_fold_cell()
    cell["oos_first_open_time"] = "2019-05-23T00:00:00"  # tz-naive
    with pytest.raises((ValueError, M3CResultsError)):
        M3CFoldCell.from_dict(cell)


def test_fold_cell_rejects_non_utc_offset() -> None:
    cell = _a_committed_fold_cell()
    cell["oos_first_open_time"] = "2019-05-23T00:00:00+05:00"  # aware but not UTC
    with pytest.raises((ValueError, M3CResultsError)):
        M3CFoldCell.from_dict(cell)


def test_fold_cell_accepts_the_committed_utc_timestamp() -> None:
    # Sanity: the strict parse is output-neutral for the real committed value.
    M3CFoldCell.from_dict(_a_committed_fold_cell())


def test_results_reject_reordered_paired_comparisons() -> None:
    payload = json.loads(_RESULTS.read_bytes())
    payload["paired_comparisons"][0], payload["paired_comparisons"][1] = (
        payload["paired_comparisons"][1],
        payload["paired_comparisons"][0],
    )
    with pytest.raises(M3CResultsError):
        M3CResults.from_json_bytes(canonical_json_bytes(payload))


def test_replay_rejects_a_symlinked_sealed_ledger(tmp_path: Path) -> None:
    (tmp_path / "research/m3a").mkdir(parents=True)
    (tmp_path / "research/m2b").mkdir(parents=True)
    empty = tmp_path / "elsewhere_empty.jsonl"
    empty.write_bytes(b"")
    # gate ledger is a symlink to an (empty) file: byte-content passes but the link must not
    (tmp_path / "research/m3a/development_gate_access.jsonl").symlink_to(empty)
    (tmp_path / "research/m2b/test_evaluations.jsonl").write_bytes(b"")
    with pytest.raises(M3CReplayError):
        _require_ledgers_byte_empty(tmp_path)
