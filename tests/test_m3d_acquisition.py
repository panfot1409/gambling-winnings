"""Tests for the M3D acquisition plan, receipt models, and offline runner.

The network boundary is the workflow's curl step; these tests exercise the
runner's offline validation by staging synthetic bodies + a status sidecar.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from eth_research.m3d.acquire_runner import (
    RESPONSES_SIDECAR,
    AcquisitionRunnerError,
    emit_curl_plan,
    verify_responses_and_write_receipt,
    window_url,
)
from eth_research.m3d.acquisition_plan import (
    GENESIS_ATTEMPT_ID,
    MAX_BUCKETS_PER_REQUEST,
    ProspectiveAcquisitionPlan,
    build_prospective_acquisition_plan,
)
from eth_research.m3d.receipt import ProspectiveAttemptReceipt

_DOCS = {
    "access_date": "2026-07-15",
    "http_status": 403,
    "accessible": False,
    "source_of_truth": "m2b_verified_adapter_contract",
}
_AS_OF = pd.Timestamp("2026-07-15T00:00:00Z")


def _plan(attempt_id: str = GENESIS_ATTEMPT_ID) -> ProspectiveAcquisitionPlan:
    return build_prospective_acquisition_plan(
        attempt_id=attempt_id, as_of_utc=_AS_OF, docs_recheck=_DOCS
    )


def _epoch(day: str) -> int:
    return int(pd.Timestamp(day).value // 1_000_000_000)


def _synthetic_body() -> bytes:
    rows = [
        [_epoch("2026-07-14T00:00:00Z"), 2900.0, 3100.0, 3000.0, 3050.0, 1234.5],
        [_epoch("2026-07-13T00:00:00Z"), 2850.0, 3050.0, 2950.0, 3000.0, 1111.0],
        [_epoch("2026-07-12T00:00:00Z"), 2800.0, 3000.0, 2900.0, 2950.0, 999.0],
    ]
    return json.dumps(rows).encode("utf-8")


def _stage(
    tmp_path: Path,
    plan: ProspectiveAcquisitionPlan,
    *,
    body: bytes | None = None,
    http_code: int = 200,
    content_type: str = "application/json; charset=utf-8",
    extra_file: str | None = None,
) -> Path:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "acquisition_plan.json").write_bytes(plan.to_json_bytes())
    lines = []
    for window in plan.windows:
        fn = str(window["raw_filename"])
        (raw_dir / fn).write_bytes(_synthetic_body() if body is None else body)
        lines.append(
            json.dumps(
                {
                    "content_type": content_type,
                    "filename": fn,
                    "http_code": http_code,
                    "ordinal": int(window["ordinal"]),
                    "retrieved_at": "2026-07-15T12:00:00Z",
                },
                sort_keys=True,
            )
        )
    (raw_dir / RESPONSES_SIDECAR).write_text("\n".join(lines) + "\n")
    if extra_file:
        (raw_dir / extra_file).write_bytes(b"x")
    return raw_dir


def _verify(raw_dir: Path, plan: ProspectiveAcquisitionPlan) -> ProspectiveAttemptReceipt:
    return verify_responses_and_write_receipt(
        raw_dir / "acquisition_plan.json",
        raw_dir,
        raw_dir / "acquisition_receipt.json",
        attempt_id=plan.attempt_id,
        workflow_run_id="123",
        source_commit="a" * 40,
        client_identity="curl/8.0",
        runner_identity="ubuntu-x64",
        created_at_utc="2026-07-15T12:00:05Z",
    )


# --------------------------------------------------------------------------- #
# plan                                                                        #
# --------------------------------------------------------------------------- #
def test_plan_tiles_contiguously_and_hashes() -> None:
    plan = _plan()
    doc = plan.document
    assert doc["overall_start"] == "2026-07-12T00:00:00Z"
    assert doc["overall_end"] == "2026-07-15T00:00:00Z"
    assert doc["expected_total_buckets"] == 3
    assert ProspectiveAcquisitionPlan.from_mapping(doc).to_json_bytes() == plan.to_json_bytes()


def test_plan_rejects_tampered_hash() -> None:
    doc = dict(_plan().document)
    doc["plan_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="plan_sha256 does not match"):
        ProspectiveAcquisitionPlan.from_mapping(doc)


def test_plan_window_never_exceeds_bucket_cap() -> None:
    assert all(w["expected_bucket_count"] <= MAX_BUCKETS_PER_REQUEST for w in _plan().windows)


def test_plan_request_end_param_is_last_completed_bucket_open() -> None:
    """Coinbase start/end are INCLUSIVE bucket opens, so the request end_param must
    be window_end - 1 day (the last completed bucket), never window_end itself —
    otherwise the request pulls the still-forming candle at window_end."""
    plan = _plan()
    for window in plan.windows:
        window_end = pd.Timestamp(str(window["window_end"]))
        assert window["start_param"] == str(window["window_start"])
        assert pd.Timestamp(str(window["end_param"])) == window_end - pd.Timedelta(days=1)
    # Genesis specifically: request [2026-07-12, 2026-07-14] inclusive → 3 completed
    # candles, excluding the forming 2026-07-15 candle at the half-open window end.
    w0 = plan.windows[0]
    assert w0["start_param"] == "2026-07-12T00:00:00Z"
    assert w0["end_param"] == "2026-07-14T00:00:00Z"
    assert w0["window_end"] == "2026-07-15T00:00:00Z"


def test_plan_rejects_end_param_equal_to_window_end() -> None:
    """Regression: the pre-fix bug set end_param == window_end, which fetched the
    forming candle. The validator must now reject any such plan."""
    doc = json.loads(_plan().to_json_bytes())
    window = doc["windows"][0]
    window["end_param"] = window["window_end"]  # reintroduce the inclusive-boundary bug
    with pytest.raises(ValueError, match="end_param must be the canonical request string"):
        ProspectiveAcquisitionPlan.from_mapping(doc)


def test_window_url_is_pinned_host_with_no_secrets() -> None:
    url = window_url("2026-07-12T00:00:00Z", "2026-07-15T00:00:00Z")
    assert url.startswith("https://api.exchange.coinbase.com/products/ETH-USD/candles?")
    assert "granularity=86400" in url
    assert "key" not in url.lower()
    assert "token" not in url.lower()


def test_emit_curl_plan_writes_request_params(tmp_path: Path) -> None:
    plan = _plan()
    plan_path = tmp_path / "acquisition_plan.json"
    plan_path.write_bytes(plan.to_json_bytes())
    out = tmp_path / "_curl_plan.json"
    emit_curl_plan(plan_path, out)
    doc = json.loads(out.read_bytes())
    assert doc["endpoint"] == "https://api.exchange.coinbase.com/products/ETH-USD/candles"
    assert doc["granularity_seconds"] == 86400
    assert len(doc["windows"]) == len(plan.windows)
    assert "curl" not in json.dumps(doc)  # no free-form command string


# --------------------------------------------------------------------------- #
# offline verification                                                        #
# --------------------------------------------------------------------------- #
def test_verify_happy_path_writes_valid_receipt(tmp_path: Path) -> None:
    plan = _plan()
    raw_dir = _stage(tmp_path, plan)
    receipt = _verify(raw_dir, plan)
    assert receipt.attempt_id == GENESIS_ATTEMPT_ID
    assert receipt.plan_sha256 == plan.plan_sha256
    from eth_research.m3d.validation import sha256_bytes

    response = receipt.responses[0]
    assert response["response_sha256"] == sha256_bytes(
        (raw_dir / response["raw_filename"]).read_bytes()
    )
    ProspectiveAttemptReceipt.from_mapping(json.loads(receipt.to_json_bytes()))


def test_verify_rejects_non_200(tmp_path: Path) -> None:
    plan = _plan()
    raw_dir = _stage(tmp_path, plan, http_code=204)
    with pytest.raises(AcquisitionRunnerError, match="not 200"):
        _verify(raw_dir, plan)


def test_verify_rejects_non_json_content_type(tmp_path: Path) -> None:
    plan = _plan()
    raw_dir = _stage(tmp_path, plan, content_type="text/html")
    with pytest.raises(AcquisitionRunnerError, match="content-type"):
        _verify(raw_dir, plan)


def test_verify_rejects_empty_candle_body(tmp_path: Path) -> None:
    plan = _plan()
    raw_dir = _stage(tmp_path, plan, body=b"[]")
    with pytest.raises(AcquisitionRunnerError, match="no candles"):
        _verify(raw_dir, plan)


def test_verify_rejects_out_of_window_row(tmp_path: Path) -> None:
    plan = _plan()
    rows = [
        [_epoch("2026-07-15T00:00:00Z"), 1.0, 2.0, 1.5, 1.8, 1.0]
    ]  # forming candle at window end
    raw_dir = _stage(tmp_path, plan, body=json.dumps(rows).encode())
    with pytest.raises(AcquisitionRunnerError):
        _verify(raw_dir, plan)


def test_verify_rejects_unexpected_staged_file(tmp_path: Path) -> None:
    plan = _plan()
    raw_dir = _stage(tmp_path, plan, extra_file="sneaky.json")
    with pytest.raises(AcquisitionRunnerError, match="unexpected staged files"):
        _verify(raw_dir, plan)


def test_verify_rejects_duplicate_sidecar_ordinal(tmp_path: Path) -> None:
    plan = _plan()
    raw_dir = _stage(tmp_path, plan)
    sidecar = raw_dir / RESPONSES_SIDECAR
    line = sidecar.read_text().splitlines()[0]
    sidecar.write_text(line + "\n" + line + "\n")
    with pytest.raises(AcquisitionRunnerError, match="duplicate ordinal"):
        _verify(raw_dir, plan)
