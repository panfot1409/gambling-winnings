#!/usr/bin/env python3
"""Genuinely independent Milestone 3F verifier — Python standard library only.

This tool deliberately imports **neither** ``eth_research`` **nor** any third-party
package. It re-derives the repository's governance facts and re-hashes the frozen
artifacts through a *separate* code path (its own strict JSON reader, its own
SHA-256 calls, its own workflow scan), so a common-mode defect in the packaged
``eth_research.m3f`` verifiers cannot conceal the same defect here. If the two
verifiers ever disagree, that disagreement is itself the finding.

It is strictly read-only: it never computes a strategy signal, a return, a metric,
a network call, or a wall-clock decision, and it never writes a file. It exits
nonzero on any failure.

Checks that need no committed M3F artifact (they hold both before and after the
registration commit):

  * the three sealed access ledgers are byte-empty (length 0, empty-file SHA-256);
  * the M3C candidate verdict is the rejected/terminal one;
  * the M3D cohort is immature and not evaluation-authorized, with row count below
    the committed maturity threshold;
  * the M3E production-proposal count (parsed, whitespace-independent, fail-closed)
    is exactly zero;
  * no committed workflow grants ``contents: write`` / ``write-all``.

Checks that run once the registration artifacts exist:

  * every artifact recorded in ``research/m3f/freeze_catalog.json`` re-hashes to its
    recorded SHA-256 from the working tree, and the catalog's own governance
    summary agrees with this tool's independent derivation;
  * the committed ``research/m3f/honest_state.json`` governance fields agree with
    this tool's independent derivation.

Usage: ``python tools/m3f_independent_verify.py [--repo-root .] [--json]``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

# Write-permission detection mirroring the packaged hardened scanner — kept as an
# independent copy here (stdlib only) so a multi-space / tab / trailing-comment / flow
# / anchor grant is caught by the independent verifier too, not just the package.
_BLOCK_WRITE_RE = re.compile(
    r"^\s*[A-Za-z_-]+\s*:\s*['\"]?write(?:-all)?['\"]?\s*(?:#.*)?$", re.MULTILINE
)
_FLOW_WRITE_RE = re.compile(r"permissions\s*:\s*\{[^}]*\bwrite(?:-all)?\b", re.IGNORECASE)
_ANCHOR_WRITE_RE = re.compile(r"&[\w-]+\s+['\"]?write(?:-all)?\b", re.IGNORECASE)

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
MATURITY_THRESHOLD = 365
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024  # a governed artifact is never this large

SEALED_LEDGERS = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)
M3C_DECISION = "research/m3c/candidate_decision.json"
M3E_ACCEPTED_BASE = "research/m3e/accepted_base.json"
M3E_REGISTRY = "research/m3e/proposal_registry.jsonl"
CATALOG_RELPATH = "research/m3f/freeze_catalog.json"
HONEST_STATE_RELPATH = "research/m3f/honest_state.json"
REJECTED_VERDICT = "rejected_for_development_gate_promotion"
WORKFLOW_DIR = ".github/workflows"
# Any of these existing means the repository is registered, so the catalog + honest
# state must also exist — a deletion of either is a failure, not a skipped check.
_REGISTRATION_MARKERS = (
    CATALOG_RELPATH,
    HONEST_STATE_RELPATH,
    "research/m3f/dependency_inventory.json",
    "research/m3f/workflow_inventory.json",
    "research/m3f/recovery_capsule_manifest.json",
    "research/m3f/recovery_drill.json",
)


class IndependentVerifyError(Exception):
    """A committed artifact failed an independent strict check."""


# --------------------------------------------------------------------------- #
# strict, dependency-free primitives                                          #
# --------------------------------------------------------------------------- #
def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise IndependentVerifyError(f"duplicate JSON key: {key!r}")
        seen[key] = value
    return seen


def _reject_constant(token: str) -> Any:
    raise IndependentVerifyError(f"non-finite JSON constant: {token}")


def _loads(text: str) -> Any:
    try:
        return json.loads(
            text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant
        )
    except json.JSONDecodeError as exc:
        raise IndependentVerifyError(f"invalid JSON: {exc}") from exc


def _read_bytes(root: Path, relpath: str) -> bytes:
    path = root / relpath
    raw = path.read_bytes()
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise IndependentVerifyError(f"{relpath}: exceeds the parse ceiling")
    return raw


def _load_json(root: Path, relpath: str) -> Any:
    raw = _read_bytes(root, relpath)
    if raw and not raw.endswith(b"\n"):
        raise IndependentVerifyError(f"{relpath}: missing canonical trailing newline")
    return _loads(raw.decode("utf-8"))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IndependentVerifyError(message)


def _count_created_proposals(raw: bytes) -> int:
    """Independently count created proposals: parse each line, fail-closed count."""
    count = 0
    for line in raw.decode("utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        record = _loads(stripped)
        if isinstance(record, dict):
            created = record.get("proposal_created")
            if created is not None and created is not False:
                count += 1
    return count


# --------------------------------------------------------------------------- #
# independent governance derivation                                           #
# --------------------------------------------------------------------------- #
def _derive_facts(root: Path) -> dict[str, Any]:
    decision = _load_json(root, M3C_DECISION)
    base = _load_json(root, M3E_ACCEPTED_BASE)
    _require(isinstance(decision, dict), f"{M3C_DECISION}: not a JSON object")
    _require(isinstance(base, dict), f"{M3E_ACCEPTED_BASE}: not a JSON object")

    row_count = base.get("row_count")
    threshold = base.get("minimum_maturity_rows", MATURITY_THRESHOLD)
    _require(isinstance(row_count, int) and not isinstance(row_count, bool), "row_count not an int")
    _require(
        isinstance(threshold, int) and not isinstance(threshold, bool),
        "minimum_maturity_rows not an int",
    )
    authorized = base.get("evaluation_authorized")
    _require(isinstance(authorized, bool), "evaluation_authorized not a bool")

    proposals = _count_created_proposals(_read_bytes(root, M3E_REGISTRY))
    return {
        "m3c_verdict": decision.get("outcome"),
        "m3d_row_count": row_count,
        "m3d_maturity_threshold": threshold,
        "m3d_maturity_state": base.get("maturity_state"),
        "m3d_evaluation_authorized": authorized,
        "m3e_production_proposal_count": proposals,
    }


def _workflow_paths(root: Path) -> list[Path]:
    wf = root / WORKFLOW_DIR
    if not wf.is_dir():
        return []
    return sorted([*wf.glob("*.yml"), *wf.glob("*.yaml")])


def _workflow_grants_write(text: str) -> bool:
    return bool(
        "write-all" in text
        or _BLOCK_WRITE_RE.search(text)
        or _FLOW_WRITE_RE.search(text)
        or _ANCHOR_WRITE_RE.search(text)
    )


# --------------------------------------------------------------------------- #
# report                                                                       #
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self) -> None:
        self.checks: list[str] = []
        self.failures: list[str] = []

    def ok(self, name: str) -> None:
        self.checks.append(name)

    def fail(self, name: str, detail: str) -> None:
        self.checks.append(name)
        self.failures.append(f"{name}: {detail}")

    def guard(self, name: str, fn: Any) -> None:
        try:
            fn()
            self.ok(name)
        except (OSError, IndependentVerifyError) as exc:
            self.fail(name, str(exc))


def verify(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    report = Report()

    facts: dict[str, Any] = {}
    try:
        facts = _derive_facts(root)
        report.ok("01_governance_facts_derivable")
    except (OSError, IndependentVerifyError) as exc:
        report.fail("01_governance_facts_derivable", str(exc))
        return _payload(report, facts)  # nothing else is trustworthy

    def check_ledgers() -> None:
        for rel in SEALED_LEDGERS:
            raw = _read_bytes(root, rel)
            _require(len(raw) == 0, f"{rel}: expected byte-empty, got {len(raw)} bytes")
            _require(_sha256(raw) == EMPTY_SHA256, f"{rel}: sha256 is not the empty-file digest")

    def check_m3c() -> None:
        _require(
            facts["m3c_verdict"] == REJECTED_VERDICT,
            f"m3c verdict is {facts['m3c_verdict']!r}, not the rejected/terminal verdict",
        )

    def check_m3d() -> None:
        _require(facts["m3d_evaluation_authorized"] is False, "m3d evaluation is authorized")
        _require(facts["m3d_maturity_state"] == "immature", "m3d cohort is not immature")
        _require(
            facts["m3d_row_count"] < facts["m3d_maturity_threshold"],
            "m3d row count is not below the maturity threshold",
        )

    def check_m3e() -> None:
        _require(
            facts["m3e_production_proposal_count"] == 0,
            f"m3e production proposal count is {facts['m3e_production_proposal_count']}, not 0",
        )

    def check_workflows() -> None:
        offenders = [
            p.relative_to(root).as_posix()
            for p in _workflow_paths(root)
            if _workflow_grants_write(p.read_text(encoding="utf-8"))
        ]
        _require(not offenders, "workflows grant write contents: " + ", ".join(offenders))

    report.guard("02_sealed_ledgers_byte_empty", check_ledgers)
    report.guard("03_m3c_candidate_rejected", check_m3c)
    report.guard("04_m3d_immature_unauthorized", check_m3d)
    report.guard("05_m3e_zero_proposals", check_m3e)
    report.guard("06_workflows_read_only", check_workflows)

    # If any M3F registration artifact is present, the repo is registered and BOTH the
    # catalog and honest state must be present — a deletion of either is a failure, not
    # a silently-skipped cross-check. Pre-registration, nothing is cross-checked.
    registered = any((root / rel).is_file() for rel in _REGISTRATION_MARKERS)

    def check_catalog() -> None:
        if not (root / CATALOG_RELPATH).is_file():
            _require(not registered, "registered repository is missing freeze_catalog.json")
            return
        _check_catalog(root, facts)

    def check_honest_state() -> None:
        if not (root / HONEST_STATE_RELPATH).is_file():
            _require(not registered, "registered repository is missing honest_state.json")
            return
        _check_honest_state(root, facts)

    report.guard("07_freeze_catalog_rehash", check_catalog)
    report.guard("08_honest_state_crosscheck", check_honest_state)

    return _payload(report, facts)


def _check_catalog(root: Path, facts: dict[str, Any]) -> None:
    catalog = _load_json(root, CATALOG_RELPATH)
    _require(isinstance(catalog, dict), "freeze_catalog.json is not a JSON object")
    artifacts = catalog.get("artifacts")
    _require(isinstance(artifacts, list), "catalog artifacts is not a list")
    _require(
        catalog.get("artifact_count") == len(artifacts),
        "catalog artifact_count does not match the artifact list length",
    )
    for record in artifacts:
        _require(isinstance(record, dict), "catalog artifact record is not an object")
        rel = record.get("path")
        _require(isinstance(rel, str) and rel != "", "catalog artifact path is not a string")
        _require(rel != CATALOG_RELPATH, "catalog must not catalog itself")
        raw = _read_bytes(root, rel)
        _require(
            _sha256(raw) == record.get("sha256"),
            f"{rel}: working-tree bytes do not match the catalogued SHA-256",
        )
        _require(
            len(raw) == record.get("byte_length"),
            f"{rel}: working-tree length does not match the catalogued byte_length",
        )
    # Sealed-ledger classification inside the catalog must itself be honest.
    ledgers = catalog.get("ledgers", {})
    _require(isinstance(ledgers, dict), "catalog ledgers block is not an object")
    for rel, entry in ledgers.items():
        _require(isinstance(entry, dict), f"catalog ledger {rel} is not an object")
        _require(entry.get("byte_length") == 0, f"catalog ledger {rel} is not recorded byte-empty")
        _require(entry.get("sha256") == EMPTY_SHA256, f"catalog ledger {rel} sha256 is not empty")
    # The catalog's own governance summary must match this tool's derivation.
    expected = catalog.get("expected_repository_state", {})
    _require(isinstance(expected, dict), "catalog expected_repository_state is not an object")
    _require(
        expected.get("m3c_outcome") == facts["m3c_verdict"],
        "catalog m3c_outcome disagrees with the independent derivation",
    )
    _require(
        expected.get("m3e_production_proposal_count") == facts["m3e_production_proposal_count"],
        "catalog proposal count disagrees with the independent derivation",
    )
    _require(
        expected.get("m3d_evaluation_authorized") == facts["m3d_evaluation_authorized"],
        "catalog m3d authorization disagrees with the independent derivation",
    )


def _check_honest_state(root: Path, facts: dict[str, Any]) -> None:
    state = _load_json(root, HONEST_STATE_RELPATH)
    _require(isinstance(state, dict), "honest_state.json is not a JSON object")
    pairs = {
        "m3c_candidate_verdict": "m3c_verdict",
        "m3d_cohort_row_count": "m3d_row_count",
        "m3d_maturity_state": "m3d_maturity_state",
        "m3d_evaluation_authorized": "m3d_evaluation_authorized",
        "m3e_production_proposal_count": "m3e_production_proposal_count",
    }
    for state_key, fact_key in pairs.items():
        _require(
            state.get(state_key) == facts[fact_key],
            f"honest_state.{state_key} disagrees with the independent derivation",
        )
    _require(state.get("m3e_active") is False, "honest_state reports m3e_active true")
    _require(
        state.get("standing_workflow_can_write_contents") is False,
        "honest_state reports a write-capable standing workflow",
    )


def _payload(report: Report, facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": not report.failures,
        "verifier": "m3f_independent_stdlib",
        "checks": report.checks,
        "failures": report.failures,
        "facts": facts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent M3F repository-freeze verifier")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true", help="emit deterministic JSON")
    args = parser.parse_args(argv)
    payload = verify(args.repo_root)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        status = "OK" if payload["ok"] else "FAIL"
        print(f"{status}: {len(payload['checks'])} checks, {len(payload['failures'])} failures")
        for failure in payload["failures"]:
            print(f"  - {failure}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
