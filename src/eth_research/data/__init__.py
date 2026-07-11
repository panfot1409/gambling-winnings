"""Historical market data: schema, loading, synthetic series, provenance."""

from eth_research.data.builder import (
    BuildResult,
    DatasetBuildError,
    DatasetVerificationError,
    LoadedDataset,
    audit_ohlcv_file,
    build_canonical_dataset,
    load_canonical_dataset,
)
from eth_research.data.load import load_ohlcv
from eth_research.data.provenance import (
    DatasetIdentity,
    DatasetManifest,
    content_fingerprint,
    sha256_file,
)
from eth_research.data.quality import QualityFinding, QualityReport, QualityThresholds
from eth_research.data.schema import (
    OHLCV_COLUMNS,
    PRICE_COLUMNS,
    TIMESTAMP_COLUMN,
    SchemaError,
    frame_interval,
    validate_ohlcv,
)
from eth_research.data.synthetic import make_synthetic_ohlcv

__all__ = [
    "OHLCV_COLUMNS",
    "PRICE_COLUMNS",
    "TIMESTAMP_COLUMN",
    "BuildResult",
    "DatasetBuildError",
    "DatasetIdentity",
    "DatasetManifest",
    "DatasetVerificationError",
    "LoadedDataset",
    "QualityFinding",
    "QualityReport",
    "QualityThresholds",
    "SchemaError",
    "audit_ohlcv_file",
    "build_canonical_dataset",
    "content_fingerprint",
    "frame_interval",
    "load_canonical_dataset",
    "load_ohlcv",
    "make_synthetic_ohlcv",
    "sha256_file",
    "validate_ohlcv",
]
