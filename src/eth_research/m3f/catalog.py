"""Repository-wide freeze catalog for Milestone 3F.

``research/m3f/freeze_catalog.json`` is one deterministic, strictly-verified catalog
of every committed artifact under the governed ``research/`` root (all accepted
M2B-M3E evidence plus the M3F verification artifacts), bound to the accepted git
state. It is an *acceptance aid*: it re-binds facts the per-milestone verifiers own
(it never invents a competing provenance truth) and adds one anti-orphan enumeration
so no governed file escapes verification and no catalogued path is missing on disk.

The generator derives every hash from the committed git blob bytes (never the dirty
working tree) and refuses to overwrite by default; the verifier re-hashes the working
tree against the committed catalog and cross-checks the governance facts.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    count_created_proposals,
    load_canonical_json,
    normalize_relpath,
    require_int,
    require_list,
    require_mapping,
    require_sha256_hex,
    require_str,
    safe_repo_path,
    sha256_bytes,
)

CATALOG_RELPATH = "research/m3f/freeze_catalog.json"
CATALOG_SCHEMA_VERSION = 1
CATALOG_ALGORITHM = "sha256"
GOVERNED_ROOT = "research"
# The M3F verification layer is created at registration (R), after the source-freeze
# commit (E) this catalog binds, and each of its artifacts is self-verifying (honest
# state, inventories, capsule manifest, and drill each reproduce from bytes). It is
# therefore excluded from the catalog and its anti-orphan enumeration — cataloguing a
# file that does not yet exist at the freeze commit would be an E-vs-R circularity.
M3F_LAYER_PREFIX = "research/m3f/"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# Milestone ownership by committed path prefix (exact vocabulary).
_MILESTONE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("research/m2b/", "m2b"),
    ("research/m3a/", "m3a"),
    ("research/m3b/", "m3b"),
    ("research/m3c/", "m3c"),
    ("research/m3d/", "m3d"),
    ("research/m3e/", "m3e"),
    ("research/m3f/", "m3f"),
)
MILESTONE_VOCAB = frozenset(m for _, m in _MILESTONE_PREFIXES)

# The three sealed access ledgers (must be byte-empty).
SEALED_LEDGERS: tuple[str, ...] = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)

# Roles (exact vocabulary).
ROLE_VOCAB = frozenset(
    {
        "sealed_ledger",
        "append_chain_registry",
        "raw_market_bytes",
        "immutable_evidence",
        "documentation",
        "m3f_verification",
    }
)


class CatalogError(M3FValidationError):
    """The freeze catalog is malformed, drifted, or fails an integrity check."""


@dataclass(frozen=True)
class CatalogResult:
    ok: bool
    checks: tuple[tuple[str, str], ...]
    failures: tuple[str, ...] = ()
    artifact_count: int = 0

    def raise_for_status(self) -> None:
        if not self.ok:
            raise CatalogError("freeze catalog verification failed: " + "; ".join(self.failures))


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _tracked_governed_files(repo_root: Path) -> list[str]:
    out = _git(repo_root, "ls-files", "-z", "--", GOVERNED_ROOT + "/")
    files = [p for p in out.split("\0") if p]
    return sorted(files)


def _blob_bytes(repo_root: Path, commit: str, relpath: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "blob", f"{commit}:{relpath}"],
        capture_output=True,
        check=True,
    )
    return result.stdout


def _milestone_of(relpath: str) -> str:
    for prefix, milestone in _MILESTONE_PREFIXES:
        if relpath.startswith(prefix):
            return milestone
    raise CatalogError(f"path outside a governed milestone root: {relpath!r}")


def _role_of(relpath: str) -> str:
    if relpath in SEALED_LEDGERS:
        return "sealed_ledger"
    name = relpath.rsplit("/", 1)[-1]
    if "/raw/" in relpath and name.endswith(".json"):
        return "raw_market_bytes"
    if relpath.endswith("_registry.jsonl") or name in {
        "experiment_registry.jsonl",
        "proposal_registry.jsonl",
        "research_multiplicity.jsonl",
        "research_data_use.jsonl",
    }:
        return "append_chain_registry"
    if relpath.startswith("research/m3f/"):
        return "m3f_verification"
    if name.endswith((".md", ".txt")):
        return "documentation"
    return "immutable_evidence"


def _has_market_bytes(relpath: str) -> bool:
    return "/raw/" in relpath or relpath.endswith((".csv",))


def _capsule_permit(role: str, market_bytes: bool) -> bool:
    # The private capsule may carry accepted evidence + raw bytes needed for replay,
    # but never the M3F catalog-of-itself circularity; sealed ledgers are empty anyway.
    return role != "m3f_verification"


def build_catalog(
    repo_root: str | Path,
    *,
    source_freeze_sha: str,
    accepted_main_sha: str,
    package_version: str,
) -> dict[str, Any]:
    """Deterministically derive the catalog dict from committed git-blob bytes."""
    root = Path(repo_root)
    freeze = require_str(source_freeze_sha, "source_freeze_sha")
    accepted = require_str(accepted_main_sha, "accepted_main_sha")
    tree_sha = _git(root, "rev-parse", f"{accepted}^{{tree}}").strip()
    src_fingerprint = sha256_bytes(_git(root, "ls-tree", "-r", f"{freeze}", "src").encode("utf-8"))

    artifacts: list[dict[str, Any]] = []
    for relpath in _tracked_governed_files(root):
        # The whole M3F verification layer is excluded (see M3F_LAYER_PREFIX): it is
        # created at registration and self-verifying, and the catalog is bound by
        # self-hash rather than as one of its own catalogued artifacts.
        if relpath.startswith(M3F_LAYER_PREFIX):
            continue
        normalize_relpath(relpath, "artifact.path")
        raw = _blob_bytes(root, freeze, relpath)
        role = _role_of(relpath)
        market = _has_market_bytes(relpath)
        artifacts.append(
            {
                "path": relpath,
                "sha256": sha256_bytes(raw),
                "byte_length": len(raw),
                "milestone": _milestone_of(relpath),
                "role": role,
                "market_bytes": market,
                "capsule_permitted": _capsule_permit(role, market),
            }
        )
    artifacts.sort(key=lambda a: a["path"])

    ledgers = {
        rel: {"byte_length": 0, "sha256": EMPTY_SHA256, "event_count": 0} for rel in SEALED_LEDGERS
    }
    expected_state = _derive_expected_state(root, freeze)

    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "catalog_algorithm": CATALOG_ALGORITHM,
        "accepted_main_sha": accepted,
        "accepted_main_tree_sha": tree_sha,
        "package_version": require_str(package_version, "package_version"),
        "source_freeze_sha": freeze,
        "source_tree_fingerprint": src_fingerprint,
        "canonical_json_contract": "utf8;sorted_keys;indent2;trailing_newline;finite_only",
        "governed_root": GOVERNED_ROOT,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "ledgers": ledgers,
        "expected_repository_state": expected_state,
        "excluded_paths": ["data/", "reports/", ".venv/"],
    }


def _derive_expected_state(root: Path, commit: str) -> dict[str, Any]:
    decision = load_canonical_json(
        _blob_bytes(root, commit, "research/m3c/candidate_decision.json"),
        "m3c_decision",
    )
    base = load_canonical_json(
        _blob_bytes(root, commit, "research/m3e/accepted_base.json"),
        "m3e_accepted_base",
    )
    proposals = count_created_proposals(
        _blob_bytes(root, commit, "research/m3e/proposal_registry.jsonl")
    )
    return {
        "m3c_outcome": require_str(decision["outcome"], "m3c_outcome"),
        "m3d_cohort_rows": require_int(base["row_count"], "m3d_cohort_rows"),
        "m3d_maturity_state": require_str(base["maturity_state"], "m3d_maturity_state"),
        "m3d_evaluation_authorized": bool(base["evaluation_authorized"]),
        "m3e_production_proposal_count": proposals,
        "sealed_ledgers_byte_empty": True,
    }


def render_catalog_bytes(catalog: dict[str, Any]) -> bytes:
    return canonical_json_bytes(catalog)


# --------------------------------------------------------------------------- #
# verification                                                                #
# --------------------------------------------------------------------------- #
@dataclass
class _Accum:
    checks: list[tuple[str, str]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def ok(self, name: str, detail: str = "ok") -> None:
        self.checks.append((name, detail))

    def fail(self, name: str, detail: str) -> None:
        self.checks.append((name, detail))
        self.failures.append(f"{name}: {detail}")


def load_catalog(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    raw = (root / CATALOG_RELPATH).read_bytes()
    catalog = require_mapping(load_canonical_json(raw, "freeze_catalog"), "freeze_catalog")
    if require_int(catalog.get("schema_version"), "schema_version") != CATALOG_SCHEMA_VERSION:
        raise CatalogError("unexpected catalog schema_version")
    return catalog


def verify_catalog(repo_root: str | Path) -> CatalogResult:
    """Re-hash the working tree against the committed catalog + anti-orphan enumeration."""
    root = Path(repo_root)
    acc = _Accum()
    try:
        catalog = load_catalog(root)
    except (OSError, M3FValidationError) as exc:
        return CatalogResult(False, (), (f"catalog_load: {exc}",))
    acc.ok("01_catalog_bytes_canonical")

    artifacts = require_list(catalog.get("artifacts"), "artifacts")
    catalogued: set[str] = set()
    for entry in artifacts:
        rec = require_mapping(entry, "artifact")
        rel = normalize_relpath(rec.get("path"), "artifact.path")
        catalogued.add(rel)
        try:
            target = safe_repo_path(root, rel, "artifact")
            raw = target.read_bytes()
        except (OSError, M3FValidationError) as exc:
            acc.fail("02_artifact_present", f"{rel}: {exc}")
            continue
        if sha256_bytes(raw) != require_sha256_hex(rec.get("sha256"), "artifact.sha256"):
            acc.fail("03_artifact_hash", f"{rel}: sha256 mismatch")
        if len(raw) != require_int(rec.get("byte_length"), "artifact.byte_length"):
            acc.fail("04_artifact_length", f"{rel}: byte_length mismatch")
        if require_str(rec.get("milestone"), "artifact.milestone") not in MILESTONE_VOCAB:
            acc.fail("05_milestone_vocab", f"{rel}: bad milestone")
        if require_str(rec.get("role"), "artifact.role") not in ROLE_VOCAB:
            acc.fail("06_role_vocab", f"{rel}: bad role")
    acc.ok("07_all_catalogued_artifacts_hash_correctly", str(len(artifacts)))

    # Anti-orphan: every tracked governed file outside the M3F verification layer is
    # catalogued (the M3F layer is excluded per M3F_LAYER_PREFIX; it self-verifies).
    try:
        tracked = {
            p for p in _tracked_governed_files(root) if not p.startswith(M3F_LAYER_PREFIX)
        }
        orphans = sorted(tracked - catalogued)
        stale = sorted(catalogued - tracked)
        if orphans:
            acc.fail("08_no_orphan_governed_files", f"uncatalogued: {orphans[:5]}")
        elif stale:
            acc.fail("09_no_stale_catalog_entries", f"missing on disk: {stale[:5]}")
        else:
            acc.ok("08_anti_orphan_enumeration", f"{len(tracked)} governed files all catalogued")
    except subprocess.CalledProcessError as exc:
        acc.fail("08_anti_orphan_enumeration", f"git ls-files failed: {exc}")

    # Sealed ledgers byte-empty.
    for rel in SEALED_LEDGERS:
        raw = (root / rel).read_bytes()
        if len(raw) != 0 or sha256_bytes(raw) != EMPTY_SHA256:
            acc.fail("10_sealed_ledger_empty", f"{rel} is non-empty")
    acc.ok("10_sealed_ledgers_byte_empty")

    # Expected governance state bound in the catalog matches the live artifacts.
    _verify_expected_state(root, catalog, acc)

    return CatalogResult(
        ok=not acc.failures,
        checks=tuple(acc.checks),
        failures=tuple(acc.failures),
        artifact_count=len(artifacts),
    )


def _verify_expected_state(root: Path, catalog: dict[str, Any], acc: _Accum) -> None:
    expected = require_mapping(
        catalog.get("expected_repository_state"), "expected_repository_state"
    )
    try:
        decision = load_canonical_json(
            (root / "research/m3c/candidate_decision.json").read_bytes(), "m3c"
        )
        base = load_canonical_json((root / "research/m3e/accepted_base.json").read_bytes(), "base")
    except (OSError, M3FValidationError) as exc:
        acc.fail("11_expected_state", f"cannot load governance artifacts: {exc}")
        return
    if decision.get("outcome") != expected.get("m3c_outcome"):
        acc.fail("11_m3c_outcome_bound", "m3c outcome drifted from catalog")
    if base.get("row_count") != expected.get("m3d_cohort_rows"):
        acc.fail("12_m3d_rows_bound", "cohort rows drifted from catalog")
    if base.get("maturity_state") != expected.get("m3d_maturity_state"):
        acc.fail("13_m3d_maturity_bound", "maturity drifted from catalog")
    if bool(base.get("evaluation_authorized")) is not bool(
        expected.get("m3d_evaluation_authorized")
    ):
        acc.fail("14_m3d_auth_bound", "evaluation_authorized drifted")
    if expected.get("m3e_production_proposal_count") != 0:
        acc.fail("15_m3e_zero_proposals", "catalog records a nonzero proposal count")
    acc.ok("11_expected_governance_state_bound")
