"""Tests for the canonical dataset builder: determinism, refusal, verification."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from eth_research.data.builder import (
    DatasetBuildError,
    DatasetVerificationError,
    audit_ohlcv_file,
    build_canonical_dataset,
    load_canonical_dataset,
)
from eth_research.data.provenance import DatasetIdentity, sha256_bytes
from eth_research.data.schema import validate_ohlcv
from eth_research.data.synthetic import make_synthetic_ohlcv

IDENTITY = DatasetIdentity(
    quote_asset="USD",
    symbol="ETH/USD",
    venue="TestVenue",
    interval=pd.Timedelta("1D"),
    source="unit-test synthetic OHLCV",
)


@pytest.fixture
def canonical() -> pd.DataFrame:
    return make_synthetic_ohlcv(n_periods=30, seed=9)


def write_csv(frame: pd.DataFrame, path: Path) -> Path:
    frame.reset_index().to_csv(path, index=False)
    return path


def write_parquet(frame: pd.DataFrame, path: Path) -> Path:
    frame.to_parquet(path)
    return path


def test_build_produces_verified_artifacts(tmp_path: Path, canonical: pd.DataFrame) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    out = tmp_path / "out"
    result = build_canonical_dataset(source, IDENTITY, out)

    assert result.canonical_path.name == "testvenue-eth-usd-86400s.canonical.parquet"
    assert result.manifest_path.exists()
    assert result.quality_report_path.exists()
    assert result.quality_report.findings == ()
    assert result.manifest.row_count == 30
    assert result.manifest.raw_filename == "raw.csv"

    loaded = load_canonical_dataset(result.manifest_path)
    pd.testing.assert_frame_equal(loaded.frame, canonical, check_freq=False)
    assert loaded.manifest == result.manifest


def test_raw_file_is_never_modified(tmp_path: Path, canonical: pd.DataFrame) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    before = source.read_bytes()
    build_canonical_dataset(source, IDENTITY, tmp_path / "out")
    assert source.read_bytes() == before


def test_equivalent_csv_and_parquet_share_the_content_fingerprint(
    tmp_path: Path, canonical: pd.DataFrame
) -> None:
    csv_result = build_canonical_dataset(
        write_csv(canonical, tmp_path / "raw.csv"), IDENTITY, tmp_path / "from-csv"
    )
    parquet_result = build_canonical_dataset(
        write_parquet(canonical, tmp_path / "raw.parquet"), IDENTITY, tmp_path / "from-parquet"
    )
    assert csv_result.manifest.content_fingerprint == parquet_result.manifest.content_fingerprint
    # The raw containers differ even though the content is identical.
    assert csv_result.manifest.raw_file_sha256 != parquet_result.manifest.raw_file_sha256


def test_modifying_one_value_changes_the_fingerprint(
    tmp_path: Path, canonical: pd.DataFrame
) -> None:
    base = build_canonical_dataset(
        write_csv(canonical, tmp_path / "a.csv"), IDENTITY, tmp_path / "a"
    )
    tweaked = canonical.copy()
    closes = tweaked["close"].to_numpy(dtype=float, copy=True)
    closes[11] *= 1.0000001
    tweaked["close"] = closes
    changed = build_canonical_dataset(
        write_csv(tweaked, tmp_path / "b.csv"), IDENTITY, tmp_path / "b"
    )
    assert base.manifest.content_fingerprint != changed.manifest.content_fingerprint


def test_rebuild_is_deterministic(tmp_path: Path, canonical: pd.DataFrame) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    first = build_canonical_dataset(source, IDENTITY, tmp_path / "one")
    second = build_canonical_dataset(source, IDENTITY, tmp_path / "two")
    assert first.manifest == second.manifest
    # Byte-identical manifests: no timestamps, sorted keys, same fingerprints.
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()


def test_unsorted_input_is_refused_not_repaired(tmp_path: Path, canonical: pd.DataFrame) -> None:
    shuffled = canonical.reset_index().sample(frac=1, random_state=3)
    path = tmp_path / "shuffled.csv"
    shuffled.to_csv(path, index=False)
    with pytest.raises(DatasetBuildError, match="never repaired") as excinfo:
        build_canonical_dataset(path, IDENTITY, tmp_path / "out")
    assert excinfo.value.report is not None
    assert "unsorted_timestamps" in excinfo.value.report.error_codes
    assert not (tmp_path / "out").exists()  # nothing was written


def test_gapped_input_is_refused(tmp_path: Path, canonical: pd.DataFrame) -> None:
    gapped = canonical.reset_index().drop(index=10)
    path = tmp_path / "gapped.csv"
    gapped.to_csv(path, index=False)
    with pytest.raises(DatasetBuildError, match="missing_candles"):
        build_canonical_dataset(path, IDENTITY, tmp_path / "out")


def test_warnings_do_not_block_the_build(tmp_path: Path, canonical: pd.DataFrame) -> None:
    noisy = canonical.copy()
    volumes = noisy["volume"].to_numpy(dtype=float, copy=True)
    volumes[4] = 0.0
    noisy["volume"] = volumes
    source = write_csv(noisy, tmp_path / "noisy.csv")
    result = build_canonical_dataset(source, IDENTITY, tmp_path / "out")
    codes = [finding.code for finding in result.quality_report.findings]
    assert "zero_volume_candles" in codes
    assert not result.quality_report.has_errors


def test_overwrite_requires_explicit_opt_in(tmp_path: Path, canonical: pd.DataFrame) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    out = tmp_path / "out"
    build_canonical_dataset(source, IDENTITY, out)
    with pytest.raises(DatasetBuildError, match="refusing to overwrite"):
        build_canonical_dataset(source, IDENTITY, out)
    result = build_canonical_dataset(source, IDENTITY, out, overwrite=True)
    assert result.manifest_path.exists()


def test_no_temp_files_left_behind(tmp_path: Path, canonical: pd.DataFrame) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    out = tmp_path / "out"
    build_canonical_dataset(source, IDENTITY, out)
    assert [p.name for p in out.iterdir() if p.suffix == ".tmp"] == []
    assert len(list(out.iterdir())) == 3


def test_network_sources_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(DatasetBuildError, match="offline-only"):
        build_canonical_dataset("https://example.com/eth.csv", IDENTITY, tmp_path)
    with pytest.raises(DatasetBuildError, match="offline-only"):
        audit_ohlcv_file("s3://bucket/eth.parquet", expected_interval=pd.Timedelta("1D"))


def test_audit_file_reports_without_writing(tmp_path: Path, canonical: pd.DataFrame) -> None:
    dirty = canonical.reset_index()
    dirty.loc[3, "volume"] = -1.0
    path = tmp_path / "dirty.csv"
    dirty.to_csv(path, index=False)
    report = audit_ohlcv_file(path, expected_interval=pd.Timedelta("1D"))
    assert "negative_volume" in report.error_codes
    assert list(tmp_path.iterdir()) == [path]  # audit writes nothing


def test_manifest_tampering_is_detected(tmp_path: Path, canonical: pd.DataFrame) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    result = build_canonical_dataset(source, IDENTITY, tmp_path / "out")

    payload = json.loads(result.manifest_path.read_bytes())
    payload["row_count"] = 29
    result.manifest_path.write_bytes(json.dumps(payload).encode())
    with pytest.raises(DatasetVerificationError, match="row_count"):
        load_canonical_dataset(result.manifest_path)

    payload["row_count"] = 30
    payload["content_fingerprint"] = "sha256:" + "0" * 64
    result.manifest_path.write_bytes(json.dumps(payload).encode())
    with pytest.raises(DatasetVerificationError, match="content_fingerprint"):
        load_canonical_dataset(result.manifest_path)

    payload["extra_field"] = "sneaky"
    result.manifest_path.write_bytes(json.dumps(payload).encode())
    with pytest.raises(DatasetVerificationError, match="invalid manifest"):
        load_canonical_dataset(result.manifest_path)


def test_data_tampering_is_detected(tmp_path: Path, canonical: pd.DataFrame) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    result = build_canonical_dataset(source, IDENTITY, tmp_path / "out")

    tampered = canonical.copy()
    closes = tampered["close"].to_numpy(dtype=float, copy=True)
    closes[5] *= 1.01
    tampered["close"] = closes
    tampered.to_parquet(result.canonical_path)  # overwrite the data behind the manifest

    with pytest.raises(DatasetVerificationError, match="content_fingerprint"):
        load_canonical_dataset(result.manifest_path)


def test_missing_canonical_file_is_detected(tmp_path: Path, canonical: pd.DataFrame) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    result = build_canonical_dataset(source, IDENTITY, tmp_path / "out")
    result.canonical_path.unlink()
    with pytest.raises(DatasetVerificationError, match="not found"):
        load_canonical_dataset(result.manifest_path)


def test_extra_columns_require_opt_in_and_are_recorded(
    tmp_path: Path, canonical: pd.DataFrame
) -> None:
    extra = canonical.reset_index().assign(symbol="ETH/USD")
    path = tmp_path / "extra.csv"
    extra.to_csv(path, index=False)

    with pytest.raises(DatasetBuildError, match="unexpected_columns"):
        build_canonical_dataset(path, IDENTITY, tmp_path / "out")

    result = build_canonical_dataset(path, IDENTITY, tmp_path / "out", allow_extra_columns=True)
    codes = {finding.code: finding for finding in result.quality_report.findings}
    assert codes["unexpected_columns"].severity == "warning"
    assert codes["unexpected_columns"].first_examples == ("symbol",)
    loaded = load_canonical_dataset(result.manifest_path)
    assert "symbol" not in loaded.frame.columns


def test_naive_timestamps_require_opt_in(tmp_path: Path, canonical: pd.DataFrame) -> None:
    naive = canonical.reset_index()
    naive["timestamp"] = naive["timestamp"].dt.tz_localize(None)
    path = tmp_path / "naive.csv"
    naive.to_csv(path, index=False)

    with pytest.raises(DatasetBuildError, match="naive_timestamps"):
        build_canonical_dataset(path, IDENTITY, tmp_path / "out")
    result = build_canonical_dataset(path, IDENTITY, tmp_path / "out", assume_utc=True)
    assert result.manifest.row_count == 30


def test_canonical_content_matches_direct_validation(
    tmp_path: Path, canonical: pd.DataFrame
) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    result = build_canonical_dataset(source, IDENTITY, tmp_path / "out")
    loaded = load_canonical_dataset(result.manifest_path)
    direct = validate_ohlcv(pd.read_csv(source), expected_interval=IDENTITY.interval)
    pd.testing.assert_frame_equal(loaded.frame, direct, check_freq=False)


def test_loaded_dataset_includes_verified_quality_report(
    tmp_path: Path, canonical: pd.DataFrame
) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    result = build_canonical_dataset(source, IDENTITY, tmp_path / "out", assume_utc=False)
    loaded = load_canonical_dataset(result.manifest_path)
    assert loaded.quality_report == result.quality_report
    assert loaded.quality_report.assume_utc is False
    assert loaded.quality_report.allow_extra_columns is False
    assert loaded.manifest.quality_report_filename == result.quality_report_path.name


def test_deleted_quality_report_fails_verification(tmp_path: Path, canonical: pd.DataFrame) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    result = build_canonical_dataset(source, IDENTITY, tmp_path / "out")
    result.quality_report_path.unlink()
    with pytest.raises(DatasetVerificationError, match=r"quality report .* not found"):
        load_canonical_dataset(result.manifest_path)


def test_edited_quality_report_fails_verification(tmp_path: Path, canonical: pd.DataFrame) -> None:
    source = write_csv(canonical, tmp_path / "raw.csv")
    result = build_canonical_dataset(source, IDENTITY, tmp_path / "out")
    payload = json.loads(result.quality_report_path.read_bytes())
    payload["row_count"] = 999  # even a "plausible" edit changes the bytes
    result.quality_report_path.write_bytes(json.dumps(payload).encode())
    with pytest.raises(DatasetVerificationError, match="quality_report_sha256"):
        load_canonical_dataset(result.manifest_path)


def test_malformed_quality_report_with_fixed_hash_fails_parse(
    tmp_path: Path, canonical: pd.DataFrame
) -> None:
    """An attacker who also fixes the manifest hash still fails strict parsing."""
    source = write_csv(canonical, tmp_path / "raw.csv")
    result = build_canonical_dataset(source, IDENTITY, tmp_path / "out")

    bad_report = b"{not json"
    result.quality_report_path.write_bytes(bad_report)
    manifest_payload = json.loads(result.manifest_path.read_bytes())
    manifest_payload["quality_report_sha256"] = sha256_bytes(bad_report)
    result.manifest_path.write_bytes(json.dumps(manifest_payload).encode())
    with pytest.raises(DatasetVerificationError, match="invalid quality report"):
        load_canonical_dataset(result.manifest_path)


def test_consistent_looking_report_edit_fails_cross_checks(
    tmp_path: Path, canonical: pd.DataFrame
) -> None:
    """A well-formed but wrong report is caught by manifest cross-checks."""
    source = write_csv(canonical, tmp_path / "raw.csv")
    result = build_canonical_dataset(source, IDENTITY, tmp_path / "out")

    payload = json.loads(result.quality_report_path.read_bytes())
    payload["assume_utc"] = True  # claim a different audit configuration
    forged = json.dumps(payload, sort_keys=True, indent=2).encode() + b"\n"
    result.quality_report_path.write_bytes(forged)
    manifest_payload = json.loads(result.manifest_path.read_bytes())
    manifest_payload["quality_report_sha256"] = sha256_bytes(forged)
    result.manifest_path.write_bytes(json.dumps(manifest_payload).encode())
    with pytest.raises(DatasetVerificationError, match="mismatch on assume_utc"):
        load_canonical_dataset(result.manifest_path)


def test_build_flags_are_recorded_in_manifest_and_report(
    tmp_path: Path, canonical: pd.DataFrame
) -> None:
    naive = canonical.reset_index()
    naive["timestamp"] = naive["timestamp"].dt.tz_localize(None)
    extra = naive.assign(symbol="ETH/USD")
    path = tmp_path / "raw.csv"
    extra.to_csv(path, index=False)

    result = build_canonical_dataset(
        path, IDENTITY, tmp_path / "out", assume_utc=True, allow_extra_columns=True
    )
    assert result.manifest.assume_utc is True
    assert result.manifest.allow_extra_columns is True
    assert result.quality_report.assume_utc is True
    assert result.quality_report.allow_extra_columns is True
    loaded = load_canonical_dataset(result.manifest_path)
    assert loaded.quality_report.assume_utc is True
