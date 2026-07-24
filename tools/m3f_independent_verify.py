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
import math
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
# --- V2D growable cohort surface (see eth_research.m3f.growable) -------------
# Growth of the prospective cohort is lawful ONLY under the committed V2D
# activation anchor; this stdlib tool re-validates the anchor through its own
# primitives and then verifies the growable surface APPEND-ONLY: the catalogued
# baseline must survive as an exact hash-verified prefix of the live chain.
V2D_ANCHOR_RELPATH = "governance/v2d/prospective_activation.json"
_V2D_ANCHOR_PREFIX = b"m3d/v2d_prospective_activation_anchor\n"
_V2D_WORKFLOW = "m3e-prospective-update.yml"
GROWABLE_APPEND_CHAINS = (
    "research/m3d/prospective_segments.jsonl",
    "research/m3e/proposal_registry.jsonl",
)
GROWABLE_CURRENT_STATE = (
    "research/m3d/prospective_manifest.json",
    "research/m3d/prospective_quality.json",
    "research/m3d/publication_manifest.json",
    "research/m3e/accepted_base.json",
)
# The V2E acceptance chain: an independent re-implementation of the chain walk
# (same on-disk format the m3e writer produces and the m3f package re-verifies).
ACCEPTANCE_REGISTRY_RELPATH = "research/m3e/acceptance_registry.jsonl"
ACCEPTANCES_ROOT_RELPATH = "research/m3e/acceptances"
_ACCEPTANCE_RECORD_PREFIX = b"m3d/m3e/proposal_acceptance_record\n"
_ACCEPTANCE_COMPLETION_PREFIX = b"m3d/m3e/proposal_acceptance_completion\n"
ACCEPTANCE_TRANSITIONED_PATHS = tuple(
    sorted((*GROWABLE_APPEND_CHAINS, *GROWABLE_CURRENT_STATE))
)
ACCEPTANCE_GENESIS_AUTHORITIES = (
    "docs/M3C_M3E_STACK_FREEZE_TABLE.json",
    "research/m3f/freeze_catalog.json",
    "research/v2ab/stack_freeze_table.json",
)
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


def _checked_float(token: str) -> float:
    # A2: reject exponent-overflow non-finite numbers (e.g. ``1e999`` -> inf) that the
    # package verifier rejects, so the two independent code paths reach the same verdict.
    value = float(token)
    if not math.isfinite(value):
        raise IndependentVerifyError(f"non-finite JSON number: {token}")
    return value


def _loads(text: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
            parse_float=_checked_float,
        )
    except json.JSONDecodeError as exc:
        raise IndependentVerifyError(f"invalid JSON: {exc}") from exc


def _read_bytes(root: Path, relpath: str) -> bytes:
    # A4: refuse to read through a symlink or any path that escapes the repository root,
    # mirroring the package's safe_repo_path guard so the independent backstop cannot be
    # steered to bytes outside the repo.
    path = root / relpath
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(root.resolve()):
        raise IndependentVerifyError(f"{relpath}: unsafe path (symlink or escapes the repository)")
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

    registry_raw = _read_bytes(root, M3E_REGISTRY)
    proposals = _count_created_proposals(registry_raw)
    created_ids = _created_proposal_ids(registry_raw)
    _require(len(created_ids) == proposals, "registry proposal accounting inconsistent")
    return {
        "m3c_verdict": decision.get("outcome"),
        "m3d_row_count": row_count,
        "m3d_maturity_threshold": threshold,
        "m3d_maturity_state": base.get("maturity_state"),
        "m3d_evaluation_authorized": authorized,
        "m3e_production_proposal_count": proposals,
        "m3e_created_proposal_ids": created_ids,
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


def _canonical_bytes(payload: Any) -> bytes:
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def _v2d_anchor_active(root: Path) -> bool:
    """Strictly validate the committed V2D activation anchor; absent → inactive."""
    path = root / V2D_ANCHOR_RELPATH
    if not path.exists():
        return False
    _require(not path.is_symlink() and path.is_file(), "v2d anchor is not a regular file")
    doc = _loads(path.read_text(encoding="utf-8"))
    _require(isinstance(doc, dict), "v2d anchor is not a JSON object")
    _require(
        doc.get("kind") == "v2d_prospective_activation" and doc.get("schema_version") == 1,
        "v2d anchor kind/schema is unexpected",
    )
    body = {k: v for k, v in doc.items() if k != "anchor_sha256"}
    digest = hashlib.sha256(_V2D_ANCHOR_PREFIX + _canonical_bytes(body)).hexdigest()
    _require(doc.get("anchor_sha256") == digest, "v2d anchor self-hash mismatch")
    mechanism = doc.get("mechanism")
    _require(isinstance(mechanism, dict), "v2d anchor mechanism missing")
    _require(
        mechanism.get("workflow_basename") == _V2D_WORKFLOW,
        "v2d anchor authorizes an unexpected workflow",
    )
    return True


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
        count = facts["m3e_production_proposal_count"]
        _require(
            count == 0 or _v2d_anchor_active(root),
            f"m3e production proposal count is {count} without the V2D activation anchor",
        )

    def check_workflows() -> None:
        allowed = {_V2D_WORKFLOW} if _v2d_anchor_active(root) else set()
        offenders = [
            p.relative_to(root).as_posix()
            for p in _workflow_paths(root)
            if p.name not in allowed and _workflow_grants_write(p.read_text(encoding="utf-8"))
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

    def check_acceptance() -> None:
        _check_acceptance_chain(root, facts)

    report.guard("09_acceptance_chain", check_acceptance)

    return _payload(report, facts)


def _created_proposal_ids(raw: bytes) -> list[str]:
    ids: list[str] = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        record = _loads(line)
        if isinstance(record, dict) and record.get("entry_kind") == "proposal":
            ids.append(str(record.get("proposal_id", "")))
    return ids


def _acceptance_authority_pins(root: Path) -> dict[str, str]:
    wanted = set(ACCEPTANCE_TRANSITIONED_PATHS)
    first: dict[str, str] | None = None
    found = 0
    for rel in ACCEPTANCE_GENESIS_AUTHORITIES:
        path = root / rel
        if not path.exists():
            continue
        _require(not path.is_symlink() and path.is_file(), f"{rel} is not a regular file")
        found += 1
        doc = _loads(path.read_text(encoding="utf-8"))
        _require(isinstance(doc, dict), f"{rel}: not a JSON object")
        rows = None
        for key in ("files", "artifacts", "entries"):
            if key in doc:
                rows = doc[key]
                break
        _require(isinstance(rows, list), f"{rel}: unrecognized freeze-table shape")
        pins: dict[str, str] = {}
        for row in rows:
            if isinstance(row, dict) and row.get("path") in wanted:
                pins[str(row["path"])] = str(row.get("sha256", ""))
        _require(set(pins) == wanted, f"{rel}: missing pre-acceptance pins")
        if first is None:
            first = pins
        else:
            _require(pins == first, f"pre-acceptance pins disagree at {rel}")
    _require(found > 0 and first is not None, "no genesis authority table is present")
    assert first is not None
    return first


def _acceptance_self_hash_ok(doc: dict[str, Any], field: str, prefix: bytes) -> None:
    body = {k: v for k, v in doc.items() if k != field}
    digest = hashlib.sha256(prefix + _canonical_bytes(body)).hexdigest()
    _require(doc.get(field) == digest, f"{field} self-hash mismatch")


def _check_acceptance_chain(root: Path, facts: dict[str, Any]) -> None:
    """Independent chain walk: every created production proposal must be covered
    by a verified acceptance record and the tree must equal the chain-head state."""
    created = list(facts.get("m3e_created_proposal_ids", []))
    registry = root / ACCEPTANCE_REGISTRY_RELPATH
    if not registry.exists():
        _require(not created, "production proposal(s) exist without an acceptance registry")
        return
    _require(not registry.is_symlink() and registry.is_file(), "acceptance registry irregular")
    raw = registry.read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    _require(bool(lines), "acceptance registry is empty")
    prev = hashlib.sha256(b"").hexdigest()
    records: list[dict[str, Any]] = []
    for line in lines:
        record = _loads(line)
        _require(isinstance(record, dict), "acceptance registry line is not an object")
        _require(record.get("previous_line_sha256") == prev, "acceptance chain broken")
        prev = hashlib.sha256(line.encode("utf-8")).hexdigest()
        records.append(record)
    genesis = records[0]
    _require(
        genesis.get("entry_kind") == "genesis"
        and genesis.get("kind") == "m3e_acceptance_registry",
        "acceptance genesis sentinel malformed",
    )
    pins = genesis.get("pre_acceptance_state")
    _require(isinstance(pins, dict), "genesis pre_acceptance_state missing")
    expected = {str(k): str(v) for k, v in pins.items()}
    _require(
        expected == _acceptance_authority_pins(root),
        "genesis pins do not match the byte-frozen authority tables",
    )
    accepted: list[str] = []
    for position, entry in enumerate(records[1:], start=1):
        _require(entry.get("entry_kind") == "acceptance", "unknown acceptance entry kind")
        _require(entry.get("sequence") == position, "acceptance sequence reordered/gapped")
        proposal_id = str(entry.get("proposal_id", ""))
        _require(bool(proposal_id) and proposal_id not in accepted, "duplicate acceptance")
        record_path = root / ACCEPTANCES_ROOT_RELPATH / proposal_id / "acceptance.json"
        _require(
            not record_path.is_symlink() and record_path.is_file(),
            f"acceptance record missing for {proposal_id}",
        )
        record = _loads(record_path.read_text(encoding="utf-8"))
        _require(isinstance(record, dict), "acceptance record is not an object")
        _acceptance_self_hash_ok(record, "acceptance_sha256", _ACCEPTANCE_RECORD_PREFIX)
        _require(
            record.get("acceptance_sha256") == entry.get("acceptance_sha256"),
            "registry entry does not bind the committed record",
        )
        previous = record.get("previous_accepted")
        _require(isinstance(previous, dict), "previous_accepted missing")
        prior_state = {str(k): str(v) for k, v in dict(previous.get("state") or {}).items()}
        _require(prior_state == expected, "acceptance does not chain from prior state")
        new_accepted = record.get("new_accepted")
        _require(isinstance(new_accepted, dict), "new_accepted missing")
        new_state = {str(k): str(v) for k, v in dict(new_accepted.get("state") or {}).items()}
        _require(
            set(new_state) == set(ACCEPTANCE_TRANSITIONED_PATHS),
            "new state does not pin exactly the transitioned paths",
        )
        _require(record.get("evaluation_authorized") is False, "record authorizes evaluation")
        _require(record.get("maturity_state") == "immature", "record claims maturity")
        flags = record.get("governance_flags")
        _require(isinstance(flags, dict), "governance_flags missing")
        for name, value in flags.items():
            _require(value is False, f"governance flag {name} is set")
        completion_path = (
            root / ACCEPTANCES_ROOT_RELPATH / proposal_id / "acceptance_completion.json"
        )
        _require(
            not completion_path.is_symlink() and completion_path.is_file(),
            f"completion record missing for {proposal_id}",
        )
        completion = _loads(completion_path.read_text(encoding="utf-8"))
        _require(isinstance(completion, dict), "completion is not an object")
        _acceptance_self_hash_ok(
            completion, "completion_sha256", _ACCEPTANCE_COMPLETION_PREFIX
        )
        _require(
            completion.get("acceptance_sha256") == record.get("acceptance_sha256")
            and completion.get("proposal_id") == proposal_id,
            "completion does not bind its record",
        )
        accepted.append(proposal_id)
        expected = new_state
    _require(
        sorted(created) == sorted(accepted),
        f"created proposals {sorted(created)} != accepted {sorted(accepted)}",
    )
    for rel, want in sorted(expected.items()):
        live = _sha256(_read_bytes(root, rel))
        _require(
            live == want,
            f"{rel}: working tree does not equal the chain-head accepted state",
        )


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
        want_sha = record.get("sha256")
        want_len = record.get("byte_length")
        if _sha256(raw) == want_sha and len(raw) == want_len:
            continue
        grown = _v2d_anchor_active(root)
        if grown and rel in GROWABLE_APPEND_CHAINS and isinstance(want_len, int):
            # Git-free append-only proof: the catalogued baseline must survive
            # as an exact prefix — hash the live file's first byte_length bytes.
            _require(
                len(raw) >= want_len and _sha256(raw[:want_len]) == want_sha,
                f"{rel}: catalogued baseline is not an exact prefix (append-only violated)",
            )
        elif grown and rel in GROWABLE_CURRENT_STATE:
            _require(
                isinstance(_loads(raw.decode("utf-8")), dict),
                f"{rel}: grown snapshot is not a JSON object",
            )
        else:
            _require(False, f"{rel}: working-tree bytes do not match the catalogued SHA-256")
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
    live_count = facts["m3e_production_proposal_count"]
    at_acceptance = expected.get("m3e_production_proposal_count")
    _require(
        at_acceptance == live_count
        or (
            _v2d_anchor_active(root)
            and isinstance(at_acceptance, int)
            and isinstance(live_count, int)
            and live_count > at_acceptance
        ),
        "catalog proposal count disagrees with the independent derivation",
    )
    _require(
        expected.get("m3d_evaluation_authorized") == facts["m3d_evaluation_authorized"],
        "catalog m3d authorization disagrees with the independent derivation",
    )


def _check_honest_state(root: Path, facts: dict[str, Any]) -> None:
    state = _load_json(root, HONEST_STATE_RELPATH)
    _require(isinstance(state, dict), "honest_state.json is not a JSON object")
    grown = facts["m3e_production_proposal_count"] != 0 and _v2d_anchor_active(root)
    exact_pairs = {
        "m3c_candidate_verdict": "m3c_verdict",
        "m3d_evaluation_authorized": "m3d_evaluation_authorized",
    }
    if not grown:
        exact_pairs.update(
            {
                "m3d_cohort_row_count": "m3d_row_count",
                "m3d_maturity_state": "m3d_maturity_state",
                "m3e_production_proposal_count": "m3e_production_proposal_count",
            }
        )
    for state_key, fact_key in exact_pairs.items():
        _require(
            state.get(state_key) == facts[fact_key],
            f"honest_state.{state_key} disagrees with the independent derivation",
        )
    if grown:
        # The committed honest state is the immutable AT-M3F-ACCEPTANCE record;
        # the live cohort may only be LARGER and must stay immature below 365.
        committed_rows = state.get("m3d_cohort_row_count")
        live_rows = facts["m3d_row_count"]
        _require(
            isinstance(committed_rows, int) and live_rows >= committed_rows,
            "live cohort shrank below the accepted honest-state row count",
        )
        _require(
            facts["m3d_maturity_state"] == "immature" or live_rows >= 365,
            "unlawful live maturity state below the 365 floor",
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
