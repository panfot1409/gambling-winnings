#!/usr/bin/env python
"""CI gate: the M3A experiment registry binds the committed results/report bytes.

Re-validates the append-only registry lifecycle (registered -> started ->
completed) and requires the terminal event's three publication hashes to equal
the SHA-256s of the committed results JSON, report Markdown, and their bundle.
Also requires the committed results' provenance SHAs to agree with the
registration context. Exits non-zero on any mismatch. Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NoReturn

from eth_research.data.provenance import sha256_bytes
from eth_research.develop_m3a import REPORT_RELPATH, RESULTS_RELPATH, result_bundle_sha256
from eth_research.development_evaluation import load_development_results_payload
from eth_research.experiment_registry import EXPERIMENT_REGISTRY_RELPATH, read_registry

REPO = Path(__file__).resolve().parents[2]


def fail(message: str) -> NoReturn:
    print(f"M3A registry verification FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    events = read_registry(REPO / EXPERIMENT_REGISTRY_RELPATH)
    if [e.event for e in events] != ["registered", "started", "completed"]:
        fail(f"expected registered -> started -> completed, got {[e.event for e in events]}")
    registered, _started, completed = events
    if (
        completed.results_json_sha256 is None
        or completed.report_markdown_sha256 is None
        or completed.result_bundle_sha256 is None
    ):
        fail("the completed event is missing a publication hash")

    results_path = REPO / RESULTS_RELPATH
    report_path = REPO / REPORT_RELPATH
    if not results_path.exists() or not report_path.exists():
        fail("committed results/report are missing")
    results_bytes = results_path.read_bytes()
    report_text = report_path.read_text("utf-8")

    if completed.results_json_sha256 != sha256_bytes(results_bytes):
        fail("completed.results_json_sha256 does not match the committed results file")
    if completed.report_markdown_sha256 != sha256_bytes(report_text.encode("utf-8")):
        fail("completed.report_markdown_sha256 does not match the committed report file")
    if completed.result_bundle_sha256 != result_bundle_sha256(results_bytes, report_text):
        fail("completed.result_bundle_sha256 does not match the committed bundle")

    payload = load_development_results_payload(results_path)
    checks = {
        "execution_code_commit_sha": registered.execution_code_commit_sha,
        "registered_code_commit_sha": registered.registered_code_commit_sha,
        "experiment_family_id": registered.experiment_family,
        "development_partition_sha256": registered.development_partition_sha256,
        "walk_forward_protocol_sha256": registered.walk_forward_protocol_sha256,
    }
    for key, expected in checks.items():
        if payload[key] != expected:
            fail(f"results {key} {payload[key]!r} disagrees with the registration {expected!r}")
    if payload["development_gate_event_count"] != 0 or payload["final_holdout_event_count"] != 0:
        fail("committed results must record zero development-gate and final-holdout events")

    print(
        "M3A registry verified: registered -> started -> completed binds the committed "
        f"results ({completed.results_json_sha256[:12]}...) and report "
        f"({completed.report_markdown_sha256[:12]}...)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
