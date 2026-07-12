"""Offline driver for the clean-room acquisition workflow.

This module contains **no networking**. It is the offline half of the
GitHub Actions acquisition job: it turns a validated request plan into the
exact per-window request parameters the workflow's ``curl`` step consumes
(``emit``), and — after ``curl`` has written the raw bodies to a staging
directory — it strictly validates every response against its declared
window and writes the signed acquisition receipt (``verify``). The
``curl`` boundary lives entirely in the workflow YAML; this code only ever
reads local files.

Every response is parsed through the same strict Coinbase adapter the
canonical build uses, so an HTTP-200 error object, an empty array, a
malformed row, a non-finite value, or a window/response mismatch is
rejected here before anything is published.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research import __version__
from eth_research._atomic import write_atomic
from eth_research.data.acquisition_plan import (
    AcquisitionAttemptReceipt,
    AcquisitionResponseReceipt,
    load_acquisition_plan,
)
from eth_research.data.coinbase import AcquisitionError, parse_candles_chunk
from eth_research.data.provenance import sha256_bytes
from eth_research.data.validation import parse_timestamp_field

_RECEIPTS_SIDECAR: str = "_responses.jsonl"
"""The workflow's curl step appends one JSON line per fetched window here."""


def emit_curl_plan(plan_path: str | Path, out_path: str | Path) -> int:
    """Write the fixed per-window request parameters for the curl step.

    Offline: loads and validates the plan, then emits the endpoint, fixed
    granularity, user-agent, and — per window — the canonical
    ``requested_start``/``requested_end`` and safe output filename. No
    free-form command is emitted; the workflow builds a ``curl -G`` call
    from these validated values.
    """
    plan = load_acquisition_plan(plan_path)
    doc = {
        "endpoint": plan.endpoint,
        "granularity_seconds": plan.granularity_seconds,
        "user_agent": plan.user_agent,
        "windows": [
            {
                "ordinal": window.ordinal,
                "requested_start": window.requested_start,
                "requested_end": window.requested_end,
                "filename": window.filename,
            }
            for window in plan.windows
        ],
    }
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False)
    write_atomic(Path(out_path), (text + "\n").encode("utf-8"))
    print(f"emitted {plan.expected_request_count} request window(s) for {plan.endpoint}")
    return 0


def _read_sidecar(staging: Path) -> dict[int, dict[str, Any]]:
    """Parse the curl step's per-window status sidecar, keyed by ordinal."""
    path = staging / _RECEIPTS_SIDECAR
    if not path.exists():
        raise AcquisitionError(f"missing response sidecar {path}")
    records: dict[int, dict[str, Any]] = {}
    for position, line in enumerate(path.read_bytes().splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise AcquisitionError(f"sidecar line {position + 1} is not valid JSON: {exc}") from exc
        if not isinstance(entry, dict) or "ordinal" not in entry:
            raise AcquisitionError(f"sidecar line {position + 1} is malformed")
        records[int(entry["ordinal"])] = entry
    return records


def verify_responses_and_write_receipt(
    plan_path: str | Path,
    staging_dir: str | Path,
    receipt_out: str | Path,
    *,
    attempt_id: str,
    workflow_run_id: str,
    source_commit: str,
    curl_version: str,
    runner: str,
) -> AcquisitionAttemptReceipt:
    """Strictly validate every staged response and write the receipt.

    For each planned window: the sidecar must record HTTP 200, the raw body
    must exist and strictly parse against the window (rejecting error
    objects, empty arrays, malformed rows, non-finite values, and
    window/response mismatches), and the receipt records the exact byte
    length, SHA-256, retrieval time, and content type. No extra staged file
    outside the plan is tolerated.
    """
    plan = load_acquisition_plan(plan_path)
    staging = Path(staging_dir)
    sidecar = _read_sidecar(staging)

    responses: list[AcquisitionResponseReceipt] = []
    for window in plan.windows:
        record = sidecar.get(window.ordinal)
        if record is None:
            raise AcquisitionError(f"no sidecar record for window {window.ordinal}")
        status = int(record.get("http_code", 0))
        if status != 200:
            raise AcquisitionError(
                f"window {window.ordinal} returned HTTP {status}, not 200; refusing to publish"
            )
        body_path = staging / window.filename
        if not body_path.exists():
            raise AcquisitionError(f"missing raw body {window.filename} in {staging}")
        raw = body_path.read_bytes()
        try:
            parse_candles_chunk(raw, window_start=window.window_start, window_end=window.window_end)
        except AcquisitionError as exc:
            raise AcquisitionError(f"window {window.ordinal} ({window.filename}): {exc}") from exc
        retrieved_at = parse_timestamp_field(
            f"window {window.ordinal} retrieved_at", record.get("retrieved_at")
        )
        responses.append(
            AcquisitionResponseReceipt(
                ordinal=window.ordinal,
                filename=window.filename,
                http_status=200,
                byte_length=len(raw),
                sha256=sha256_bytes(raw),
                retrieved_at=retrieved_at,
                content_type=str(record.get("content_type") or "application/json"),
            )
        )

    # No stray body outside the plan may be published.
    planned = {window.filename for window in plan.windows}
    stray = sorted(
        p.name
        for p in staging.glob("*.json")
        if p.name not in planned and p.name != _RECEIPTS_SIDECAR
    )
    if stray:
        raise AcquisitionError(f"unexpected staged file(s) not in the plan: {stray}")

    receipt = AcquisitionAttemptReceipt(
        receipt_schema_version=1,
        package_version=__version__,
        plan_sha256=plan.plan_sha256(),
        attempt_id=attempt_id,
        workflow_run_id=workflow_run_id,
        source_commit=source_commit,
        curl_version=curl_version,
        runner=runner,
        user_agent=plan.user_agent,
        responses=tuple(responses),
    )
    write_atomic(Path(receipt_out), receipt.to_json_bytes())
    print(f"verified {len(responses)} response(s); wrote receipt {Path(receipt_out).name}")
    return receipt


def _now_utc_iso() -> str:  # pragma: no cover - only used by the CLI default
    return pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eth_research.data.acquire_runner")
    sub = parser.add_subparsers(dest="command", required=True)

    emit = sub.add_parser("emit", help="emit per-window curl parameters from a plan")
    emit.add_argument("--plan", required=True)
    emit.add_argument("--out", required=True)

    verify = sub.add_parser("verify", help="validate staged responses and write the receipt")
    verify.add_argument("--plan", required=True)
    verify.add_argument("--staging", required=True)
    verify.add_argument("--receipt-out", required=True)
    verify.add_argument("--attempt-id", required=True)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--commit", required=True)
    verify.add_argument("--curl-version", required=True)
    verify.add_argument("--runner", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "emit":
            return emit_curl_plan(args.plan, args.out)
        verify_responses_and_write_receipt(
            args.plan,
            args.staging,
            args.receipt_out,
            attempt_id=args.attempt_id,
            workflow_run_id=args.run_id,
            source_commit=args.commit,
            curl_version=args.curl_version,
            runner=args.runner,
        )
    except (AcquisitionError, ValueError) as exc:
        print(f"acquisition driver failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
