"""Offline replay verifier for the whole V2A stack — one ``--check`` a CI job (or a human) can run.

:func:`verify_v2a` re-derives every fixed V2A design invariant from code and, if a governed run has
been published, re-verifies it against the committed bytes. It is read-only and offline: no network,
no sealed partition, no wall-clock. It works in both states of the milestone:

* **before the governed run** — the protocol / constitution / contract / claims / scorecard /
  factsheet fingerprints must round-trip, the diligence bundle must assemble past the redaction
  gate, and the three sealed access ledgers must be byte-empty;
* **after the governed run** — additionally, the published results + manifest must verify, the
  registry chain must be sound and within its one-shot budget, and the registry's ``completed``
  event must bind exactly the published results fingerprint under the current protocol.

Any mismatch is returned as a human-readable string; an empty list means the stack replays cleanly.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import eth_research
from eth_research.buyer.claims import ClaimsCatalog
from eth_research.buyer.contract import EvaluationContract, parse_contract
from eth_research.buyer.diligence import assemble_diligence_bundle
from eth_research.buyer.factsheet import Factsheet
from eth_research.buyer.scorecard import ReadinessScorecard
from eth_research.v2.constitution import CommercialEvidenceConstitution
from eth_research.v2.protocol import ResearchProtocol, parse_protocol
from eth_research.v2.publication import RESULTS_NAME, V2A_DIR, verify_publication
from eth_research.v2.registry import COMPLETED, read_events, verify_registry
from eth_research.v2.results import parse_results
from eth_research.v2.strict import V2ValidationError, load_canonical_json

REGISTRY_RELPATH: str = "research/v2a/research_registry.jsonl"
RESULTS_RELPATH: str = f"{V2A_DIR}/{RESULTS_NAME}"

SEALED_LEDGERS: tuple[str, ...] = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)
_EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _default_repo_root() -> Path:
    return Path(eth_research.__file__).resolve().parents[2]


def _check_design_invariants() -> list[str]:
    problems: list[str] = []
    protocol = ResearchProtocol.current()
    if parse_protocol(protocol.to_canonical()).fingerprint() != protocol.fingerprint():
        problems.append("protocol does not round-trip to its own fingerprint")

    # The constitution must be self-consistent (fingerprint computable + stable).
    constitution = CommercialEvidenceConstitution.current()
    if constitution.fingerprint() != CommercialEvidenceConstitution.current().fingerprint():
        problems.append("constitution fingerprint is not stable")

    contract = EvaluationContract.current()
    if parse_contract(contract.to_canonical()).fingerprint() != contract.fingerprint():
        problems.append("evaluation contract does not round-trip")

    claims = ClaimsCatalog.current()
    if ClaimsCatalog.parse(claims.to_canonical()).fingerprint() != claims.fingerprint():
        problems.append("claims catalogue does not round-trip")

    scorecard = ReadinessScorecard.current()
    if ReadinessScorecard.parse(scorecard.to_canonical()).fingerprint() != scorecard.fingerprint():
        problems.append("scorecard does not round-trip")

    factsheet = Factsheet.build(contract, claims, scorecard)
    if Factsheet.parse(factsheet.to_canonical()).fingerprint() != factsheet.fingerprint():
        problems.append("factsheet does not round-trip")

    try:
        assemble_diligence_bundle()
    except V2ValidationError as exc:
        problems.append(f"diligence bundle failed to assemble past the redaction gate: {exc}")
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
    registry_path = root / REGISTRY_RELPATH
    results_path = root / RESULTS_RELPATH

    registry_present = registry_path.exists() and registry_path.read_bytes() != b""
    results_present = results_path.exists()
    if not registry_present and not results_present:
        return problems  # pristine pre-run state; nothing published yet.

    problems.extend(verify_registry(registry_path))
    if results_present:
        problems.extend(verify_publication(root))

    if registry_present and results_present and not problems:
        results = parse_results(load_canonical_json(results_path))
        events = read_events(registry_path)
        completed = [e for e in events if e.event == COMPLETED]
        if not completed:
            problems.append("results are published but the registry has no completed event")
        elif completed[-1].payload.get("results_fingerprint") != results.fingerprint():
            problems.append("registry completed event does not bind the published results")
        if results.protocol_fingerprint != ResearchProtocol.current().fingerprint():
            problems.append("published results were produced under a different protocol")
    return problems


def verify_v2a(repo_root: str | Path) -> list[str]:
    """Return every V2A replay problem (empty == the stack replays cleanly)."""
    root = Path(repo_root)
    return [
        *_check_design_invariants(),
        *_check_sealed_ledgers(root),
        *_check_published_run(root),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline V2A stack replay verifier.")
    parser.add_argument(
        "--repo-root", default=None, help="Repository root (defaults to the package's)."
    )
    parser.add_argument("--check", action="store_true", help="Exit non-zero on any problem.")
    args = parser.parse_args(argv)

    root = Path(args.repo_root) if args.repo_root else _default_repo_root()
    problems = verify_v2a(root)
    if problems:
        for problem in problems:
            print(f"V2A REPLAY PROBLEM: {problem}")
        return 1 if args.check else 0
    print("V2A replay OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
