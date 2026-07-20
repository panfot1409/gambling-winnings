"""V2B offline acquisition runner: emit-plan params + strict staged-response verification.

All fixtures are synthetic; no real BTC price is read. The runner never opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eth_research.v2b import acquire_runner as ar
from eth_research.v2b import acquisition as aq


def _synth_body(window: aq.BtcAcquisitionWindow, *, base: float = 100.0) -> bytes:
    t0 = int(window.window_start.timestamp())
    rows = [
        [t0 + i * 86400, base + i, base + 20 + i, base + 5 + i, base + 10 + i, 3.0]
        for i in range(window.expected_open_count())
    ]
    return json.dumps(list(reversed(rows))).encode()  # Coinbase returns newest-first


def _stage_full(staging: Path, *, http_code: int = 200, ctype: str = "application/json") -> None:
    plan = aq.build_btc_acquisition_plan()
    lines = []
    for w in plan.windows:
        (staging / w.filename).write_bytes(_synth_body(w))
        lines.append(
            json.dumps(
                {
                    "ordinal": w.ordinal,
                    "filename": w.filename,
                    "http_code": http_code,
                    "retrieved_at": "2026-07-19T00:00:00Z",
                    "content_type": ctype,
                }
            )
        )
    (staging / ar.RESPONSES_SIDECAR).write_text("\n".join(lines) + "\n")


def _verify(staging: Path, *, attempt_id: str = aq.GENESIS_ATTEMPT_ID) -> aq.BtcAttemptReceipt:
    return ar.verify_responses_and_write_receipt(
        staging,
        staging / ar.RECEIPT_FILE,
        attempt_id=attempt_id,
        workflow_run_id="run-1",
        source_commit="a" * 40,
        client_identity="curl/8.0.0",
        runner_identity="Linux x86_64",
        created_at_utc="2026-07-19T00:00:00Z",
    )


def test_emit_curl_plan_writes_fixed_params(tmp_path: Path) -> None:
    ar.emit_curl_plan(tmp_path / ar.CURL_PLAN_FILE)
    doc = json.loads((tmp_path / ar.CURL_PLAN_FILE).read_text())
    plan = aq.build_btc_acquisition_plan()
    assert doc["endpoint"] == aq.BTC_CANDLES_ENDPOINT
    assert doc["granularity_seconds"] == aq.BTC_GRANULARITY_SECONDS
    assert doc["plan_sha256"] == plan.plan_sha256()
    assert len(doc["windows"]) == 8
    assert doc["windows"][0]["start_param"] == "2016-05-23T00:00:00Z"
    assert doc["windows"][-1]["end_param"] == "2022-06-21T00:00:00Z"
    # No free-form command string is stored.
    assert "curl" not in json.dumps(doc)
    assert "run" not in doc


def test_verify_accepts_full_synthetic_and_reproduces_receipt(tmp_path: Path) -> None:
    _stage_full(tmp_path)
    receipt = _verify(tmp_path)
    assert receipt.total_parsed_opens() == aq.EXPECTED_DAILY_OPENS == 2221
    assert len(receipt.windows) == 8
    assert receipt.plan_sha256 == aq.build_btc_acquisition_plan().plan_sha256()
    assert receipt.to_json_bytes() == (tmp_path / ar.RECEIPT_FILE).read_bytes()


def test_verify_rejects_non_200(tmp_path: Path) -> None:
    _stage_full(tmp_path, http_code=429)
    with pytest.raises(aq.BtcAcquisitionError, match="not 200"):
        _verify(tmp_path)


def test_verify_rejects_wrong_content_type(tmp_path: Path) -> None:
    _stage_full(tmp_path, ctype="text/html")
    with pytest.raises(aq.BtcAcquisitionError, match="content-type"):
        _verify(tmp_path)


def test_verify_rejects_unexpected_staged_file(tmp_path: Path) -> None:
    _stage_full(tmp_path)
    (tmp_path / "sneaky.json").write_text("[]")
    with pytest.raises(aq.BtcAcquisitionError, match="unexpected staged files"):
        _verify(tmp_path)


def test_verify_rejects_missing_body(tmp_path: Path) -> None:
    _stage_full(tmp_path)
    plan = aq.build_btc_acquisition_plan()
    (tmp_path / plan.windows[0].filename).unlink()
    with pytest.raises(aq.BtcAcquisitionError, match="missing raw body"):
        _verify(tmp_path)


def test_verify_rejects_short_window(tmp_path: Path) -> None:
    plan = aq.build_btc_acquisition_plan()
    _stage_full(tmp_path)
    # Drop the last row of window 0's body -> parsed opens < expected.
    w0 = plan.windows[0]
    rows = json.loads((tmp_path / w0.filename).read_bytes())
    (tmp_path / w0.filename).write_bytes(json.dumps(rows[1:]).encode())
    with pytest.raises(aq.BtcAcquisitionError, match="expected"):
        _verify(tmp_path)


def test_verify_rejects_sidecar_key_mismatch(tmp_path: Path) -> None:
    _stage_full(tmp_path)
    bad = (tmp_path / ar.RESPONSES_SIDECAR).read_text().splitlines()
    bad[0] = json.dumps({"ordinal": 0, "filename": "candles_000.json", "http_code": 200})
    (tmp_path / ar.RESPONSES_SIDECAR).write_text("\n".join(bad) + "\n")
    with pytest.raises(aq.BtcAcquisitionError, match="keys must be"):
        _verify(tmp_path)


def test_verify_rejects_non_allowlisted_attempt(tmp_path: Path) -> None:
    _stage_full(tmp_path)
    with pytest.raises(aq.BtcAcquisitionError, match="allowlisted"):
        _verify(tmp_path, attempt_id="coinbase-btc-usd-research-sneaky-003")


def test_build_attempt_receipt_rejects_wrong_window_count() -> None:
    plan = aq.build_btc_acquisition_plan()
    with pytest.raises(aq.BtcAcquisitionError, match="window receipt count"):
        aq.build_attempt_receipt(
            attempt_id=aq.GENESIS_ATTEMPT_ID,
            package_version="2.0.0.dev1",
            plan=plan,
            window_receipts=(),
            source_commit="a" * 40,
            workflow_run_id="run-1",
            runner_identity="r",
            client_identity="c",
            created_at_utc="2026-07-19T00:00:00Z",
        )
