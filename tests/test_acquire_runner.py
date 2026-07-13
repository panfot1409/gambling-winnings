"""Offline acquisition driver: emit + strict response validation / receipt."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from eth_research.data.acquire_runner import (
    emit_curl_plan,
    verify_responses_and_write_receipt,
)
from eth_research.data.acquisition_plan import (
    AcquisitionAttemptReceipt,
    build_acquisition_plan,
    load_acquisition_plan,
)
from eth_research.data.coinbase import AcquisitionError

START = pd.Timestamp("2016-05-18", tz="UTC")
END = pd.Timestamp("2016-05-20", tz="UTC")  # 2-day window
# epoch seconds for the two daily opens in the window
_D0 = 1463529600  # 2016-05-18
_D1 = 1463616000  # 2016-05-19


def write_plan(tmp: Path) -> Path:
    plan = build_acquisition_plan(overall_start=START, overall_end=END)
    path = tmp / "plan.json"
    path.write_bytes(plan.to_json_bytes())
    return path


def good_body() -> str:
    # Coinbase newest-first [time, low, high, open, close, volume]
    return json.dumps([[_D1, 9.0, 12.0, 10.0, 11.0, 100.0], [_D0, 8.0, 11.0, 9.0, 10.0, 90.0]])


def stage(tmp: Path, body: str, *, http_code: int = 200, filename: str | None = None) -> Path:
    plan = load_acquisition_plan(tmp / "plan.json")
    window = plan.windows[0]
    name = filename or window.filename
    staging = tmp / "staging"
    staging.mkdir(exist_ok=True)
    (staging / name).write_text(body, encoding="utf-8")
    sidecar = {
        "ordinal": 0,
        "filename": window.filename,
        "http_code": http_code,
        "retrieved_at": "2026-07-12T00:00:00Z",
        "content_type": "application/json",
    }
    (staging / "_responses.jsonl").write_text(json.dumps(sidecar) + "\n", encoding="utf-8")
    return staging


def run_verify(tmp: Path, staging: Path) -> AcquisitionAttemptReceipt:
    return verify_responses_and_write_receipt(
        tmp / "plan.json",
        staging,
        tmp / "receipt.json",
        attempt_id="disc-001",
        workflow_run_id="999",
        source_commit="c" * 40,
        curl_version="curl 8.5.0",
        runner="gha ubuntu-24.04",
    )


class TestEmit:
    def test_emit_writes_curl_plan(self, tmp_path: Path) -> None:
        write_plan(tmp_path)
        out = tmp_path / "curlplan.json"
        assert emit_curl_plan(tmp_path / "plan.json", out) == 0
        doc = json.loads(out.read_bytes())
        assert doc["endpoint"].endswith("/products/ETH-USD/candles")
        assert doc["granularity_seconds"] == 86400
        assert len(doc["windows"]) == 1
        assert doc["windows"][0]["requested_start"] == "2016-05-18T00:00:00Z"


class TestVerifyHappyPath:
    def test_valid_response_produces_receipt(self, tmp_path: Path) -> None:
        write_plan(tmp_path)
        staging = stage(tmp_path, good_body())
        receipt = run_verify(tmp_path, staging)
        assert len(receipt.responses) == 1
        assert receipt.responses[0].http_status == 200
        # receipt round-trips
        raw = (tmp_path / "receipt.json").read_bytes()
        assert AcquisitionAttemptReceipt.from_json_bytes(raw).to_json_bytes() == raw


class TestVerifyFailures:
    def test_missing_sidecar_is_rejected(self, tmp_path: Path) -> None:
        write_plan(tmp_path)
        staging = stage(tmp_path, good_body())
        (staging / "_responses.jsonl").unlink()
        with pytest.raises(AcquisitionError, match="missing response sidecar"):
            run_verify(tmp_path, staging)

    def test_non_200_is_rejected(self, tmp_path: Path) -> None:
        write_plan(tmp_path)
        staging = stage(tmp_path, good_body(), http_code=429)
        with pytest.raises(AcquisitionError, match="HTTP 429"):
            run_verify(tmp_path, staging)

    def test_missing_body_is_rejected(self, tmp_path: Path) -> None:
        write_plan(tmp_path)
        staging = stage(tmp_path, good_body())
        plan = load_acquisition_plan(tmp_path / "plan.json")
        (staging / plan.windows[0].filename).unlink()
        with pytest.raises(AcquisitionError, match="missing raw body"):
            run_verify(tmp_path, staging)

    def test_error_object_body_is_rejected(self, tmp_path: Path) -> None:
        write_plan(tmp_path)
        staging = stage(tmp_path, json.dumps({"message": "NotFound"}))
        with pytest.raises(AcquisitionError, match=r"top-level array|API error"):
            run_verify(tmp_path, staging)

    def test_empty_array_body_is_rejected(self, tmp_path: Path) -> None:
        write_plan(tmp_path)
        staging = stage(tmp_path, "[]")
        with pytest.raises(AcquisitionError, match="no candles"):
            run_verify(tmp_path, staging)

    def test_malformed_row_is_rejected(self, tmp_path: Path) -> None:
        write_plan(tmp_path)
        staging = stage(tmp_path, json.dumps([[_D1, 9.0, 12.0, 10.0, 11.0]]))  # 5 fields
        with pytest.raises(AcquisitionError, match="fields"):
            run_verify(tmp_path, staging)

    def test_stray_file_not_in_plan_is_rejected(self, tmp_path: Path) -> None:
        write_plan(tmp_path)
        staging = stage(tmp_path, good_body())
        (staging / "extra_unexpected.json").write_text("[]", encoding="utf-8")
        with pytest.raises(AcquisitionError, match="unexpected staged file"):
            run_verify(tmp_path, staging)

    def test_out_of_window_row_is_rejected(self, tmp_path: Path) -> None:
        write_plan(tmp_path)
        # a candle at/after window_end (2016-05-20) must be rejected
        after = 1463702400  # 2016-05-20
        staging = stage(tmp_path, json.dumps([[after, 9.0, 12.0, 10.0, 11.0, 100.0]]))
        with pytest.raises(AcquisitionError, match="at or after the declared window end"):
            run_verify(tmp_path, staging)


def _good_sidecar(filename: str) -> dict[str, object]:
    return {
        "ordinal": 0,
        "filename": filename,
        "http_code": 200,
        "retrieved_at": "2026-07-12T00:00:00Z",
        "content_type": "application/json",
    }


def _write_raw_sidecar(staging: Path, *lines: str) -> None:
    (staging / "_responses.jsonl").write_text("".join(line + "\n" for line in lines), "utf-8")


class TestStrictSidecar:
    """P2: the permissive sidecar parse laundered a 500 into a 200 via a
    duplicate key. Every laundering vector is now rejected."""

    def _staged(self, tmp_path: Path) -> tuple[Path, str]:
        write_plan(tmp_path)
        staging = stage(tmp_path, good_body())
        return staging, load_acquisition_plan(tmp_path / "plan.json").windows[0].filename

    def test_duplicate_http_code_key_is_rejected(self, tmp_path: Path) -> None:
        staging, fn = self._staged(tmp_path)
        # A second http_code (200) after a 500 must not launder the failure.
        _write_raw_sidecar(
            staging,
            '{"ordinal":0,"filename":"' + fn + '","http_code":500,'
            '"retrieved_at":"2026-07-12T00:00:00Z",'
            '"content_type":"application/json","http_code":200}',
        )
        with pytest.raises(AcquisitionError, match="duplicate JSON object key"):
            run_verify(tmp_path, staging)

    def test_unknown_key_is_rejected(self, tmp_path: Path) -> None:
        staging, fn = self._staged(tmp_path)
        record = _good_sidecar(fn) | {"note": "x"}
        _write_raw_sidecar(staging, json.dumps(record))
        with pytest.raises(AcquisitionError, match=r"unknown=\['note'\]"):
            run_verify(tmp_path, staging)

    def test_missing_key_is_rejected(self, tmp_path: Path) -> None:
        staging, fn = self._staged(tmp_path)
        record = _good_sidecar(fn)
        del record["content_type"]
        _write_raw_sidecar(staging, json.dumps(record))
        with pytest.raises(AcquisitionError, match=r"missing=\['content_type'\]"):
            run_verify(tmp_path, staging)

    def test_stringified_http_code_is_rejected(self, tmp_path: Path) -> None:
        staging, fn = self._staged(tmp_path)
        _write_raw_sidecar(staging, json.dumps(_good_sidecar(fn) | {"http_code": "200"}))
        with pytest.raises(AcquisitionError, match="http_code must be an integer"):
            run_verify(tmp_path, staging)

    def test_boolean_ordinal_is_rejected(self, tmp_path: Path) -> None:
        staging, fn = self._staged(tmp_path)
        _write_raw_sidecar(staging, json.dumps(_good_sidecar(fn) | {"ordinal": True}))
        with pytest.raises(AcquisitionError, match="ordinal must be an integer"):
            run_verify(tmp_path, staging)

    def test_non_utc_retrieved_at_is_rejected(self, tmp_path: Path) -> None:
        staging, fn = self._staged(tmp_path)
        record = _good_sidecar(fn) | {"retrieved_at": "2026-07-12T00:00:00-05:00"}
        _write_raw_sidecar(staging, json.dumps(record))
        with pytest.raises(AcquisitionError, match="must be in UTC"):
            run_verify(tmp_path, staging)

    def test_non_json_content_type_is_rejected(self, tmp_path: Path) -> None:
        staging, fn = self._staged(tmp_path)
        _write_raw_sidecar(staging, json.dumps(_good_sidecar(fn) | {"content_type": "text/html"}))
        with pytest.raises(AcquisitionError, match="content-type"):
            run_verify(tmp_path, staging)

    def test_filename_mismatch_is_rejected(self, tmp_path: Path) -> None:
        staging, _ = self._staged(tmp_path)
        _write_raw_sidecar(staging, json.dumps(_good_sidecar("evil.json")))
        with pytest.raises(AcquisitionError, match="does not match the plan"):
            run_verify(tmp_path, staging)

    def test_duplicate_ordinal_line_is_rejected(self, tmp_path: Path) -> None:
        staging, fn = self._staged(tmp_path)
        _write_raw_sidecar(staging, json.dumps(_good_sidecar(fn)), json.dumps(_good_sidecar(fn)))
        with pytest.raises(AcquisitionError, match="duplicate record for ordinal"):
            run_verify(tmp_path, staging)

    def test_nan_token_is_rejected(self, tmp_path: Path) -> None:
        staging, fn = self._staged(tmp_path)
        _write_raw_sidecar(
            staging,
            '{"ordinal":0,"filename":"' + fn + '","http_code":NaN,'
            '"retrieved_at":"2026-07-12T00:00:00Z","content_type":"application/json"}',
        )
        with pytest.raises(AcquisitionError, match="not valid strict JSON"):
            run_verify(tmp_path, staging)
