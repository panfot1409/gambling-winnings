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


def make_manifest(canonical: pd.DataFrame) -> DatasetManifest:
    return build_manifest(
        canonical,
        identity(),
        raw_filename="eth.csv",
        raw_file_sha256="f" * 64,
        canonical_filename="x.canonical.parquet",
        quality_report_filename="x.quality.json",
        quality_report_sha256="a" * 64,
        assume_utc=False,
        allow_extra_columns=False,
    )


def parse_with(canonical: pd.DataFrame, **overrides: object) -> DatasetManifest:
    payload = json.loads(make_manifest(canonical).to_json_bytes())
    payload.update(overrides)
    return DatasetManifest.from_json_bytes(json.dumps(payload).encode())


def test_build_manifest_fields(canonical: pd.DataFrame) -> None:
    manifest = make_manifest(canonical)
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
    assert manifest.quality_report_filename == "x.quality.json"
    assert manifest.quality_report_sha256 == "a" * 64
    assert manifest.assume_utc is False
    assert manifest.allow_extra_columns is False


def test_manifest_never_claims_a_foreign_package_version(canonical: pd.DataFrame) -> None:
    # Tagged v0.1.0 is different code; a manifest built here must carry
    # this build's own version.
    manifest = make_manifest(canonical)
    assert manifest.package_version == __version__
    assert manifest.package_version != "0.1.0"


def test_manifest_serialization_is_deterministic_and_round_trips(
    canonical: pd.DataFrame,
) -> None:
    manifest = make_manifest(canonical)
    first = manifest.to_json_bytes()
    second = manifest.to_json_bytes()
    assert first == second
    assert first.endswith(b"\n")
    payload = json.loads(first)
    assert list(payload) == sorted(payload)  # keys are sorted on disk
    assert DatasetManifest.from_json_bytes(first) == manifest


def test_constructed_and_parsed_manifests_share_one_validation_path(
    canonical: pd.DataFrame,
) -> None:
    """The same ValueError fires whether the bad field is constructed or parsed."""
    manifest = make_manifest(canonical)
    fields = {f: getattr(manifest, f) for f in manifest.__dataclass_fields__}
    fields["row_count"] = True
    with pytest.raises(ValueError, match="bool is rejected"):
        DatasetManifest(**fields)
    with pytest.raises(ValueError, match="bool is rejected"):
        parse_with(canonical, row_count=True)


def test_manifest_rejects_unknown_and_missing_keys(canonical: pd.DataFrame) -> None:
    payload = json.loads(make_manifest(canonical).to_json_bytes())

    tampered = dict(payload)
    tampered["surprise"] = 1
    with pytest.raises(ValueError, match=r"unknown=\['surprise'\]"):
        DatasetManifest.from_json_bytes(json.dumps(tampered).encode())

    del payload["venue"]
    with pytest.raises(ValueError, match=r"missing=\['venue'\]"):
        DatasetManifest.from_json_bytes(json.dumps(payload).encode())


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"manifest_schema_version": 999}, "unsupported manifest schema version"),
        ({"manifest_schema_version": True}, "bool is rejected"),
        ({"manifest_schema_version": "1"}, "bool is rejected|must be an integer"),
        ({"row_count": True}, "bool is rejected"),
        ({"row_count": 0}, "row_count must be a positive integer"),
        ({"row_count": -3}, "row_count must be a positive integer"),
        ({"base_asset": "BTC"}, "base_asset must be 'ETH'"),
        ({"market_type": "futures"}, "market_type must be 'spot'"),
        ({"timestamp_convention": "close time"}, "timestamp_convention"),
        ({"venue": 42}, "venue must be a string"),
        ({"symbol": None}, "symbol must be a string"),
        ({"quote_asset": "   "}, "quote_asset must be a non-empty string"),
        ({"source": ""}, "source must be a non-empty string"),
        ({"package_version": 1.5}, "package_version must be a string"),
        ({"raw_file_sha256": "f" * 63}, "64 lowercase hex"),
        ({"raw_file_sha256": "F" * 64}, "64 lowercase hex"),
        ({"raw_file_sha256": "g" * 64}, "64 lowercase hex"),
        ({"raw_file_sha256": 12345}, "raw_file_sha256 must be a string"),
        ({"quality_report_sha256": "z" * 64}, "64 lowercase hex"),
        ({"content_fingerprint": "0" * 64}, "sha256:<64 lowercase hex"),
        ({"content_fingerprint": "sha256:" + "F" * 64}, "sha256:<64 lowercase hex"),
        ({"content_fingerprint": "md5:" + "0" * 64}, "sha256:<64 lowercase hex"),
        ({"fingerprint_algorithm": "ohlcv-fp-v2/sha256"}, "unsupported fingerprint algorithm"),
        ({"candle_interval": "P0DT0H0M0S"}, "positive Timedelta"),
        ({"candle_interval": "-1D"}, "positive Timedelta"),
        ({"candle_interval": "NaT"}, "positive Timedelta"),
        ({"candle_interval": 86400}, "candle_interval must be a string"),
        ({"first_open_time": "2020-01-01T00:00:00"}, "timezone-aware"),
        ({"first_open_time": "nonsense"}, "unparseable"),
        ({"first_open_time": None}, "first_open_time must be a string"),
        ({"canonical_filename": "../../outside.parquet"}, "safe file basename"),
        ({"canonical_filename": "/etc/passwd"}, "safe file basename"),
        ({"canonical_filename": "dir/inside.parquet"}, "safe file basename"),
        ({"raw_filename": "..\\evil.csv"}, "safe file basename"),
        ({"quality_report_filename": ""}, "non-empty string"),
        ({"assume_utc": "false"}, "assume_utc must be a boolean"),
        ({"allow_extra_columns": 0}, "allow_extra_columns must be a boolean"),
    ],
)
def test_manifest_rejects_adversarial_values(
    canonical: pd.DataFrame, overrides: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        parse_with(canonical, **overrides)


def test_manifest_rejects_disordered_or_inconsistent_time_bounds(
    canonical: pd.DataFrame,
) -> None:
    payload = json.loads(make_manifest(canonical).to_json_bytes())

    swapped = dict(payload)
    swapped["first_open_time"], swapped["last_open_time"] = (
        swapped["last_open_time"],
        swapped["first_open_time"],
    )
    with pytest.raises(ValueError, match="must not be after"):
        DatasetManifest.from_json_bytes(json.dumps(swapped).encode())

    # Ordered but inconsistent with row_count * interval.
    inconsistent = dict(payload)
    inconsistent["row_count"] = 19
    with pytest.raises(ValueError, match=r"row_count"):
        DatasetManifest.from_json_bytes(json.dumps(inconsistent).encode())


def test_manifest_rejects_malformed_json(canonical: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        DatasetManifest.from_json_bytes(b"{nope")
    with pytest.raises(ValueError, match="must be an object"):
        DatasetManifest.from_json_bytes(b"[1, 2]")
