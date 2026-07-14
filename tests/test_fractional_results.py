"""Strict, symmetric results model: every number re-derives and round-trips."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pandas as pd
import pytest

from eth_research.fractional.cost_model import SCENARIOS
from eth_research.fractional.protocol import EXPERIMENT_FAMILY, RUN_001_EXPERIMENT_ID
from eth_research.fractional.results import (
    FRACTIONAL_RESULTS_SCHEMA_VERSION,
    FractionalFoldCell,
    FractionalResults,
    ResultsError,
    build_aggregates,
    load_fractional_results,
    render_fractional_report,
)
from eth_research.fractional.strategies import STRATEGY_NAMES
from eth_research.walkforward import OOS_FOLD_COUNT

_SCEN: tuple[str, ...] = tuple(s.name for s in SCENARIOS)
_EPOCH = pd.Timestamp("2020-01-01", tz="UTC")


def _cell(si: int, strategy: str, ci: int, scenario: str, fold: int) -> FractionalFoldCell:
    """A deterministic, constraint-satisfying synthetic fold cell (no engine)."""
    k = si * 37 + ci * 11 + fold * 3
    trades = strategy != "cash"
    marked_return = ((k % 11) - 5) / 20.0  # in [-0.25, 0.25]
    marked_equity = 10_000.0 * (1.0 + marked_return)
    liquidation_equity = marked_equity - float(k % 3)  # <= marked
    exposure = (k % 5) / 4.0 if trades else 0.0
    sharpe = None if not trades else ((k % 9) - 4) / 3.0
    return FractionalFoldCell(
        fold_index=fold,
        strategy=strategy,
        cost_scenario=scenario,
        oos_row_count=226 if fold == 0 else 225,
        oos_first_open_time=_EPOCH + pd.Timedelta(days=fold * 225),
        oos_last_open_time=_EPOCH + pd.Timedelta(days=fold * 225 + 224),
        initial_cash=10_000.0,
        marked_terminal_equity=marked_equity,
        terminal_liquidation_equity=liquidation_equity,
        marked_total_return=marked_return,
        liquidation_total_return=liquidation_equity / 10_000.0 - 1.0,
        annualized_return=marked_return * 0.5,
        annualized_volatility=0.4 + (k % 3) / 10.0,
        sharpe_ratio=sharpe,
        sortino_ratio=sharpe,
        max_drawdown=-((k % 6) / 10.0),  # in [-0.5, 0]
        num_fills=0 if not trades else (k % 4),
        num_partial_fills=0 if not trades else (k % 2),
        total_traded_notional=0.0 if not trades else 100.0 * (k % 4),
        turnover=0.0 if not trades else 0.01 * (k % 4),
        total_fees=0.0 if not trades else 0.1 * (k % 4),
        average_achieved_exposure=exposure,
        time_in_market=exposure,
    )


def _make_cells() -> tuple[FractionalFoldCell, ...]:
    cells: list[FractionalFoldCell] = []
    for fold in range(OOS_FOLD_COUNT):
        for ci, scenario in enumerate(_SCEN):
            for si, strategy in enumerate(STRATEGY_NAMES):
                cells.append(_cell(si, strategy, ci, scenario, fold))
    return tuple(cells)


def _make_results(cells: tuple[FractionalFoldCell, ...]) -> FractionalResults:
    return FractionalResults(
        fractional_results_schema_version=FRACTIONAL_RESULTS_SCHEMA_VERSION,
        experiment_id=RUN_001_EXPERIMENT_ID,
        experiment_family=EXPERIMENT_FAMILY,
        package_version="0.5.0",
        execution_code_commit_sha="b" * 40,
        registered_code_commit_sha="c" * 40,
        execution_source_tree_fingerprint="sha256:" + "d" * 64,
        fractional_protocol_path="research/m3b/fractional_protocol.json",
        fractional_protocol_sha256="e" * 64,
        frozen_m2_dossier_sha256="f" * 64,
        development_partition_sha256="0" * 64,
        research_train_content_fingerprint="ohlcv-fp-v1/sha256:" + "1" * 64,
        strategies=STRATEGY_NAMES,
        cost_scenarios=_SCEN,
        fold_cells=cells,
        aggregates=build_aggregates(cells),
        development_gate_event_count=0,
        final_holdout_event_count=0,
    )


@pytest.fixture(scope="module")
def results() -> FractionalResults:
    return _make_results(_make_cells())


class TestRoundTrip:
    def test_cell_round_trips(self) -> None:
        cell = _cell(0, "cash", 0, "compatibility_v1", 0)
        assert FractionalFoldCell.from_dict(cell.to_dict()) == cell

    def test_bytes_round_trip_is_stable(self, results: FractionalResults) -> None:
        raw = results.to_json_bytes()
        assert FractionalResults.from_json_bytes(raw).to_json_bytes() == raw
        assert FractionalResults.from_json_bytes(raw) == results

    def test_serialization_is_canonical(self, results: FractionalResults) -> None:
        raw = results.to_json_bytes()
        assert raw.endswith(b"\n")
        reencoded = (
            json.dumps(json.loads(raw), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        assert raw == reencoded

    def test_covers_the_full_75_cell_grid(self, results: FractionalResults) -> None:
        assert len(results.fold_cells) == 75
        assert len(results.aggregates) == len(STRATEGY_NAMES) * len(_SCEN)


class TestStrictParsing:
    def test_unknown_top_level_key_is_rejected(self, results: FractionalResults) -> None:
        payload = json.loads(results.to_json_bytes())
        payload["surprise"] = 1
        with pytest.raises(ResultsError, match="keys do not match"):
            FractionalResults.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_unknown_cell_key_is_rejected(self, results: FractionalResults) -> None:
        payload = json.loads(results.to_json_bytes())
        payload["fold_cells"][0]["surprise"] = 1
        with pytest.raises(ResultsError, match="fold cell keys"):
            FractionalResults.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestValidation:
    def test_missing_cell_breaks_the_grid(self, results: FractionalResults) -> None:
        with pytest.raises(ResultsError, match="expected 75 fold cells"):
            dataclasses.replace(results, fold_cells=results.fold_cells[:-1])

    def test_duplicate_cell_breaks_the_grid(self, results: FractionalResults) -> None:
        cells = (results.fold_cells[0], *results.fold_cells[:-1])
        with pytest.raises(ResultsError, match=r"exact .* grid"):
            dataclasses.replace(results, fold_cells=cells)

    def test_tampered_aggregate_fails_rederivation(self, results: FractionalResults) -> None:
        original = results.aggregates[0]
        bad = dataclasses.replace(
            original, median_marked_return=original.median_marked_return + 1.0
        )
        with pytest.raises(ResultsError, match="do not re-derive"):
            dataclasses.replace(results, aggregates=(bad, *results.aggregates[1:]))

    def test_nonzero_sealed_ledger_is_rejected(self, results: FractionalResults) -> None:
        with pytest.raises(ResultsError, match="sealed access ledgers"):
            dataclasses.replace(results, development_gate_event_count=1)

    def test_max_drawdown_out_of_range_is_rejected(self, results: FractionalResults) -> None:
        bad = dataclasses.replace(results.fold_cells[0], max_drawdown=0.5)
        with pytest.raises(ResultsError, match="max_drawdown"):
            dataclasses.replace(results, fold_cells=(bad, *results.fold_cells[1:]))

    def test_liquidation_exceeding_marked_is_rejected(self, results: FractionalResults) -> None:
        c0 = results.fold_cells[0]
        bad = dataclasses.replace(c0, terminal_liquidation_equity=c0.marked_terminal_equity + 10.0)
        with pytest.raises(ResultsError, match="liquidation equity exceeds"):
            dataclasses.replace(results, fold_cells=(bad, *results.fold_cells[1:]))

    def test_wrong_experiment_family_is_rejected(self, results: FractionalResults) -> None:
        with pytest.raises(ResultsError, match="experiment family"):
            dataclasses.replace(results, experiment_family="not-the-family")


class TestReport:
    def test_report_is_deterministic(self, results: FractionalResults) -> None:
        assert render_fractional_report(results) == render_fractional_report(results)

    def test_report_has_every_section_and_disclaimer(self, results: FractionalResults) -> None:
        report = render_fractional_report(results)
        for marker in (
            "# Milestone 3B fractional execution-risk report",
            "not** a profitability claim",
            "## 2. Data-access boundaries",
            "## 5. Full fold grid",
            "remain sealed and byte-empty",
        ):
            assert marker in report
        # every scenario names its own aggregate + grid sub-section (2 headers each)
        for scenario in _SCEN:
            assert report.count(f"### {scenario}") == 2


class TestLoad:
    def test_load_requires_canonical_bytes(
        self, results: FractionalResults, tmp_path: Path
    ) -> None:
        path = tmp_path / "fractional_results.json"
        path.write_bytes(results.to_json_bytes())
        loaded = load_fractional_results(str(path))
        assert loaded == results

    def test_load_rejects_wrong_schema(self, tmp_path: Path) -> None:
        path = tmp_path / "fractional_results.json"
        # Canonically formatted (so it passes the byte-shape gate) but missing
        # every field but one — the strict model must reject the key set.
        canonical = (
            json.dumps({"fractional_results_schema_version": 1}, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        path.write_bytes(canonical)
        with pytest.raises(ResultsError, match="keys do not match"):
            load_fractional_results(str(path))
