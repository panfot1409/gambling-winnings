"""V2B BTC-USD acquisition plan + strict offline response parser."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from eth_research.v2b import acquisition as aq


def _synthetic_body(window: aq.BtcAcquisitionWindow, *, base: float = 100.0) -> bytes:
    t0 = int(window.window_start.timestamp())
    rows = [
        [t0 + i * 86400, base + i, base + 20 + i, base + 5 + i, base + 10 + i, 3.0]
        for i in range(window.expected_open_count())
    ]
    return json.dumps(list(reversed(rows))).encode()  # Coinbase returns newest-first


def test_plan_reproduces_and_covers_the_exact_window() -> None:
    plan = aq.build_btc_acquisition_plan()
    assert plan.product == "BTC-USD"
    assert plan.expected_request_count() == 8
    assert sum(w.expected_open_count() for w in plan.windows) == aq.EXPECTED_DAILY_OPENS == 2221
    assert plan.windows[0].window_start == aq.WINDOW_START
    assert plan.windows[-1].window_end == aq.WINDOW_END_EXCLUSIVE
    assert plan.windows[0].requested_start == "2016-05-23T00:00:00Z"
    assert plan.windows[-1].requested_end == "2022-06-21T00:00:00Z"
    assert aq.build_btc_acquisition_plan().plan_sha256() == plan.plan_sha256()  # deterministic


def test_windows_are_contiguous_and_within_the_cap() -> None:
    plan = aq.build_btc_acquisition_plan()
    for a, b in zip(plan.windows, plan.windows[1:], strict=False):
        assert a.window_end == b.window_start
    assert all(w.expected_open_count() <= aq.MAX_BUCKETS_PER_REQUEST for w in plan.windows)


def test_parser_accepts_in_window_and_excludes_pre_window_rows() -> None:
    plan = aq.build_btc_acquisition_plan()
    w0 = plan.windows[0]
    rows = aq.parse_candles_body(_synthetic_body(w0), w0)
    assert len(rows) == w0.expected_open_count()
    assert rows[0][0] == int(w0.window_start.timestamp())
    # A pre-window candle is excluded, not an error.
    pre = [[int(w0.window_start.timestamp()) - 86400, 1.0, 2.0, 1.5, 1.5, 1.0]]
    body = json.dumps(json.loads(_synthetic_body(w0)) + pre).encode()
    assert len(aq.parse_candles_body(body, w0)) == w0.expected_open_count()


def test_parser_rejects_post_cutoff_duplicate_nonfinite_and_ohlcv_violations() -> None:
    plan = aq.build_btc_acquisition_plan()
    last = plan.windows[-1]
    post = [[int(aq.RESEARCH_CUTOFF_LAST_OPEN.timestamp()) + 86400, 1.0, 2.0, 1.5, 1.5, 1.0]]
    with pytest.raises(aq.BtcAcquisitionError, match="cutoff"):
        aq.parse_candles_body(json.dumps(post).encode(), last)
    w0 = plan.windows[0]
    t0 = int(w0.window_start.timestamp())
    dup = [[t0, 1.0, 2.0, 1.5, 1.5, 1.0], [t0, 1.0, 2.0, 1.5, 1.5, 1.0]]
    with pytest.raises(aq.BtcAcquisitionError, match="duplicate"):
        aq.parse_candles_body(json.dumps(dup).encode(), w0)
    bad_ohlcv = [[t0, 5.0, 2.0, 3.0, 3.0, 1.0]]  # low > high
    with pytest.raises(aq.BtcAcquisitionError):
        aq.parse_candles_body(json.dumps(bad_ohlcv).encode(), w0)
    nonfinite = [[t0, 1.0, 2.0, 0.0, 1.5, 1.0]]  # open == 0 (not positive)
    with pytest.raises(aq.BtcAcquisitionError, match="positive"):
        aq.parse_candles_body(json.dumps(nonfinite).encode(), w0)


def test_receipt_binds_plan_and_body() -> None:
    plan = aq.build_btc_acquisition_plan()
    w0 = plan.windows[0]
    body = _synthetic_body(w0)
    r = aq.build_window_receipt(aq.GENESIS_ATTEMPT_ID, w0, body, plan.plan_sha256())
    assert r.plan_sha256() if False else r.plan_sha256 == plan.plan_sha256()
    assert r.body_bytes == len(body)
    assert r.parsed_open_count == w0.expected_open_count()
    with pytest.raises(aq.BtcAcquisitionError, match="allowlisted"):
        aq.build_window_receipt("not-an-attempt", w0, body, plan.plan_sha256())


def test_canonical_daily_frame_assembles_and_fingerprints() -> None:
    plan = aq.build_btc_acquisition_plan()
    rows_by_window = [aq.parse_candles_body(_synthetic_body(w), w) for w in plan.windows]
    frame = aq.canonical_daily_frame(rows_by_window)
    assert len(frame) == aq.EXPECTED_DAILY_OPENS
    assert pd.Timestamp(frame.index[0]) == aq.WINDOW_START
    assert pd.Timestamp(frame.index[-1]) == aq.RESEARCH_CUTOFF_LAST_OPEN
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    fp = aq.content_fingerprint(frame)
    assert len(fp) == 64
    assert aq.content_fingerprint(frame) == fp  # deterministic


def test_frame_rejects_a_missing_daily_bucket() -> None:
    plan = aq.build_btc_acquisition_plan()
    rows_by_window = [aq.parse_candles_body(_synthetic_body(w), w) for w in plan.windows]
    rows_by_window[0] = rows_by_window[0][:-1]  # drop one bucket → count mismatch / gap
    with pytest.raises(aq.BtcAcquisitionError):
        aq.canonical_daily_frame(rows_by_window)
