"""Tests for the cumulative research-debt register.

Confirms the derived debt state reconciles (ten primary family evaluations, the closed qualitative
levels, three sealed partitions still untouched), reproduces byte-for-byte, and that verification
refuses a forged closure status, a broken evaluation count, and any recorded sealed access.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from eth_research.v2ab import research_debt as rd

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _clone(tmp_path: Path) -> Path:
    dst = tmp_path / "repo"
    shutil.copytree(_REPO_ROOT / "research", dst / "research")
    return dst


# --------------------------------------------------------------------------- #
# clean-state guarantees                                                       #
# --------------------------------------------------------------------------- #
def test_verify_is_clean_on_committed_tree() -> None:
    assert rd.verify_research_debt(_REPO_ROOT) == []


def test_state_counts_reconcile() -> None:
    state = rd.ResearchDebtState.current(_REPO_ROOT)
    assert state.primary_family_evaluations == 10
    assert state.historical_candidate_families == 8
    assert state.v2a_candidate_families == 3
    assert state.v2b_candidate_families == 2
    assert state.diagnostic_neighborhoods == 12
    assert state.adaptive_research_milestones == 5
    assert state.result_reports_reviewed == 5
    assert state.sealed_partitions_remaining == 3
    assert len(state.unresolved_researcher_degrees_of_freedom) == 5
    assert state.data_sources_used == ("btc_usd_daily", "eth_usd_daily")


def test_closure_is_qualitative_and_terminal() -> None:
    state = rd.ResearchDebtState.current(_REPO_ROOT)
    assert state.closure_status == "closed_to_further_research"
    assert state.closure_status in rd.CLOSURE_LEVELS
    assert state.pre_closure_pressure_level == "high"
    assert state.prospective_data_status == "unavailable_pending_forward_collection"


def test_state_reproduces_byte_for_byte() -> None:
    committed = (_REPO_ROOT / rd.RESEARCH_DEBT_RELPATH).read_bytes()
    assert committed == rd.build_research_debt_state_bytes(_REPO_ROOT)


def test_canonical_document_carries_the_expected_keys() -> None:
    doc = rd.ResearchDebtState.current(_REPO_ROOT).to_canonical()
    for key in (
        "partitions_repeatedly_observed",
        "primary_family_evaluations",
        "diagnostic_neighborhoods",
        "result_reports_reviewed",
        "adaptive_research_milestones",
        "unresolved_researcher_degrees_of_freedom",
        "data_sources_used",
        "sealed_partitions_remaining",
        "prospective_data_status",
        "closure_status",
    ):
        assert key in doc


# --------------------------------------------------------------------------- #
# adversarial                                                                  #
# --------------------------------------------------------------------------- #
def test_missing_state_is_flagged(tmp_path: Path) -> None:
    problems = rd.verify_research_debt(tmp_path)
    assert any("missing" in p for p in problems)


def test_forged_closure_status_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    path = root / rd.RESEARCH_DEBT_RELPATH
    path.write_bytes(path.read_bytes().replace(b"closed_to_further_research", b"low"))
    assert any("closure" in p for p in rd.verify_research_debt(root))


def test_broken_evaluation_count_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    path = root / rd.RESEARCH_DEBT_RELPATH
    path.write_bytes(
        path.read_bytes().replace(
            b'"primary_family_evaluations": 10', b'"primary_family_evaluations": 9'
        )
    )
    problems = rd.verify_research_debt(root)
    assert any("primary_family_evaluations" in p or "reconcile" in p for p in problems)


def test_recorded_sealed_access_is_rejected(tmp_path: Path) -> None:
    root = _clone(tmp_path)
    (root / rd.SEALED_LEDGER_RELPATHS[0]).write_bytes(b'{"accessed":true}\n')
    problems = rd.verify_research_debt(root)
    assert any("byte-empty" in p for p in problems)
