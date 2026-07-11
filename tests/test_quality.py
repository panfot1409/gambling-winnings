"""Tests for the offline data-quality audit: exact counts, first examples."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from eth_research.data.quality import QualityReport, QualityThresholds, audit_frame
from eth_research.data.synthetic import make_synthetic_ohlcv

DAY = pd.Timedelta("1D")


def raw_frame(n: int = 8) -> pd.DataFrame:
    frame = make_synthetic_ohlcv(n_periods=n, seed=11).reset_index()
    frame["timestamp"] = frame["timestamp"].astype(str)
    return frame


def audit(frame: pd.DataFrame, **kwargs: object) -> QualityReport:
    return audit_frame(frame, expected_interval=DAY, **kwargs)  # type: ignore[arg-type]


def finding_codes(report: QualityReport) -> list[str]:
    return [finding.code for finding in report.findings]


def get(report: QualityReport, code: str) -> object:
    matches = [finding for finding in report.findings if finding.code == code]
    assert len(matches) == 1, f"expected exactly one {code!r} finding: {report.findings}"
    return matches[0]


def test_clean_frame_has_no_findings() -> None:
    report = audit(raw_frame())
    assert report.findings == ()
    assert not report.has_errors
    assert report.row_count == 8


def test_duplicate_timestamps_reported() -> None:
    frame = raw_frame()
    frame.loc[3, "timestamp"] = frame.loc[2, "timestamp"]
    finding = get(audit(frame), "duplicate_timestamps")
    assert finding.severity == "error"  # type: ignore[attr-defined]
    assert finding.count == 1  # type: ignore[attr-defined]


def test_unsorted_timestamps_reported_not_repaired() -> None:
    frame = raw_frame().iloc[::-1].reset_index(drop=True)
    finding = get(audit(frame), "unsorted_timestamps")
    assert finding.severity == "error"  # type: ignore[attr-defined]
    assert finding.count == 7  # type: ignore[attr-defined]
    assert "never sorted" in finding.description  # type: ignore[attr-defined]


def test_missing_candles_reported_with_gap_details() -> None:
    frame = raw_frame(8).drop(index=3).reset_index(drop=True)
    finding = get(audit(frame), "missing_candles")
    assert finding.severity == "error"  # type: ignore[attr-defined]
    assert finding.count == 1  # type: ignore[attr-defined]
    assert "spacing 2 days" in finding.first_examples[0]  # type: ignore[attr-defined]


def test_naive_timestamps_require_opt_in() -> None:
    frame = raw_frame()
    frame["timestamp"] = frame["timestamp"].str.replace("+00:00", "", regex=False)
    finding = get(audit(frame), "naive_timestamps")
    assert finding.count == 8  # type: ignore[attr-defined]
    assert audit(frame, assume_utc=True).findings == ()


def test_unparseable_and_missing_timestamps_reported() -> None:
    frame = raw_frame()
    frame.loc[2, "timestamp"] = "not-a-date"
    frame.loc[5, "timestamp"] = None
    report = audit(frame)
    bad = get(report, "unparseable_timestamps")
    assert bad.count == 1  # type: ignore[attr-defined]
    assert "row 2: 'not-a-date'" in bad.first_examples  # type: ignore[attr-defined]
    missing = get(report, "missing_timestamps")
    assert missing.count == 1  # type: ignore[attr-defined]


def test_numeric_timestamps_reported() -> None:
    frame = raw_frame()
    frame["timestamp"] = np.arange(len(frame))
    finding = get(audit(frame), "numeric_timestamps")
    assert finding.severity == "error"  # type: ignore[attr-defined]


def test_missing_and_non_finite_values_reported() -> None:
    frame = raw_frame()
    frame.loc[1, "close"] = np.nan
    frame.loc[2, "open"] = np.inf
    report = audit(frame)
    missing = get(report, "missing_values")
    assert missing.count == 1  # type: ignore[attr-defined]
    assert missing.first_examples[0].endswith(": close")  # type: ignore[attr-defined]
    non_finite = get(report, "non_finite_values")
    assert non_finite.count == 1  # type: ignore[attr-defined]


def test_non_numeric_values_reported() -> None:
    frame = raw_frame()
    frame["close"] = frame["close"].astype(object)
    frame.loc[4, "close"] = "oops"
    finding = get(audit(frame), "non_numeric_values")
    assert finding.count == 1  # type: ignore[attr-defined]
    assert "close='oops'" in finding.first_examples[0]  # type: ignore[attr-defined]


def test_non_positive_prices_and_negative_volume_reported() -> None:
    frame = raw_frame()
    frame.loc[0, "low"] = 0.0
    frame.loc[1, "volume"] = -3.0
    report = audit(frame)
    assert get(report, "non_positive_prices").count == 1  # type: ignore[attr-defined]
    assert get(report, "negative_volume").count == 1  # type: ignore[attr-defined]


def test_ohlc_violations_reported() -> None:
    frame = raw_frame()
    frame.loc[2, "high"] = 0.5  # below the body and below low
    frame.loc[4, "low"] = 1e9
    report = audit(frame)
    assert get(report, "high_below_body").count == 1  # type: ignore[attr-defined]
    assert get(report, "low_above_body").count == 1  # type: ignore[attr-defined]
    assert get(report, "high_below_low").count == 2  # type: ignore[attr-defined]


def test_missing_and_unexpected_columns_reported() -> None:
    frame = raw_frame().drop(columns=["volume"])
    frame["symbol"] = "ETH-USD"
    report = audit(frame)
    assert get(report, "missing_columns").count == 1  # type: ignore[attr-defined]
    unexpected = get(report, "unexpected_columns")
    assert unexpected.severity == "error"  # type: ignore[attr-defined]
    assert unexpected.first_examples == ("symbol",)  # type: ignore[attr-defined]


def test_unexpected_columns_downgrade_to_warning_when_dropping_allowed() -> None:
    frame = raw_frame()
    frame["symbol"] = "ETH-USD"
    report = audit(frame, allow_extra_columns=True)
    finding = get(report, "unexpected_columns")
    assert finding.severity == "warning"  # type: ignore[attr-defined]
    assert not report.has_errors


def test_zero_volume_candles_and_longest_run() -> None:
    frame = raw_frame(10)
    frame.loc[[1, 2, 3, 7], "volume"] = 0.0
    report = audit(frame)
    assert not report.has_errors
    assert get(report, "zero_volume_candles").count == 4  # type: ignore[attr-defined]
    run = get(report, "zero_volume_run")
    assert run.count == 3  # type: ignore[attr-defined]
    assert run.severity == "warning"  # type: ignore[attr-defined]


def test_extreme_returns_and_ranges_flagged_as_warnings() -> None:
    frame = raw_frame(6)
    frame.loc[3, "close"] = float(frame["close"].iloc[2]) * 2.0  # +100% move
    frame.loc[3, "high"] = float(frame["close"].iloc[3]) * 1.6  # huge range
    report = audit(frame)
    assert not report.has_errors
    returns = get(report, "extreme_returns")
    assert returns.severity == "warning"  # type: ignore[attr-defined]
    assert returns.count >= 1  # type: ignore[attr-defined]
    assert get(report, "extreme_ranges").count >= 1  # type: ignore[attr-defined]


def test_thresholds_are_respected() -> None:
    frame = raw_frame(6)
    frame.loc[3, "close"] = float(frame["close"].iloc[2]) * 1.10  # +10% move
    frame.loc[3, "high"] = float(frame["close"].iloc[3]) * 1.02  # keep OHLC valid
    loose = audit(frame, thresholds=QualityThresholds(extreme_return=0.5, extreme_range=5.0))
    assert "extreme_returns" not in finding_codes(loose)
    tight = audit(frame, thresholds=QualityThresholds(extreme_return=0.05, extreme_range=5.0))
    assert "extreme_returns" in finding_codes(tight)


def test_outlier_checks_skipped_on_broken_data() -> None:
    frame = raw_frame(6)
    frame.loc[3, "close"] = float(frame["close"].iloc[2]) * 2.0  # would be extreme
    frame.loc[1, "volume"] = -1.0  # integrity error
    report = audit(frame)
    assert report.has_errors
    assert "extreme_returns" not in finding_codes(report)


def test_invalid_thresholds_rejected() -> None:
    with pytest.raises(ValueError, match="extreme_return"):
        QualityThresholds(extreme_return=0.0)
    with pytest.raises(ValueError, match="extreme_range"):
        QualityThresholds(extreme_range=-1.0)


def test_invalid_expected_interval_rejected() -> None:
    with pytest.raises(ValueError, match="expected_interval"):
        audit_frame(raw_frame(), expected_interval=pd.Timedelta(0))


def test_report_serialization_is_deterministic() -> None:
    frame = raw_frame()
    frame.loc[1, "volume"] = -1.0
    report = audit(frame)
    first = report.to_json_bytes()
    assert first == audit(frame).to_json_bytes()
    payload = json.loads(first)
    assert payload["schema_version"] == 1
    assert payload["row_count"] == 8
    assert payload["expected_interval"] == "P1DT0H0M0S"
    assert payload["findings"][0]["code"] == "negative_volume"


def test_findings_sorted_errors_first() -> None:
    frame = raw_frame(10)
    frame.loc[1, "volume"] = -1.0  # error
    frame.loc[[4, 5], "volume"] = 0.0  # warnings
    severities = [f.severity for f in audit(frame).findings]
    assert severities == sorted(severities)  # "error" sorts before "warning"
