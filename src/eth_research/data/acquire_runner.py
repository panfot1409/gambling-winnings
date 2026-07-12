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
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from eth_research import __version__
from eth_research._atomic import write_atomic
from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.acquisition_plan import (
    AcquisitionAttemptReceipt,
    AcquisitionResponseReceipt,
    load_acquisition_plan,
    require_safe_json_filename,
)
from eth_research.data.coinbase import AcquisitionError, parse_candles_chunk
from eth_research.data.provenance import require_int, require_nonempty_str, sha256_bytes
from eth_research.data.validation import (
    parse_timestamp_field,
    require_nonnegative_int,
    require_utc_timestamp,
)

_RECEIPTS_SIDECAR: str = "_responses.jsonl"
"""The workflow's curl step appends one JSON line per fetched window here."""

_JSON_CONTENT_TYPE_PREFIX: str = "application/json"

_SIDECAR_KEYS: frozenset[str] = frozenset(
    {"ordinal", "filename", "http_code", "retrieved_at", "content_type"}
)


@dataclass(frozen=True)
class _SidecarRecord:
    """One strictly-validated per-window status line from the curl step."""

    ordinal: int
    filename: str
    http_code: int
    retrieved_at: pd.Timestamp
    content_type: str


def _parse_sidecar_line(line: bytes, position: int) -> _SidecarRecord:
    """Strictly parse one sidecar line, rejecting every laundering vector.

    The permissive ``json.loads`` this replaces silently kept the last of
    duplicate object keys, so a second ``http_code`` could launder a 500
    into a 200. The shared strict decoder rejects duplicate keys, NaN, and
    exponent-overflow tokens; the schema then rejects unknown/missing keys,
    booleans or strings where an integer is required, a non-UTC or
    unparseable retrieval time, and an unsafe filename.
    """
    try:
        payload = strict_json_loads(line)
    except StrictJSONError as exc:
        raise AcquisitionError(f"sidecar line {position} is not valid strict JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AcquisitionError(f"sidecar line {position} must be a JSON object")
    keys = set(payload)
    if keys != _SIDECAR_KEYS:
        unknown = sorted(keys - _SIDECAR_KEYS)
        missing = sorted(_SIDECAR_KEYS - keys)
        raise AcquisitionError(
            f"sidecar line {position} keys do not match schema: "
            f"unknown={unknown}, missing={missing}"
        )
    try:
        ordinal = require_nonnegative_int("ordinal", payload["ordinal"])
        filename = require_safe_json_filename("filename", payload["filename"])
        http_code = require_int("http_code", payload["http_code"])
        retrieved_at = require_utc_timestamp(
            "retrieved_at", parse_timestamp_field("retrieved_at", payload["retrieved_at"])
        )
        content_type = require_nonempty_str("content_type", payload["content_type"])
    except ValueError as exc:
        raise AcquisitionError(f"sidecar line {position} is invalid: {exc}") from exc
    return _SidecarRecord(
        ordinal=ordinal,
        filename=filename,
        http_code=http_code,
        retrieved_at=retrieved_at,
        content_type=content_type,
    )


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


def _read_sidecar(staging: Path) -> dict[int, _SidecarRecord]:
    """Strictly parse the curl step's per-window status sidecar, by ordinal."""
    path = staging / _RECEIPTS_SIDECAR
    if not path.exists():
        raise AcquisitionError(f"missing response sidecar {path}")
    records: dict[int, _SidecarRecord] = {}
    for position, line in enumerate(path.read_bytes().splitlines(), start=1):
        if not line.strip():
            continue
        record = _parse_sidecar_line(line, position)
        if record.ordinal in records:
            raise AcquisitionError(
                f"sidecar line {position}: duplicate record for ordinal {record.ordinal}"
            )
        records[record.ordinal] = record
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
        if record.filename != window.filename:
            raise AcquisitionError(
                f"window {window.ordinal} sidecar filename {record.filename!r} does not match "
                f"the plan's {window.filename!r}"
            )
        if record.http_code != 200:
            raise AcquisitionError(
                f"window {window.ordinal} returned HTTP {record.http_code}, not 200; "
                "refusing to publish"
            )
        if not record.content_type.startswith(_JSON_CONTENT_TYPE_PREFIX):
            raise AcquisitionError(
                f"window {window.ordinal} content-type {record.content_type!r} is not "
                f"{_JSON_CONTENT_TYPE_PREFIX!r}; refusing to publish"
            )
        body_path = staging / window.filename
        if not body_path.exists():
            raise AcquisitionError(f"missing raw body {window.filename} in {staging}")
        raw = body_path.read_bytes()
        try:
            parse_candles_chunk(raw, window_start=window.window_start, window_end=window.window_end)
        except AcquisitionError as exc:
            raise AcquisitionError(f"window {window.ordinal} ({window.filename}): {exc}") from exc
        responses.append(
            AcquisitionResponseReceipt(
                ordinal=window.ordinal,
                filename=window.filename,
                http_status=200,
                byte_length=len(raw),
                sha256=sha256_bytes(raw),
                retrieved_at=record.retrieved_at,
                content_type=record.content_type,
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
