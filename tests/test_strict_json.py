"""R5: one strict JSON decoder — duplicate keys and non-finite numbers.

Each provenance-bearing format must reject duplicate object keys (at every
nesting level) and non-finite numbers, through the shared decoder. The
adversarial documents below all parse fine under stock ``json.loads`` (last
value wins), so they exercise a real trust-boundary gap, not an
implementation branch.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from conftest import CoinbasePipeline
from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.coinbase import AcquisitionEvidence
from eth_research.data.lock import DatasetLock, build_dataset_lock
from eth_research.data.provenance import DatasetManifest
from eth_research.data.quality import QualityReport
from eth_research.ledger import LedgerEvent
from eth_research.protocol import (
    BenchmarkProtocol,
    BenchmarkResults,
    build_benchmark_protocol,
)
from test_ledger import make_event
from test_protocol import make_results


def dup_top_level_key(raw: bytes) -> bytes:
    """Duplicate the first top-level key of a pretty-printed JSON object."""
    obj = json.loads(raw)
    first_key = next(iter(obj))
    value = json.dumps(obj[first_key])
    body = raw.decode("utf-8")
    assert body.lstrip().startswith("{")
    brace = body.index("{")
    return (body[: brace + 1] + f'"{first_key}": {value}, ' + body[brace + 1 :]).encode("utf-8")


class TestStrictDecoder:
    def test_rejects_top_level_duplicate(self) -> None:
        with pytest.raises(StrictJSONError, match="duplicate JSON object key 'a'"):
            strict_json_loads(b'{"a": 1, "a": 2}')

    def test_rejects_nested_duplicate(self) -> None:
        with pytest.raises(StrictJSONError, match="duplicate JSON object key 'x'"):
            strict_json_loads(b'{"outer": {"x": 1, "x": 2}}')

    def test_rejects_duplicate_inside_array_element(self) -> None:
        with pytest.raises(StrictJSONError, match="duplicate JSON object key 'k'"):
            strict_json_loads(b'{"items": [{"k": 1, "k": 2}]}')

    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_rejects_nonfinite_constants(self, literal: str) -> None:
        with pytest.raises(StrictJSONError, match="non-finite JSON constant"):
            strict_json_loads(f'{{"v": {literal}}}'.encode())

    def test_rejects_exponent_overflow(self) -> None:
        with pytest.raises(StrictJSONError, match="exponent overflow"):
            strict_json_loads(b'{"v": 1e999}')

    def test_accepts_normal_numbers(self) -> None:
        parsed = strict_json_loads(b'{"i": 5, "f": 1.5, "neg": -3}')
        assert parsed == {"i": 5, "f": 1.5, "neg": -3}
        assert isinstance(parsed["i"], int)
        assert isinstance(parsed["f"], float)


class TestManifestDuplicateKeys:
    def test_top_level_duplicate_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        raw = coinbase_pipeline.build.manifest.to_json_bytes()
        with pytest.raises(ValueError, match="duplicate JSON object key"):
            DatasetManifest.from_json_bytes(dup_top_level_key(raw))

    def test_duplicate_hash_field_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        raw = coinbase_pipeline.build.manifest.to_json_bytes().decode("utf-8")
        tampered = raw.replace(
            '"raw_file_sha256":', '"raw_file_sha256": "' + "0" * 64 + '",\n  "raw_file_sha256":', 1
        )
        with pytest.raises(ValueError, match="duplicate JSON object key 'raw_file_sha256'"):
            DatasetManifest.from_json_bytes(tampered.encode("utf-8"))


class TestQualityReportDuplicateKeys:
    def test_top_level_duplicate_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        raw = coinbase_pipeline.build.quality_report.to_json_bytes()
        with pytest.raises(ValueError, match="duplicate JSON object key"):
            QualityReport.from_json_bytes(dup_top_level_key(raw))

    def test_nested_thresholds_duplicate_rejected(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        raw = coinbase_pipeline.build.quality_report.to_json_bytes().decode("utf-8")
        tampered = raw.replace(
            '"extreme_range":', '"extreme_range": 0.25,\n      "extreme_range":', 1
        )
        with pytest.raises(ValueError, match="duplicate JSON object key 'extreme_range'"):
            QualityReport.from_json_bytes(tampered.encode("utf-8"))


class TestAcquisitionEvidenceDuplicateKeys:
    def test_top_level_duplicate_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        raw = coinbase_pipeline.evidence.to_json_bytes()
        with pytest.raises(ValueError, match="duplicate JSON object key"):
            AcquisitionEvidence.from_json_bytes(dup_top_level_key(raw))

    def test_nested_chunk_duplicate_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        raw = coinbase_pipeline.evidence.to_json_bytes().decode("utf-8")
        tampered = raw.replace('"row_count":', '"row_count": 60,\n      "row_count":', 1)
        with pytest.raises(ValueError, match="duplicate JSON object key 'row_count'"):
            AcquisitionEvidence.from_json_bytes(tampered.encode("utf-8"))


class TestDatasetLockDuplicateKeys:
    def test_top_level_duplicate_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        lock = build_dataset_lock(
            coinbase_pipeline.build.manifest,
            manifest_sha256=coinbase_pipeline.manifest_sha256,
            acquisition_evidence_sha256=coinbase_pipeline.evidence_sha256,
        )
        with pytest.raises(ValueError, match="duplicate JSON object key"):
            DatasetLock.from_json_bytes(dup_top_level_key(lock.to_json_bytes()))


class TestProtocolDuplicateKeys:
    def _protocol(self, pipeline: CoinbasePipeline) -> BenchmarkProtocol:
        lock = build_dataset_lock(
            pipeline.build.manifest,
            manifest_sha256=pipeline.manifest_sha256,
            acquisition_evidence_sha256=pipeline.evidence_sha256,
        )
        return build_benchmark_protocol(lock, package_version="0.3.0")

    def test_top_level_duplicate_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        raw = self._protocol(coinbase_pipeline).to_json_bytes()
        with pytest.raises(ValueError, match="duplicate JSON object key"):
            BenchmarkProtocol.from_json_bytes(dup_top_level_key(raw))

    def test_duplicate_key_inside_strategy_rejected(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        raw = self._protocol(coinbase_pipeline).to_json_bytes().decode("utf-8")
        tampered = raw.replace(
            '"name": "buy_and_hold"',
            '"name": "buy_and_hold",\n      "name": "buy_and_hold"',
            1,
        )
        with pytest.raises(ValueError, match="duplicate JSON object key 'name'"):
            BenchmarkProtocol.from_json_bytes(tampered.encode("utf-8"))


class TestResultsDuplicateKeys:
    def test_top_level_duplicate_rejected(self) -> None:
        raw = make_results().to_json_bytes()
        with pytest.raises(ValueError, match="duplicate JSON object key"):
            BenchmarkResults.from_json_bytes(dup_top_level_key(raw))

    def test_duplicate_inside_segment_rejected(self) -> None:
        raw = make_results().to_json_bytes().decode("utf-8")
        tampered = raw.replace('"num_fills":', '"num_fills": 1,\n      "num_fills":', 1)
        with pytest.raises(ValueError, match="duplicate JSON object key 'num_fills'"):
            BenchmarkResults.from_json_bytes(tampered.encode("utf-8"))


class TestLedgerDuplicateKeys:
    def test_duplicate_event_key_rejected(self) -> None:
        # The exact example from R5: a line carrying both event values.
        line = make_event("started").to_json_line().decode("utf-8")
        tampered = line.replace('"event":"started"', '"event":"failed","event":"started"', 1)
        with pytest.raises(ValueError, match="duplicate JSON object key 'event'"):
            LedgerEvent.from_json_line(tampered.encode("utf-8"))


def test_coinbase_response_exponent_overflow_still_rejected() -> None:
    # The candle adapter shares the same finite-number guarantee.
    from eth_research.data.coinbase import AcquisitionError, parse_candles_chunk

    raw = b"[[86400, 1e999, 111.0, 100.0, 105.0, 10.0]]"
    with pytest.raises(AcquisitionError, match="finite"):
        parse_candles_chunk(
            raw,
            window_start=pd.Timestamp("1970-01-02", tz="UTC"),
            window_end=pd.Timestamp("1970-01-03", tz="UTC"),
        )
