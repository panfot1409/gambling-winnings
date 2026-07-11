"""Deterministic canonical dataset builder — offline, local files only.

Pipeline: local CSV/Parquet file → streaming SHA-256 of the raw bytes →
quality audit (reports, never repairs) → refuse on any error-severity
finding → strict schema validation against the declared candle interval →
content fingerprint → write three artifacts:

* ``<slug>.canonical.parquet`` — the validated canonical frame;
* ``<slug>.quality.json`` — the quality report;
* ``<slug>.manifest.json`` — the provenance manifest, written last as the
  completeness marker.

Guarantees:

* the raw source file is opened read-only and never modified;
* observations are never sorted, filled, clipped, dropped, or repaired —
  a problematic file is refused with its findings attached (the only
  transformation is the documented canonicalization: UTC/ns timestamps,
  float64 columns, and — only with ``allow_extra_columns=True`` —
  dropping columns outside the OHLCV set);
* writes are atomic (temp file in the target directory, fsync, then
  ``os.replace``); existing artifacts are never overwritten unless
  ``overwrite=True`` is passed explicitly;
* no network access: URL-like sources are rejected outright. Generated
  artifacts belong under the git-ignored ``data/`` directory and are
  never committed.

``load_canonical_dataset`` is verification-on-read: the manifest is parsed
strictly, the Parquet is re-validated, the content fingerprint is
recomputed and compared, and row count and first/last open times are
cross-checked. Any mismatch raises :class:`DatasetVerificationError`.
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from eth_research.data.provenance import (
    DatasetIdentity,
    DatasetManifest,
    build_manifest,
    content_fingerprint,
    sha256_bytes,
    sha256_file,
)
from eth_research.data.quality import QualityReport, QualityThresholds, audit_frame
from eth_research.data.schema import SchemaError, validate_ohlcv

_NETWORK_PREFIXES: tuple[str, ...] = ("http://", "https://", "ftp://", "s3://", "gs://")


class DatasetBuildError(RuntimeError):
    """The builder refused to build; the audit report (if any) is attached."""

    def __init__(self, message: str, report: QualityReport | None = None) -> None:
        super().__init__(message)
        self.report = report


class DatasetVerificationError(RuntimeError):
    """A canonical dataset failed verification against its manifest."""


@dataclass(frozen=True)
class BuildResult:
    """Artifacts produced by one successful build."""

    canonical_path: Path
    manifest_path: Path
    quality_report_path: Path
    manifest: DatasetManifest
    quality_report: QualityReport


@dataclass(frozen=True)
class LoadedDataset:
    """A verified canonical frame together with its manifest."""

    frame: pd.DataFrame
    manifest: DatasetManifest


def _reject_network_sources(path: str | Path) -> None:
    if str(path).lower().startswith(_NETWORK_PREFIXES):
        raise DatasetBuildError(
            f"network sources are not supported ({path!s}); "
            "Milestone 2A is offline-only — provide a local file"
        )


def read_raw_ohlcv(path: str | Path) -> pd.DataFrame:
    """Read a local CSV/Parquet file without validating or modifying it.

    CSV floats are parsed with round-trip precision so that a CSV and a
    Parquet container holding the same values yield bit-identical doubles
    (and therefore the same content fingerprint).
    """
    _reject_network_sources(path)
    file = Path(path)
    suffix = file.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file, float_precision="round_trip")
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(file)
    raise DatasetBuildError(
        f"unsupported data file extension {suffix!r} for {file.name!r}; "
        "expected .csv, .parquet, or .pq"
    )


def audit_ohlcv_file(
    path: str | Path,
    *,
    expected_interval: pd.Timedelta,
    assume_utc: bool = False,
    allow_extra_columns: bool = False,
    thresholds: QualityThresholds | None = None,
) -> QualityReport:
    """Audit a raw local OHLCV file; report problems without touching it."""
    raw = read_raw_ohlcv(path)
    return audit_frame(
        raw,
        expected_interval=expected_interval,
        assume_utc=assume_utc,
        allow_extra_columns=allow_extra_columns,
        thresholds=thresholds,
    )


def build_canonical_dataset(
    source_path: str | Path,
    identity: DatasetIdentity,
    output_dir: str | Path,
    *,
    assume_utc: bool = False,
    allow_extra_columns: bool = False,
    thresholds: QualityThresholds | None = None,
    overwrite: bool = False,
) -> BuildResult:
    """Turn a local raw OHLCV file into an audited canonical dataset.

    Refuses to build — raising :class:`DatasetBuildError` with the quality
    report attached — if the audit produces any error-severity finding.
    Nothing is ever repaired on the caller's behalf.
    """
    _reject_network_sources(source_path)
    source = Path(source_path)
    raw_sha256 = sha256_file(source)
    raw = read_raw_ohlcv(source)

    report = audit_frame(
        raw,
        expected_interval=identity.interval,
        assume_utc=assume_utc,
        allow_extra_columns=allow_extra_columns,
        thresholds=thresholds,
    )
    if report.has_errors:
        summary = "; ".join(
            f"{finding.code} (count {finding.count})"
            for finding in report.findings
            if finding.severity == "error"
        )
        raise DatasetBuildError(
            f"refusing to build from {source.name!r}: integrity errors — {summary}. "
            "The raw data is never repaired; fix the source file.",
            report=report,
        )

    canonical = validate_ohlcv(
        raw,
        expected_interval=identity.interval,
        assume_utc=assume_utc,
        allow_extra_columns=allow_extra_columns,
    )

    slug = identity.slug
    directory = Path(output_dir)
    canonical_path = directory / f"{slug}.canonical.parquet"
    quality_path = directory / f"{slug}.quality.json"
    manifest_path = directory / f"{slug}.manifest.json"
    existing = [p for p in (canonical_path, quality_path, manifest_path) if p.exists()]
    if existing and not overwrite:
        names = ", ".join(p.name for p in existing)
        raise DatasetBuildError(
            f"refusing to overwrite existing artifact(s) in {directory}: {names}. "
            "Pass overwrite=True to replace them explicitly."
        )

    quality_bytes = report.to_json_bytes()
    manifest = build_manifest(
        canonical,
        identity,
        raw_filename=source.name,
        raw_file_sha256=raw_sha256,
        canonical_filename=canonical_path.name,
        quality_report_filename=quality_path.name,
        quality_report_sha256=sha256_bytes(quality_bytes),
        assume_utc=assume_utc,
        allow_extra_columns=allow_extra_columns,
    )

    directory.mkdir(parents=True, exist_ok=True)
    parquet_buffer = io.BytesIO()
    canonical.to_parquet(parquet_buffer)
    _write_atomic(canonical_path, parquet_buffer.getvalue())
    _write_atomic(quality_path, quality_bytes)
    _write_atomic(manifest_path, manifest.to_json_bytes())

    return BuildResult(
        canonical_path=canonical_path,
        manifest_path=manifest_path,
        quality_report_path=quality_path,
        manifest=manifest,
        quality_report=report,
    )


def load_canonical_dataset(manifest_path: str | Path) -> LoadedDataset:
    """Load a canonical dataset, verifying it against its manifest.

    Detects manifest tampering and data/manifest mismatches: strict
    manifest parsing, schema re-validation, fingerprint recomputation, and
    row-count / first / last open-time cross-checks.
    """
    path = Path(manifest_path)
    try:
        manifest = DatasetManifest.from_json_bytes(path.read_bytes())
    except ValueError as exc:
        raise DatasetVerificationError(f"invalid manifest {path.name!r}: {exc}") from exc

    canonical_path = path.parent / manifest.canonical_filename
    if not canonical_path.exists():
        raise DatasetVerificationError(
            f"canonical file {manifest.canonical_filename!r} not found next to the manifest"
        )
    try:
        frame = validate_ohlcv(
            pd.read_parquet(canonical_path), expected_interval=manifest.candle_interval
        )
    except SchemaError as exc:
        raise DatasetVerificationError(
            f"canonical file {canonical_path.name!r} fails schema validation: {exc}"
        ) from exc

    checks: list[tuple[str, str, str]] = [
        ("content_fingerprint", manifest.content_fingerprint, content_fingerprint(frame)),
        ("row_count", str(manifest.row_count), str(len(frame))),
        ("first_open_time", manifest.first_open_time.isoformat(), frame.index[0].isoformat()),
        ("last_open_time", manifest.last_open_time.isoformat(), frame.index[-1].isoformat()),
    ]
    for label, expected, actual in checks:
        if expected != actual:
            raise DatasetVerificationError(
                f"data/manifest mismatch on {label}: manifest says {expected!r}, "
                f"data has {actual!r} — the dataset or its manifest was modified"
            )
    return LoadedDataset(frame=frame, manifest=manifest)


def _write_atomic(path: Path, data: bytes) -> None:
    """Write bytes to ``path`` atomically (temp file + fsync + rename)."""
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise
