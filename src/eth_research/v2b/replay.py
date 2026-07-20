"""Offline replay verifier for the whole V2B one-shot stack — one ``--check`` for CI and audits.

:func:`verify_v2b` re-derives every frozen V2B design invariant from code and, if a governed run has
been registered or published, re-verifies it against the committed bytes. It is read-only and
offline: no network, no sealed partition, no wall clock. It handles all three states of the
milestone:

* **pristine (before R)** — the budget, protocol identity, execution scenarios, and cumulative
  multiplicity state reproduce byte-for-byte, and the three sealed access ledgers are byte-empty
  (registry + results still absent);
* **registered (after R)** — additionally, the registry chain is sound, within its one-shot budget,
  and every event is bound to the committed protocol fingerprint (results still absent);
* **completed (after P)** — additionally, the published results + manifest verify, and the registry
  ``completed`` event binds exactly the published results fingerprint under the current protocol.

Any mismatch is returned as a human-readable string; an empty list means the stack replays cleanly.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import eth_research
from eth_research.v2.strict import V2ValidationError
from eth_research.v2b import V2B_DIR
from eth_research.v2b.governance import (
    COMPLETED,
    V2B_REGISTRY_RELPATH,
    protocol_fingerprint,
    read_events,
    verify_budget,
    verify_protocol_identity,
    verify_registry_bound,
)
from eth_research.v2b.multiplicity import verify_multiplicity
from eth_research.v2b.publication import RESULTS_NAME, verify_publication
from eth_research.v2b.results import summarize_committed
from eth_research.v2b.scenarios import verify_scenario_declaration

V2B_RESULTS_RELPATH: str = f"{V2B_DIR}/{RESULTS_NAME}"

SEALED_LEDGERS: tuple[str, ...] = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)
_EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _default_repo_root() -> Path:
    return Path(eth_research.__file__).resolve().parents[2]


def _check_design_invariants(root: Path) -> list[str]:
    """The frozen governance inputs reproduce byte-for-byte from the running package."""
    problems: list[str] = []
    for check in (verify_budget, verify_protocol_identity, verify_scenario_declaration):
        try:
            check(root)
        except (OSError, V2ValidationError) as exc:
            problems.append(str(exc))
    problems.extend(verify_multiplicity(root))
    return problems


def _check_sealed_ledgers(root: Path) -> list[str]:
    from eth_research.data.provenance import sha256_file

    problems: list[str] = []
    for rel in SEALED_LEDGERS:
        path = root / rel
        if not path.exists():
            problems.append(f"sealed ledger {rel} is missing")
        elif path.read_bytes() != b"" or sha256_file(path) != _EMPTY_SHA:
            problems.append(f"sealed ledger {rel} is not byte-empty")
    return problems


def _check_published_run(root: Path) -> list[str]:
    problems: list[str] = []
    registry_path = root / V2B_REGISTRY_RELPATH
    results_path = root / V2B_RESULTS_RELPATH

    registry_present = registry_path.exists() and registry_path.read_bytes() != b""
    results_present = results_path.exists()
    if not registry_present and not results_present:
        return problems  # pristine pre-run state; nothing registered or published yet.

    # Chain integrity + lifecycle + every event bound to the committed protocol fingerprint.
    problems.extend(verify_registry_bound(root))
    try:
        events = read_events(registry_path) if registry_present else ()
    except V2ValidationError:
        events = ()  # already reported by verify_registry_bound above
    completed = [e for e in events if e.event == COMPLETED]

    # The expectation is derived from the REGISTRY, not from file existence: a completed run must
    # have published verifiable results, and published results must be backed by a completed event.
    if completed and not results_present:
        problems.append("registry has a completed event but no published results")
    if results_present and not completed:
        problems.append("published results are not backed by a completed registry event")

    if results_present:
        problems.extend(verify_publication(root))
        if completed and not problems:
            summary = summarize_committed(results_path.read_bytes())
            if completed[-1].payload.get("results_fingerprint") != summary.fingerprint:
                problems.append("registry completed event does not bind the published results")
            if summary.protocol_fingerprint != protocol_fingerprint(root):
                problems.append("published results were produced under a different protocol")
    return problems


def verify_v2b(repo_root: str | Path) -> list[str]:
    """Return every V2B replay problem (empty == the stack replays cleanly)."""
    root = Path(repo_root)
    return [
        *_check_design_invariants(root),
        *_check_sealed_ledgers(root),
        *_check_published_run(root),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline V2B one-shot stack replay verifier.")
    parser.add_argument("--repo-root", default=None, help="Repository root (defaults to package).")
    parser.add_argument("--check", action="store_true", help="Exit non-zero on any problem.")
    args = parser.parse_args(argv)

    root = Path(args.repo_root) if args.repo_root else _default_repo_root()
    problems = verify_v2b(root)
    if problems:
        for problem in problems:
            print(f"V2B REPLAY PROBLEM: {problem}")
        return 1 if args.check else 0
    print("V2B replay OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
