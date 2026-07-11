"""Tests for dataset identity, manifest serialization, and fingerprinting."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from eth_research import __version__
from eth_research.data.provenance import (
    FINGERPRINT_ALGORITHM,
    MANIFEST_SCHEMA_VERSION,
    TIMESTAMP_CONVENTION,
    DatasetIdentity,
    DatasetManifest,
    build_manifest,
    content_fingerprint,
    sha256_file,
)
from eth_research.data.synthetic import make_synthetic_ohlcv


def identity(**overrides: object) -> DatasetIdentity:
    values: dict[str, object] = {
        "quote_asset": "USD",
        "symbol": "ETH/USD",
        "venue": "TestVenue",
        "interval": pd.Timedelta("1D"),
        "source": "unit-test synthetic OHLCV",
    }
    values.update(overrides)
    return DatasetIdentity(**values)  # type: ignore[arg-type]


@pytest.fixture
def canonical() -> pd.DataFrame:
    return make_synthetic_ohlcv(n_periods=20, seed=5)


def test_identity_slug_is_filesystem_safe() -> None:
    assert identity().slug == "testvenue-eth-usd-86400s"


def test_identity_is_eth_spot_only() -> None:
    with pytest.raises(ValueError, match="ETH only"):
        identity(base_asset="BTC")
    with pytest.raises(ValueError, match="spot"):
        identity(market_type="futures")


@pytest.mark.parametrize("label", ["quote_asset", "symbol", "venue", "source"])
def test_identity_rejects_empty_fields(label: str) -> None:
    with pytest.raises(ValueError, match=label):
        identity(**{label: "  "})


def test_identity_rejects_non_positive_interval() -> None:
    with pytest.raises(ValueError, match="positive Timedelta"):
        identity(interval=pd.Timedelta(0))


def test_fingerprint_is_deterministic(canonical: pd.DataFrame) -> None:
    assert content_fingerprint(canonical) == content_fingerprint(canonical.copy())
    assert content_fingerprint(canonical).startswith("sha256:")


def test_fingerprint_changes_when_one_value_changes(canonical: pd.DataFrame) -> None:
    modified = canonical.copy()
    closes = modified["close"].to_numpy(dtype=float, copy=True)
    closes[7] *= 1.000001
    modified["close"] = closes
    assert content_fingerprint(modified) != content_fingerprint(canonical)


def test_fingerprint_changes_when_one_timestamp_changes(canonical: pd.DataFrame) -> None:
    shifted = canonical.copy()
    shifted.index = shifted.index + pd.Timedelta("1h")
    assert content_fingerprint(shifted) != content_fingerprint(canonical)


def test_fingerprint_requires_canonical_frame(canonical: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="canonical frame"):
        content_fingerprint(canonical.reset_index())
    with pytest.raises(ValueError, match="exactly the columns"):
        content_fingerprint(canonical[["open", "close"]])
    with pytest.raises(ValueError, match="at least one candle"):
        content_fingerprint(canonical.iloc[0:0])


def test_sha256_file_matches_known_digest(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    path = tmp_path / "blob.bin"
    path.write_bytes(b"abc")
    # SHA-256("abc") is a published test vector.
    assert sha256_file(path) == ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_build_manifest_fields(canonical: pd.DataFrame) -> None:
    manifest = build_manifest(
        canonical,
        identity(),
        raw_filename="eth.csv",
        raw_file_sha256="f" * 64,
        canonical_filename="testvenue-eth-usd-86400s.canonical.parquet",
    )
    assert manifest.manifest_schema_version == MANIFEST_SCHEMA_VERSION
    assert manifest.package_version == __version__
    assert manifest.base_asset == "ETH"
    assert manifest.quote_asset == "USD"
    assert manifest.symbol == "ETH/USD"
    assert manifest.venue == "TestVenue"
    assert manifest.market_type == "spot"
    assert manifest.candle_interval == pd.Timedelta("1D")
    assert manifest.timestamp_convention == TIMESTAMP_CONVENTION
    assert manifest.fingerprint_algorithm == FINGERPRINT_ALGORITHM
    assert manifest.content_fingerprint == content_fingerprint(canonical)
    assert manifest.row_count == 20
    assert manifest.first_open_time == canonical.index[0]
    assert manifest.last_open_time == canonical.index[-1]


def test_manifest_serialization_is_deterministic_and_round_trips(
    canonical: pd.DataFrame,
) -> None:
    manifest = build_manifest(
        canonical,
        identity(),
        raw_filename="eth.csv",
        raw_file_sha256="f" * 64,
        canonical_filename="x.parquet",
    )
    first = manifest.to_json_bytes()
    second = manifest.to_json_bytes()
    assert first == second
    assert first.endswith(b"\n")
    payload = json.loads(first)
    assert list(payload) == sorted(payload)  # keys are sorted on disk
    assert DatasetManifest.from_json_bytes(first) == manifest


def test_manifest_rejects_unknown_and_missing_keys(canonical: pd.DataFrame) -> None:
    manifest = build_manifest(
        canonical,
        identity(),
        raw_filename="eth.csv",
        raw_file_sha256="f" * 64,
        canonical_filename="x.parquet",
    )
    payload = json.loads(manifest.to_json_bytes())

    tampered = dict(payload)
    tampered["surprise"] = 1
    with pytest.raises(ValueError, match=r"unknown=\['surprise'\]"):
        DatasetManifest.from_json_bytes(json.dumps(tampered).encode())

    del payload["venue"]
    with pytest.raises(ValueError, match=r"missing=\['venue'\]"):
        DatasetManifest.from_json_bytes(json.dumps(payload).encode())


def test_manifest_rejects_wrong_schema_version(canonical: pd.DataFrame) -> None:
    manifest = build_manifest(
        canonical,
        identity(),
        raw_filename="eth.csv",
        raw_file_sha256="f" * 64,
        canonical_filename="x.parquet",
    )
    payload = json.loads(manifest.to_json_bytes())
    payload["manifest_schema_version"] = 999
    with pytest.raises(ValueError, match="unsupported manifest schema version"):
        DatasetManifest.from_json_bytes(json.dumps(payload).encode())


def test_manifest_rejects_invalid_values(canonical: pd.DataFrame) -> None:
    manifest = build_manifest(
        canonical,
        identity(),
        raw_filename="eth.csv",
        raw_file_sha256="f" * 64,
        canonical_filename="x.parquet",
    )
    payload = json.loads(manifest.to_json_bytes())

    bad_rows = dict(payload)
    bad_rows["row_count"] = 0
    with pytest.raises(ValueError, match="row_count"):
        DatasetManifest.from_json_bytes(json.dumps(bad_rows).encode())

    naive = dict(payload)
    naive["first_open_time"] = "2020-01-01T00:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        DatasetManifest.from_json_bytes(json.dumps(naive).encode())

    with pytest.raises(ValueError, match="not valid JSON"):
        DatasetManifest.from_json_bytes(b"{nope")
