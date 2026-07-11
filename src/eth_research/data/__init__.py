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
from eth_research.data.coinbase import (
    AcquisitionChunk,
    AcquisitionError,
    AcquisitionEvidence,
    ChunkRequest,
    derive_daily_ohlcv,
    load_acquisition_evidence,
    parse_candles_chunk,
    verify_acquisition_evidence,
    write_acquisition_evidence,
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
    "AcquisitionChunk",
    "AcquisitionError",
    "AcquisitionEvidence",
    "BuildResult",
    "ChunkRequest",
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
    "derive_daily_ohlcv",
    "frame_interval",
    "load_acquisition_evidence",
    "load_canonical_dataset",
    "load_ohlcv",
    "make_synthetic_ohlcv",
    "parse_candles_chunk",
    "sha256_file",
    "validate_ohlcv",
    "verify_acquisition_evidence",
    "write_acquisition_evidence",
]
