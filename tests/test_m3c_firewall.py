"""Sealed-partition firewall on the real committed M3C tree (integration).

Complements the unit-level causality/context tests: proves that the research-train
loader exposes only research-train rows (never a development-gate or final-holdout
candle), that the whole read-only verification surface leaves both sealed ledgers
byte-empty, and that the committed candidate never takes leverage or a short.
"""

from __future__ import annotations

from pathlib import Path

from eth_research.data.provenance import sha256_file
from eth_research.development import DEVELOPMENT_PARTITION_RELPATH, load_development_partition
from eth_research.fractional.dataset import verify_dataset_integrity_only
from eth_research.m3c.candidate import M3C_CANDIDATE_ID
from eth_research.m3c.completion import read_completion_intent
from eth_research.m3c.replay import check_replay
from eth_research.m3c.results import load_m3c_results
from eth_research.m3c.verify_archive import verify_m3c_run_archive

REPO = Path(__file__).resolve().parents[1]
_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_GATE_LEDGER = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER = "research/m2b/test_evaluations.jsonl"


def _ledger_shas() -> dict[str, str]:
    return {rel: sha256_file(REPO / rel) for rel in (_GATE_LEDGER, _HOLDOUT_LEDGER)}


def test_research_train_loader_exposes_no_row_beyond_the_partition_boundary() -> None:
    partition = load_development_partition(REPO / DEVELOPMENT_PARTITION_RELPATH)
    boundary = partition.research_train.last_open_time
    research_train = verify_dataset_integrity_only(REPO).research_train
    # Every exposed row is at or before the research-train boundary: no gate/holdout row.
    assert research_train.index.max() <= boundary
    assert (research_train.index <= boundary).all()
    # The exposed row count matches the frozen research-train partition exactly.
    assert len(research_train) == partition.research_train.row_count


def test_sealed_ledgers_are_byte_empty_and_stay_so_across_the_verification_surface() -> None:
    before = _ledger_shas()
    assert before == {_GATE_LEDGER: _EMPTY_SHA256, _HOLDOUT_LEDGER: _EMPTY_SHA256}
    # Exercise the whole read-only surface.
    assert check_replay(REPO)[0] == "completed"
    assert verify_m3c_run_archive(REPO, deep=True)
    assert read_completion_intent(REPO) is None
    # Nothing wrote a sealed row.
    assert _ledger_shas() == before


def test_committed_candidate_never_levers_or_shorts() -> None:
    results = load_m3c_results(REPO / "research/m3c/candidate_results.json")
    candidate_cells = [c for c in results.fold_cells if c.strategy == M3C_CANDIDATE_ID]
    assert candidate_cells
    for cell in candidate_cells:
        # Long-only, unlevered: achieved and requested exposure within [0, 1].
        assert -1e-9 <= cell.average_achieved_exposure <= 1.0 + 1e-9
        assert -1e-9 <= cell.average_requested_exposure <= 1.0 + 1e-9
        # No ruin: terminal equity strictly positive, marked return above total loss.
        assert cell.marked_terminal_equity > 0.0
        assert cell.marked_total_return > -1.0
