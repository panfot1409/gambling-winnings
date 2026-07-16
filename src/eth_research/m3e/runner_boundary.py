"""The workflow-artifact ↔ offline-runner trust boundary.

A runner *job* in the update workflow produces an untrusted artifact directory: the
committed update plan, a strict acquisition receipt, and the retained raw JSON
bodies. This module is the single, typed boundary that turns that untrusted
artifact into a :class:`VerifiedRunner` — trusting **no** value that is not
re-derived from bytes:

* the update plan reloads and re-validates (idempotency + plan hash recomputed);
* the receipt's plan hash binds to that plan;
* every raw file's SHA-256 binds to the receipt and transforms into canonical rows
  under the strict adapter, bound to the pre-registered window
  (:func:`eth_research.m3e.acquisition.build_runner_bundles`);
* the new-window fingerprint is computed from the canonical rows.

Only the runner **identity** facts (attempt id, source commit, workflow run id,
runner identity) are read from the receipt as recorded provenance; every *content*
claim is re-derived. Two independently-produced ``VerifiedRunner`` objects feed the
canonical-equality comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.m3d.receipt import ProspectiveAttemptReceipt, load_prospective_attempt_receipt
from eth_research.m3e.acquire_runner import RUNNER_PLAN_FILENAME, RUNNER_RECEIPT_FILENAME
from eth_research.m3e.acquisition import (
    RunnerWindowBundle,
    build_runner_bundles,
    new_window_canonical_rows,
    new_window_fingerprint,
)
from eth_research.m3e.update_plan import ProspectiveUpdatePlan, load_update_plan
from eth_research.m3e.validation import (
    M3EValidationError,
    require_sha256_hex,
    require_str,
)


@dataclass(frozen=True)
class VerifiedRunner:
    """A fully re-derived, trusted view of one runner's acquisition artifact."""

    runner_label: str
    attempt_id: str
    source_commit: str
    workflow_run_id: str
    runner_identity: str
    plan_sha256: str
    idempotency_key: str
    new_window_fingerprint: str
    first_open: str
    last_open: str
    row_count: int
    bundles: tuple[RunnerWindowBundle, ...]

    @property
    def canonical_rows(self) -> list[list[Any]]:
        return new_window_canonical_rows(list(self.bundles))

    def identity_tuple(self) -> tuple[str, str, str]:
        """The independence-bearing identity (source commit, run id, runner)."""
        return (self.source_commit, self.workflow_run_id, self.runner_identity)


def load_and_verify_runner(
    runner_dir: str | Path,
    *,
    runner_label: str,
    expected_plan_sha256: str | None = None,
) -> VerifiedRunner:
    """Re-derive and verify a runner artifact directory into a :class:`VerifiedRunner`.

    ``expected_plan_sha256``, when given, requires this runner to have replayed
    exactly that update plan — so both runners are pinned to the *same* plan.
    """
    directory = Path(runner_dir)
    plan_path = directory / RUNNER_PLAN_FILENAME
    receipt_path = directory / RUNNER_RECEIPT_FILENAME
    for path in (plan_path, receipt_path):
        if path.is_symlink() or not path.is_file():
            raise M3EValidationError(f"runner artifact missing a regular {path.name}")

    plan: ProspectiveUpdatePlan = load_update_plan(plan_path)
    if expected_plan_sha256 is not None and plan.plan_sha256 != require_sha256_hex(
        "expected_plan_sha256", expected_plan_sha256
    ):
        raise M3EValidationError(f"runner {runner_label!r} replayed a different update plan")

    # A runner directory is a CLOSED file-set: exactly the plan, the receipt, and the
    # raw bodies the plan declares — nothing else. An extra file (even one whose name
    # carries no strategy marker, so the proposal marker-scan would miss it), a
    # subdirectory, or a symlink is a smuggled artifact and is refused here, at the one
    # typed boundary that re-derives the runner from bytes.
    allowed = {RUNNER_PLAN_FILENAME, RUNNER_RECEIPT_FILENAME} | {
        str(window["raw_filename"]) for window in plan.windows
    }
    for entry in sorted(directory.iterdir()):
        if entry.is_symlink() or not entry.is_file():
            raise M3EValidationError(
                f"runner {runner_label!r} directory has a non-regular entry: {entry.name}"
            )
        if entry.name not in allowed:
            raise M3EValidationError(
                f"runner {runner_label!r} directory has an unexpected file: {entry.name}"
            )

    receipt: ProspectiveAttemptReceipt = load_prospective_attempt_receipt(receipt_path)
    bundles = build_runner_bundles(raw_dir=directory, update_plan=plan, receipt=receipt)
    rows = new_window_canonical_rows(bundles)
    fingerprint = new_window_fingerprint(bundles)

    doc = receipt.document
    return VerifiedRunner(
        runner_label=require_str("runner_label", runner_label),
        attempt_id=require_str("attempt_id", doc["attempt_id"]),
        source_commit=require_str("source_commit", doc["source_commit"]),
        workflow_run_id=require_str("workflow_run_id", doc["workflow_run_id"]),
        runner_identity=require_str("runner_identity", doc["runner_identity"]),
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.idempotency_key,
        new_window_fingerprint=fingerprint,
        first_open=rows[0][0],
        last_open=rows[-1][0],
        row_count=len(rows),
        bundles=tuple(bundles),
    )
