"""Dataset lock: strict parsing and cross-checks against pinned artifacts."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pandas as pd
import pytest

from conftest import CoinbasePipeline
from eth_research.data.builder import build_canonical_dataset
from eth_research.data.lock import (
    DatasetLock,
    DatasetLockError,
    build_dataset_lock,
    load_dataset_lock,
    verify_dataset_lock,
)
from eth_research.data.provenance import sha256_file


def make_lock(pipeline: CoinbasePipeline) -> DatasetLock:
    return build_dataset_lock(
        pipeline.build.manifest,
        manifest_sha256=pipeline.manifest_sha256,
        acquisition_evidence_sha256=pipeline.evidence_sha256,
    )


class TestDatasetLockModel:
    def test_round_trip_is_byte_identical(self, coinbase_pipeline: CoinbasePipeline) -> None:
        lock = make_lock(coinbase_pipeline)
        raw = lock.to_json_bytes()
        parsed = DatasetLock.from_json_bytes(raw)
        assert parsed == lock
        assert parsed.to_json_bytes() == raw

    def test_lock_contains_no_market_rows_or_paths(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        lock = make_lock(coinbase_pipeline)
        payload: dict[str, Any] = json.loads(lock.to_json_bytes().decode("utf-8"))
        for key, value in payload.items():
            assert "path" not in key
            assert "filename" not in key
            assert "dir" not in key
            if isinstance(value, str):
                assert "/" not in value
                assert "\\" not in value

    def _payload(self, lock: DatasetLock, **changes: Any) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(lock.to_json_bytes().decode("utf-8"))
        payload.update(changes)
        return payload

    def _parse(self, payload: dict[str, Any]) -> DatasetLock:
        return DatasetLock.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_unknown_key_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(make_lock(coinbase_pipeline), attacker_note="hi")
        with pytest.raises(ValueError, match=r"unknown=\['attacker_note'\]"):
            self._parse(payload)

    def test_missing_key_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(make_lock(coinbase_pipeline))
        del payload["row_count"]
        with pytest.raises(ValueError, match=r"missing=\['row_count'\]"):
            self._parse(payload)

    def test_boolean_row_count_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(make_lock(coinbase_pipeline), row_count=True)
        with pytest.raises(ValueError, match="bool is rejected"):
            self._parse(payload)

    def test_unsupported_schema_version_is_rejected(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        payload = self._payload(make_lock(coinbase_pipeline), lock_schema_version=2)
        with pytest.raises(ValueError, match="unsupported lock schema version"):
            self._parse(payload)

    def test_fingerprint_without_prefix_is_rejected(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        payload = self._payload(make_lock(coinbase_pipeline), content_fingerprint="0" * 64)
        with pytest.raises(ValueError, match="must match sha256:"):
            self._parse(payload)

    def test_short_hash_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(make_lock(coinbase_pipeline), manifest_sha256="abc123")
        with pytest.raises(ValueError, match="64 lowercase hex"):
            self._parse(payload)

    def test_naive_timestamp_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        payload = self._payload(make_lock(coinbase_pipeline))
        payload["first_open_time"] = payload["first_open_time"].replace("+00:00", "")
        with pytest.raises(ValueError, match="timezone-aware"):
            self._parse(payload)

    def test_inconsistent_time_bounds_are_rejected(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        lock = make_lock(coinbase_pipeline)
        with pytest.raises(ValueError, match="inconsistent with first_open_time"):
            dataclasses.replace(lock, row_count=lock.row_count - 1)

    def test_wrong_base_asset_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        with pytest.raises(ValueError, match="base_asset must be 'ETH'"):
            dataclasses.replace(make_lock(coinbase_pipeline), base_asset="BTC")


class TestVerifyDatasetLock:
    def test_clean_verification_returns_manifest_and_evidence(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        lock = make_lock(coinbase_pipeline)
        manifest, evidence = verify_dataset_lock(
            lock,
            manifest_path=coinbase_pipeline.build.manifest_path,
            acquisition_evidence_path=coinbase_pipeline.evidence_path,
        )
        assert manifest == coinbase_pipeline.build.manifest
        assert evidence == coinbase_pipeline.evidence

    def test_tampered_manifest_is_detected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        lock = make_lock(coinbase_pipeline)
        manifest_path = coinbase_pipeline.build.manifest_path
        manifest_path.write_bytes(manifest_path.read_bytes().replace(b"ETH-USD", b"ETH-EUR", 1))
        with pytest.raises(DatasetLockError, match="mismatch on manifest_sha256"):
            verify_dataset_lock(
                lock,
                manifest_path=manifest_path,
                acquisition_evidence_path=coinbase_pipeline.evidence_path,
            )

    def test_tampered_evidence_is_detected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        lock = make_lock(coinbase_pipeline)
        evidence_path = coinbase_pipeline.evidence_path
        evidence_path.write_bytes(evidence_path.read_bytes().replace(b'"chunks"', b'"chunkz"', 1))
        with pytest.raises(DatasetLockError, match="mismatch on acquisition_evidence_sha256"):
            verify_dataset_lock(
                lock,
                manifest_path=coinbase_pipeline.build.manifest_path,
                acquisition_evidence_path=evidence_path,
            )

    def test_lock_field_disagreeing_with_manifest_is_detected(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        lock = dataclasses.replace(make_lock(coinbase_pipeline), quote_asset="EUR")
        with pytest.raises(DatasetLockError, match="mismatch on quote_asset"):
            verify_dataset_lock(
                lock,
                manifest_path=coinbase_pipeline.build.manifest_path,
                acquisition_evidence_path=coinbase_pipeline.evidence_path,
            )

    def test_manifest_built_from_different_bytes_than_evidence_derived_is_detected(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        # Rebuild the canonical dataset from a subtly modified derived CSV
        # while the lock still pins the original acquisition evidence: the
        # evidence -> manifest chain link must fail.
        csv_path = coinbase_pipeline.derived_csv
        original = csv_path.read_bytes()
        modified = original.replace(b",10.0\n", b",10.25\n", 1)
        assert modified != original
        csv_path.write_bytes(modified)
        rebuild = build_canonical_dataset(
            csv_path,
            coinbase_pipeline.identity,
            coinbase_pipeline.build.manifest_path.parent,
            overwrite=True,
        )
        lock = build_dataset_lock(
            rebuild.manifest,
            manifest_sha256=coinbase_pipeline.manifest_sha256,
            acquisition_evidence_sha256=coinbase_pipeline.evidence_sha256,
        )
        with pytest.raises(DatasetLockError, match="derived sha256"):
            verify_dataset_lock(
                lock,
                manifest_path=rebuild.manifest_path,
                acquisition_evidence_path=coinbase_pipeline.evidence_path,
            )

    def test_evidence_version_mismatch_breaks_the_chain(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        # R6: acquisition evidence reporting a different software version than
        # the manifest breaks the version chain, even with a matching hash.
        forged = dataclasses.replace(coinbase_pipeline.evidence, package_version="9.9.9")
        forged_path = coinbase_pipeline.evidence_path.with_name("forged_evidence.json")
        forged_path.write_bytes(forged.to_json_bytes())
        lock = build_dataset_lock(
            coinbase_pipeline.build.manifest,
            manifest_sha256=coinbase_pipeline.manifest_sha256,
            acquisition_evidence_sha256=sha256_file(forged_path),
        )
        with pytest.raises(DatasetLockError, match=r"package_version \(evidence\)"):
            verify_dataset_lock(
                lock,
                manifest_path=coinbase_pipeline.build.manifest_path,
                acquisition_evidence_path=forged_path,
            )

    def test_missing_manifest_is_detected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        lock = make_lock(coinbase_pipeline)
        with pytest.raises(DatasetLockError, match="does not exist"):
            verify_dataset_lock(
                lock,
                manifest_path=coinbase_pipeline.build.manifest_path.with_name("gone.json"),
                acquisition_evidence_path=coinbase_pipeline.evidence_path,
            )


class TestLoadDatasetLock:
    def test_load_round_trip(self, coinbase_pipeline: CoinbasePipeline) -> None:
        lock = make_lock(coinbase_pipeline)
        target = coinbase_pipeline.evidence_path.parent / "dataset_lock.json"
        target.write_bytes(lock.to_json_bytes())
        assert load_dataset_lock(target) == lock

    def test_load_wraps_errors(self, coinbase_pipeline: CoinbasePipeline) -> None:
        target = coinbase_pipeline.evidence_path.parent / "dataset_lock.json"
        target.write_bytes(b"{not json")
        with pytest.raises(DatasetLockError, match="invalid dataset lock"):
            load_dataset_lock(target)


def test_verify_detects_time_bound_consistency_with_interval(
    coinbase_pipeline: CoinbasePipeline,
) -> None:
    """A lock whose interval disagrees with the manifest is caught field-by-field."""
    lock = make_lock(coinbase_pipeline)
    broken = dataclasses.replace(
        lock,
        candle_interval=pd.Timedelta(hours=12),
        last_open_time=lock.first_open_time + (lock.row_count - 1) * pd.Timedelta(hours=12),
    )
    with pytest.raises(DatasetLockError, match="mismatch on candle_interval"):
        verify_dataset_lock(
            broken,
            manifest_path=coinbase_pipeline.build.manifest_path,
            acquisition_evidence_path=coinbase_pipeline.evidence_path,
        )
