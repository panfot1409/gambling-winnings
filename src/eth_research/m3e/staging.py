"""Stage the cohort extension a verified proposal proposes (transactional, offline).

With V2D, the bot branch carries — in one reviewable commit — both the proposal
evidence (``research/m3e/proposals/<id>/``) and the **staged cohort extension** it
implies, so a single human merge lands evidence and growth atomically and the
cohort state can never lag its own accepted evidence. This module derives that
extension deterministically from the already-assembled, already-35-check-verified
proposal:

1. the m3d update-attempt evidence directory
   (``research/m3d/raw/coinbase/<attempt-id>/``) — runner A's update plan, receipt,
   and raw bodies **byte-for-byte** (runner B stays in the proposal directory as the
   independent attestation);
2. the appended ``research/m3d/update_attempts.jsonl`` ledger entry (exact-prefix
   preserving);
3. the rebuilt derived artifacts — segment chain, quality report, cohort manifest,
   publication manifest, ``research/m3e/accepted_base.json`` — via the reviewed
   deterministic builders over the grown evidence;
4. the appended ``research/m3e/proposal_registry.jsonl`` record.

Everything is written through the reviewed transactional primitive and then
**self-verified** with :func:`eth_research.m3e.verify_m3e_program.verify_landed_update`;
any failure rolls the whole staged extension back to its exact previous bytes
(created files removed, the attempt directory deleted). No socket is opened, no
strategy quantity is computed, no value leaves the data plane, and nothing here
pushes or merges — the staged extension still lands only through a human merge of
the draft proposal PR.
"""

from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from eth_research._atomic import write_atomic
from eth_research.m3d.cohort import build_prospective_publication_blobs
from eth_research.m3d.publication import publish_bundle
from eth_research.m3d.quality import QUALITY_PATH, build_prospective_quality_bytes
from eth_research.m3d.segment import SEGMENTS_PATH, build_prospective_segments_bytes
from eth_research.m3d.update_attempts import (
    UPDATE_ATTEMPTS_PATH,
    UPDATE_ATTEMPTS_SCHEMA_VERSION,
    extend_update_attempts_bytes,
    load_update_attempt_entries,
)
from eth_research.m3d.validation import sha256_bytes
from eth_research.m3e.accepted_base import ACCEPTED_BASE_PATH, build_accepted_base_bytes
from eth_research.m3e.acquire_runner import RUNNER_PLAN_FILENAME, RUNNER_RECEIPT_FILENAME
from eth_research.m3e.proposal import RUNNER_A_DIR, AssembledProposal
from eth_research.m3e.registry import REGISTRY_PATH, build_registry_bytes
from eth_research.m3e.runner_boundary import load_and_verify_runner
from eth_research.m3e.validation import M3EValidationError
from eth_research.m3e.verify_m3e_program import verify_landed_update


class StagingError(M3EValidationError):
    """Staging the cohort extension failed and was fully rolled back."""


@dataclass(frozen=True)
class StagedExtension:
    """The exact repository-relative paths one staged cohort extension touches."""

    attempt_id: str
    attempt_relpaths: tuple[str, ...]
    derived_relpaths: tuple[str, ...]

    @property
    def all_relpaths(self) -> tuple[str, ...]:
        return (*self.attempt_relpaths, *self.derived_relpaths)


def update_attempt_id(assembled: AssembledProposal) -> str:
    """Deterministic attempt id: window bounds + idempotency-key prefix."""
    transition = assembled.transition
    first = transition.new_window_first_open[:10].replace("-", "")
    last = transition.new_window_last_open[:10].replace("-", "")
    return f"coinbase-eth-usd-prospective-update-{first}-{last}-{assembled.idempotency_key[:16]}"


def stage_cohort_extension(repo_root: str | Path, assembled: AssembledProposal) -> StagedExtension:
    """Derive, transactionally write, and self-verify the staged cohort extension.

    ``assembled`` must be the output of :func:`~eth_research.m3e.assembly.assemble_update_proposal`
    (its proposal directory already written and 35-check self-verified against the
    pre-update base). On success the working tree carries the grown cohort and the
    full landed-update verification has passed; on any failure every touched path
    is restored to its exact previous state and :class:`StagingError` is raised.
    """
    root = Path(repo_root)
    proposal_dir = assembled.proposal_dir
    runner_a = load_and_verify_runner(proposal_dir / RUNNER_A_DIR, runner_label="a")
    transition = assembled.transition
    attempt_id = update_attempt_id(assembled)

    attempt_rel = f"research/m3d/raw/coinbase/{attempt_id}"
    attempt_dir = root / attempt_rel
    if attempt_dir.exists():
        raise StagingError(f"update attempt directory already exists: {attempt_rel}")
    ledger_path = root / UPDATE_ATTEMPTS_PATH
    existing_ledger = ledger_path.read_bytes() if ledger_path.exists() else None

    receipt_bytes = (proposal_dir / RUNNER_A_DIR / RUNNER_RECEIPT_FILENAME).read_bytes()
    entry = {
        "schema_version": UPDATE_ATTEMPTS_SCHEMA_VERSION,
        "entry_kind": "update_attempt",
        "ordinal": len(load_update_attempt_entries(root)) + 1,
        "attempt_id": attempt_id,
        "first_open": transition.new_window_first_open,
        "last_open": transition.new_window_last_open,
        "row_count": transition.new_window_row_count,
        "plan_sha256": runner_a.plan_sha256,
        "receipt_sha256": sha256_bytes(receipt_bytes),
        "proposal_id": proposal_dir.name,
        "created_at_utc": _receipt_created_at(proposal_dir),
        "package_version": _m3d_package_version(),
    }

    # Remember the exact previous bytes of every derived artifact we will rewrite.
    derived_rels = (
        SEGMENTS_PATH,
        QUALITY_PATH,
        "research/m3d/prospective_manifest.json",
        "research/m3d/publication_manifest.json",
        ACCEPTED_BASE_PATH,
        REGISTRY_PATH,
        UPDATE_ATTEMPTS_PATH,
    )
    previous: dict[Path, bytes | None] = {
        root / rel: ((root / rel).read_bytes() if (root / rel).exists() else None)
        for rel in derived_rels
    }

    attempt_relpaths: list[str] = []
    try:
        # 1. The attempt evidence directory — runner A's artifact, byte-for-byte
        #    (the update plan is committed under the m3d evidence name).
        attempt_dir.mkdir(parents=True)
        copies = [
            (RUNNER_PLAN_FILENAME, "acquisition_plan.json"),
            (RUNNER_RECEIPT_FILENAME, "acquisition_receipt.json"),
            *((b.raw_filename, b.raw_filename) for b in runner_a.bundles),
        ]
        for src_name, dst_name in copies:
            data = (proposal_dir / RUNNER_A_DIR / src_name).read_bytes()
            write_atomic(attempt_dir / dst_name, data)
            attempt_relpaths.append(f"{attempt_rel}/{dst_name}")

        # 2. The ledger entry (exact-prefix preserving append).
        write_atomic(ledger_path, extend_update_attempts_bytes(existing_ledger, entry))

        # 3. The derived artifacts, rebuilt over the grown evidence: chain +
        #    quality first (pure functions), then the transactional publication
        #    bundle (segments/audit/quality/manifest + completeness marker), then
        #    the accepted-base snapshot and the registry.
        write_atomic(root / SEGMENTS_PATH, build_prospective_segments_bytes(root))
        write_atomic(root / QUALITY_PATH, build_prospective_quality_bytes(root))
        publish_bundle(root, build_prospective_publication_blobs(root))
        write_atomic(root / ACCEPTED_BASE_PATH, build_accepted_base_bytes(root))
        write_atomic(root / REGISTRY_PATH, build_registry_bytes(root))

        # 4. Self-verify the grown tree against this proposal, end to end.
        verify_landed_update(root, proposal_dir)
    except BaseException as exc:
        for path, original in previous.items():
            with contextlib.suppress(OSError):
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    write_atomic(path, original)
        with contextlib.suppress(OSError):
            shutil.rmtree(attempt_dir, ignore_errors=True)
        if isinstance(exc, M3EValidationError):
            raise StagingError(f"staging failed and was rolled back: {exc}") from exc
        raise StagingError(  # pragma: no cover - defensive
            f"staging failed and was rolled back ({exc})"
        ) from exc

    return StagedExtension(
        attempt_id=attempt_id,
        attempt_relpaths=tuple(attempt_relpaths),
        derived_relpaths=derived_rels,
    )


def _receipt_created_at(proposal_dir: Path) -> str:
    from eth_research.m3d.receipt import load_prospective_attempt_receipt

    receipt = load_prospective_attempt_receipt(
        proposal_dir / RUNNER_A_DIR / RUNNER_RECEIPT_FILENAME
    )
    return str(receipt.document["created_at_utc"])


def _m3d_package_version() -> str:
    from eth_research.m3d import M3D_PACKAGE_VERSION

    return str(M3D_PACKAGE_VERSION)
