"""Benchmark protocol and result models: pinned values, strict parsing."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pandas as pd
import pytest

from conftest import CoinbasePipeline
from eth_research.data.lock import DatasetLock, build_dataset_lock
from eth_research.protocol import (
    ACCOUNTING,
    INITIAL_CASH,
    SMA_CONTEXT_BARS,
    BenchmarkProtocol,
    BenchmarkResults,
    ProtocolError,
    QualityWarningSummary,
    SegmentMetrics,
    SplitBoundary,
    build_benchmark_protocol,
    load_benchmark_protocol,
    verify_protocol,
)

DAY = pd.Timedelta(days=1)


def make_lock(pipeline: CoinbasePipeline) -> DatasetLock:
    return build_dataset_lock(
        pipeline.build.manifest,
        manifest_sha256=pipeline.manifest_sha256,
        acquisition_evidence_sha256=pipeline.evidence_sha256,
    )


class TestBenchmarkProtocol:
    def test_round_trip_is_byte_identical(self, coinbase_pipeline: CoinbasePipeline) -> None:
        protocol = build_benchmark_protocol(make_lock(coinbase_pipeline), package_version="0.3.0")
        raw = protocol.to_json_bytes()
        parsed = BenchmarkProtocol.from_json_bytes(raw)
        assert parsed == protocol
        assert parsed.to_json_bytes() == raw

    def test_verify_against_its_lock_passes(self, coinbase_pipeline: CoinbasePipeline) -> None:
        lock = make_lock(coinbase_pipeline)
        protocol = build_benchmark_protocol(lock, package_version="0.3.0")
        verify_protocol(protocol, lock)

    def test_verify_against_a_different_lock_fails(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        lock = make_lock(coinbase_pipeline)
        protocol = build_benchmark_protocol(lock, package_version="0.3.0")
        other = dataclasses.replace(lock, quote_asset="EUR")
        with pytest.raises(ProtocolError, match="mismatch on dataset_lock_sha256"):
            verify_protocol(protocol, other)

    def _payload(self, pipeline: CoinbasePipeline, **changes: Any) -> dict[str, Any]:
        protocol = build_benchmark_protocol(make_lock(pipeline), package_version="0.3.0")
        payload: dict[str, Any] = json.loads(protocol.to_json_bytes().decode("utf-8"))
        payload.update(changes)
        return payload

    def _parse(self, payload: dict[str, Any]) -> BenchmarkProtocol:
        return BenchmarkProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("train_fraction", 0.5),
            ("validation_fraction", 0.25),
            ("initial_cash", 5000.0),
            ("fee_rate", 0.002),
            ("slippage_rate", -0.0005),
            ("sma_context_bars", 49),
            ("buy_and_hold_context_bars", 1),
            ("risk_free_rate", 0.01),
            ("split_semantics", "positional-ceil-v1"),
            ("accounting", "stitched-portfolio"),
            ("annualization", "252-day-year"),
        ],
    )
    def test_unpinned_values_are_rejected(
        self, coinbase_pipeline: CoinbasePipeline, field: str, value: Any
    ) -> None:
        payload = self._payload(coinbase_pipeline, **{field: value})
        with pytest.raises(ValueError, match="pinned"):
            self._parse(payload)

    def test_boolean_cost_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(coinbase_pipeline, fee_rate=True)
        with pytest.raises(ValueError, match="bool is rejected"):
            self._parse(payload)

    def test_nan_literal_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        protocol = build_benchmark_protocol(make_lock(coinbase_pipeline), package_version="0.3.0")
        raw = protocol.to_json_bytes().replace(b'"train_fraction": 0.6', b'"train_fraction": NaN')
        with pytest.raises(ValueError, match="non-finite JSON constant"):
            BenchmarkProtocol.from_json_bytes(raw)

    def test_duplicate_strategies_are_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(coinbase_pipeline)
        payload["strategies"] = [{"name": "buy_and_hold"}, {"name": "buy_and_hold"}]
        with pytest.raises(ValueError, match="strategies are pinned"):
            self._parse(payload)

    def test_reordered_strategies_are_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(coinbase_pipeline)
        payload["strategies"] = list(reversed(payload["strategies"]))
        with pytest.raises(ValueError, match="strategies are pinned"):
            self._parse(payload)

    def test_extra_strategy_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(coinbase_pipeline)
        payload["strategies"].append({"name": "buy_and_hold"})
        with pytest.raises(ValueError, match="strategies are pinned"):
            self._parse(payload)

    def test_unknown_strategy_name_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(coinbase_pipeline)
        payload["strategies"][0] = {"name": "momentum"}
        with pytest.raises(ValueError, match="unsupported strategy 'momentum'"):
            self._parse(payload)

    def test_changed_sma_windows_are_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(coinbase_pipeline)
        payload["strategies"][1]["fast_window"] = 10
        with pytest.raises(ValueError, match="fast_window is pinned"):
            self._parse(payload)

    def test_parameters_on_buy_and_hold_are_rejected(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        payload = self._payload(coinbase_pipeline)
        payload["strategies"][0] = {"name": "buy_and_hold", "fast_window": 5}
        with pytest.raises(ValueError, match=r"unknown=\['fast_window'\]"):
            self._parse(payload)

    def test_altered_metric_list_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(coinbase_pipeline)
        payload["metrics"] = payload["metrics"][:-1]
        with pytest.raises(ValueError, match="metrics are pinned"):
            self._parse(payload)

    def test_unknown_key_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(coinbase_pipeline, optimizer="grid-search")
        with pytest.raises(ValueError, match=r"unknown=\['optimizer'\]"):
            self._parse(payload)

    def test_missing_key_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(coinbase_pipeline)
        del payload["fee_rate"]
        with pytest.raises(ValueError, match=r"missing=\['fee_rate'\]"):
            self._parse(payload)

    def test_load_wraps_errors(self, coinbase_pipeline: CoinbasePipeline) -> None:
        target = coinbase_pipeline.evidence_path.parent / "protocol.json"
        target.write_bytes(b"[]")
        with pytest.raises(ProtocolError, match="invalid benchmark protocol"):
            load_benchmark_protocol(target)


START = pd.Timestamp("2024-01-01", tz="UTC")


def segment_metrics(
    strategy: str,
    segment: str,
    first_open: pd.Timestamp,
    n_bars: int,
    *,
    sharpe: float | None = 0.5,
) -> SegmentMetrics:
    context = 0
    if strategy == "sma_20_50" and segment != "train":
        context = SMA_CONTEXT_BARS
    return SegmentMetrics(
        strategy=strategy,
        segment=segment,
        n_bars=n_bars,
        start_time=first_open,
        end_time=first_open + n_bars * DAY,
        context_bars=context,
        initial_cash=INITIAL_CASH,
        terminal_equity=10_500.0,
        terminal_liquidation_equity=10_480.0,
        total_return=0.05,
        cagr=0.2,
        sharpe=sharpe,
        sortino=0.7,
        max_drawdown=-0.1,
        total_traded_notional=9_990.0,
        turnover=0.999,
        num_fills=1,
    )


def make_results(
    *,
    include_test: bool = True,
    test_evaluation_id: str | None = "test-eval-0001",
    sharpe: float | None = 0.5,
) -> BenchmarkResults:
    train = SplitBoundary(
        segment="train", first_open_time=START, last_open_time=START + 5 * DAY, n_bars=6
    )
    validation = SplitBoundary(
        segment="validation",
        first_open_time=START + 6 * DAY,
        last_open_time=START + 7 * DAY,
        n_bars=2,
    )
    test = SplitBoundary(
        segment="test",
        first_open_time=START + 8 * DAY,
        last_open_time=START + 9 * DAY,
        n_bars=2,
    )
    segment_names = ["train", "validation", "test"] if include_test else ["train", "validation"]
    boundaries = {"train": train, "validation": validation, "test": test}
    segments = tuple(
        segment_metrics(
            strategy,
            name,
            boundaries[name].first_open_time,
            boundaries[name].n_bars,
            sharpe=sharpe,
        )
        for strategy in ("buy_and_hold", "sma_20_50")
        for name in segment_names
    )
    return BenchmarkResults(
        results_schema_version=1,
        package_version="0.3.0",
        base_asset="ETH",
        quote_asset="USD",
        symbol="ETH-USD",
        venue="coinbase-exchange",
        market_type="spot",
        candle_interval=DAY,
        dataset_content_fingerprint="sha256:" + "1" * 64,
        dataset_manifest_sha256="2" * 64,
        dataset_lock_sha256="3" * 64,
        quality_report_sha256="4" * 64,
        acquisition_evidence_sha256="5" * 64,
        protocol_sha256="6" * 64,
        pre_registered_commit_sha="a" * 40,
        dataset_row_count=10,
        dataset_first_open_time=START,
        dataset_last_open_time=START + 9 * DAY,
        quality_warnings=(
            QualityWarningSummary(code="zero_volume", count=2, first_examples=("row 3", "row 7")),
        ),
        splits=(train, validation, test),
        segments=segments,
        accounting=ACCOUNTING,
        test_evaluation_id=test_evaluation_id if include_test else None,
    )


class TestBenchmarkResults:
    def test_round_trip_is_byte_identical(self) -> None:
        results = make_results()
        raw = results.to_json_bytes()
        parsed = BenchmarkResults.from_json_bytes(raw)
        assert parsed == results
        assert parsed.to_json_bytes() == raw

    def test_train_validation_only_results_are_valid(self) -> None:
        results = make_results(include_test=False)
        assert results.test_evaluation_id is None
        assert BenchmarkResults.from_json_bytes(results.to_json_bytes()) == results

    def test_undefined_sharpe_serializes_as_json_null(self) -> None:
        results = make_results(sharpe=None)
        raw = results.to_json_bytes()
        assert b'"sharpe": null' in raw
        assert b"NaN" not in raw
        assert BenchmarkResults.from_json_bytes(raw).segments[0].sharpe is None

    def test_nan_metric_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="sharpe must be finite"):
            make_results(sharpe=float("nan"))

    def test_nan_literal_in_json_is_rejected(self) -> None:
        raw = (
            make_results().to_json_bytes().replace(b'"total_return": 0.05', b'"total_return": NaN')
        )
        with pytest.raises(ValueError, match="non-finite JSON constant"):
            BenchmarkResults.from_json_bytes(raw)

    def test_missing_test_evaluation_id_with_test_segments_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="test_evaluation_id must be a string"):
            make_results(test_evaluation_id=None)

    def test_test_evaluation_id_without_test_segments_is_rejected(self) -> None:
        results = make_results(include_test=False)
        with pytest.raises(ValueError, match="must be null when no test segment"):
            dataclasses.replace(results, test_evaluation_id="test-eval-0001")

    @pytest.mark.parametrize("identifier", ["short", "UPPER-CASE-ID", "-leading-dash"])
    def test_malformed_test_evaluation_id_is_rejected(self, identifier: str) -> None:
        with pytest.raises(ValueError, match="test_evaluation_id must match"):
            make_results(test_evaluation_id=identifier)

    def test_non_canonical_segment_order_is_rejected(self) -> None:
        results = make_results()
        swapped = results.segments[3:] + results.segments[:3]
        with pytest.raises(ValueError, match="canonical strategy-major order"):
            dataclasses.replace(results, segments=swapped)

    def test_segment_reversal_is_rejected(self) -> None:
        results = make_results()
        with pytest.raises(ValueError, match="segments must cover"):
            dataclasses.replace(results, segments=tuple(reversed(results.segments)))

    def test_asymmetric_strategy_coverage_is_rejected(self) -> None:
        results = make_results()
        with pytest.raises(ValueError, match="same segments"):
            dataclasses.replace(results, segments=results.segments[:-1])

    def test_single_strategy_results_are_rejected(self) -> None:
        results = make_results()
        with pytest.raises(ValueError, match="cover exactly the strategies"):
            dataclasses.replace(results, segments=results.segments[:3])

    def test_segment_boundary_disagreeing_with_split_is_rejected(self) -> None:
        results = make_results()
        shifted = dataclasses.replace(
            results.segments[0],
            start_time=results.segments[0].start_time + DAY,
            end_time=results.segments[0].end_time + DAY,
        )
        with pytest.raises(ValueError, match="expected the split's first open"):
            dataclasses.replace(results, segments=(shifted, *results.segments[1:]))

    def test_split_bar_counts_must_sum_to_row_count(self) -> None:
        results = make_results()
        with pytest.raises(ValueError, match="sum to the dataset row count"):
            dataclasses.replace(results, dataset_row_count=11)

    def test_non_contiguous_splits_are_rejected(self) -> None:
        results = make_results()
        gapped = dataclasses.replace(
            results.splits[1],
            first_open_time=results.splits[1].first_open_time + DAY,
            last_open_time=results.splits[1].last_open_time + DAY,
        )
        with pytest.raises(ValueError, match="contiguous"):
            dataclasses.replace(results, splits=(results.splits[0], gapped, results.splits[2]))

    def test_pinned_context_bars_are_enforced(self) -> None:
        results = make_results()
        sma_validation = results.segments[4]
        assert (sma_validation.strategy, sma_validation.segment) == ("sma_20_50", "validation")
        with pytest.raises(ValueError, match="context_bars for 'sma_20_50'"):
            dataclasses.replace(sma_validation, context_bars=49)

    def test_unsorted_quality_warnings_are_rejected(self) -> None:
        results = make_results()
        warnings = (
            QualityWarningSummary(code="zzz", count=1, first_examples=()),
            QualityWarningSummary(code="aaa", count=1, first_examples=()),
        )
        with pytest.raises(ValueError, match="sorted by code"):
            dataclasses.replace(results, quality_warnings=warnings)

    @pytest.mark.parametrize("sha", ["ABC", "a" * 39, "g" * 40])
    def test_malformed_commit_sha_is_rejected(self, sha: str) -> None:
        results = make_results()
        with pytest.raises(ValueError, match="pre_registered_commit_sha"):
            dataclasses.replace(results, pre_registered_commit_sha=sha)

    def test_unknown_segment_key_is_rejected(self) -> None:
        results = make_results()
        payload: dict[str, Any] = json.loads(results.to_json_bytes().decode("utf-8"))
        payload["segments"][0]["alpha"] = 1.5
        with pytest.raises(ValueError, match=r"unknown=\['alpha'\]"):
            BenchmarkResults.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_boolean_n_bars_is_rejected(self) -> None:
        results = make_results()
        payload: dict[str, Any] = json.loads(results.to_json_bytes().decode("utf-8"))
        payload["segments"][0]["n_bars"] = True
        with pytest.raises(ValueError, match="bool is rejected"):
            BenchmarkResults.from_json_bytes(json.dumps(payload).encode("utf-8"))
