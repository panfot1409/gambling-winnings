"""Acceptance-audit guard: the report's Section 2 boundary table is honest.

Independent acceptance finding A3 (Class C): ``render_fractional_report``'s
docstring claimed "every reported number is a field of a reconciled fold cell or
a re-derivable aggregate — the renderer computes nothing new", but the Section 2
data-access table's row counts (2221 / 740 / 741) and date ranges are fixed
literals, not fields of any ``FractionalFoldCell`` or aggregate. The literals are
*correct* today (no live data error), so this is an overclaim + latent-decoupling
finding, corrected in the docstring and pinned here.

These standing guards make the decoupling loud:
  * the research-train row count printed in the report must equal the authoritative
    ``RESEARCH_TRAIN_ROWS`` constant (so the report and the walk-forward partition
    can never silently diverge), and
  * the two sealed partitions must be shown as forbidden / not-evaluated (M3B may
    only restate their pre-registered boundaries, never recompute them).

Read-only: renders from the committed results model; evaluates no sealed row.
"""

from __future__ import annotations

from pathlib import Path

import eth_research
from eth_research.fractional.results import (
    FRACTIONAL_REPORT_RELPATH,
    load_fractional_results,
    render_fractional_report,
)
from eth_research.walkforward import RESEARCH_TRAIN_ROWS

REPO = Path(eth_research.__file__).resolve().parents[2]


def _rendered() -> str:
    results = load_fractional_results(str(REPO / "research/m3b/fractional_results.json"))
    return render_fractional_report(results)


def test_rendered_report_is_byte_identical_to_the_committed_report() -> None:
    # Guards that any change to the renderer (including this finding's docstring
    # edit) leaves the published run-001 report byte-for-byte unchanged.
    committed = (REPO / FRACTIONAL_REPORT_RELPATH).read_text(encoding="utf-8")
    assert _rendered() == committed


def test_research_train_row_count_equals_the_authoritative_constant() -> None:
    # The report's research-train count must track the walk-forward partition
    # constant, not a coincidental literal that could silently drift.
    report = _rendered()
    assert f"| research train | 2016-05-23 .. 2022-06-21 | {RESEARCH_TRAIN_ROWS} |" in report


def test_sealed_partitions_are_shown_forbidden_never_evaluated() -> None:
    report = _rendered()
    for level, dates in (
        ("development gate", "2022-06-22 .. 2024-06-30"),
        ("final holdout", "2024-07-01 .. 2026-07-11"),
    ):
        line = next(ln for ln in report.splitlines() if ln.startswith(f"| {level} |"))
        assert dates in line
        assert "**not evaluated (forbidden)**" in line
