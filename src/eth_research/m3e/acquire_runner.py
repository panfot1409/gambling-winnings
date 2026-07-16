"""Offline acquisition runner for one update-proposal runner.

This module never opens a socket. The network boundary lives entirely in the
workflow's ``curl`` step: :func:`emit_curl_plan` writes the fixed per-window
request parameters the workflow's ``curl`` consumes (endpoint read from the
committed update plan, so the workflow YAML carries no literal host), and — after
``curl`` has written the raw bodies plus a per-window status sidecar into a staging
directory — :func:`verify_responses_and_write_receipt` strictly validates every
response offline (HTTP 200, ``application/json``, size cap, day-aligned finite
OHLCV rows inside the declared half-open window, no forming/empty response, no
unexpected staged file) and writes a strict :class:`ProspectiveAttemptReceipt`
recording body hashes and lengths, never candle values.

Two isolated runner jobs each run this independently over the *same* committed
update plan; a matching receipt from each is the two-runner attestation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from eth_research._atomic import write_atomic
from eth_research.data.coinbase import AcquisitionError, parse_candles_chunk
from eth_research.m3d.acquisition_plan import (
    ENDPOINT,
    GRANULARITY_SECONDS,
    USER_AGENT,
    require_safe_json_filename,
)
from eth_research.m3d.receipt import (
    RECEIPT_KIND,
    RECEIPT_SCHEMA_VERSION,
    ProspectiveAttemptReceipt,
)
from eth_research.m3e import M3E_PACKAGE_VERSION
from eth_research.m3e.update_plan import ProspectiveUpdatePlan, load_update_plan
from eth_research.m3e.validation import (
    M3EValidationError,
    require_mapping,
    require_nonnegative_int,
    require_positive_int,
    require_str,
    require_utc_timestamp,
    sha256_bytes,
    strict_json_loads,
)

MAX_BODY_BYTES = 2 * 1024 * 1024
RESPONSES_SIDECAR = "_responses.jsonl"
RUNNER_PLAN_FILENAME = "update_plan.json"
RUNNER_RECEIPT_FILENAME = "acquisition_receipt.json"
CURL_PLAN_FILENAME = "_curl_plan.json"
_JSON_CONTENT_TYPE_PREFIX = "application/json"
_SIDECAR_KEYS = {"ordinal", "filename", "http_code", "retrieved_at", "content_type"}


class AcquisitionRunnerError(M3EValidationError):
    """The runner refused an unsafe or malformed acquisition state."""


def emit_curl_plan(plan_path: str | Path, out_path: str | Path) -> int:
    """Emit the fixed per-window request parameters for the workflow's curl step.

    Offline: loads + validates the committed update plan, then writes the endpoint,
    fixed granularity, user agent, and per-window canonical start/end params + safe
    output filename. No free-form command string is emitted.
    """
    plan = load_update_plan(plan_path)
    document = {
        "endpoint": ENDPOINT,
        "granularity_seconds": GRANULARITY_SECONDS,
        "user_agent": USER_AGENT,
        "max_body_bytes": MAX_BODY_BYTES,
        "windows": [
            {
                "ordinal": int(w["ordinal"]),
                "start_param": str(w["start_param"]),
                "end_param": str(w["end_param"]),
                "filename": str(w["raw_filename"]),
            }
            for w in plan.windows
        ],
    }
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
    write_atomic(Path(out_path), (text + "\n").encode("utf-8"))
    print(f"emitted {len(plan.windows)} request window(s) for {ENDPOINT}")
    return 0


@dataclass(frozen=True)
class _SidecarRecord:
    ordinal: int
    filename: str
    http_code: int
    retrieved_at: str
    content_type: str


def _parse_sidecar_line(line: bytes, position: int) -> _SidecarRecord:
    try:
        payload = strict_json_loads(line)
    except ValueError as exc:
        raise AcquisitionRunnerError(f"sidecar line {position} is not strict JSON: {exc}") from exc
    mapping = require_mapping(f"sidecar line {position}", payload)
    if set(mapping) != _SIDECAR_KEYS:
        raise AcquisitionRunnerError(
            f"sidecar line {position} keys must be {sorted(_SIDECAR_KEYS)}"
        )
    retrieved_at = require_str(f"sidecar line {position} retrieved_at", mapping["retrieved_at"])
    require_utc_timestamp("retrieved_at", pd.Timestamp(retrieved_at))
    return _SidecarRecord(
        ordinal=require_nonnegative_int("ordinal", mapping["ordinal"]),
        filename=require_safe_json_filename("filename", mapping["filename"]),
        http_code=require_positive_int("http_code", mapping["http_code"]),
        retrieved_at=retrieved_at,
        content_type=require_str("content_type", mapping["content_type"]),
    )


def _read_sidecar(staging: Path) -> dict[int, _SidecarRecord]:
    path = staging / RESPONSES_SIDECAR
    if not path.is_file():
        raise AcquisitionRunnerError(f"missing response sidecar {path}")
    records: dict[int, _SidecarRecord] = {}
    for position, line in enumerate(path.read_bytes().splitlines(), start=1):
        if not line.strip():
            continue
        record = _parse_sidecar_line(line, position)
        if record.ordinal in records:
            raise AcquisitionRunnerError(
                f"sidecar line {position}: duplicate ordinal {record.ordinal}"
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
    client_identity: str,
    runner_identity: str,
    created_at_utc: str,
) -> ProspectiveAttemptReceipt:
    """Strictly validate every staged response offline and write the receipt."""
    plan = load_update_plan(plan_path)
    staging = Path(staging_dir)
    sidecar = _read_sidecar(staging)

    responses: list[dict[str, object]] = []
    for window in plan.windows:
        ordinal = int(window["ordinal"])
        record = sidecar.get(ordinal)
        if record is None:
            raise AcquisitionRunnerError(f"no sidecar record for window {ordinal}")
        if record.filename != window["raw_filename"]:
            raise AcquisitionRunnerError(f"window {ordinal} sidecar filename mismatch")
        if record.http_code != 200:
            raise AcquisitionRunnerError(
                f"window {ordinal} returned HTTP {record.http_code}, not 200"
            )
        if (
            not record.content_type.split(";")[0]
            .strip()
            .lower()
            .startswith(_JSON_CONTENT_TYPE_PREFIX)
        ):
            raise AcquisitionRunnerError(f"window {ordinal} content-type {record.content_type!r}")
        body_path = staging / str(window["raw_filename"])
        if body_path.is_symlink() or not body_path.is_file():
            raise AcquisitionRunnerError(f"missing raw body {window['raw_filename']} in {staging}")
        body = body_path.read_bytes()
        if len(body) > MAX_BODY_BYTES:
            raise AcquisitionRunnerError(f"window {ordinal} body exceeds the size cap")
        window_start = pd.Timestamp(str(window["window_start"]))
        window_end = pd.Timestamp(str(window["window_end"]))
        try:
            parsed = parse_candles_chunk(body, window_start=window_start, window_end=window_end)
        except AcquisitionError as exc:
            raise AcquisitionRunnerError(f"window {ordinal}: {exc}") from exc
        if not parsed.candles:
            raise AcquisitionRunnerError(f"window {ordinal}: no completed candle (HARD STOP)")
        responses.append(
            {
                "ordinal": ordinal,
                "raw_filename": str(window["raw_filename"]),
                "start_param": str(window["start_param"]),
                "end_param": str(window["end_param"]),
                "http_status": record.http_code,
                "content_type": record.content_type,
                "response_byte_length": len(body),
                "response_sha256": sha256_bytes(body),
                "retrieved_at": record.retrieved_at,
            }
        )

    _reject_unexpected_files(staging, plan)

    document = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": RECEIPT_KIND,
        "package_version": M3E_PACKAGE_VERSION,
        "attempt_id": attempt_id,
        "plan_sha256": plan.plan_sha256,
        "endpoint": ENDPOINT,
        "user_agent": USER_AGENT,
        "source_commit": source_commit,
        "workflow_run_id": workflow_run_id,
        "runner_identity": runner_identity,
        "client_identity": client_identity,
        "created_at_utc": created_at_utc,
        "responses": responses,
    }
    receipt = ProspectiveAttemptReceipt.from_mapping(document)
    write_atomic(Path(receipt_out), receipt.to_json_bytes())
    return receipt


def plan_update(repo_root: str | Path, as_of_utc: str, out_path: str | Path) -> int:
    """Verify the accepted base, compute the due window, and write the update plan.

    Wall-clock-free: ``as_of_utc`` is injected by the workflow (never read inside the
    library). Writes the update plan only when a new completed day is due; on a no-op
    it writes nothing and prints ``NO-OP`` so the workflow can exit without fetching.
    """
    from eth_research.m3e.accepted_base import verify_accepted_base
    from eth_research.m3e.cutoff import plan_update_window
    from eth_research.m3e.update_plan import build_update_plan

    base = verify_accepted_base(repo_root)
    decision = plan_update_window(base, as_of_utc)
    if decision.is_noop:
        print(f"NO-OP: {decision.reason}")
        return 0
    plan = build_update_plan(base, decision)
    write_atomic(Path(out_path), plan.to_json_bytes())
    print(f"DUE: {plan.expected_total_buckets} bucket(s); idempotency {plan.idempotency_key[:16]}")
    return 0


def _reject_unexpected_files(staging: Path, plan: ProspectiveUpdatePlan) -> None:
    expected = {str(w["raw_filename"]) for w in plan.windows}
    allowed = expected | {
        RESPONSES_SIDECAR,
        RUNNER_PLAN_FILENAME,
        RUNNER_RECEIPT_FILENAME,
        CURL_PLAN_FILENAME,
    }
    present = {p.name for p in staging.iterdir() if p.is_file()}
    if unexpected := present - allowed:
        raise AcquisitionRunnerError(f"unexpected staged files: {sorted(unexpected)}")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - workflow entry
    """CLI: ``emit-plan`` writes the curl request params; ``verify`` validates + writes."""
    import argparse

    parser = argparse.ArgumentParser(description="M3E prospective update runner (offline)")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("--repo-root", required=True)
    plan_cmd.add_argument("--as-of", required=True)
    plan_cmd.add_argument("--out", required=True)

    emit = sub.add_parser("emit-plan")
    emit.add_argument("--plan", required=True)
    emit.add_argument("--out", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--plan", required=True)
    verify.add_argument("--staging", required=True)
    verify.add_argument("--receipt-out", required=True)
    verify.add_argument("--attempt-id", required=True)
    verify.add_argument("--workflow-run-id", required=True)
    verify.add_argument("--source-commit", required=True)
    verify.add_argument("--client-identity", required=True)
    verify.add_argument("--runner-identity", required=True)
    verify.add_argument("--created-at", required=True)

    args = parser.parse_args(argv)
    if args.command == "plan":
        return plan_update(args.repo_root, args.as_of, args.out)
    if args.command == "emit-plan":
        return emit_curl_plan(args.plan, args.out)
    receipt = verify_responses_and_write_receipt(
        args.plan,
        args.staging,
        args.receipt_out,
        attempt_id=args.attempt_id,
        workflow_run_id=args.workflow_run_id,
        source_commit=args.source_commit,
        client_identity=args.client_identity,
        runner_identity=args.runner_identity,
        created_at_utc=args.created_at,
    )
    for response in receipt.responses:
        name = response["raw_filename"]
        digest = response["response_sha256"]
        length = response["response_byte_length"]
        print(f"{name}  {digest}  {length}B")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
