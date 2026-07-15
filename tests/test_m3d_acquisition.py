"""Tests for the M3D acquisition plan, receipt models, and hardened runner.

The runner's network client is injected, so its offline validation path is
exercised with synthetic Coinbase responses (no network).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from eth_research.m3d.acquire_runner import (
    AcquisitionRunnerError,
    FetchResult,
    run_acquisition,
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
    # Newest-first [time, low, high, open, close, volume] for 07-14, 07-13, 07-12.
    rows = [
        [_epoch("2026-07-14T00:00:00Z"), 2900.0, 3100.0, 3000.0, 3050.0, 1234.5],
        [_epoch("2026-07-13T00:00:00Z"), 2850.0, 3050.0, 2950.0, 3000.0, 1111.0],
        [_epoch("2026-07-12T00:00:00Z"), 2800.0, 3000.0, 2900.0, 2950.0, 999.0],
    ]
    return json.dumps(rows).encode("utf-8")


def _fetcher_ok(url: str) -> FetchResult:
    return FetchResult(
        status=200,
        content_type="application/json; charset=utf-8",
        body=_synthetic_body(),
        attempt_count=1,
    )


# --------------------------------------------------------------------------- #
# plan                                                                         #
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
    plan = _plan()
    assert all(w["expected_bucket_count"] <= MAX_BUCKETS_PER_REQUEST for w in plan.windows)


def test_window_url_is_pinned_host_with_no_secrets() -> None:
    url = window_url("2026-07-12T00:00:00Z", "2026-07-15T00:00:00Z")
    assert url.startswith("https://api.exchange.coinbase.com/products/ETH-USD/candles?")
    assert "granularity=86400" in url
    assert "key" not in url.lower()
    assert "token" not in url.lower()


# --------------------------------------------------------------------------- #
# runner (offline validation with injected fetcher)                           #
# --------------------------------------------------------------------------- #
def _write_plan(tmp_path: Path, plan: ProspectiveAcquisitionPlan) -> Path:
    path = tmp_path / "plan.json"
    path.write_bytes(plan.to_json_bytes())
    return path


def test_runner_happy_path_writes_raw_and_valid_receipt(tmp_path: Path) -> None:
    plan = _plan()
    plan_path = _write_plan(tmp_path, plan)
    raw_dir = tmp_path / "raw"
    receipt = run_acquisition(
        ".",
        plan_path,
        raw_dir,
        source_commit="a" * 40,
        workflow_run_id="123456",
        runner_identity="ubuntu-x64",
        client_identity="python-urllib/3.12",
        fetcher=_fetcher_ok,
        clock=lambda: "2026-07-15T12:00:00Z",
    )
    assert isinstance(receipt, ProspectiveAttemptReceipt)
    assert receipt.attempt_id == GENESIS_ATTEMPT_ID
    assert receipt.plan_sha256 == plan.plan_sha256
    response = receipt.responses[0]
    raw_bytes = (raw_dir / response["raw_filename"]).read_bytes()
    from eth_research.m3d.validation import sha256_bytes

    assert response["response_sha256"] == sha256_bytes(raw_bytes)
    # Re-parse the committed receipt bytes strictly.
    ProspectiveAttemptReceipt.from_mapping(json.loads(receipt.to_json_bytes()))


def test_runner_rejects_non_json_content_type(tmp_path: Path) -> None:
    def fetch(url: str) -> FetchResult:
        return FetchResult(
            status=200, content_type="text/html", body=_synthetic_body(), attempt_count=1
        )

    with pytest.raises(AcquisitionRunnerError, match="content-type"):
        run_acquisition(
            ".",
            _write_plan(tmp_path, _plan()),
            tmp_path / "raw",
            source_commit="a" * 40,
            workflow_run_id="1",
            runner_identity="r",
            client_identity="c",
            fetcher=fetch,
            clock=lambda: "2026-07-15T12:00:00Z",
        )


def test_runner_rejects_non_200(tmp_path: Path) -> None:
    def fetch(url: str) -> FetchResult:
        return FetchResult(status=204, content_type="application/json", body=b"[]", attempt_count=1)

    with pytest.raises(AcquisitionRunnerError, match="HTTP 204"):
        run_acquisition(
            ".",
            _write_plan(tmp_path, _plan()),
            tmp_path / "raw",
            source_commit="a" * 40,
            workflow_run_id="1",
            runner_identity="r",
            client_identity="c",
            fetcher=fetch,
            clock=lambda: "2026-07-15T12:00:00Z",
        )


def test_runner_rejects_empty_candle_body(tmp_path: Path) -> None:
    def fetch(url: str) -> FetchResult:
        return FetchResult(status=200, content_type="application/json", body=b"[]", attempt_count=1)

    with pytest.raises(AcquisitionRunnerError, match="no candles"):
        run_acquisition(
            ".",
            _write_plan(tmp_path, _plan()),
            tmp_path / "raw",
            source_commit="a" * 40,
            workflow_run_id="1",
            runner_identity="r",
            client_identity="c",
            fetcher=fetch,
            clock=lambda: "2026-07-15T12:00:00Z",
        )


def test_runner_rejects_out_of_window_row(tmp_path: Path) -> None:
    def fetch(url: str) -> FetchResult:
        rows = [
            [_epoch("2026-07-15T00:00:00Z"), 1.0, 2.0, 1.5, 1.8, 1.0]
        ]  # at window end (forming)
        return FetchResult(
            status=200,
            content_type="application/json",
            body=json.dumps(rows).encode(),
            attempt_count=1,
        )

    with pytest.raises(AcquisitionRunnerError):
        run_acquisition(
            ".",
            _write_plan(tmp_path, _plan()),
            tmp_path / "raw",
            source_commit="a" * 40,
            workflow_run_id="1",
            runner_identity="r",
            client_identity="c",
            fetcher=fetch,
            clock=lambda: "2026-07-15T12:00:00Z",
        )


def test_hardened_fetch_refuses_non_pinned_url() -> None:
    from eth_research.m3d.acquire_runner import hardened_urllib_fetch

    with pytest.raises(AcquisitionRunnerError, match="non-pinned URL"):
        hardened_urllib_fetch("https://evil.example.com/candles")
    with pytest.raises(AcquisitionRunnerError, match="non-pinned URL"):
        hardened_urllib_fetch("http://api.exchange.coinbase.com/products/ETH-USD/candles")
