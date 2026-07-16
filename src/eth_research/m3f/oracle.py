"""Independent semantic oracles over the accepted M2B-M3E stack (Milestone 3F).

Beyond the top-level governance booleans that ``honest_state`` derives, these
oracles re-derive milestone-internal and cross-milestone *relationships* that must
hold, entirely from committed bytes, and fail closed on any violation. They are a
second opinion on the accepted stack's internal consistency:

* the M3C rejection is self-coherent — the sealed partitions were untouched, no
  parameter changed, verification passed, and a rejected decision genuinely has a
  failing criterion;
* the M3E accepted base is cryptographically bound to the exact M3C decision and
  the exact committed M3D upstream artifacts it claims (re-hashed here);
* the M3E cohort's row count equals the open-window span implied by its own
  timestamps, and its maturity label agrees with the count-vs-threshold rule;
* the M3E proposal registry's hash chain reproduces line-by-line from the empty
  genesis anchor;
* the three sealed ledgers are byte-empty across milestones; and
* the packaged ``honest_state`` derivation agrees with these independent readings.

Strictly read-only: no strategy signal, no return, no metric, no sealed-partition
evaluation, no ledger mutation, no network, no wall-clock decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from eth_research.m3f.honest_state import derive_honest_state
from eth_research.m3f.validation import (
    M3FValidationError,
    count_created_proposals,
    load_canonical_json,
    require_bool,
    require_int,
    require_list,
    require_mapping,
    require_sha256_hex,
    require_str,
    sha256_bytes,
    sha256_file,
    strict_jsonl_records,
)

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
REJECTED_VERDICT = "rejected_for_development_gate_promotion"

_M3C_DECISION = "research/m3c/candidate_decision.json"
_M3E_BASE = "research/m3e/accepted_base.json"
_M3E_REGISTRY = "research/m3e/proposal_registry.jsonl"
_SEALED_LEDGERS = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)
# The M3E accepted base pins these exact upstream M3D artifacts by SHA-256.
_PROVENANCE_BINDINGS = {
    "manifest_sha256": "research/m3d/prospective_manifest.json",
    "segment_chain_sha256": "research/m3d/prospective_segments.jsonl",
    "publication_manifest_sha256": "research/m3d/publication_manifest.json",
    "reacquisition_audit_sha256": "research/m3d/reacquisition_audit.json",
}


def _load(root: Path, relpath: str, label: str) -> dict[str, Any]:
    return require_mapping(load_canonical_json((root / relpath).read_bytes(), label), label)


def _parse_utc(value: object, label: str) -> datetime:
    text = require_str(value, label)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise M3FValidationError(f"{label}: not an ISO-8601 instant: {text!r}") from exc


# --------------------------------------------------------------------------- #
# oracles                                                                      #
# --------------------------------------------------------------------------- #
def oracle_m3c_decision_coherent(root: Path) -> None:
    decision = _load(root, _M3C_DECISION, "m3c_decision")
    if require_str(decision.get("outcome"), "m3c_outcome") != REJECTED_VERDICT:
        raise M3FValidationError("m3c outcome is not the rejected/terminal verdict")
    for flag in ("development_gate_accessed", "final_holdout_accessed", "test_accessed"):
        if require_bool(decision.get(flag), flag):
            raise M3FValidationError(f"m3c decision reports {flag} true — a sealed partition")
    if require_str(decision.get("parameter_changes"), "parameter_changes") != "none":
        raise M3FValidationError("m3c decision reports a parameter change")
    if not require_bool(decision.get("verification_passed"), "verification_passed"):
        raise M3FValidationError("m3c decision reports verification did not pass")
    if require_int(decision.get("candidate_count"), "candidate_count") != 1:
        raise M3FValidationError("m3c decision does not describe exactly one candidate")
    criteria = require_list(decision.get("criteria"), "criteria")
    failed = sum(
        1
        for c in criteria
        if not require_bool(require_mapping(c, "criterion").get("passed"), "criterion.passed")
    )
    if failed < 1:
        raise M3FValidationError("a rejected decision must have at least one failing criterion")


def oracle_m3e_base_binds_upstream(root: Path) -> None:
    decision = _load(root, _M3C_DECISION, "m3c_decision")
    base = _load(root, _M3E_BASE, "m3e_accepted_base")
    prov = require_mapping(base.get("provenance"), "provenance")
    if require_str(base.get("upstream_milestone"), "upstream_milestone") != "M3D":
        raise M3FValidationError("m3e base does not declare M3D as upstream")
    if prov.get("m3c_candidate_decision_outcome") != decision.get("outcome"):
        raise M3FValidationError("m3e base provenance disagrees with the m3c decision outcome")
    for key, relpath in _PROVENANCE_BINDINGS.items():
        want = require_sha256_hex(prov.get(key), key)
        got = sha256_file(root / relpath)
        if got != want:
            raise M3FValidationError(
                f"m3e base provenance {key} does not match committed {relpath}"
            )


def oracle_m3e_cohort_window(root: Path) -> None:
    base = _load(root, _M3E_BASE, "m3e_accepted_base")
    identity = require_mapping(base.get("identity"), "identity")
    interval = require_int(identity.get("interval_seconds"), "interval_seconds")
    if interval <= 0:
        raise M3FValidationError("cohort interval_seconds is not positive")
    first = _parse_utc(base.get("first_open"), "first_open")
    last = _parse_utc(base.get("last_open"), "last_open")
    span_seconds = (last - first).total_seconds()
    if span_seconds < 0 or span_seconds % interval != 0:
        raise M3FValidationError("cohort open window is not an integer number of intervals")
    computed_rows = int(span_seconds // interval) + 1
    row_count = require_int(base.get("row_count"), "row_count")
    if computed_rows != row_count:
        raise M3FValidationError(
            f"cohort row_count {row_count} disagrees with the open-window span {computed_rows}"
        )
    minimum = require_int(base.get("minimum_maturity_rows"), "minimum_maturity_rows")
    state = require_str(base.get("maturity_state"), "maturity_state")
    if (state == "immature") != (row_count < minimum):
        raise M3FValidationError("maturity label disagrees with the row-count-vs-threshold rule")
    if base.get("cohort_start") != base.get("first_open"):
        raise M3FValidationError("cohort_start does not equal first_open")


def oracle_m3e_registry_chain(root: Path) -> None:
    raw = (root / _M3E_REGISTRY).read_bytes()
    records = strict_jsonl_records(raw, "m3e_registry")
    line_strs = raw.decode("utf-8").splitlines()
    if len(line_strs) != len(records):
        raise M3FValidationError("m3e registry line/record count mismatch")
    prev = EMPTY_SHA256
    for line, record in zip(line_strs, records, strict=True):
        mapping = require_mapping(record, "m3e_registry_record")
        if require_sha256_hex(mapping.get("previous_line_sha256"), "previous_line_sha256") != prev:
            raise M3FValidationError("m3e registry hash chain is broken")
        prev = sha256_bytes(line.encode("utf-8"))
    if count_created_proposals(raw) != 0:
        raise M3FValidationError("m3e registry records a created production proposal")


def oracle_sealed_ledgers_triple(root: Path) -> None:
    for rel in _SEALED_LEDGERS:
        raw = (root / rel).read_bytes()
        if len(raw) != 0 or sha256_bytes(raw) != EMPTY_SHA256:
            raise M3FValidationError(f"sealed ledger {rel} is not byte-empty")


def oracle_matches_honest_state(root: Path) -> None:
    """Bridge: the packaged honest-state derivation agrees with the oracle inputs."""
    state = derive_honest_state(root)
    decision = _load(root, _M3C_DECISION, "m3c_decision")
    base = _load(root, _M3E_BASE, "m3e_accepted_base")
    proposals = count_created_proposals((root / _M3E_REGISTRY).read_bytes())
    if state["m3c_candidate_verdict"] != decision.get("outcome"):
        raise M3FValidationError("honest_state m3c verdict disagrees with the decision file")
    if state["m3d_cohort_row_count"] != base.get("row_count"):
        raise M3FValidationError("honest_state row count disagrees with the accepted base")
    if state["m3e_production_proposal_count"] != proposals:
        raise M3FValidationError("honest_state proposal count disagrees with the registry")


ORACLES: tuple[tuple[str, Any], ...] = (
    ("m3c_decision_coherent", oracle_m3c_decision_coherent),
    ("m3e_base_binds_upstream", oracle_m3e_base_binds_upstream),
    ("m3e_cohort_window", oracle_m3e_cohort_window),
    ("m3e_registry_chain", oracle_m3e_registry_chain),
    ("sealed_ledgers_triple", oracle_sealed_ledgers_triple),
    ("matches_honest_state", oracle_matches_honest_state),
)


@dataclass
class OracleReport:
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def raise_for_status(self) -> None:
        if self.failures:
            raise M3FValidationError("semantic oracle failures: " + "; ".join(self.failures))


def run_oracles(repo_root: str | Path) -> OracleReport:
    """Run every semantic oracle read-only; collect all failures."""
    root = Path(repo_root)
    report = OracleReport()
    for name, fn in ORACLES:
        try:
            fn(root)
            report.checks.append(name)
        except (OSError, M3FValidationError) as exc:
            report.checks.append(name)
            report.failures.append(f"{name}: {exc}")
    return report


def _oracle_payload(repo_root: str | Path) -> dict[str, Any]:
    report = run_oracles(repo_root)
    return {"ok": report.ok, "checks": report.checks, "failures": report.failures}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    from eth_research.m3f.cli import repo_root_parser, run_guarded

    args = repo_root_parser("M3F semantic oracles over the accepted stack (read-only)").parse_args(
        argv
    )
    return run_guarded(lambda: _oracle_payload(args.repo_root), as_json=args.json or args.check)


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
