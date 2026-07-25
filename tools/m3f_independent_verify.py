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
import subprocess
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
ACCEPTANCE_TRANSITIONED_PATHS = tuple(sorted((*GROWABLE_APPEND_CHAINS, *GROWABLE_CURRENT_STATE)))
# The M3F freeze catalog is NOT an authority here: it is rebuilt at
# re-registration and snapshots the current (not pre-acceptance) state.
ACCEPTANCE_GENESIS_AUTHORITIES = (
    "docs/M3C_M3E_STACK_FREEZE_TABLE.json",
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


_AUTHORITY_SOURCE_RELPATH = "src/eth_research/m3e/proposal_authority.py"
_GENESIS_ROOT_DOMAIN = b"m3e/proposal_authority/genesis_root\n"


def _authority_constants(root: Path) -> dict[str, Any]:
    """Module-level literals of the pinned authority source, via ast only.

    Independence does not mean ignoring the frozen constants — it means
    interpreting the same frozen evidence with different code. This tool may not
    load the package at all, so it reads that source as text and walks the syntax
    tree instead. ``literal_eval`` never executes it, so a tampered source cannot
    run code inside the verifier that is inspecting it."""
    import ast

    path = root / _AUTHORITY_SOURCE_RELPATH
    _require(
        not path.is_symlink() and path.is_file(),
        f"{_AUTHORITY_SOURCE_RELPATH} is missing or not a regular file",
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=_AUTHORITY_SOURCE_RELPATH)
    out: dict[str, Any] = {}
    for node in tree.body:
        targets = [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
        value = getattr(node, "value", None)
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                try:
                    out[target.id] = ast.literal_eval(value)
                except ValueError:
                    continue
    return out


def _derive_genesis_root(root: Path) -> tuple[str, list[str]]:
    """Re-derive the chain's root of authority (catalog ROOT-01, ROOT-02, ROOT-03).

    Every input is a pinned source constant or a byte read out of the trusted
    commit's git objects. The working-tree copies of the authority tables are
    never consulted, so they cannot be anything but a derived cache."""
    pins = _authority_constants(root)
    for required in (
        "AUTHORITY_SCHEMA_VERSION",
        "TRUSTED_BASELINE_COMMIT",
        "TRUSTED_BASELINE_TREE",
        "AUTHORITY_TABLES",
        "ACCEPTED_MANIFEST_PATH",
        "ACCEPTED_MANIFEST_SHA256",
        "ACCEPTED_ROW_COUNT",
        "ACCEPTED_LAST_OPEN",
    ):
        _require(required in pins, f"authority source does not define {required}")

    commit = str(pins["TRUSTED_BASELINE_COMMIT"])
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)), "trusted baseline is not a 40-hex id")
    _require(
        _git_out(root, ["cat-file", "-t", commit]).decode().strip() == "commit",
        f"trusted baseline {commit[:12]} is not a commit",
    )
    tree_sha = _git_out(root, ["rev-parse", commit + "^{tree}"]).decode().strip()
    _require(
        tree_sha == str(pins["TRUSTED_BASELINE_TREE"]),
        "trusted baseline tree does not equal the pinned tree",
    )

    historical: dict[str, str] = {}
    tables = dict(pins["AUTHORITY_TABLES"])
    for relpath in sorted(tables):
        blob = _git_out(root, ["cat-file", "-p", f"{commit}:{relpath}"])
        digest = _sha256(blob)
        _require(
            digest == str(tables[relpath]),
            f"authority table {relpath!r} at the trusted commit does not hash to the "
            "digest committed source pins",
        )
        historical[relpath] = digest

    manifest = _git_out(root, ["cat-file", "-p", f"{commit}:{pins['ACCEPTED_MANIFEST_PATH']}"])
    _require(
        _sha256(manifest) == str(pins["ACCEPTED_MANIFEST_SHA256"]),
        "accepted manifest at the trusted commit does not hash to the pinned digest",
    )

    body = {
        "authority_schema_version": pins["AUTHORITY_SCHEMA_VERSION"],
        "trusted_commit": commit,
        "trusted_tree": tree_sha,
        "authority_tables": historical,
        "accepted_manifest_sha256": pins["ACCEPTED_MANIFEST_SHA256"],
        "accepted_row_count": pins["ACCEPTED_ROW_COUNT"],
        "accepted_last_open": pins["ACCEPTED_LAST_OPEN"],
    }
    compact = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(_GENESIS_ROOT_DOMAIN + compact).hexdigest(), sorted(historical)


def _check_genesis_root(root: Path, genesis: dict[str, Any]) -> None:
    derived, authorities = _derive_genesis_root(root)
    _require(
        genesis.get("genesis_root") == derived,
        "acceptance genesis root does not equal the root re-derived from pinned "
        "source constants and trusted history",
    )
    _require(
        [str(a) for a in (genesis.get("genesis_authorities") or [])] == authorities,
        "acceptance genesis authority list does not match the tables the root was derived from",
    )


_FILE_SET_POLICY_ID = "m3e-proposal-file-policy-v1"
_ALLOWED_PROPOSAL_ROOTS = ("research/m3d/", "research/m3e/")
_ALLOWED_PROPOSAL_SUFFIXES = (".json", ".jsonl")
_TRANSITIONED = frozenset(ACCEPTANCE_TRANSITIONED_PATHS)
_PROPOSAL_DOCS = frozenset(
    {"proposal_manifest.json", "acquisition_comparison.json", "update_transition.json"}
)
_RAW_NAME_RE = re.compile(r"^coinbase-eth-usd-1d-update_(\d{4})_\d{8}_\d{8}\.json$")
_MANIFEST_ROLE_SET = frozenset(
    {"proposal_document", "runner_update_plan", "runner_acquisition_receipt", "runner_raw_response"}
)
_RAW_ROLE_SET = frozenset({"m3d_bundle_raw_response", "runner_raw_response"})
_GOVERNANCE_ROLE_SET = frozenset({"transitioned_state", "update_attempts_ledger"})


def _git_out(root: Path, argv: list[str]) -> bytes:
    proc = subprocess.run(  # fixed argv, never a shell string
        ["git", "-C", str(root), *argv], capture_output=True, timeout=120, check=False
    )
    _require(proc.returncode == 0, f"git {argv[0]} failed: {proc.stderr.decode()[:200]}")
    _require(len(proc.stdout) <= 8 * 1024 * 1024, f"git {argv[0]} output exceeds the ceiling")
    return proc.stdout


def _canon(payload: Any) -> bytes:
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def _dom(domain: str, payload: Any) -> str:
    return hashlib.sha256(f"m3d/{domain}\n".encode() + _canon(payload)).hexdigest()


def _paths_digest(paths: list[str]) -> str:
    return _dom("m3e/proposal_file_policy/path_set", {"paths": sorted(paths)})


def _proposal_role(path: str, proposal_id: str) -> str:
    """This tool's own path→role rules, written from the policy specification.

    A third implementation of the same decision. It shares no code with the m3e
    policy or the m3f re-derivation, so a defect in either is visible here as a
    disagreement instead of being confirmed by a copy of itself."""
    _require(bool(re.fullmatch(r"[A-Za-z0-9._/-]+", path)), f"unlawful path spelling: {path!r}")
    _require(
        not path.startswith("/") and ".." not in path.split("/") and "//" not in path,
        f"unlawful path shape: {path!r}",
    )
    _require(
        not any(seg.startswith(".") for seg in path.split("/")), f"hidden/dotfile path: {path}"
    )
    _require(path.startswith(_ALLOWED_PROPOSAL_ROOTS), f"path outside allowed roots: {path}")
    _require(path.endswith(_ALLOWED_PROPOSAL_SUFFIXES), f"disallowed extension: {path}")
    if path in _TRANSITIONED:
        return "transitioned_state"
    if path == "research/m3d/update_attempts.jsonl":
        return "update_attempts_ledger"
    if path.startswith("research/m3d/raw/coinbase/"):
        tail = path[len("research/m3d/raw/coinbase/") :].split("/")
        _require(len(tail) == 2, f"unknown file under the m3d raw root: {path}")
        bundle, name = tail
        _require(
            bool(
                re.fullmatch(
                    r"coinbase-eth-usd-prospective-update-\d{8}-\d{8}-"
                    + re.escape(proposal_id[-16:]),
                    bundle,
                )
            ),
            f"raw bundle does not belong to {proposal_id}: {path}",
        )
        if name == "acquisition_plan.json":
            return "m3d_bundle_plan"
        if name == "acquisition_receipt.json":
            return "m3d_bundle_receipt"
        _require(bool(_RAW_NAME_RE.fullmatch(name)), f"unknown file in the raw bundle: {path}")
        return "m3d_bundle_raw_response"
    if path.startswith("research/m3e/proposals/"):
        tail = path[len("research/m3e/proposals/") :].split("/")
        _require(tail[0] == proposal_id, f"file belongs to another proposal: {path}")
        rest = tail[1:]
        if len(rest) == 1:
            _require(rest[0] in _PROPOSAL_DOCS, f"unknown file in the proposal directory: {path}")
            return "proposal_document"
        _require(len(rest) == 2, f"proposal directory nested too deeply: {path}")
        runner, name = rest
        _require(runner in {"runner_a", "runner_b"}, f"unknown runner directory: {path}")
        if name == "update_plan.json":
            return "runner_update_plan"
        if name == "acquisition_receipt.json":
            return "runner_acquisition_receipt"
        _require(bool(_RAW_NAME_RE.fullmatch(name)), f"unknown file in a runner directory: {path}")
        return "runner_raw_response"
    _require(False, f"unknown file (no policy rule admits it): {path}")
    raise AssertionError("unreachable")


def _rederive_file_set_binding(root: Path, proposal_id: str, parent: str, head: str) -> dict:
    """Rebuild the whole binding from git objects, taking no input from the record
    except the two commit ids (which are the proposal's identity)."""
    tree: dict[str, tuple[str, str, str]] = {}
    for chunk in _git_out(root, ["ls-tree", "-r", "-z", head]).split(b"\0"):
        if not chunk:
            continue
        meta, _, raw_path = chunk.partition(b"\t")
        parts = meta.decode("utf-8", "surrogateescape").split(" ")
        _require(len(parts) == 3 and bool(raw_path), f"unparsable ls-tree record: {chunk!r}")
        tree[raw_path.decode("utf-8", "surrogateescape")] = (parts[0], parts[1], parts[2])

    fields = [
        f
        for f in _git_out(
            root, ["diff", "--name-status", "-z", "--no-renames", "--no-ext-diff", parent, head]
        ).split(b"\0")
        if f
    ]
    _require(len(fields) % 2 == 0, "git diff --name-status produced an odd field count")
    changed = [
        (
            fields[i].decode("utf-8", "surrogateescape"),
            fields[i + 1].decode("utf-8", "surrogateescape"),
        )
        for i in range(0, len(fields), 2)
    ]
    changed.sort(key=lambda item: item[1])
    numstat = _git_out(root, ["diff", "--numstat", "-z", "--no-renames", parent, head]).decode(
        "utf-8", "surrogateescape"
    )

    members: list[dict[str, Any]] = []
    for status, path in changed:
        _require(status in {"A", "M"}, f"{path}: status {status!r} (only A/M are legal)")
        role = _proposal_role(path, proposal_id)
        entry = tree.get(path)
        _require(entry is not None, f"changed path absent from the proposal tree: {path}")
        mode, otype, obj_sha = entry  # type: ignore[misc]
        _require(otype == "blob" and mode == "100644", f"{path}: unlawful object {otype}/{mode}")
        blob = _git_out(root, ["cat-file", "blob", obj_sha])
        member: dict[str, Any] = {
            "byte_length": len(blob),
            "mode": mode,
            "object_type": otype,
            "path": path,
            "role": role,
            "sha256": _dom("m3e/proposal_file_policy/blob", {"bytes": blob.hex()}),
        }
        ordinal = _RAW_NAME_RE.fullmatch(path.rsplit("/", 1)[-1])
        if ordinal:
            member["acquisition_ordinal"] = int(ordinal.group(1))
        members.append(member)
    members.sort(key=lambda m: str(m["path"]))
    paths = [str(m["path"]) for m in members]
    roles = {str(m["path"]): str(m["role"]) for m in members}

    return {
        "file_set_policy_id": _FILE_SET_POLICY_ID,
        "binding_schema_version": 1,
        "proposal_parent_commit": parent,
        "proposal_commit": head,
        "proposal_tree_sha256": _dom(
            "m3e/proposal_file_policy/tree",
            {
                "entries": [
                    {"mode": m, "path": p, "sha": s, "type": t}
                    for p, (m, t, s) in sorted(tree.items())
                ]
            },
        ),
        "proposal_diff_name_status_sha256": _dom(
            "m3e/proposal_file_policy/diff_name_status",
            {"name_status": [[s, p] for s, p in changed]},
        ),
        "proposal_diff_numstat_sha256": _dom(
            "m3e/proposal_file_policy/diff_numstat", {"numstat": numstat}
        ),
        "allowed_member_count": len(paths),
        "allowed_member_paths_sha256": _paths_digest(paths),
        "manifest_member_paths_sha256": _paths_digest(
            [p for p in paths if roles[p] in _MANIFEST_ROLE_SET]
        ),
        "raw_member_paths_sha256": _paths_digest([p for p in paths if roles[p] in _RAW_ROLE_SET]),
        "governance_member_paths_sha256": _paths_digest(
            [p for p in paths if roles[p] in _GOVERNANCE_ROLE_SET]
        ),
        "proposal_bundle_sha256": _dom("m3e/proposal_file_policy/bundle", {"members": members}),
    }


def _check_file_set_binding(root: Path, record: dict[str, Any], proposal_id: str) -> None:
    binding = record.get("file_set_binding")
    _require(isinstance(binding, dict), f"acceptance {proposal_id}: file_set_binding missing")
    _require(
        binding.get("file_set_policy_id") == _FILE_SET_POLICY_ID
        and binding.get("binding_schema_version") == 1,
        f"acceptance {proposal_id}: unknown file-set policy or schema version",
    )
    parent = str(binding.get("proposal_parent_commit", ""))
    head = str(binding.get("proposal_commit", ""))
    for label, commit in (("parent", parent), ("head", head)):
        _require(
            bool(re.fullmatch(r"[0-9a-f]{40}", commit)),
            f"acceptance {proposal_id}: binding {label} is not a full 40-hex commit id",
        )
    _require(
        head == str(record.get("proposal_head_commit"))
        and parent == str(record.get("expected_parent_commit")),
        f"acceptance {proposal_id}: binding certifies different commits than the record",
    )
    derived = _rederive_file_set_binding(root, proposal_id, parent, head)
    for key in sorted(derived):
        _require(
            binding.get(key) == derived[key],
            f"acceptance {proposal_id}: file-set binding disagrees with git at {key!r} "
            f"(record={binding.get(key)!r}, derived={derived[key]!r})",
        )
    unknown = sorted(set(binding) - set(derived))
    _require(not unknown, f"acceptance {proposal_id}: binding carries unknown field(s): {unknown}")


_GOVERNANCE_FLAG_KEYS = frozenset(
    {
        "candidate_declared",
        "money_moved",
        "performance_metrics_computed",
        "promotion_decision_exists",
        "strategy_evaluated",
    }
)


def _utc_day_span(proposal_id: str, first_open: str, last_open: str) -> int:
    """Inclusive whole-day span of [first_open, last_open], both UTC midnights.

    Written with plain arithmetic rather than a date library, so this tool's
    answer is not the same code path as either packaged implementation."""
    import datetime as _dt

    parsed: list[_dt.datetime] = []
    for label, value in (("first_open", first_open), ("last_open", last_open)):
        try:
            moment = _dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.UTC)
        except ValueError as exc:
            raise IndependentVerifyError(
                f"acceptance {proposal_id}: {label} {value!r} is not a UTC instant"
            ) from exc
        _require(
            (moment.hour, moment.minute, moment.second) == (0, 0, 0),
            f"acceptance {proposal_id}: {label} {value!r} is not a UTC midnight",
        )
        parsed.append(moment)
    days = (parsed[1] - parsed[0]).days
    _require(days >= 0, f"acceptance {proposal_id}: append window runs backwards")
    return days + 1


def _check_record_provenance(
    root: Path, record: dict[str, Any], completion: dict[str, Any], proposal_id: str
) -> None:
    """Catalog GIT-04, GIT-05, PROV-01 and PROV-03, from git and the record alone."""
    parent = str(record.get("expected_parent_commit", ""))
    head = str(record.get("proposal_head_commit", ""))

    # GIT-05: an ancestry answer is only as good as the history behind it.
    _require(
        _git_out(root, ["rev-parse", "--is-shallow-repository"]).decode().strip() != "true",
        f"acceptance {proposal_id}: shallow clone — ancestry is computed over truncated history",
    )
    git_dir = Path(_git_out(root, ["rev-parse", "--git-dir"]).decode().strip())
    resolved = git_dir if git_dir.is_absolute() else root / git_dir
    _require(
        not (resolved / "info" / "grafts").exists(),
        f"acceptance {proposal_id}: a graft file fabricates parentage",
    )
    replaced = set(_git_out(root, ["replace", "--list"]).decode("utf-8", "replace").split())
    hijacked = sorted(replaced & {parent, head})
    _require(
        not hijacked,
        f"acceptance {proposal_id}: refs/replace substitutes pinned object(s) {hijacked}",
    )

    # GIT-04: exactly one parent, exactly the one the record names.
    line = _git_out(root, ["rev-list", "--parents", "-n", "1", head]).decode("ascii").split()
    _require(bool(line) and line[0] == head, f"acceptance {proposal_id}: unresolvable head parents")
    parents = tuple(line[1:])
    _require(
        parents == (parent,),
        f"acceptance {proposal_id}: proposal head has parents {[p[:12] for p in parents]}, "
        f"the record names {parent[:12]}… as its sole parent",
    )

    # PROV-01: the head must carry this proposal's manifest, byte for byte. The
    # blob digest and the manifest's own self-hash field are different values and
    # are bound separately, so neither is left free.
    manifest_path = f"research/m3e/proposals/{proposal_id}/proposal_manifest.json"
    blob = _git_out(root, ["cat-file", "-p", f"{head}:{manifest_path}"])
    created = dict(dict(record.get("new_accepted") or {}).get("created") or {})
    _require(
        _sha256(blob) == str(created.get(manifest_path)),
        f"acceptance {proposal_id}: the manifest at commit {head[:12]}… does not hash to "
        "the digest the record pins for it",
    )
    document = _loads(blob.decode("utf-8"))
    _require(isinstance(document, dict), f"acceptance {proposal_id}: manifest is not an object")
    _require(
        document.get("manifest_sha256") == record.get("proposal_manifest_sha256"),
        f"acceptance {proposal_id}: the manifest's own self-hash is not the one the record attests",
    )

    # PROV-03: the publication commit must be real and behind HEAD.
    publication = str(completion.get("publication_commit", ""))
    for label, commit in (("proposal head", head), ("publication commit", publication)):
        _require(
            bool(re.fullmatch(r"[0-9a-f]{40}", commit)),
            f"acceptance {proposal_id}: {label} is not a full 40-hex commit id",
        )
        proc = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-C",
                str(root),
                "merge-base",
                "--is-ancestor",
                commit,
                "HEAD",
            ],
            capture_output=True,
            timeout=120,
        )
        _require(
            proc.returncode == 0,
            f"acceptance {proposal_id}: {label} {commit[:12]}… is not an ancestor of HEAD",
        )


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
        genesis.get("entry_kind") == "genesis" and genesis.get("kind") == "m3e_acceptance_registry",
        "acceptance genesis sentinel malformed",
    )
    pins = genesis.get("pre_acceptance_state")
    _require(isinstance(pins, dict), "genesis pre_acceptance_state missing")
    expected = {str(k): str(v) for k, v in pins.items()}
    _require(
        expected == _acceptance_authority_pins(root),
        "genesis pins do not match the byte-frozen authority tables",
    )
    _require(
        [str(a) for a in (genesis.get("genesis_authorities") or [])]
        == list(ACCEPTANCE_GENESIS_AUTHORITIES),
        "genesis authority list does not match the enforced set",
    )
    _require(genesis.get("pre_acceptance_proposal_count") == 0, "genesis proposal count non-zero")
    # ROOT-01..03, derived here rather than taken from the record.
    if (root / ".git").exists():
        _check_genesis_root(root, genesis)
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
        # Re-derive the record's own semantics: hashing proves self-consistency,
        # not truth, so a coordinated reseal must still fail here.
        prev_rows = previous.get("row_count")
        new_rows = new_accepted.get("row_count")
        appended = dict(record.get("append_interval") or {}).get("row_count")
        for label, value in (
            ("previous row_count", prev_rows),
            ("new row_count", new_rows),
            ("appended row_count", appended),
        ):
            _require(isinstance(value, int) and not isinstance(value, bool), f"{label} not an int")
        _require(
            appended >= 1 and new_rows == prev_rows + appended and new_rows < 365,
            f"acceptance {proposal_id}: row arithmetic false or claims maturity",
        )
        proof = record.get("append_only_proof")
        _require(isinstance(proof, dict), "append_only_proof missing")
        _require(proof.get("is_append_only") is True, "append-only proof is not affirmative")
        for counter in ("prior_rows_changed", "prior_rows_deleted"):
            _require(proof.get(counter) == 0, f"{counter} is non-zero")
        _require(bool(new_accepted.get("created")), "record pins no created evidence")
        for logical, facts in dict(record.get("sealed_ledgers") or {}).items():
            _require(isinstance(facts, dict), f"sealed_ledgers.{logical} malformed")
            _require(facts.get("byte_count") == 0, f"sealed ledger {logical} claims bytes")
        _require(record.get("evaluation_authorized") is False, "record authorizes evaluation")
        _require(record.get("maturity_state") == "immature", "record claims maturity")
        # Two runners with byte-identical payloads, re-derived from the pinned hashes.
        runners = record.get("runner_evidence")
        _require(isinstance(runners, dict) and len(runners) >= 2, "fewer than two runners attested")
        raw_sets = set()
        for rname, rbody in runners.items():
            _require(isinstance(rbody, dict), f"runner_evidence.{rname} malformed")
            raws = rbody.get("raw_response_sha256")
            _require(isinstance(raws, dict) and bool(raws), f"runner {rname} pins no raw payload")
            raw_sets.add(tuple(sorted(raws.items())))
        _require(len(raw_sets) == 1, "attested runner payloads are not byte-identical")
        # Acceptance time must be bounded and must not predate its own window.
        at = record.get("acceptance_time")
        _require(isinstance(at, str) and at.endswith("Z"), "acceptance_time malformed")
        _require(
            at >= str(dict(record.get("append_interval") or {}).get("last_open"))
            and at < "2031-01-01T00:00:00Z",
            "acceptance_time is outside the lawful window",
        )
        _require(
            record.get("proposal_head_commit") != record.get("expected_parent_commit"),
            "proposal head equals its own expected parent",
        )
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
        _acceptance_self_hash_ok(completion, "completion_sha256", _ACCEPTANCE_COMPLETION_PREFIX)
        _require(
            completion.get("acceptance_sha256") == record.get("acceptance_sha256")
            and completion.get("proposal_id") == proposal_id,
            "completion does not bind its record",
        )
        # Created evidence must exist with exactly the pinned hash, and the accepted
        # proposal directory must be a CLOSED set (no file smuggled in afterwards).
        created_pins = new_accepted.get("created")
        _require(isinstance(created_pins, dict) and bool(created_pins), "no created evidence")
        for rel, want in created_pins.items():
            live = root / str(rel)
            _require(
                not live.is_symlink() and live.is_file(),
                f"created evidence {rel} is missing or irregular",
            )
            _require(_sha256(live.read_bytes()) == str(want), f"created evidence {rel} drifted")
        pdir = root / "research/m3e/proposals" / proposal_id
        if pdir.is_dir():
            live_set = {
                p.relative_to(root).as_posix()
                for p in pdir.rglob("*")
                if p.is_file() or p.is_symlink()
            }
            pinned_set = {
                str(r) for r in created_pins if str(r).startswith("research/m3e/proposals/")
            }
            _require(
                live_set == pinned_set,
                f"accepted proposal directory {proposal_id} is not a closed set",
            )
        # Catalog SAFE-02: the KEY SET, then the values. Iterating whatever is
        # present lets a reseal delete the map wholesale and assert nothing.
        _require(
            frozenset(str(k) for k in flags) == _GOVERNANCE_FLAG_KEYS,
            f"acceptance {proposal_id}: governance_flags keys {sorted(flags)} != "
            f"required {sorted(_GOVERNANCE_FLAG_KEYS)}",
        )
        # Catalog DATA-02: the window must span exactly as many days as it claims
        # rows. old + appended == new constrains only counts the forger controls.
        interval = dict(record.get("append_interval") or {})
        span = _utc_day_span(
            proposal_id, str(interval.get("first_open")), str(interval.get("last_open"))
        )
        _require(
            span == appended,
            f"acceptance {proposal_id}: append window spans {span} day(s) but claims "
            f"{appended} appended row(s)",
        )
        # Third, separately written derivation of the record's closed file set,
        # straight from git objects, plus the genealogy and provenance this tool
        # can state without the M3E source pins (GIT-04, GIT-05, PROV-01, PROV-03).
        if (root / ".git").exists():
            _check_file_set_binding(root, record, proposal_id)
            _check_record_provenance(root, record, completion, proposal_id)
        accepted.append(proposal_id)
        expected = new_state
    _require(
        sorted(created) == sorted(accepted),
        f"created proposals {sorted(created)} != accepted {sorted(accepted)}",
    )
    # An acceptance directory that no registry line references is illegal: without
    # this the whole acceptances/ prefix would be an unaudited drop zone.
    acceptances_dir = root / ACCEPTANCES_ROOT_RELPATH
    if acceptances_dir.is_dir():
        on_disk = sorted(p.name for p in acceptances_dir.iterdir() if p.is_dir())
        _require(
            on_disk == sorted(accepted),
            f"acceptance directories {on_disk} do not match the chain {sorted(accepted)}",
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
    # ``m3e_active`` in the COMMITTED record is the AT-M3F-ACCEPTANCE historical fact
    # (false: no anchor, no proposal). Under lawful growth it is not compared to the
    # live world — the live world is proved instead by the anchor plus check 09's
    # independent acceptance-chain coverage. Without growth it must still be false,
    # exactly as accepted.
    active = state.get("m3e_active")
    _require(isinstance(active, bool), "honest_state.m3e_active is not a bool")
    if grown:
        _require(
            _v2d_anchor_active(root),
            "grown repository lacks a valid V2D activation anchor",
        )
    else:
        _require(active is False, "honest_state reports m3e_active true")
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
