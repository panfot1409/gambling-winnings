"""V2A-V2B stacked-acceptance package (read-only, result-neutral).

Independent acceptance machinery for the stacked V2A->V2B milestones: a complete immutable freeze
table, independent result-reconstruction oracles, a BTC acquisition and raw->result provenance
audit, a cumulative research-family enumeration, the permanent legacy-research moratorium, a
negative-evidence index and research-debt register, and the commercial-truth pack. Nothing here
evaluates a candidate, reads a sealed partition, appends a research-experiment event, or mutates any
accepted result; every module reconstructs and verifies from already-committed primitive evidence.

The one governance addition here -- the legacy-research moratorium -- is explicitly a post-run
control and never claims to have existed before the V2A/V2B executions.
"""

from __future__ import annotations

from pathlib import Path

#: Governed content roots enumerated by the freeze table and the acceptance verifiers.
GOVERNED_ROOTS: tuple[str, ...] = ("research", "release")

#: The accepted stacked SHAs, frozen at acceptance-plan time. Recorded for documentation and
#: cross-checks; the verifiers never trust these over the live git state.
ACCEPTED_MAIN_SHA: str = "30e119933feb3d30cf3a890b177ea24b14ffc0da"
ACCEPTED_V2A_HEAD_SHA: str = "d437dafd67047470eae2c88fb14f0d8db6bf7091"
ACCEPTED_V2B_HEAD_SHA: str = "5798610389af0905331fc5da20f54f4b8f7930fb"

#: Frozen immutable identities the acceptance verifiers must reproduce (§2 of the plan).
EMPTY_LEDGER_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
V2A_RESULTS_FINGERPRINT: str = "6327de21759c21a97c8b1ee9c14782bb36534c8d968d6792eba54b7c9c58cbca"
V2B_RESULTS_FINGERPRINT: str = "d0b668f45c9e1f6adfeb606e16003a4bd5649d39bb0676a444cb691ec9fe6f1f"
V2B_PROTOCOL_FINGERPRINT: str = "2bdf606e24b6715442c5e3f0b14c16c11acac66d30f9d7774a16a82b20cf61f7"

#: The three sealed access ledgers that must stay byte-empty throughout.
SEALED_LEDGER_RELPATHS: tuple[str, ...] = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)


def repo_root_of(path: str | Path) -> Path:
    """Return an absolute, resolved repository root for ``path`` (no traversal surprises)."""
    return Path(path).resolve()


__all__ = [
    "ACCEPTED_MAIN_SHA",
    "ACCEPTED_V2A_HEAD_SHA",
    "ACCEPTED_V2B_HEAD_SHA",
    "EMPTY_LEDGER_SHA256",
    "GOVERNED_ROOTS",
    "SEALED_LEDGER_RELPATHS",
    "V2A_RESULTS_FINGERPRINT",
    "V2B_PROTOCOL_FINGERPRINT",
    "V2B_RESULTS_FINGERPRINT",
    "repo_root_of",
]
