"""Offline BTC-USD acquisition runner for V2B — this module never opens a socket.

The network boundary lives entirely in the temporary workflow's hardened ``curl``
step. :func:`emit_curl_plan` writes the fixed per-window request parameters that
``curl`` consumes (endpoint, granularity, user agent, canonical start/end params,
safe output filename); after ``curl`` has written the raw bodies plus a per-window
status sidecar into a staging directory, :func:`verify_responses_and_write_receipt`
strictly validates every response **offline** (HTTP 200, ``application/json``, in-window
day-aligned finite OHLCV candles, no forming/duplicate/missing bucket, no unexpected
staged file) and writes a byte-reproducible :class:`~eth_research.v2b.acquisition.BtcAttemptReceipt`
recording body hashes + lengths, never candle values.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from eth_research.v2.strict import strict_json_loads
from eth_research.v2b.acquisition import (
    ATTEMPT_IDS,
    BTC_USER_AGENT,
    MAX_BODY_BYTES,
    BtcAcquisitionError,
    BtcAcquisitionPlan,
    BtcAttemptReceipt,
    BtcResponseReceipt,
    build_attempt_receipt,
    build_btc_acquisition_plan,
    build_window_receipt,
)

RESPONSES_SIDECAR: str = "_responses.jsonl"
CURL_PLAN_FILE: str = "_curl_plan.json"
RECEIPT_FILE: str = "acquisition_receipt.json"
_JSON_CONTENT_TYPE_PREFIX: str = "application/json"
_SIDECAR_KEYS: frozenset[str] = frozenset(
    {"ordinal", "filename", "http_code", "retrieved_at", "content_type"}
)


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _package_version() -> str:
    from eth_research import __version__

    return __version__


# --------------------------------------------------------------------------- #
# emit: the fixed per-window curl request parameters                          #
# --------------------------------------------------------------------------- #
def emit_curl_plan(out_path: str | Path) -> int:
    """Emit the fixed per-window request parameters for the workflow's curl step.

    Offline: builds the one immutable plan and writes the endpoint, fixed granularity,
    user agent, plan hash, and per-window canonical start/end params + safe filename.
    No free-form command string is emitted; the workflow builds ``curl -G`` from these
    validated values only.
    """
    plan = build_btc_acquisition_plan()
    document = {
        "endpoint": plan.endpoint,
        "granularity_seconds": plan.granularity_seconds,
        "user_agent": BTC_USER_AGENT,
        "max_body_bytes": MAX_BODY_BYTES,
        "plan_sha256": plan.plan_sha256(),
        "windows": [
            {
                "ordinal": w.ordinal,
                "start_param": w.requested_start,
                "end_param": w.requested_end,
                "filename": w.filename,
            }
            for w in plan.windows
        ],
    }
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
    _write_atomic(Path(out_path), (text + "\n").encode("utf-8"))
    print(f"emitted {len(plan.windows)} request window(s) for {plan.endpoint}")
    return 0


# --------------------------------------------------------------------------- #
# verify: strict offline validation + receipt                                 #
# --------------------------------------------------------------------------- #
def _parse_sidecar(staging: Path) -> dict[int, dict[str, object]]:
    path = staging / RESPONSES_SIDECAR
    if not path.is_file():
        raise BtcAcquisitionError(f"missing response sidecar {path}")
    records: dict[int, dict[str, object]] = {}
    for position, line in enumerate(path.read_bytes().splitlines(), start=1):
        if not line.strip():
            continue
        payload = strict_json_loads(line)
        if not isinstance(payload, dict):
            raise BtcAcquisitionError(f"sidecar line {position} is not a JSON object")
        if frozenset(payload) != _SIDECAR_KEYS:
            raise BtcAcquisitionError(
                f"sidecar line {position} keys must be {sorted(_SIDECAR_KEYS)}"
            )
        ordinal = payload["ordinal"]
        http_code = payload["http_code"]
        if not isinstance(ordinal, int) or isinstance(ordinal, bool):
            raise BtcAcquisitionError(f"sidecar line {position} ordinal is not an int")
        if not isinstance(http_code, int) or isinstance(http_code, bool):
            raise BtcAcquisitionError(f"sidecar line {position} http_code is not an int")
        for key in ("filename", "retrieved_at", "content_type"):
            if not isinstance(payload[key], str):
                raise BtcAcquisitionError(f"sidecar line {position} {key} is not a string")
        if ordinal in records:
            raise BtcAcquisitionError(f"sidecar line {position}: duplicate ordinal {ordinal}")
        records[ordinal] = payload
    return records


def _reject_unexpected_files(staging: Path, plan: BtcAcquisitionPlan) -> None:
    expected = {w.filename for w in plan.windows}
    allowed = expected | {RESPONSES_SIDECAR, CURL_PLAN_FILE, RECEIPT_FILE}
    present = {p.name for p in staging.iterdir() if p.is_file()}
    unexpected = present - allowed
    if unexpected:
        raise BtcAcquisitionError(f"unexpected staged files: {sorted(unexpected)}")


def verify_responses_and_write_receipt(
    staging_dir: str | Path,
    receipt_out: str | Path,
    *,
    attempt_id: str,
    workflow_run_id: str,
    source_commit: str,
    client_identity: str,
    runner_identity: str,
    created_at_utc: str,
    package_version: str | None = None,
) -> BtcAttemptReceipt:
    """Strictly validate every staged response offline and write the attempt receipt."""
    if attempt_id not in ATTEMPT_IDS:
        raise BtcAcquisitionError(f"attempt_id {attempt_id!r} is not allowlisted")
    staging = Path(staging_dir)
    plan = build_btc_acquisition_plan()
    plan_sha = plan.plan_sha256()
    sidecar = _parse_sidecar(staging)

    receipts: list[BtcResponseReceipt] = []
    for window in plan.windows:
        record = sidecar.get(window.ordinal)
        if record is None:
            raise BtcAcquisitionError(f"no sidecar record for window {window.ordinal}")
        if record["filename"] != window.filename:
            raise BtcAcquisitionError(f"window {window.ordinal} sidecar filename mismatch")
        if record["http_code"] != 200:
            raise BtcAcquisitionError(
                f"window {window.ordinal} returned HTTP {record['http_code']}, not 200"
            )
        content_type = record["content_type"]
        assert isinstance(content_type, str)
        if not content_type.split(";")[0].strip().lower().startswith(_JSON_CONTENT_TYPE_PREFIX):
            raise BtcAcquisitionError(f"window {window.ordinal} content-type {content_type!r}")
        body_path = staging / window.filename
        if body_path.is_symlink() or not body_path.is_file():
            raise BtcAcquisitionError(f"missing raw body {window.filename} in {staging}")
        body = body_path.read_bytes()
        if len(body) > MAX_BODY_BYTES:
            raise BtcAcquisitionError(f"window {window.ordinal} body exceeds the size cap")
        receipt = build_window_receipt(attempt_id, window, body, plan_sha)
        if receipt.parsed_open_count != window.expected_open_count():
            raise BtcAcquisitionError(
                f"window {window.ordinal} parsed {receipt.parsed_open_count} opens, "
                f"expected {window.expected_open_count()}"
            )
        receipts.append(receipt)

    _reject_unexpected_files(staging, plan)

    attempt = build_attempt_receipt(
        attempt_id=attempt_id,
        package_version=package_version or _package_version(),
        plan=plan,
        window_receipts=tuple(receipts),
        source_commit=source_commit,
        workflow_run_id=workflow_run_id,
        runner_identity=runner_identity,
        client_identity=client_identity,
        created_at_utc=created_at_utc,
    )
    _write_atomic(Path(receipt_out), attempt.to_json_bytes())
    return attempt


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - workflow entry
    """CLI: ``emit-plan`` writes the curl request params; ``verify`` validates + writes."""
    parser = argparse.ArgumentParser(description="V2B BTC-USD acquisition runner (offline)")
    sub = parser.add_subparsers(dest="command", required=True)

    emit = sub.add_parser("emit-plan")
    emit.add_argument("--out", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--staging", required=True)
    verify.add_argument("--receipt-out", required=True)
    verify.add_argument("--attempt-id", required=True)
    verify.add_argument("--workflow-run-id", required=True)
    verify.add_argument("--source-commit", required=True)
    verify.add_argument("--client-identity", required=True)
    verify.add_argument("--runner-identity", required=True)
    verify.add_argument("--created-at", required=True)

    args = parser.parse_args(argv)
    if args.command == "emit-plan":
        return emit_curl_plan(args.out)
    receipt = verify_responses_and_write_receipt(
        args.staging,
        args.receipt_out,
        attempt_id=args.attempt_id,
        workflow_run_id=args.workflow_run_id,
        source_commit=args.source_commit,
        client_identity=args.client_identity,
        runner_identity=args.runner_identity,
        created_at_utc=args.created_at,
    )
    for window in receipt.windows:
        print(f"{window.filename}  {window.body_sha256}  {window.body_bytes}B")
    print(f"attempt {receipt.attempt_id}: {receipt.total_parsed_opens()} daily opens")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
