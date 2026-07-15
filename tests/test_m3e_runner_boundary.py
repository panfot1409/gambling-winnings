"""Workflow-artifact boundary + offline acquisition runner (commit 8)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import eth_research
from eth_research.m3e.accepted_base import verify_accepted_base
from eth_research.m3e.acquire_runner import (
    RESPONSES_SIDECAR,
    emit_curl_plan,
    verify_responses_and_write_receipt,
)
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.runner_boundary import load_and_verify_runner
from eth_research.m3e.update_plan import build_update_plan
from eth_research.m3e.validation import M3EValidationError, sha256_bytes

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
_AS_OF = "2026-07-22T02:17:00Z"


@pytest.fixture
def plan():
    base = verify_accepted_base(REPO_ROOT)
    return build_update_plan(base, plan_update_window(base, _AS_OF))


def _descending(window_start: str, window_end: str) -> list[list[float | int]]:
    day = pd.Timedelta(days=1)
    start = pd.Timestamp(window_start)
    cursor = pd.Timestamp(window_end) - day
    rows: list[list[float | int]] = []
    while cursor >= start:
        n = int(cursor.timestamp()) // 86_400
        o = 1700.0 + float(n % 37)
        c = o + float((n % 7) - 3)
        rows.append([int(cursor.timestamp()), min(o, c) - 2.0, max(o, c) + 2.0, o, c, 40_000.0])
        cursor = cursor - day
    return rows


def _stage_with_sidecar(staging: Path, plan) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "update_plan.json").write_bytes(plan.to_json_bytes())
    lines = []
    for w in plan.windows:
        raw = json.dumps(_descending(str(w["window_start"]), str(w["window_end"]))).encode("ascii")
        (staging / str(w["raw_filename"])).write_bytes(raw)
        lines.append(
            json.dumps(
                {
                    "content_type": "application/json",
                    "filename": str(w["raw_filename"]),
                    "http_code": 200,
                    "ordinal": int(w["ordinal"]),
                    "retrieved_at": "2026-07-22T02:17:05Z",
                },
                sort_keys=True,
            )
        )
    (staging / RESPONSES_SIDECAR).write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# workflow-artifact boundary                                                  #
# --------------------------------------------------------------------------- #
def test_boundary_re_derives_a_runner_artifact(m3e_write_runner, tmp_path, plan) -> None:
    raw_dir = tmp_path / "runner_a"
    m3e_write_runner(
        raw_dir,
        plan,
        attempt_id="coinbase-eth-usd-prospective-update-runner-a",
        source_commit="a" * 40,
        workflow_run_id="run-a",
        runner_identity="ubuntu-x64-a",
    )
    runner = load_and_verify_runner(raw_dir, runner_label="a")
    assert runner.row_count == 7
    assert runner.first_open == "2026-07-15T00:00:00Z"
    assert runner.last_open == "2026-07-21T00:00:00Z"
    assert runner.plan_sha256 == plan.plan_sha256
    assert runner.identity_tuple() == ("a" * 40, "run-a", "ubuntu-x64-a")


def test_boundary_pins_both_runners_to_the_same_plan(m3e_write_runner, tmp_path, plan) -> None:
    raw_dir = tmp_path / "runner_a"
    m3e_write_runner(
        raw_dir,
        plan,
        attempt_id="coinbase-eth-usd-prospective-update-runner-a",
        source_commit="a" * 40,
        workflow_run_id="run-a",
        runner_identity="ubuntu-x64-a",
    )
    # Correct expected plan hash passes; a different one is refused.
    load_and_verify_runner(raw_dir, runner_label="a", expected_plan_sha256=plan.plan_sha256)
    with pytest.raises(M3EValidationError, match="replayed a different update plan"):
        load_and_verify_runner(raw_dir, runner_label="a", expected_plan_sha256="0" * 64)


# --------------------------------------------------------------------------- #
# offline runner CLI                                                          #
# --------------------------------------------------------------------------- #
def test_emit_curl_plan_lists_the_windows(tmp_path, plan) -> None:
    (tmp_path / "update_plan.json").write_bytes(plan.to_json_bytes())
    out = tmp_path / "curl_plan.json"
    emit_curl_plan(tmp_path / "update_plan.json", out)
    doc = json.loads(out.read_text())
    assert doc["endpoint"].endswith("/products/ETH-USD/candles")
    assert [w["ordinal"] for w in doc["windows"]] == [w["ordinal"] for w in plan.windows]
    # The per-window params carry no URL; only the top-level endpoint names the host.
    assert "://" not in json.dumps(doc["windows"])


def test_offline_verify_writes_a_matching_receipt(tmp_path, plan) -> None:
    staging = tmp_path / "staging"
    _stage_with_sidecar(staging, plan)
    receipt = verify_responses_and_write_receipt(
        staging / "update_plan.json",
        staging,
        staging / "acquisition_receipt.json",
        attempt_id="coinbase-eth-usd-prospective-update-runner-a",
        workflow_run_id="run-a",
        source_commit="a" * 40,
        client_identity="curl/8.0",
        runner_identity="ubuntu-x64-a",
        created_at_utc="2026-07-22T02:17:06Z",
    )
    assert len(receipt.responses) == len(plan.windows)
    # The complete staged artifact re-derives through the boundary.
    runner = load_and_verify_runner(staging, runner_label="a")
    assert runner.row_count == 7


def test_offline_verify_rejects_an_unexpected_staged_file(tmp_path, plan) -> None:
    staging = tmp_path / "staging"
    _stage_with_sidecar(staging, plan)
    (staging / "stowaway.json").write_text("[]")
    with pytest.raises(M3EValidationError, match="unexpected staged files"):
        verify_responses_and_write_receipt(
            staging / "update_plan.json",
            staging,
            staging / "acquisition_receipt.json",
            attempt_id="coinbase-eth-usd-prospective-update-runner-a",
            workflow_run_id="run-a",
            source_commit="a" * 40,
            client_identity="curl/8.0",
            runner_identity="ubuntu-x64-a",
            created_at_utc="2026-07-22T02:17:06Z",
        )


def test_offline_verify_rejects_a_non_200_sidecar(tmp_path, plan) -> None:
    staging = tmp_path / "staging"
    _stage_with_sidecar(staging, plan)
    # Rewrite the sidecar with a 500 for the first window.
    lines = (staging / RESPONSES_SIDECAR).read_text().splitlines()
    first = json.loads(lines[0])
    first["http_code"] = 500
    lines[0] = json.dumps(first, sort_keys=True)
    (staging / RESPONSES_SIDECAR).write_text("\n".join(lines) + "\n")
    with pytest.raises(M3EValidationError, match="HTTP 500"):
        verify_responses_and_write_receipt(
            staging / "update_plan.json",
            staging,
            staging / "acquisition_receipt.json",
            attempt_id="coinbase-eth-usd-prospective-update-runner-a",
            workflow_run_id="run-a",
            source_commit="a" * 40,
            client_identity="curl/8.0",
            runner_identity="ubuntu-x64-a",
            created_at_utc="2026-07-22T02:17:06Z",
        )


def test_sha256_helper_is_available() -> None:
    # Guard: the runner records body hashes, never candle values.
    assert len(sha256_bytes(b"x")) == 64
