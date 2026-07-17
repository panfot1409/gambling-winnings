"""Public dataset functions: synthetic generation, validation, splitting, canonical build/load.

Every function delegates to the accepted ``eth_research.data`` pipeline and translates its
internal exceptions into the public error taxonomy. No function contacts the network, and
none reads or writes anything outside the paths the caller explicitly supplies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from eth_research.api.errors import DatasetError, DatasetIntegrityError, DatasetSchemaError
from eth_research.api.models import (
    VALIDATION_REPORT_SCHEMA_VERSION,
    CanonicalDataset,
    ChronologicalSplitSpec,
    DatasetHandle,
    DatasetSpec,
    ValidatedDataset,
    ValidationFinding,
    ValidationReport,
    _iso_utc,
)
from eth_research.api.serialization import sha256_hex
from eth_research.data.builder import (
    DatasetBuildError,
    DatasetVerificationError,
)
from eth_research.data.builder import (
    build_canonical_dataset as _internal_build,
)
from eth_research.data.builder import (
    load_canonical_dataset as _internal_load,
)
from eth_research.data.provenance import DatasetIdentity, content_fingerprint
from eth_research.data.quality import QualityReport, audit_frame
from eth_research.data.schema import SchemaError, frame_interval, validate_ohlcv
from eth_research.data.synthetic import make_synthetic_ohlcv
from eth_research.splits import DataSplits
from eth_research.splits import chronological_split as _internal_split

__all__ = [
    "CanonicalDatasetArtifacts",
    "DataSplitResult",
    "build_canonical_dataset",
    "chronological_split",
    "generate_synthetic_dataset",
    "load_canonical_dataset",
    "validate_dataset",
]


def _safe_frame_interval(frame: pd.DataFrame) -> pd.Timedelta:
    """Determine the bar interval, translating the internal ``ValueError`` into the taxonomy.

    ``frame_interval`` raises a bare ``ValueError`` for a frame that is too short to have an
    interval; a caller can provoke that with a one-row dataset, so it must surface as the
    public :class:`DatasetError` rather than an untyped built-in.
    """
    try:
        return frame_interval(frame)
    except (ValueError, TypeError) as exc:
        raise DatasetError(f"could not determine the dataset interval: {exc}") from exc


def _to_validation_report(report: QualityReport) -> ValidationReport:
    findings = tuple(
        ValidationFinding(
            code=finding.code,
            severity=finding.severity,
            count=finding.count,
            description=finding.description,
        )
        for finding in report.findings
    )
    return ValidationReport(
        schema_version=VALIDATION_REPORT_SCHEMA_VERSION,
        row_count=report.row_count,
        interval_seconds=int(report.expected_interval.total_seconds()),
        error_count=report.error_count,
        warning_count=report.warning_count,
        findings=findings,
    )


def _build_validated(
    canonical: pd.DataFrame, *, require_clean: bool, interval: pd.Timedelta | None = None
) -> ValidatedDataset:
    if len(canonical) == 0:
        raise DatasetError("dataset is empty")
    if interval is None:
        interval = _safe_frame_interval(canonical)
    quality = audit_frame(canonical, expected_interval=interval)
    report = _to_validation_report(quality)
    if require_clean and report.error_count > 0:
        raise DatasetIntegrityError(
            f"dataset has {report.error_count} error-severity quality finding(s): "
            + ", ".join(quality.error_codes)
        )
    return ValidatedDataset(
        frame=canonical,
        fingerprint=content_fingerprint(canonical),
        row_count=len(canonical),
        interval_seconds=int(interval.total_seconds()),
        start_time=_iso_utc(pd.Timestamp(canonical.index[0])),
        end_time=_iso_utc(pd.Timestamp(canonical.index[-1])),
        report=report,
    )


def validate_dataset(
    frame: pd.DataFrame, spec: DatasetSpec, *, require_clean: bool = True
) -> ValidatedDataset:
    """Validate a raw OHLCV frame against the canonical schema and quality contract.

    Delegates to :func:`eth_research.data.schema.validate_ohlcv` (hard schema invariants)
    and :func:`eth_research.data.quality.audit_frame` (soft quality findings). A schema
    violation raises :class:`DatasetSchemaError`; if ``require_clean`` (the default), any
    error-severity quality finding raises :class:`DatasetIntegrityError`. The returned
    handle carries the validated frame and a serializable :class:`ValidationReport`.
    """
    if not isinstance(frame, pd.DataFrame):
        raise DatasetError("frame must be a pandas DataFrame")
    try:
        canonical = validate_ohlcv(
            frame,
            expected_interval=spec.interval,
            assume_utc=spec.assume_utc,
            allow_extra_columns=spec.allow_extra_columns,
        )
    except SchemaError as exc:
        raise DatasetSchemaError(f"dataset failed schema validation: {exc}") from exc
    return _build_validated(canonical, require_clean=require_clean, interval=spec.interval)


def generate_synthetic_dataset(
    *,
    n_periods: int = 500,
    interval: str = "1D",
    start: str = "2020-01-01",
    start_price: float = 1_000.0,
    drift: float = 0.0002,
    volatility: float = 0.02,
    seed: int = 0,
) -> ValidatedDataset:
    """Deterministically generate a validated synthetic OHLCV dataset (no network, no I/O).

    Delegates to :func:`eth_research.data.synthetic.make_synthetic_ohlcv`; the same
    arguments always produce the same bytes.
    """
    try:
        frame = make_synthetic_ohlcv(
            n_periods,
            freq=interval,
            start=start,
            start_price=start_price,
            drift=drift,
            volatility=volatility,
            seed=seed,
        )
    except (ValueError, TypeError) as exc:
        raise DatasetError(f"invalid synthetic parameters: {exc}") from exc
    return _build_validated(frame, require_clean=True)


@dataclass(frozen=True)
class DataSplitResult:
    """A chronological train / validation / test split, each a validated handle."""

    train: ValidatedDataset
    validation: ValidatedDataset
    test: ValidatedDataset
    _splits: DataSplits = field(compare=False, repr=False)
    _interval: pd.Timedelta = field(compare=False, repr=False)

    def validation_context(self, bars: int) -> ValidatedDataset:
        """Trailing ``bars`` rows of train, as a warm-up context for a validation run."""
        return self._context(self._splits.validation_context(bars), bars)

    def test_context(self, bars: int) -> ValidatedDataset:
        """Trailing ``bars`` rows of train+validation, as a warm-up context for a test run."""
        return self._context(self._splits.test_context(bars), bars)

    def _context(self, frame: pd.DataFrame, bars: int) -> ValidatedDataset:
        if bars < 1:
            raise DatasetError("context bars must be >= 1")
        return _build_validated(frame, require_clean=False, interval=self._interval)


def chronological_split(dataset: DatasetHandle, spec: ChronologicalSplitSpec) -> DataSplitResult:
    """Split a validated dataset chronologically into train / validation / test segments.

    Delegates to :func:`eth_research.splits.chronological_split`; each returned segment is
    re-wrapped as a validated handle (quality findings are recorded, not fatal).
    """
    frame = dataset.frame
    interval = _safe_frame_interval(frame)
    try:
        splits = _internal_split(
            frame,
            train_fraction=spec.train_fraction,
            validation_fraction=spec.validation_fraction,
        )
    except (ValueError, TypeError) as exc:
        raise DatasetError(f"could not split dataset: {exc}") from exc
    for name, segment in (
        ("train", splits.train),
        ("validation", splits.validation),
        ("test", splits.test),
    ):
        if len(segment) == 0:
            raise DatasetError(
                f"the {name} segment is empty; the dataset is too small for this split"
            )
    return DataSplitResult(
        train=_build_validated(splits.train, require_clean=False, interval=interval),
        validation=_build_validated(splits.validation, require_clean=False, interval=interval),
        test=_build_validated(splits.test, require_clean=False, interval=interval),
        _splits=splits,
        _interval=interval,
    )


@dataclass(frozen=True)
class CanonicalDatasetArtifacts:
    """The on-disk artifacts produced by :func:`build_canonical_dataset`."""

    canonical_path: str
    manifest_path: str
    quality_report_path: str
    fingerprint: str
    manifest_sha256: str
    report: ValidationReport


def build_canonical_dataset(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    symbol: str,
    venue: str,
    quote_asset: str,
    interval_seconds: int,
    source_description: str,
    assume_utc: bool = False,
    allow_extra_columns: bool = False,
    overwrite: bool = False,
) -> CanonicalDatasetArtifacts:
    """Build a canonical dataset (parquet + quality report + manifest) from a local file.

    Delegates to :func:`eth_research.data.builder.build_canonical_dataset`. Reads only
    ``source_path`` and writes only into ``output_dir``. Refuses to overwrite existing
    artifacts unless ``overwrite`` is set, and refuses any error-severity quality finding.
    """
    identity = DatasetIdentity(
        quote_asset=quote_asset,
        symbol=symbol,
        venue=venue,
        interval=pd.Timedelta(seconds=interval_seconds),
        source=source_description,
    )
    try:
        result = _internal_build(
            source_path,
            identity,
            output_dir,
            assume_utc=assume_utc,
            allow_extra_columns=allow_extra_columns,
            overwrite=overwrite,
        )
    except SchemaError as exc:
        raise DatasetSchemaError(f"source failed schema validation: {exc}") from exc
    except DatasetBuildError as exc:
        raise DatasetIntegrityError(f"canonical build refused: {exc}") from exc
    except (ValueError, TypeError, OSError) as exc:
        raise DatasetError(f"could not build canonical dataset: {exc}") from exc
    manifest_bytes = result.manifest.to_json_bytes()
    return CanonicalDatasetArtifacts(
        canonical_path=str(result.canonical_path),
        manifest_path=str(result.manifest_path),
        quality_report_path=str(result.quality_report_path),
        fingerprint=result.manifest.content_fingerprint,
        manifest_sha256=sha256_hex(manifest_bytes),
        report=_to_validation_report(result.quality_report),
    )


def load_canonical_dataset(manifest_path: str | Path) -> CanonicalDataset:
    """Load and re-verify a canonical dataset from its manifest.

    Delegates to :func:`eth_research.data.builder.load_canonical_dataset`, which
    re-validates the schema, recomputes the content fingerprint, and cross-checks the
    quality report before returning. A verification failure raises
    :class:`DatasetIntegrityError`.
    """
    try:
        loaded = _internal_load(manifest_path)
    except DatasetVerificationError as exc:
        raise DatasetIntegrityError(f"canonical dataset failed verification: {exc}") from exc
    except (ValueError, TypeError, OSError) as exc:
        raise DatasetError(f"could not load canonical dataset: {exc}") from exc
    frame = loaded.frame
    manifest_bytes = loaded.manifest.to_json_bytes()
    return CanonicalDataset(
        frame=frame,
        fingerprint=loaded.manifest.content_fingerprint,
        row_count=len(frame),
        interval_seconds=int(loaded.manifest.candle_interval.total_seconds()),
        start_time=_iso_utc(pd.Timestamp(frame.index[0])),
        end_time=_iso_utc(pd.Timestamp(frame.index[-1])),
        manifest_sha256=sha256_hex(manifest_bytes),
    )
