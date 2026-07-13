#!/usr/bin/env python
"""CI gate: the M3A experiment registry binds the committed results/report bytes.

Re-validates the append-only registry lifecycle, verifies **every** completed
experiment's immutable archive and the experiment index (via
:func:`eth_research.experiment_archive.verify_experiment_archive`, which also
refuses a completed-looking archive with no completed event or an extra archive),
requires both sealed access ledgers to be byte-empty, and requires the **latest**
completed experiment's publication hashes to equal the SHA-256s of the committed
compatibility aliases. It dispatches on the latest completed experiment's schema:

* State A (run-003 registered-only, or pre-run-003): the latest completed is a v1
  experiment (run-002) and the aliases are v1 — a registered-only v2 run-003 is
  accepted as history.
* State B (run-003 completed): the latest completed is a v2 experiment and the
  aliases are v2; the v2 provenance, commit-identity, and return-evidence bindings
  are checked.

Exits non-zero on any mismatch. Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NoReturn

from eth_research.artifact_errata import ArtifactErrataError, verify_artifact_errata
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.develop_m3a import REPORT_RELPATH, RESULTS_RELPATH, result_bundle_sha256
from eth_research.experiment_archive import bundle_sha256, verify_experiment_archive
from eth_research.experiment_registry import (
    EXPERIMENT_REGISTRY_RELPATH,
    ExperimentEvent,
    ExperimentEventV2,
    read_registry,
)
from eth_research.gitcheck import is_commit_object

REPO = Path(__file__).resolve().parents[2]
_EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_GATE_LEDGER = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER = "research/m2b/test_evaluations.jsonl"
# The immutable six-line registry-v1 prefix (run-001 + run-002 lifecycles). Its
# byte hash is pinned here so the CI gate — not only a unit test — refuses any
# edit to a v1 prefix line (e.g. a monotonic-preserving timestamp change that the
# append-chain, which only binds v2 lines to their predecessor, would not catch).
_V1_PREFIX_LINES = 6
_V1_PREFIX_SHA256 = "7920d9fdf4e936ef6c6d79dfd1c10cdd12dcb9b2db264b9ab9d5640332e9af67"


def _verify_v1_prefix() -> None:
    raw = (REPO / EXPERIMENT_REGISTRY_RELPATH).read_bytes()
    lines = [line for line in raw.split(b"\n") if line]
    if len(lines) < _V1_PREFIX_LINES:
        fail(f"registry has fewer than {_V1_PREFIX_LINES} lines")
    prefix = b"".join(line + b"\n" for line in lines[:_V1_PREFIX_LINES])
    if sha256_bytes(prefix) != _V1_PREFIX_SHA256:
        fail("the immutable six-line registry v1 prefix has changed")


def fail(message: str) -> NoReturn:
    print(f"M3A registry verification FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def _verify_ledgers() -> None:
    for relpath in (_GATE_LEDGER, _HOLDOUT_LEDGER):
        path = REPO / relpath
        if not path.exists() or path.is_symlink() or sha256_file(path) != _EMPTY_SHA:
            fail(f"sealed ledger {relpath} must be a byte-empty regular file")


def _verify_v1(completed: ExperimentEvent, registered: ExperimentEvent) -> None:
    from eth_research.development_evaluation import load_development_results_payload

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


def _verify_v2(completed: ExperimentEventV2, registered: ExperimentEventV2) -> None:
    from eth_research.development_results_v2 import load_development_results_v2

    results_path = REPO / RESULTS_RELPATH
    report_path = REPO / REPORT_RELPATH
    evidence_path = REPO / registered.return_evidence_path
    for path in (results_path, report_path, evidence_path):
        if not path.exists():
            fail(f"committed v2 artifact {path} is missing")
    results_bytes = results_path.read_bytes()
    report_bytes = report_path.read_text("utf-8").encode("utf-8")
    if completed.results_json_sha256 != sha256_bytes(results_bytes):
        fail("completed.results_json_sha256 does not match the committed v2 results alias")
    if completed.report_markdown_sha256 != sha256_bytes(report_bytes):
        fail("completed.report_markdown_sha256 does not match the committed v2 report alias")
    if completed.return_evidence_sha256 != sha256_file(evidence_path):
        fail("completed.return_evidence_sha256 does not match the committed return evidence")
    if completed.result_bundle_sha256 != bundle_sha256(results_bytes, report_bytes):
        fail("completed.result_bundle_sha256 does not match the committed v2 bundle")

    results = load_development_results_v2(results_path)
    checks = {
        "experiment_id": registered.experiment_id,
        "experiment_family_id": registered.experiment_family,
        "methodology_id": registered.methodology_id,
        "execution_source_commit_sha": registered.execution_code_commit_sha,
        "methodology_freeze_commit_sha": registered.registered_code_commit_sha,
        "execution_source_tree_fingerprint": registered.execution_source_tree_fingerprint,
        "development_partition_sha256": registered.development_partition_sha256,
    }
    for key, expected in checks.items():
        actual = getattr(results, key)
        if actual != expected:
            fail(f"v2 results {key} {actual!r} disagrees with the registration {expected!r}")
    if results.development_gate_event_count != 0 or results.final_holdout_event_count != 0:
        fail("committed v2 results must record zero development-gate and final-holdout events")
    # Git identity: both the execution-source (E) and run-head (R) commits are real.
    for label, sha in (
        ("execution_source_commit_sha", results.execution_source_commit_sha),
        ("run_head_commit_sha", results.run_head_commit_sha),
    ):
        if not is_commit_object(REPO, sha):
            fail(f"v2 results {label} {sha!r} is not a real commit object")


def main() -> int:
    events = read_registry(REPO / EXPERIMENT_REGISTRY_RELPATH)  # validates all lifecycles
    _verify_v1_prefix()  # the immutable six-line v1 prefix is byte-identical
    # Every completed experiment's archive + the index verify (and no extras).
    verify_experiment_archive(REPO)
    _verify_ledgers()
    # Every append-only artifact erratum must verify against its target + results,
    # so a bound correction can never be orphaned or drift from the immutable bytes.
    try:
        errata = verify_artifact_errata(REPO)
    except ArtifactErrataError as exc:
        fail(f"artifact errata do not verify: {exc}")

    completed_events = [e for e in events if e.event == "completed"]
    if not completed_events:
        fail("no completed experiment in the registry")
    completed = completed_events[-1]  # the latest completed experiment binds the current aliases
    registered = next(
        e for e in events if e.experiment_id == completed.experiment_id and e.event == "registered"
    )
    if (
        completed.results_json_sha256 is None
        or completed.report_markdown_sha256 is None
        or completed.result_bundle_sha256 is None
    ):
        fail("the completed event is missing a publication hash")

    if isinstance(completed, ExperimentEventV2):
        assert isinstance(registered, ExperimentEventV2)
        _verify_v2(completed, registered)
        schema = "v2"
    else:
        assert isinstance(registered, ExperimentEvent)
        _verify_v1(completed, registered)
        schema = "v1"

    errata_note = f"; {len(errata)} bound erratum verified" if errata else ""
    alias_prefix = completed.results_json_sha256[:12]
    print(
        f"M3A registry verified ({schema}): {completed.experiment_id} binds the committed aliases "
        f"({alias_prefix}...) with both sealed ledgers byte-empty{errata_note}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
