"""Strict offline Coinbase adapter and acquisition evidence."""

from __future__ import annotations

import dataclasses
import io
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from eth_research.data import coinbase
from eth_research.data.coinbase import (
    ADAPTER_TRANSFORMATIONS,
    AcquisitionError,
    AcquisitionEvidence,
    ChunkRequest,
    DailyCandle,
    canonical_utc_request,
    derive_daily_ohlcv,
    load_acquisition_evidence,
    parse_candles_chunk,
    verify_acquisition_evidence,
    write_acquisition_evidence,
)
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.data.schema import validate_ohlcv

RETRIEVED = pd.Timestamp("2026-07-11T12:34:56+00:00")


def day(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def epoch_s(text: str) -> int:
    return int(day(text).value) // 10**9


def make_row(date: str, offset: float = 0.0) -> list[Any]:
    """[time, low, high, open, close, volume] — Coinbase field order."""
    return [epoch_s(date), 95.0 + offset, 111.0 + offset, 100.0 + offset, 105.0 + offset, 10.0]


def chunk_bytes(rows: list[list[Any]]) -> bytes:
    return json.dumps(rows).encode("ascii")


def window(start: str, end: str) -> dict[str, pd.Timestamp]:
    return {"window_start": day(start), "window_end": day(end)}


class TestParseCandlesChunk:
    def test_field_mapping_against_literal_hand_data(self) -> None:
        raw = b"[[172800, 90.5, 110.25, 100.0, 105.125, 7.5]]"
        parsed = parse_candles_chunk(
            raw, window_start=day("1970-01-03"), window_end=day("1970-01-04")
        )
        assert parsed.candles == (
            DailyCandle(
                open_time_s=172800, open=100.0, high=110.25, low=90.5, close=105.125, volume=7.5
            ),
        )
        assert parsed.rows_before_window == 0
        assert parsed.row_count == 1

    def test_strictly_descending_is_reversed(self) -> None:
        rows = [make_row("2024-01-03"), make_row("2024-01-02"), make_row("2024-01-01")]
        parsed = parse_candles_chunk(chunk_bytes(rows), **window("2024-01-01", "2024-01-04"))
        times = [candle.open_time_s for candle in parsed.candles]
        assert times == sorted(times)
        assert len(times) == 3

    def test_strictly_ascending_is_accepted(self) -> None:
        rows = [make_row("2024-01-01"), make_row("2024-01-02")]
        parsed = parse_candles_chunk(chunk_bytes(rows), **window("2024-01-01", "2024-01-03"))
        assert [candle.open_time_s for candle in parsed.candles] == [
            epoch_s("2024-01-01"),
            epoch_s("2024-01-02"),
        ]

    def test_shuffled_rows_are_rejected_not_sorted(self) -> None:
        rows = [make_row("2024-01-01"), make_row("2024-01-03"), make_row("2024-01-02")]
        with pytest.raises(AcquisitionError, match="neither strictly ascending nor strictly"):
            parse_candles_chunk(chunk_bytes(rows), **window("2024-01-01", "2024-01-04"))

    @pytest.mark.parametrize("second_offset", [0.0, 5.0])
    def test_duplicate_timestamps_identical_or_conflicting_are_rejected(
        self, second_offset: float
    ) -> None:
        rows = [make_row("2024-01-01"), make_row("2024-01-01", offset=second_offset)]
        with pytest.raises(AcquisitionError, match="neither strictly ascending nor strictly"):
            parse_candles_chunk(chunk_bytes(rows), **window("2024-01-01", "2024-01-03"))

    def test_api_error_object_with_http_success_is_rejected(self) -> None:
        raw = b'{"message": "NotFound"}'
        with pytest.raises(AcquisitionError, match="API error object with message 'NotFound'"):
            parse_candles_chunk(raw, **window("2024-01-01", "2024-01-02"))

    def test_truncated_json_is_rejected(self) -> None:
        raw = chunk_bytes([make_row("2024-01-01")])[:-4]
        with pytest.raises(AcquisitionError, match="not valid JSON"):
            parse_candles_chunk(raw, **window("2024-01-01", "2024-01-02"))

    def test_non_array_scalar_is_rejected(self) -> None:
        with pytest.raises(AcquisitionError, match="top-level array"):
            parse_candles_chunk(b"42", **window("2024-01-01", "2024-01-02"))

    def test_empty_response_is_rejected(self) -> None:
        with pytest.raises(AcquisitionError, match="contains no candles"):
            parse_candles_chunk(b"[]", **window("2024-01-01", "2024-01-02"))

    @pytest.mark.parametrize("width", [5, 7])
    def test_wrong_candle_width_is_rejected(self, width: int) -> None:
        row = make_row("2024-01-01")
        row = row[:width] if width < 6 else [*row, 1.0]
        with pytest.raises(AcquisitionError, match=rf"has {width} fields, expected exactly 6"):
            parse_candles_chunk(chunk_bytes([row]), **window("2024-01-01", "2024-01-02"))

    def test_boolean_timestamp_is_rejected(self) -> None:
        row = [True, 95.0, 111.0, 100.0, 105.0, 10.0]
        with pytest.raises(AcquisitionError, match="time must be a JSON integer"):
            parse_candles_chunk(chunk_bytes([row]), **window("2024-01-01", "2024-01-02"))

    def test_float_timestamp_is_rejected(self) -> None:
        row: list[Any] = make_row("2024-01-01")
        row[0] = float(row[0])
        with pytest.raises(AcquisitionError, match="time must be a JSON integer"):
            parse_candles_chunk(chunk_bytes([row]), **window("2024-01-01", "2024-01-02"))

    def test_boolean_price_is_rejected(self) -> None:
        row: list[Any] = make_row("2024-01-01")
        row[3] = True
        with pytest.raises(AcquisitionError, match="open must be a JSON number"):
            parse_candles_chunk(chunk_bytes([row]), **window("2024-01-01", "2024-01-02"))

    def test_string_number_is_rejected(self) -> None:
        row: list[Any] = make_row("2024-01-01")
        row[4] = "105.0"
        with pytest.raises(AcquisitionError, match="close must be a JSON number"):
            parse_candles_chunk(chunk_bytes([row]), **window("2024-01-01", "2024-01-02"))

    @pytest.mark.parametrize("literal", [b"NaN", b"Infinity", b"-Infinity"])
    def test_nonfinite_json_literals_are_rejected(self, literal: bytes) -> None:
        raw = b"[[86400, " + literal + b", 111.0, 100.0, 105.0, 10.0]]"
        with pytest.raises(AcquisitionError, match="non-finite JSON constant"):
            parse_candles_chunk(raw, **window("1970-01-02", "1970-01-03"))

    @pytest.mark.parametrize(
        "raw",
        [
            b"[[86400, 1e999, 111.0, 100.0, 105.0, 10.0]]",
            b"[[86400, 95.0, 111.0, 100.0, 105.0, 1e999]]",
            b"[[86400, 95.0, 111.0, -1e999, 105.0, 10.0]]",
        ],
    )
    def test_exponent_overflow_to_infinity_is_rejected(self, raw: bytes) -> None:
        # json.loads("1e999") silently overflows to float infinity. The strict
        # decoder now rejects it at decode time; the field-level finiteness
        # check remains as defense in depth. Either layer's message contains
        # "finite".
        with pytest.raises(AcquisitionError, match="finite"):
            parse_candles_chunk(raw, **window("1970-01-02", "1970-01-03"))

    def test_unaligned_epoch_is_rejected(self) -> None:
        row: list[Any] = make_row("2024-01-01")
        row[0] += 1
        with pytest.raises(AcquisitionError, match="not aligned to a 86400-second UTC day"):
            parse_candles_chunk(chunk_bytes([row]), **window("2024-01-01", "2024-01-02"))

    @pytest.mark.parametrize(("field", "value"), [(1, 0.0), (2, -1.0), (3, 0.0), (4, -3.5)])
    def test_non_positive_price_is_rejected(self, field: int, value: float) -> None:
        row: list[Any] = make_row("2024-01-01")
        row[field] = value
        with pytest.raises(AcquisitionError, match="must be positive"):
            parse_candles_chunk(chunk_bytes([row]), **window("2024-01-01", "2024-01-02"))

    def test_negative_volume_is_rejected(self) -> None:
        row: list[Any] = make_row("2024-01-01")
        row[5] = -0.25
        with pytest.raises(AcquisitionError, match="volume must be non-negative"):
            parse_candles_chunk(chunk_bytes([row]), **window("2024-01-01", "2024-01-02"))

    def test_high_below_low_flags_field_order(self) -> None:
        row = [epoch_s("2024-01-01"), 111.0, 95.0, 100.0, 105.0, 10.0]
        with pytest.raises(AcquisitionError, match="field order"):
            parse_candles_chunk(chunk_bytes([row]), **window("2024-01-01", "2024-01-02"))

    def test_pre_window_rows_are_excluded_and_counted(self) -> None:
        rows = [make_row(d) for d in ("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04")]
        parsed = parse_candles_chunk(chunk_bytes(rows), **window("2024-01-03", "2024-01-05"))
        assert parsed.rows_before_window == 2
        assert parsed.row_count == 4
        assert [candle.open_time_s for candle in parsed.candles] == [
            epoch_s("2024-01-03"),
            epoch_s("2024-01-04"),
        ]

    def test_row_at_window_end_is_rejected(self) -> None:
        rows = [make_row("2024-01-01"), make_row("2024-01-02")]
        with pytest.raises(AcquisitionError, match="at or after the declared window end"):
            parse_candles_chunk(chunk_bytes(rows), **window("2024-01-01", "2024-01-02"))

    def test_only_pre_window_rows_is_rejected(self) -> None:
        rows = [make_row("2023-12-30"), make_row("2023-12-31")]
        with pytest.raises(AcquisitionError, match="no candles inside the declared window"):
            parse_candles_chunk(chunk_bytes(rows), **window("2024-01-01", "2024-01-03"))


class TestChunkRequest:
    def test_url_like_path_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="network sources are not supported"):
            ChunkRequest(
                path=Path("https://api.exchange.coinbase.com/x.json"),
                window_start=day("2024-01-01"),
                window_end=day("2024-01-02"),
                requested_start="2024-01-01T00:00:00Z",
                requested_end="2024-01-01T00:00:00Z",
                retrieved_at=RETRIEVED,
            )

    def test_window_wider_than_299_days_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="more than 299 daily buckets"):
            ChunkRequest(
                path=Path("chunk.json"),
                window_start=day("2024-01-01"),
                window_end=day("2024-01-01") + pd.Timedelta(days=300),
                requested_start="x",
                requested_end="y",
                retrieved_at=RETRIEVED,
            )

    def test_misaligned_window_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="day boundary"):
            ChunkRequest(
                path=Path("chunk.json"),
                window_start=day("2024-01-01T12:00:00"),
                window_end=day("2024-01-03"),
                requested_start="x",
                requested_end="y",
                retrieved_at=RETRIEVED,
            )

    def test_naive_retrieved_at_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            ChunkRequest(
                path=Path("chunk.json"),
                window_start=day("2024-01-01"),
                window_end=day("2024-01-03"),
                requested_start=canonical_utc_request(day("2024-01-01")),
                requested_end=canonical_utc_request(day("2024-01-02")),
                retrieved_at=pd.Timestamp("2026-07-11"),
            )


def write_chunks(
    directory: Path, specs: list[tuple[str, str, str, list[list[Any]]]]
) -> list[ChunkRequest]:
    """specs: (filename, window_start, window_end, rows)."""
    requests = []
    for filename, start, end, rows in specs:
        path = directory / filename
        path.write_bytes(chunk_bytes(rows))
        requests.append(
            ChunkRequest(
                path=path,
                window_start=day(start),
                window_end=day(end),
                requested_start=canonical_utc_request(day(start)),
                requested_end=canonical_utc_request(day(end) - pd.Timedelta(days=1)),
                retrieved_at=RETRIEVED,
            )
        )
    return requests


def standard_requests(directory: Path) -> list[ChunkRequest]:
    """Two chunks tiling 2024-01-01 .. 2024-01-07 (6 days), descending order."""
    first = [
        make_row(d, offset=i) for i, d in enumerate(("2024-01-03", "2024-01-02", "2024-01-01"))
    ]
    second = [
        make_row(d, offset=3 + i) for i, d in enumerate(("2024-01-06", "2024-01-05", "2024-01-04"))
    ]
    return write_chunks(
        directory,
        [
            ("chunk_000.json", "2024-01-01", "2024-01-04", first),
            ("chunk_001.json", "2024-01-04", "2024-01-07", second),
        ],
    )


class TestDeriveDailyOhlcv:
    def test_derived_csv_bytes_match_literal_hand_expectation(self, tmp_path: Path) -> None:
        rows = [[epoch_s("2024-01-02"), 90.5, 110.25, 100.0, 105.125, 7.5]]
        requests = write_chunks(tmp_path, [("c.json", "2024-01-02", "2024-01-03", rows)])
        output = tmp_path / "derived.csv"
        evidence = derive_daily_ohlcv(
            requests,
            overall_start=day("2024-01-02"),
            overall_end=day("2024-01-03"),
            output_csv=output,
        )
        expected = (
            b"timestamp,open,high,low,close,volume\n"
            b"2024-01-02T00:00:00+00:00,100.0,110.25,90.5,105.125,7.5\n"
        )
        assert output.read_bytes() == expected
        assert evidence.derived_row_count == 1
        assert evidence.total_rows_before_window == 0

    def test_multi_chunk_combination_is_chronological_and_deterministic(
        self, tmp_path: Path
    ) -> None:
        requests = standard_requests(tmp_path)
        output = tmp_path / "derived.csv"
        evidence_one = derive_daily_ohlcv(
            requests,
            overall_start=day("2024-01-01"),
            overall_end=day("2024-01-07"),
            output_csv=output,
        )
        first_bytes = output.read_bytes()
        evidence_two = derive_daily_ohlcv(
            requests,
            overall_start=day("2024-01-01"),
            overall_end=day("2024-01-07"),
            output_csv=output,
            overwrite=True,
        )
        assert output.read_bytes() == first_bytes
        assert evidence_one.to_json_bytes() == evidence_two.to_json_bytes()
        assert evidence_one == evidence_two
        assert evidence_one.derived_row_count == 6
        assert evidence_one.first_open_time == day("2024-01-01")
        assert evidence_one.last_open_time == day("2024-01-06")

    def test_derived_csv_round_trips_exact_values_through_strict_parsing(
        self, tmp_path: Path
    ) -> None:
        requests = standard_requests(tmp_path)
        output = tmp_path / "derived.csv"
        derive_daily_ohlcv(
            requests,
            overall_start=day("2024-01-01"),
            overall_end=day("2024-01-07"),
            output_csv=output,
        )
        frame = validate_ohlcv(
            pd.read_csv(io.BytesIO(output.read_bytes()), float_precision="round_trip"),
            expected_interval=pd.Timedelta(days=1),
        )
        assert list(frame["open"]) == [100.0 + i for i in (2, 1, 0, 5, 4, 3)]
        assert list(frame["low"]) == [95.0 + i for i in (2, 1, 0, 5, 4, 3)]
        assert frame.index[0] == day("2024-01-01")
        assert frame.index[-1] == day("2024-01-06")

    def test_missing_day_inside_a_chunk_aborts_with_count(self, tmp_path: Path) -> None:
        rows = [make_row("2024-01-01"), make_row("2024-01-03")]
        requests = write_chunks(tmp_path, [("c.json", "2024-01-01", "2024-01-04", rows)])
        output = tmp_path / "derived.csv"
        with pytest.raises(AcquisitionError, match=r"1 missing daily candle\(s\).*2024-01-02"):
            derive_daily_ohlcv(
                requests,
                overall_start=day("2024-01-01"),
                overall_end=day("2024-01-04"),
                output_csv=output,
            )
        assert not output.exists()

    def test_window_tiling_gap_is_rejected(self, tmp_path: Path) -> None:
        requests = write_chunks(
            tmp_path,
            [
                ("a.json", "2024-01-01", "2024-01-02", [make_row("2024-01-01")]),
                ("b.json", "2024-01-03", "2024-01-04", [make_row("2024-01-03")]),
            ],
        )
        with pytest.raises(AcquisitionError, match="tile the overall range"):
            derive_daily_ohlcv(
                requests,
                overall_start=day("2024-01-01"),
                overall_end=day("2024-01-04"),
                output_csv=tmp_path / "d.csv",
            )

    def test_overlapping_windows_are_rejected(self, tmp_path: Path) -> None:
        requests = write_chunks(
            tmp_path,
            [
                (
                    "a.json",
                    "2024-01-01",
                    "2024-01-03",
                    [make_row("2024-01-01"), make_row("2024-01-02")],
                ),
                (
                    "b.json",
                    "2024-01-02",
                    "2024-01-04",
                    [make_row("2024-01-02"), make_row("2024-01-03")],
                ),
            ],
        )
        with pytest.raises(AcquisitionError, match="tile the overall range"):
            derive_daily_ohlcv(
                requests,
                overall_start=day("2024-01-01"),
                overall_end=day("2024-01-04"),
                output_csv=tmp_path / "d.csv",
            )

    def test_reordered_chunk_declarations_are_rejected(self, tmp_path: Path) -> None:
        requests = list(reversed(standard_requests(tmp_path)))
        with pytest.raises(AcquisitionError, match="first window starts at"):
            derive_daily_ohlcv(
                requests,
                overall_start=day("2024-01-01"),
                overall_end=day("2024-01-07"),
                output_csv=tmp_path / "d.csv",
            )

    def test_overwrite_refusal_and_explicit_overwrite(self, tmp_path: Path) -> None:
        requests = standard_requests(tmp_path)
        output = tmp_path / "derived.csv"
        output.write_bytes(b"previous")
        with pytest.raises(AcquisitionError, match="refusing to overwrite"):
            derive_daily_ohlcv(
                requests,
                overall_start=day("2024-01-01"),
                overall_end=day("2024-01-07"),
                output_csv=output,
            )
        assert output.read_bytes() == b"previous"
        derive_daily_ohlcv(
            requests,
            overall_start=day("2024-01-01"),
            overall_end=day("2024-01-07"),
            output_csv=output,
            overwrite=True,
        )
        assert output.read_bytes().startswith(b"timestamp,")

    def test_no_temporary_files_remain(self, tmp_path: Path) -> None:
        requests = standard_requests(tmp_path)
        derive_daily_ohlcv(
            requests,
            overall_start=day("2024-01-01"),
            overall_end=day("2024-01-07"),
            output_csv=tmp_path / "derived.csv",
        )
        assert list(tmp_path.glob("*.tmp")) == []

    def test_internal_failure_after_hashing_leaves_no_output_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Red-team: a failure while assembling the evidence record must not
        # leave a freshly written CSV behind as partial publication state.
        requests = standard_requests(tmp_path)
        output = tmp_path / "derived.csv"

        def exploding(**kwargs: Any) -> Any:
            raise RuntimeError("simulated evidence construction failure")

        monkeypatch.setattr(coinbase, "AcquisitionEvidence", exploding)
        with pytest.raises(RuntimeError, match="simulated evidence construction"):
            derive_daily_ohlcv(
                requests,
                overall_start=day("2024-01-01"),
                overall_end=day("2024-01-07"),
                output_csv=output,
            )
        assert not output.exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_source_mutation_during_derivation_aborts_before_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        requests = standard_requests(tmp_path)
        output = tmp_path / "derived.csv"
        monkeypatch.setattr(coinbase, "sha256_file", lambda path: "0" * 64)
        with pytest.raises(AcquisitionError, match="changed during derivation"):
            derive_daily_ohlcv(
                requests,
                overall_start=day("2024-01-01"),
                overall_end=day("2024-01-07"),
                output_csv=output,
            )
        assert not output.exists()

    def test_raw_files_are_byte_identical_after_derivation(self, tmp_path: Path) -> None:
        requests = standard_requests(tmp_path)
        before = [request.path.read_bytes() for request in requests]
        derive_daily_ohlcv(
            requests,
            overall_start=day("2024-01-01"),
            overall_end=day("2024-01-07"),
            output_csv=tmp_path / "derived.csv",
        )
        assert [request.path.read_bytes() for request in requests] == before

    def test_non_csv_output_is_rejected(self, tmp_path: Path) -> None:
        requests = standard_requests(tmp_path)
        with pytest.raises(AcquisitionError, match=r"must be a \.csv file"):
            derive_daily_ohlcv(
                requests,
                overall_start=day("2024-01-01"),
                overall_end=day("2024-01-07"),
                output_csv=tmp_path / "derived.parquet",
            )


def make_evidence(tmp_path: Path) -> tuple[AcquisitionEvidence, Path, Path]:
    requests = standard_requests(tmp_path)
    output = tmp_path / "derived.csv"
    evidence = derive_daily_ohlcv(
        requests,
        overall_start=day("2024-01-01"),
        overall_end=day("2024-01-07"),
        output_csv=output,
    )
    return evidence, tmp_path, output


class TestAcquisitionEvidence:
    def test_round_trip_is_byte_identical(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        raw = evidence.to_json_bytes()
        parsed = AcquisitionEvidence.from_json_bytes(raw)
        assert parsed == evidence
        assert parsed.to_json_bytes() == raw

    def test_write_and_load_evidence(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        target = tmp_path / "evidence.json"
        write_acquisition_evidence(evidence, target)
        assert load_acquisition_evidence(target) == evidence
        with pytest.raises(AcquisitionError, match="refusing to overwrite"):
            write_acquisition_evidence(evidence, target)

    def _mutated(self, evidence: AcquisitionEvidence, **changes: Any) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(evidence.to_json_bytes().decode("utf-8"))
        payload.update(changes)
        return payload

    def _parse(self, payload: dict[str, Any]) -> AcquisitionEvidence:
        return AcquisitionEvidence.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_unknown_key_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        payload = self._mutated(evidence, extra_field=1)
        with pytest.raises(ValueError, match=r"unknown=\['extra_field'\]"):
            self._parse(payload)

    def test_missing_key_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        payload = self._mutated(evidence)
        del payload["derived_sha256"]
        with pytest.raises(ValueError, match=r"missing=\['derived_sha256'\]"):
            self._parse(payload)

    def test_boolean_schema_version_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        payload = self._mutated(evidence, acquisition_schema_version=True)
        with pytest.raises(ValueError, match="bool is rejected"):
            self._parse(payload)

    def test_unsupported_schema_version_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        payload = self._mutated(evidence, acquisition_schema_version=2)
        with pytest.raises(ValueError, match="unsupported acquisition schema version"):
            self._parse(payload)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("venue", "kraken"),
            ("product", "BTC-USD"),
            ("granularity_seconds", 3600),
            ("documentation_url", "https://example.com/docs"),
            ("endpoint", "https://api.example.com/candles"),
            ("adapter_algorithm", "coinbase-candles-v2"),
        ],
    )
    def test_pinned_source_fields_are_rejected_when_changed(
        self, tmp_path: Path, field: str, value: Any
    ) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        payload = self._mutated(evidence, **{field: value})
        with pytest.raises(ValueError, match=field.replace("_", "_")):
            self._parse(payload)

    def test_modified_transformation_list_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        payload = self._mutated(
            evidence, transformations=[*ADAPTER_TRANSFORMATIONS, "forward-fill missing candles"]
        )
        with pytest.raises(ValueError, match=r"documented .* transformation list"):
            self._parse(payload)

    def test_no_repair_false_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        payload = self._mutated(evidence, no_repair=False)
        with pytest.raises(ValueError, match="no_repair must be true"):
            self._parse(payload)

    def test_boolean_row_count_in_chunk_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        payload = self._mutated(evidence)
        payload["chunks"][0]["row_count"] = True
        with pytest.raises(ValueError, match="bool is rejected"):
            self._parse(payload)

    def test_unsafe_chunk_filename_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        for name in ("../evil.json", "a/b.json", "/abs.json", "bad\x00.json"):
            payload = self._mutated(evidence)
            payload["chunks"][0]["filename"] = name
            with pytest.raises(ValueError, match="safe file basename"):
                self._parse(payload)

    def test_duplicate_chunk_filenames_are_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        payload = self._mutated(evidence)
        payload["chunks"][1]["filename"] = payload["chunks"][0]["filename"]
        with pytest.raises(ValueError, match="chunk filenames must be unique"):
            self._parse(payload)

    def test_derived_row_count_mismatch_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        with pytest.raises(ValueError, match="does not equal the 6 daily buckets"):
            dataclasses.replace(evidence, derived_row_count=5)

    def test_chunk_claiming_more_candles_than_its_window_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        first = evidence.chunks[0]
        with pytest.raises(ValueError, match="candles inside a 3-day window"):
            dataclasses.replace(first, row_count=first.row_count + 1)

    def test_contributed_rows_mismatch_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        # Per-chunk fields stay self-consistent; only the cross-chunk sum breaks.
        first = dataclasses.replace(evidence.chunks[0], rows_before_window=1)
        with pytest.raises(ValueError, match="chunks contribute 5 candles"):
            dataclasses.replace(
                evidence, chunks=(first, *evidence.chunks[1:]), total_rows_before_window=1
            )

    def test_total_rows_before_window_mismatch_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        with pytest.raises(ValueError, match="total_rows_before_window"):
            dataclasses.replace(evidence, total_rows_before_window=99)

    def test_first_open_time_must_equal_overall_start(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        with pytest.raises(ValueError, match="must equal overall_start"):
            dataclasses.replace(evidence, first_open_time=day("2024-01-02"))

    def test_last_open_time_must_be_final_completed_day(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        with pytest.raises(ValueError, match="must equal overall_end - 1 day"):
            dataclasses.replace(evidence, last_open_time=day("2024-01-05"))

    def test_chunk_window_reordering_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        with pytest.raises(ValueError, match="first window starts at"):
            dataclasses.replace(evidence, chunks=tuple(reversed(evidence.chunks)))


class TestSemanticVerification:
    def test_raw_change_with_updated_hash_but_unchanged_csv_is_detected(
        self, tmp_path: Path
    ) -> None:
        # R1 attack: change a raw candle value, update its recorded SHA in the
        # evidence, and leave the derived CSV (and its recorded hash)
        # untouched. Per-file hashing alone accepts this; semantic
        # re-derivation must reject it.
        evidence, chunk_dir, derived = make_evidence(tmp_path)
        target = chunk_dir / evidence.chunks[0].filename
        tampered_raw = target.read_bytes().replace(b"100.0", b"123.0", 1)
        assert tampered_raw != target.read_bytes()
        target.write_bytes(tampered_raw)
        tampered_chunk = dataclasses.replace(evidence.chunks[0], sha256=sha256_bytes(tampered_raw))
        forged = dataclasses.replace(evidence, chunks=(tampered_chunk, *evidence.chunks[1:]))
        with pytest.raises(AcquisitionError, match=r"does not re-derive byte-for-byte"):
            verify_acquisition_evidence(forged, chunk_dir=chunk_dir, derived_csv=derived)

    def test_clean_semantic_verification_passes(self, tmp_path: Path) -> None:
        evidence, chunk_dir, derived = make_evidence(tmp_path)
        verify_acquisition_evidence(evidence, chunk_dir=chunk_dir, derived_csv=derived)

    def test_source_mutation_during_verification_is_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        evidence, chunk_dir, derived = make_evidence(tmp_path)
        calls = {"n": 0}

        def drifting(path: Any) -> str:
            calls["n"] += 1
            # The final re-hash loop uses sha256_file: first chunk honest,
            # a later one drifts, simulating mutation during verification.
            return sha256_file(path) if calls["n"] == 1 else "0" * 64

        monkeypatch.setattr(coinbase, "sha256_file", drifting)
        with pytest.raises(AcquisitionError, match="changed during verification"):
            verify_acquisition_evidence(evidence, chunk_dir=chunk_dir, derived_csv=derived)


class TestRequestMetadataBinding:
    def test_requested_start_must_equal_window_start(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        with pytest.raises(ValueError, match="canonical UTC request"):
            dataclasses.replace(evidence.chunks[0], requested_start="whenever")

    def test_requested_end_must_be_window_end_minus_one_day(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        chunk = evidence.chunks[0]
        # window_end itself (not window_end - 1 day) must be rejected.
        wrong = chunk.window_end.strftime("%Y-%m-%dT%H:%M:%SZ")
        with pytest.raises(ValueError, match="canonical UTC request"):
            dataclasses.replace(chunk, requested_end=wrong)

    def test_non_utc_retrieved_at_is_rejected(self, tmp_path: Path) -> None:
        evidence, _, _ = make_evidence(tmp_path)
        eastern = pd.Timestamp("2026-07-11T12:00:00-05:00")
        with pytest.raises(ValueError, match="UTC"):
            dataclasses.replace(evidence.chunks[0], retrieved_at=eastern)

    def test_chunk_request_binds_metadata_too(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_bytes(chunk_bytes([make_row("2024-01-01")]))
        with pytest.raises(ValueError, match="canonical UTC request"):
            ChunkRequest(
                path=path,
                window_start=day("2024-01-01"),
                window_end=day("2024-01-02"),
                requested_start="2024-01-01T00:00:00Z",
                requested_end="2024-01-02T00:00:00Z",  # should be 2024-01-01 (end - 1 day)
                retrieved_at=RETRIEVED,
            )


class TestVerifyAcquisitionEvidence:
    def test_clean_verification_passes(self, tmp_path: Path) -> None:
        evidence, chunk_dir, derived = make_evidence(tmp_path)
        verify_acquisition_evidence(evidence, chunk_dir=chunk_dir, derived_csv=derived)

    def test_tampered_raw_chunk_is_detected(self, tmp_path: Path) -> None:
        evidence, chunk_dir, derived = make_evidence(tmp_path)
        target = chunk_dir / evidence.chunks[0].filename
        target.write_bytes(target.read_bytes().replace(b"100.0", b"100.1", 1))
        with pytest.raises(AcquisitionError, match="modified after evidence creation"):
            verify_acquisition_evidence(evidence, chunk_dir=chunk_dir, derived_csv=derived)

    def test_tampered_derived_csv_is_detected(self, tmp_path: Path) -> None:
        evidence, chunk_dir, derived = make_evidence(tmp_path)
        derived.write_bytes(derived.read_bytes().replace(b"105.0", b"105.5", 1))
        with pytest.raises(AcquisitionError, match="modified after evidence creation"):
            verify_acquisition_evidence(evidence, chunk_dir=chunk_dir, derived_csv=derived)

    def test_missing_chunk_file_is_detected(self, tmp_path: Path) -> None:
        evidence, chunk_dir, derived = make_evidence(tmp_path)
        (chunk_dir / evidence.chunks[1].filename).unlink()
        with pytest.raises(AcquisitionError, match="not found"):
            verify_acquisition_evidence(evidence, chunk_dir=chunk_dir, derived_csv=derived)

    def test_wrong_derived_filename_is_detected(self, tmp_path: Path) -> None:
        evidence, chunk_dir, derived = make_evidence(tmp_path)
        renamed = derived.with_name("other.csv")
        derived.rename(renamed)
        with pytest.raises(AcquisitionError, match="evidence records"):
            verify_acquisition_evidence(evidence, chunk_dir=chunk_dir, derived_csv=renamed)
