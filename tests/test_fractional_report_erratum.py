"""The append-only M3B report erratum is complete and machine-verified (R10)."""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.fractional.report_erratum import (
    FRACTIONAL_ERRATA_DIR_RELPATH,
    RUN001_MONOTONICITY_ERRATUM_ID,
    FractionalReportErrataError,
    FractionalReportErratum,
    MonotonicityCounterexample,
    build_run001_monotonicity_erratum,
    derive_monotonicity_counterexamples,
    statement_domain_sha256,
    verify_fractional_report_errata,
)
from eth_research.fractional.results import FRACTIONAL_REPORT_RELPATH

REPO = Path(eth_research.__file__).resolve().parents[2]
_ERRATUM_JSON = f"{FRACTIONAL_ERRATA_DIR_RELPATH}/{RUN001_MONOTONICITY_ERRATUM_ID}.json"


def _copy_m3b(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "research" / "m3b", tmp_path / "research" / "m3b")
    # The erratum verifier also reads the two sealed ledgers (outside research/m3b);
    # recreate them byte-empty so verification reaches the erratum checks.
    for ledger in (
        "research/m3a/development_gate_access.jsonl",
        "research/m2b/test_evaluations.jsonl",
    ):
        path = tmp_path / ledger
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return tmp_path


def test_committed_erratum_verifies() -> None:
    assert verify_fractional_report_errata(REPO) == (RUN001_MONOTONICITY_ERRATUM_ID,)


def test_erratum_records_the_single_complete_counterexample() -> None:
    derived = derive_monotonicity_counterexamples(REPO)
    assert len(derived) == 1
    cx = derived[0]
    assert (cx.strategy, cx.fold_index) == ("donchian_55_20", 1)
    assert cx.lower_friction_scenario == "causal_proxy_base"
    assert cx.higher_friction_scenario == "causal_proxy_stressed"
    assert cx.higher_friction_marked_return > cx.lower_friction_marked_return
    # the committed erratum's declared counterexamples are exactly the derived set
    erratum = build_run001_monotonicity_erratum(REPO)
    assert erratum.counterexamples == derived


def test_overbroad_statement_is_present_verbatim_in_the_report() -> None:
    report = (REPO / FRACTIONAL_REPORT_RELPATH).read_text(encoding="utf-8")
    erratum = build_run001_monotonicity_erratum(REPO)
    assert erratum.erroneous_statement in report


def test_erratum_json_round_trips_canonically() -> None:
    raw = (REPO / _ERRATUM_JSON).read_bytes()
    assert FractionalReportErratum.from_json_bytes(raw).to_canonical_bytes() == raw


def test_tampered_erratum_bytes_are_rejected(tmp_path: Path) -> None:
    root = _copy_m3b(tmp_path)
    victim = root / _ERRATUM_JSON
    victim.write_bytes(victim.read_bytes().replace(b"overbroad", b"0verbroad", 1))
    with pytest.raises(FractionalReportErrataError, match=r"hash != registry|not canonical"):
        verify_fractional_report_errata(root)


def test_orphan_errata_file_is_rejected(tmp_path: Path) -> None:
    root = _copy_m3b(tmp_path)
    (root / FRACTIONAL_ERRATA_DIR_RELPATH / "stray.txt").write_bytes(b"unreferenced\n")
    with pytest.raises(FractionalReportErrataError, match="orphan"):
        verify_fractional_report_errata(root)


def test_a_different_benign_statement_is_rejected() -> None:
    # A forged erratum cannot quote some other true report sentence — the
    # corrected claim is pinned to the one canonical overbroad statement, even
    # when its self-hash is internally consistent.
    erratum = build_run001_monotonicity_erratum(REPO)
    benign = "No alpha is claimed"
    with pytest.raises(FractionalReportErrataError, match="pinned overbroad"):
        dataclasses.replace(
            erratum,
            erroneous_statement=benign,
            erroneous_statement_sha256=statement_domain_sha256(benign),
        )


def test_non_finite_counterexample_return_is_rejected() -> None:
    with pytest.raises(FractionalReportErrataError, match="finite"):
        MonotonicityCounterexample(
            strategy="donchian_55_20",
            fold_index=1,
            lower_friction_scenario="causal_proxy_base",
            higher_friction_scenario="causal_proxy_stressed",
            lower_friction_marked_return=float("nan"),
            higher_friction_marked_return=0.9,
        )
