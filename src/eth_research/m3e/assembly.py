"""Transactional offline assembly of an update proposal.

Given a staged proposal directory (``runner_a/`` + ``runner_b/`` already present),
:func:`assemble_update_proposal` derives the three bound evidence documents
offline, writes them **all-or-nothing** into the proposal directory using the
reviewed transactional primitive (atomic write, readback, strict reparse, rehash,
rollback on any failure), and then **self-verifies** the written proposal against
the full 35-check graph. If the written proposal fails to verify, the derived files
are rolled back to their exact previous bytes and the assembly is refused — a failed
assembly never leaves a partial or unverifiable proposal on disk.

This module moves and verifies bytes only. It opens no socket, computes no strategy
quantity, creates no branch, and opens no pull request — publication of the proposal
as a *draft* PR is a separate, human-gated workflow step.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from eth_research._atomic import write_atomic
from eth_research.m3d.publication import publish_bundle
from eth_research.m3e.proposal import AssembledProposal, assemble_proposal
from eth_research.m3e.validation import M3EValidationError
from eth_research.m3e.verify_m3e_program import verify_update_proposal


class ProposalAssemblyError(M3EValidationError):
    """A transactional proposal assembly failed and was rolled back."""


def assemble_update_proposal(
    repo_root: str | Path, proposal_dir: str | Path
) -> tuple[AssembledProposal, list[tuple[str, str]]]:
    """Derive, transactionally write, and self-verify a proposal; roll back on failure.

    Returns the :class:`AssembledProposal` and the ``(relpath, sha256)`` digests of
    the written evidence files. Raises :class:`ProposalAssemblyError` (after full
    rollback) if the derived proposal cannot be written or does not self-verify.
    """
    root = Path(repo_root)
    directory = Path(proposal_dir)

    assembled = assemble_proposal(root, directory)
    targets = [directory / rel for rel, _ in assembled.blobs]
    for path in targets:
        if path.exists() and not path.is_file():
            raise ProposalAssemblyError(f"proposal target {path.name} is not a regular file")
    previous: dict[Path, bytes | None] = {
        path: (path.read_bytes() if path.is_file() else None) for path in targets
    }

    # Write the three derived blobs all-or-nothing (rollback on write/readback fail).
    digests = publish_bundle(directory, assembled.blobs)

    # Self-verify the written proposal end-to-end; roll back if it does not hold.
    try:
        checks = verify_update_proposal(root, directory)
        if len(checks) != 35:  # pragma: no cover - defensive
            raise ProposalAssemblyError(f"self-verify produced {len(checks)} checks, expected 35")
    except BaseException as exc:
        for path, original in previous.items():
            with contextlib.suppress(OSError):
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    write_atomic(path, original)
        if isinstance(exc, M3EValidationError):
            raise
        raise ProposalAssemblyError(  # pragma: no cover - defensive
            f"proposal assembly failed self-verification and was rolled back ({exc})"
        ) from exc
    return assembled, digests
