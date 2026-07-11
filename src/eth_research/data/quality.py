"""Offline data-quality audit for raw OHLCV frames.

The audit only **reports** — it never sorts, fills, clips, drops, or
repairs observations. Findings carry a severity:

* ``error`` — integrity problems (duplicates, ordering, missing candles,
  missing/non-finite/non-positive values, OHLC violations, timestamp
  problems, column problems). The dataset builder refuses to build from a
  file with any error finding.
* ``warning`` — diagnostics (zero-volume candles and runs, extreme
  returns, suspicious candle ranges). Thresholds are configurable and are
  diagnostics only: a warning is never permission to modify the data.

Outlier checks run only when no integrity errors exist, because return and
range statistics are meaningless on broken data. Every finding records the
exact affected count and up to three first examples.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from eth_research.data.provenance import (
    require_bool,
    require_int,
    require_nonempty_str,
    require_str,
)
from eth_research.data.schema import OHLCV_COLUMNS, PRICE_COLUMNS, TIMESTAMP_COLUMN

QUALITY_REPORT_SCHEMA_VERSION: int = 1

Severity = Literal["error", "warning"]

_MAX_EXAMPLES: int = 3


@dataclass(frozen=True)
class QualityThresholds:
    """Outlier thresholds — diagnostics only, never permission to modify data.

    Values must be real, finite, non-bool numbers > 0; accepted integers are
    normalized to ``float`` so constructed and parsed instances compare and
    serialize identically.
    """

    extreme_return: float = 0.25
    """Flag candles where ``|close/previous close - 1|`` exceeds this."""
    extreme_range: float = 0.25
    """Flag candles where ``(high - low) / open`` exceeds this."""

    def __post_init__(self) -> None:
        for label in ("extreme_return", "extreme_range"):
            value = getattr(self, label)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{label} must be a real number (bool is rejected), got {value!r}")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be positive and finite, got {value}")
            object.__setattr__(self, label, float(value))


@dataclass(frozen=True)
class QualityFinding:
    """One audited problem: exact count plus the first examples.

    Validated on construction — the same invariants apply whether the
    finding is produced by the audit or parsed back from JSON.
    """

    code: str
    severity: Severity
    count: int
    description: str
    first_examples: tuple[str, ...]

    def __post_init__(self) -> None:
        require_nonempty_str("finding code", self.code)
        if self.severity not in ("error", "warning"):
            raise ValueError(
                f"finding severity must be 'error' or 'warning', got {self.severity!r}"
            )
        if require_int("finding count", self.count) < 1:
            raise ValueError(f"finding count must be a positive integer, got {self.count}")
        require_nonempty_str("finding description", self.description)
        if not isinstance(self.first_examples, tuple) or len(self.first_examples) > _MAX_EXAMPLES:
            raise ValueError(
                f"first_examples must be a tuple of at most {_MAX_EXAMPLES} strings, "
                f"got {self.first_examples!r}"
            )
        for example in self.first_examples:
            require_str("finding example", example)


_REPORT_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "row_count",
        "expected_interval",
        "thresholds",
        "assume_utc",
        "allow_extra_columns",
        "error_finding_count",
        "warning_finding_count",
        "findings",
    }
)
_FINDING_KEYS: frozenset[str] = frozenset(
    {"code", "severity", "count", "description", "first_examples"}
)


@dataclass(frozen=True)
class QualityReport:
    """Immutable result of auditing one raw OHLCV frame.

    Records the two build flags that shaped the audit so the manifest can
    bind the evidence to the exact audit configuration. Every field is
    validated in ``__post_init__`` — the single shared path for constructed
    and parsed reports.

    Canonical finding order is part of the format: findings must be sorted
    by ``(severity, code)`` with no duplicate pairs ("error" sorts before
    "warning"). Reports that are constructed or parsed in any other order
    are rejected.
    """

    schema_version: int
    row_count: int
    expected_interval: pd.Timedelta
    thresholds: QualityThresholds
    assume_utc: bool
    allow_extra_columns: bool
    findings: tuple[QualityFinding, ...]

    def __post_init__(self) -> None:
        version = require_int("schema_version", self.schema_version)
        if version != QUALITY_REPORT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported quality report schema version {version!r}; "
                f"this package reads version {QUALITY_REPORT_SCHEMA_VERSION}"
            )
        if require_int("row_count", self.row_count) < 0:
            raise ValueError(f"row_count must be non-negative, got {self.row_count}")
        if (
            not isinstance(self.expected_interval, pd.Timedelta)
            or pd.isna(self.expected_interval)
            or self.expected_interval <= pd.Timedelta(0)
        ):
            raise ValueError(
                f"expected_interval must be a positive Timedelta, got {self.expected_interval!r}"
            )
        if not isinstance(self.thresholds, QualityThresholds):
            raise ValueError("thresholds must be a QualityThresholds instance")
        require_bool("assume_utc", self.assume_utc)
        require_bool("allow_extra_columns", self.allow_extra_columns)
        if not isinstance(self.findings, tuple):
            raise ValueError("findings must be a tuple of QualityFinding instances")
        previous_key: tuple[str, str] | None = None
        for finding in self.findings:
            if not isinstance(finding, QualityFinding):
                raise ValueError("findings must be QualityFinding instances")
            key = (finding.severity, finding.code)
            if previous_key is not None and key <= previous_key:
                raise ValueError(
                    "findings must be in canonical order: sorted by (severity, code) "
                    f"with no duplicates; {key!r} follows {previous_key!r}"
                )
            previous_key = key

    @property
    def error_count(self) -> int:
        return sum(finding.count for finding in self.findings if finding.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(finding.count for finding in self.findings if finding.severity == "warning")

    @property
    def error_codes(self) -> tuple[str, ...]:
        return tuple(f.code for f in self.findings if f.severity == "error")

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == "error" for finding in self.findings)

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "row_count": self.row_count,
            "expected_interval": self.expected_interval.isoformat(),
            "thresholds": {
                "extreme_return": self.thresholds.extreme_return,
                "extreme_range": self.thresholds.extreme_range,
            },
            "assume_utc": self.assume_utc,
            "allow_extra_columns": self.allow_extra_columns,
            "error_finding_count": len(self.error_codes),
            "warning_finding_count": sum(1 for f in self.findings if f.severity == "warning"),
            "findings": [
                {
                    "code": finding.code,
                    "severity": finding.severity,
                    "count": finding.count,
                    "description": finding.description,
                    "first_examples": list(finding.first_examples),
                }
                for finding in self.findings
            ],
        }
        return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> QualityReport:
        """Strict parse: exact keys, exact JSON types, no repair."""
        try:
            payload: Any = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"quality report is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("quality report JSON must be an object")
        keys = set(payload)
        if keys != _REPORT_KEYS:
            unknown = sorted(keys - _REPORT_KEYS)
            missing = sorted(_REPORT_KEYS - keys)
            raise ValueError(
                f"quality report keys do not match schema: unknown={unknown}, missing={missing}"
            )

        interval_text = payload["expected_interval"]
        if not isinstance(interval_text, str):
            raise ValueError("expected_interval must be a string")
        try:
            interval = pd.Timedelta(interval_text)
        except ValueError as exc:
            raise ValueError(f"expected_interval is unparseable: {interval_text!r}") from exc

        # Declared counts must be well-typed BEFORE any comparison: Python's
        # False == 0 and True == 1 would otherwise let booleans slip through.
        declared_counts: dict[str, int] = {}
        for label in ("error_finding_count", "warning_finding_count"):
            declared = require_int(label, payload[label])
            if declared < 0:
                raise ValueError(f"{label} must be >= 0, got {declared}")
            declared_counts[label] = declared

        thresholds_payload = payload["thresholds"]
        if not isinstance(thresholds_payload, dict) or set(thresholds_payload) != {
            "extreme_return",
            "extreme_range",
        }:
            raise ValueError("thresholds must contain exactly extreme_return and extreme_range")

        findings_payload = payload["findings"]
        if not isinstance(findings_payload, list):
            raise ValueError("findings must be a list")
        findings: list[QualityFinding] = []
        for entry in findings_payload:
            if not isinstance(entry, dict) or set(entry) != _FINDING_KEYS:
                raise ValueError(
                    f"finding entries must have exactly the keys {sorted(_FINDING_KEYS)}"
                )
            examples = entry["first_examples"]
            if not isinstance(examples, list):
                raise ValueError("finding first_examples must be a list of strings")
            # Field invariants live in QualityFinding.__post_init__ — the
            # same path that validates audit-constructed findings.
            findings.append(
                QualityFinding(
                    code=entry["code"],
                    severity=entry["severity"],
                    count=entry["count"],
                    description=entry["description"],
                    first_examples=tuple(examples),
                )
            )

        report = cls(
            schema_version=payload["schema_version"],
            row_count=payload["row_count"],
            expected_interval=interval,
            thresholds=QualityThresholds(
                extreme_return=thresholds_payload["extreme_return"],
                extreme_range=thresholds_payload["extreme_range"],
            ),
            assume_utc=payload["assume_utc"],
            allow_extra_columns=payload["allow_extra_columns"],
            findings=tuple(findings),
        )
        error_findings = sum(1 for f in report.findings if f.severity == "error")
        warning_findings = sum(1 for f in report.findings if f.severity == "warning")
        if declared_counts["error_finding_count"] != error_findings:
            raise ValueError("error_finding_count does not match the findings list")
        if declared_counts["warning_finding_count"] != warning_findings:
            raise ValueError("warning_finding_count does not match the findings list")
        return report


def _examples(items: list[str]) -> tuple[str, ...]:
    return tuple(items[:_MAX_EXAMPLES])


def audit_frame(
    raw: pd.DataFrame,
    *,
    expected_interval: pd.Timedelta,
    assume_utc: bool = False,
    allow_extra_columns: bool = False,
    thresholds: QualityThresholds | None = None,
) -> QualityReport:
    """Audit a raw OHLCV frame against the strict schema rules; never repair.

    Mirrors the acceptance rules of
    :func:`eth_research.data.schema.validate_ohlcv` as structured findings,
    then adds warning-severity diagnostics on structurally sound data.
    """
    if not isinstance(expected_interval, pd.Timedelta) or expected_interval <= pd.Timedelta(0):
        raise ValueError(
            f"expected_interval must be a positive Timedelta, got {expected_interval!r}"
        )
    limits = thresholds if thresholds is not None else QualityThresholds()
    findings: list[QualityFinding] = []

    def finish() -> QualityReport:
        ordered = tuple(sorted(findings, key=lambda finding: (finding.severity, finding.code)))
        return QualityReport(
            schema_version=QUALITY_REPORT_SCHEMA_VERSION,
            row_count=len(raw),
            expected_interval=expected_interval,
            thresholds=limits,
            assume_utc=assume_utc,
            allow_extra_columns=allow_extra_columns,
            findings=ordered,
        )

    duplicated_names = [str(c) for c in raw.columns[raw.columns.duplicated()]]
    if duplicated_names:
        findings.append(
            QualityFinding(
                code="duplicated_column_names",
                severity="error",
                count=len(duplicated_names),
                description="column names appear more than once",
                first_examples=_examples(sorted(set(duplicated_names))),
            )
        )
        return finish()

    findings.extend(_column_findings(raw, allow_extra_columns=allow_extra_columns))
    timestamps = _timestamp_findings(raw, findings, assume_utc=assume_utc)
    if timestamps is not None:
        _order_and_gap_findings(timestamps, expected_interval, findings)

    values = _value_findings(raw, timestamps, findings)
    if values is not None:
        _volume_findings(values, timestamps, findings)
        if not any(finding.severity == "error" for finding in findings):
            _outlier_findings(values, timestamps, limits, findings)

    return finish()


def _column_findings(raw: pd.DataFrame, *, allow_extra_columns: bool) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    known = set(OHLCV_COLUMNS) | {TIMESTAMP_COLUMN}
    missing = [c for c in OHLCV_COLUMNS if c not in raw.columns]
    extras = [str(c) for c in raw.columns if c not in known]
    if missing:
        findings.append(
            QualityFinding(
                code="missing_columns",
                severity="error",
                count=len(missing),
                description="required OHLCV column(s) absent",
                first_examples=_examples(missing),
            )
        )
    if extras:
        findings.append(
            QualityFinding(
                code="unexpected_columns",
                severity="warning" if allow_extra_columns else "error",
                count=len(extras),
                description=(
                    "columns outside the OHLCV set"
                    + (
                        " (will be dropped: allow_extra_columns=True)"
                        if allow_extra_columns
                        else " (rejected; pass allow_extra_columns=True to drop)"
                    )
                ),
                first_examples=_examples(extras),
            )
        )
    if len(raw) == 0:
        findings.append(
            QualityFinding(
                code="empty_frame",
                severity="error",
                count=1,
                description="the frame has no rows",
                first_examples=(),
            )
        )
    return findings


def _timestamp_findings(
    raw: pd.DataFrame, findings: list[QualityFinding], *, assume_utc: bool
) -> pd.DatetimeIndex | None:
    """Parse timestamps tolerantly, recording problems; None if unusable."""
    if TIMESTAMP_COLUMN in raw.columns:
        series = raw[TIMESTAMP_COLUMN]
        if pd.api.types.is_numeric_dtype(series):
            findings.append(
                QualityFinding(
                    code="numeric_timestamps",
                    severity="error",
                    count=len(series),
                    description="epoch timestamps must be converted first (loader timestamp_unit)",
                    first_examples=_examples([f"row 0: {series.iloc[0]!r}"] if len(series) else []),
                )
            )
            return None
        parsed, naive_rows, malformed, malformed_positions = _parse_timestamps(series)
    elif isinstance(raw.index, pd.DatetimeIndex):
        parsed = [None if pd.isna(value) else pd.Timestamp(value) for value in raw.index]
        naive_rows = list(range(len(parsed))) if raw.index.tz is None and len(parsed) else []
        malformed = []
        malformed_positions = set()
    else:
        findings.append(
            QualityFinding(
                code="no_timestamps",
                severity="error",
                count=1,
                description="no 'timestamp' column and the index is not a DatetimeIndex",
                first_examples=(),
            )
        )
        return None

    if malformed:
        findings.append(
            QualityFinding(
                code="unparseable_timestamps",
                severity="error",
                count=len(malformed),
                description="values that do not parse as ISO-8601 datetimes",
                first_examples=_examples(malformed),
            )
        )
    if naive_rows and not assume_utc:
        findings.append(
            QualityFinding(
                code="naive_timestamps",
                severity="error",
                count=len(naive_rows),
                description=("timezone-naive timestamps; pass assume_utc=True to interpret as UTC"),
                first_examples=_examples([f"row {r}" for r in naive_rows]),
            )
        )
    missing_rows = [
        position
        for position, value in enumerate(parsed)
        if value is None and position not in malformed_positions
    ]
    if missing_rows:
        findings.append(
            QualityFinding(
                code="missing_timestamps",
                severity="error",
                count=len(missing_rows),
                description="missing (NaT) timestamps",
                first_examples=_examples([f"row {r}" for r in missing_rows]),
            )
        )
    if malformed or missing_rows:
        return None

    utc = [ts.tz_localize("UTC") if ts is not None and ts.tz is None else ts for ts in parsed]
    return pd.DatetimeIndex(utc).as_unit("ns")


def _parse_timestamps(
    series: pd.Series[Any],
) -> tuple[list[pd.Timestamp | None], list[int], list[str], set[int]]:
    parsed: list[pd.Timestamp | None] = []
    naive_rows: list[int] = []
    malformed: list[str] = []
    malformed_positions: set[int] = set()
    for position, value in enumerate(series):
        if pd.isna(value):
            parsed.append(None)
            continue
        try:
            converted: Any = pd.to_datetime(value, format="ISO8601")
        except (ValueError, TypeError):
            malformed.append(f"row {position}: {value!r}")
            malformed_positions.add(position)
            parsed.append(None)
            continue
        if pd.isna(converted):
            parsed.append(None)
            continue
        timestamp = pd.Timestamp(converted)
        if timestamp.tz is None:
            naive_rows.append(position)
            parsed.append(timestamp)
        else:
            parsed.append(timestamp.tz_convert("UTC"))
    return parsed, naive_rows, malformed, malformed_positions


def _order_and_gap_findings(
    timestamps: pd.DatetimeIndex,
    expected_interval: pd.Timedelta,
    findings: list[QualityFinding],
) -> None:
    if len(timestamps) < 2:
        return
    duplicated_mask = timestamps.duplicated()
    if bool(duplicated_mask.any()):
        duplicates = timestamps[duplicated_mask]
        findings.append(
            QualityFinding(
                code="duplicate_timestamps",
                severity="error",
                count=int(duplicated_mask.sum()),
                description="open times that appear more than once",
                first_examples=_examples([str(ts) for ts in duplicates[:_MAX_EXAMPLES]]),
            )
        )
    spacings = timestamps[1:] - timestamps[:-1]
    out_of_order = int((spacings < pd.Timedelta(0)).sum())
    if out_of_order > 0:
        examples = [
            f"{timestamps[i]} -> {timestamps[i + 1]}"
            for i in range(len(spacings))
            if spacings[i] < pd.Timedelta(0)
        ]
        findings.append(
            QualityFinding(
                code="unsorted_timestamps",
                severity="error",
                count=out_of_order,
                description="open times that go backwards; data is never sorted for you",
                first_examples=_examples(examples),
            )
        )
        return  # gap analysis is meaningless on unsorted data
    if bool(duplicated_mask.any()):
        return
    irregular = spacings != expected_interval
    if bool(irregular.any()):
        examples = [
            f"{timestamps[i]} -> {timestamps[i + 1]} (spacing {spacings[i]})"
            for i in range(len(spacings))
            if spacings[i] != expected_interval
        ]
        findings.append(
            QualityFinding(
                code="missing_candles",
                severity="error",
                count=int(irregular.sum()),
                description=(
                    f"intervals that differ from the expected {expected_interval} "
                    "(missing candles or irregular gaps; never filled)"
                ),
                first_examples=_examples(examples),
            )
        )


def _value_findings(
    raw: pd.DataFrame,
    timestamps: pd.DatetimeIndex | None,
    findings: list[QualityFinding],
) -> pd.DataFrame | None:
    """Coerce OHLCV columns to float, recording problems; None if unusable."""
    present = [c for c in OHLCV_COLUMNS if c in raw.columns]
    if len(present) != len(OHLCV_COLUMNS) or len(raw) == 0:
        return None

    def label(position: int) -> str:
        if timestamps is not None and position < len(timestamps):
            return str(timestamps[position])
        return f"row {position}"

    coerced = pd.DataFrame(index=raw.index)
    non_numeric: list[str] = []
    non_numeric_count = 0
    for column in present:
        original = raw[column]
        numeric = pd.to_numeric(original, errors="coerce")
        newly_missing = numeric.isna() & ~original.isna()
        if bool(newly_missing.any()):
            non_numeric_count += int(newly_missing.sum())
            for position in np.flatnonzero(newly_missing.to_numpy())[:_MAX_EXAMPLES]:
                non_numeric.append(
                    f"{label(int(position))}: {column}={original.iloc[int(position)]!r}"
                )
        coerced[column] = numeric.astype(float)
    if non_numeric_count:
        findings.append(
            QualityFinding(
                code="non_numeric_values",
                severity="error",
                count=non_numeric_count,
                description="values that are not numbers",
                first_examples=_examples(non_numeric),
            )
        )
        return None

    def collect(mask: Any, column: str) -> tuple[int, list[str]]:
        positions = np.flatnonzero(np.asarray(mask, dtype=bool))
        return len(positions), [f"{label(int(p))}: {column}" for p in positions[:_MAX_EXAMPLES]]

    missing_total = 0
    missing_examples: list[str] = []
    non_finite_total = 0
    non_finite_examples: list[str] = []
    non_positive_total = 0
    non_positive_examples: list[str] = []
    for column in OHLCV_COLUMNS:
        series = coerced[column]
        count, examples = collect(series.isna(), column)
        missing_total += count
        missing_examples.extend(examples)
        count, examples = collect(np.isinf(series.to_numpy(dtype=float)), column)
        non_finite_total += count
        non_finite_examples.extend(examples)
    for column in PRICE_COLUMNS:
        series = coerced[column]
        count, examples = collect(series.notna() & (series <= 0), column)
        non_positive_total += count
        non_positive_examples.extend(examples)
    negative_volume_count, negative_volume_examples = collect(
        coerced["volume"].notna() & (coerced["volume"] < 0), "volume"
    )

    if missing_total:
        findings.append(
            QualityFinding(
                code="missing_values",
                severity="error",
                count=missing_total,
                description="missing (NaN) OHLCV values",
                first_examples=_examples(missing_examples),
            )
        )
    if non_finite_total:
        findings.append(
            QualityFinding(
                code="non_finite_values",
                severity="error",
                count=non_finite_total,
                description="infinite OHLCV values",
                first_examples=_examples(non_finite_examples),
            )
        )
    if non_positive_total:
        findings.append(
            QualityFinding(
                code="non_positive_prices",
                severity="error",
                count=non_positive_total,
                description="prices that are zero or negative",
                first_examples=_examples(non_positive_examples),
            )
        )
    if negative_volume_count:
        findings.append(
            QualityFinding(
                code="negative_volume",
                severity="error",
                count=negative_volume_count,
                description="negative volume values",
                first_examples=_examples(negative_volume_examples),
            )
        )
    if missing_total or non_finite_total:
        return None

    high = coerced["high"]
    low = coerced["low"]
    body_high = coerced[["open", "close"]].max(axis=1)
    body_low = coerced[["open", "close"]].min(axis=1)
    for code, mask, description in (
        ("high_below_body", high < body_high, "high below max(open, close)"),
        ("low_above_body", low > body_low, "low above min(open, close)"),
        ("high_below_low", high < low, "high below low"),
    ):
        count, examples = collect(mask, code)
        if count:
            findings.append(
                QualityFinding(
                    code=code,
                    severity="error",
                    count=count,
                    description=description,
                    first_examples=_examples(examples),
                )
            )
    return coerced


def _volume_findings(
    values: pd.DataFrame,
    timestamps: pd.DatetimeIndex | None,
    findings: list[QualityFinding],
) -> None:
    volume = values["volume"].to_numpy(dtype=float)
    zero_positions = np.flatnonzero(volume == 0.0)
    if len(zero_positions) == 0:
        return

    def label(position: int) -> str:
        if timestamps is not None and position < len(timestamps):
            return str(timestamps[position])
        return f"row {position}"

    findings.append(
        QualityFinding(
            code="zero_volume_candles",
            severity="warning",
            count=len(zero_positions),
            description="candles with zero traded volume",
            first_examples=_examples([label(int(p)) for p in zero_positions[:_MAX_EXAMPLES]]),
        )
    )
    longest, longest_start, current, current_start = 0, 0, 0, 0
    for position, is_zero in enumerate(volume == 0.0):
        if is_zero:
            if current == 0:
                current_start = position
            current += 1
            if current > longest:
                longest, longest_start = current, current_start
        else:
            current = 0
    if longest >= 2:
        findings.append(
            QualityFinding(
                code="zero_volume_run",
                severity="warning",
                count=longest,
                description="longest run of consecutive zero-volume candles",
                first_examples=(f"starts at {label(longest_start)}",),
            )
        )


def _outlier_findings(
    values: pd.DataFrame,
    timestamps: pd.DatetimeIndex | None,
    limits: QualityThresholds,
    findings: list[QualityFinding],
) -> None:
    def label(position: int) -> str:
        if timestamps is not None and position < len(timestamps):
            return str(timestamps[position])
        return f"row {position}"

    closes = values["close"].to_numpy(dtype=float)
    if len(closes) >= 2:
        returns = closes[1:] / closes[:-1] - 1.0
        extreme = np.flatnonzero(np.abs(returns) > limits.extreme_return)
        if len(extreme):
            findings.append(
                QualityFinding(
                    code="extreme_returns",
                    severity="warning",
                    count=len(extreme),
                    description=(
                        f"|close-to-close return| above {limits.extreme_return:.2%} "
                        "(diagnostic only; data is never modified)"
                    ),
                    first_examples=_examples(
                        [
                            f"{label(int(p) + 1)}: {returns[int(p)]:+.2%}"
                            for p in extreme[:_MAX_EXAMPLES]
                        ]
                    ),
                )
            )
    ranges = (values["high"].to_numpy(dtype=float) - values["low"].to_numpy(dtype=float)) / values[
        "open"
    ].to_numpy(dtype=float)
    wide = np.flatnonzero(ranges > limits.extreme_range)
    if len(wide):
        findings.append(
            QualityFinding(
                code="extreme_ranges",
                severity="warning",
                count=len(wide),
                description=(
                    f"(high - low) / open above {limits.extreme_range:.2%} "
                    "(diagnostic only; data is never modified)"
                ),
                first_examples=_examples(
                    [f"{label(int(p))}: {ranges[int(p)]:.2%}" for p in wide[:_MAX_EXAMPLES]]
                ),
            )
        )
