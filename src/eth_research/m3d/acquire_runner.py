"""Hardened one-shot acquisition runner for the prospective cohort.

Invoked only by the temporary GitHub Actions workflow. It replays a committed
:class:`ProspectiveAcquisitionPlan` window-by-window against the pinned public
Coinbase endpoint, captures each response body's exact bytes to an allowlisted raw
file, validates it strictly offline (application/json, bounded size, day-aligned
finite OHLCV rows in the declared half-open window), and writes a strict
:class:`ProspectiveAttemptReceipt`. It records body hashes/lengths, never candle
values; it follows no cross-host redirect, uses no secrets, retries only on
429/5xx with bounded backoff, and never retries a policy 403/407.

The HTTP client is injected so the offline validation path is fully testable
without network access; the workflow supplies the real hardened urllib client.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from eth_research.data.coinbase import AcquisitionError, parse_candles_chunk
from eth_research.m3d.acquisition_plan import (
    ENDPOINT,
    GRANULARITY_SECONDS,
    USER_AGENT,
    ProspectiveAcquisitionPlan,
    load_prospective_acquisition_plan,
)
from eth_research.m3d.receipt import (
    RECEIPT_KIND,
    RECEIPT_SCHEMA_VERSION,
    ProspectiveAttemptReceipt,
)
from eth_research.m3d.validation import M3DValidationError, sha256_bytes

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ATTEMPTS = 5
_ALLOWED_HOST = "api.exchange.coinbase.com"
_ALLOWED_SCHEME = "https"


@dataclass(frozen=True)
class FetchResult:
    status: int
    content_type: str
    body: bytes
    attempt_count: int


class AcquisitionRunnerError(M3DValidationError):
    """The runner refused an unsafe or malformed acquisition state."""


def window_url(start_param: str, end_param: str) -> str:
    """The exact request URL for a plan window (pinned host/path, no secrets)."""
    return f"{ENDPOINT}?start={start_param}&end={end_param}&granularity={GRANULARITY_SECONDS}"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise AcquisitionRunnerError(f"refusing redirect to {newurl!r}")


def hardened_urllib_fetch(url: str, *, timeout: float = 30.0) -> FetchResult:
    """Fetch ``url`` with TLS, no cross-host redirect, size + content-type limits.

    Retries only on 429/5xx with linear backoff up to :data:`MAX_ATTEMPTS`; a policy
    403/407 is never retried. Never follows a redirect to a different host.
    """
    parts = urlsplit(url)
    if parts.scheme != _ALLOWED_SCHEME or parts.hostname != _ALLOWED_HOST:
        raise AcquisitionRunnerError(f"refusing non-pinned URL {url!r}")
    opener = urllib.request.build_opener(_NoRedirectHandler())
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with opener.open(request, timeout=timeout) as response:
                final_host = urlsplit(response.geturl()).hostname
                if final_host != _ALLOWED_HOST:
                    raise AcquisitionRunnerError(f"response host changed to {final_host!r}")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise AcquisitionRunnerError("response exceeds the maximum allowed size")
                content_type = response.headers.get("Content-Type", "")
                return FetchResult(
                    status=response.status,
                    content_type=content_type,
                    body=body,
                    attempt_count=attempt,
                )
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 407):
                raise AcquisitionRunnerError(f"policy status {exc.code}; not retrying") from exc
            if exc.code == 429 or 500 <= exc.code < 600:
                last_error = f"status {exc.code}"
                _sleep_backoff(attempt)
                continue
            raise AcquisitionRunnerError(f"HTTP status {exc.code}") from exc
        except urllib.error.URLError as exc:
            last_error = str(exc.reason)
            _sleep_backoff(attempt)
            continue
    raise AcquisitionRunnerError(f"exhausted {MAX_ATTEMPTS} attempts: {last_error}")


def _sleep_backoff(attempt: int) -> None:  # pragma: no cover - timing side effect
    import time

    time.sleep(min(8.0, 1.0 * attempt))


def run_acquisition(
    repo_root: str | Path,
    plan_path: str | Path,
    raw_dir: str | Path,
    *,
    source_commit: str,
    workflow_run_id: str,
    runner_identity: str,
    client_identity: str,
    fetcher: Callable[[str], FetchResult] = hardened_urllib_fetch,
    clock: Callable[[], str] | None = None,
) -> ProspectiveAttemptReceipt:
    """Replay the plan, capture + strictly validate each response, write the receipt.

    Writes each response body verbatim to ``raw_dir/<raw_filename>`` and returns the
    validated attempt receipt (the caller serializes it beside the raw files).
    Refuses unsafe filenames, unexpected/duplicate raw files, malformed content
    types, non-200 statuses, and any candle outside the declared half-open window.
    """
    tick = clock if clock is not None else _utc_now_z
    plan: ProspectiveAcquisitionPlan = load_prospective_acquisition_plan(plan_path)
    out_dir = Path(raw_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    expected_files = {str(w["raw_filename"]) for w in plan.windows}
    responses: list[dict[str, object]] = []
    for window in plan.windows:
        start_param = str(window["start_param"])
        end_param = str(window["end_param"])
        started = tick()
        result = fetcher(window_url(start_param, end_param))
        completed = tick()
        if result.status != 200:
            raise AcquisitionRunnerError(f"window {window['ordinal']}: HTTP {result.status}")
        if not result.content_type.split(";")[0].strip().lower().startswith("application/json"):
            raise AcquisitionRunnerError(
                f"window {window['ordinal']}: content-type {result.content_type!r}"
            )
        # Strict offline validation of the candle body in the declared window.
        window_start = pd.Timestamp(start_param)
        window_end = pd.Timestamp(end_param)
        try:
            parsed = parse_candles_chunk(
                result.body, window_start=window_start, window_end=window_end
            )
        except AcquisitionError as exc:
            raise AcquisitionRunnerError(f"window {window['ordinal']}: {exc}") from exc
        if not parsed.candles:
            raise AcquisitionRunnerError(
                f"window {window['ordinal']}: no completed candle (HARD STOP)"
            )
        raw_name = str(window["raw_filename"])
        (out_dir / raw_name).write_bytes(result.body)
        responses.append(
            {
                "ordinal": int(window["ordinal"]),
                "raw_filename": raw_name,
                "start_param": start_param,
                "end_param": end_param,
                "http_status": result.status,
                "content_type": result.content_type,
                "response_byte_length": len(result.body),
                "response_sha256": sha256_bytes(result.body),
                "retrieval_started_utc": started,
                "retrieval_completed_utc": completed,
                "attempt_count": result.attempt_count,
            }
        )

    # No unexpected raw file may exist in the output directory.
    present = {p.name for p in out_dir.iterdir() if p.is_file() and p.suffix == ".json"}
    if unexpected := present - expected_files - {"acquisition_receipt.json"}:
        raise AcquisitionRunnerError(f"unexpected raw files present: {sorted(unexpected)}")

    from eth_research.m3d import M3D_PACKAGE_VERSION

    document = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": RECEIPT_KIND,
        "package_version": M3D_PACKAGE_VERSION,
        "attempt_id": plan.attempt_id,
        "plan_sha256": plan.plan_sha256,
        "endpoint": ENDPOINT,
        "user_agent": USER_AGENT,
        "source_commit": source_commit,
        "workflow_run_id": workflow_run_id,
        "runner_identity": runner_identity,
        "client_identity": client_identity,
        "created_at_utc": tick(),
        "responses": responses,
    }
    return ProspectiveAttemptReceipt.from_mapping(document)


def _utc_now_z() -> str:  # pragma: no cover - wall clock
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - workflow entry
    """CLI used by the one-shot acquisition workflow to fetch + write evidence."""
    import argparse

    parser = argparse.ArgumentParser(description="M3D prospective one-shot acquisition runner")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--runner-identity", required=True)
    parser.add_argument("--client-identity", required=True)
    parser.add_argument("--receipt-out", required=True)
    args = parser.parse_args(argv)

    receipt = run_acquisition(
        ".",
        args.plan,
        args.raw_dir,
        source_commit=args.source_commit,
        workflow_run_id=args.workflow_run_id,
        runner_identity=args.runner_identity,
        client_identity=args.client_identity,
    )
    Path(args.receipt_out).write_bytes(receipt.to_json_bytes())
    # Print body hashes only, never candle values.
    for response in receipt.responses:
        name = response["raw_filename"]
        digest = response["response_sha256"]
        length = response["response_byte_length"]
        print(f"{name}  {digest}  {length}B")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
