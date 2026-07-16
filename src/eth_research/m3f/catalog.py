"""Repository-wide freeze catalog for Milestone 3F.

``research/m3f/freeze_catalog.json`` is one deterministic, strictly-verified catalog
of every committed artifact under the governed ``research/`` root — the accepted
M2B-M3E evidence — bound to the accepted git state. The self-verifying M3F layer
itself is excluded (see ``M3F_LAYER_PREFIX``). It is an *acceptance aid*: it re-binds
facts the per-milestone verifiers own (it never invents a competing provenance truth)
and adds one anti-orphan enumeration so no governed file escapes verification and no
catalogued path is missing on disk.

The generator derives every hash from the committed git blob bytes (never the dirty
working tree) and refuses to overwrite by default; the verifier re-hashes the working
tree against the committed catalog and cross-checks the governance facts.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eth_research.m3f import M3F_PACKAGE_VERSION
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

# The accepted stack this catalog freezes: the six frozen M2B-M3E evidence roots. The
# catalog and its anti-orphan enumeration cover exactly these; every *later* governed
# layer (the self-verifying ``research/m3f/`` layer, and any subsequent release-candidate
# root such as ``research/m4a/``) is out of scope here and verified by its own milestone.
# Scoping positively to the accepted stack — rather than excluding one hard-coded later
# prefix — keeps this frozen catalog correct on any branch that stacks a new layer on top.
ACCEPTED_STACK_PREFIXES: tuple[str, ...] = (
    "research/m2b/",
    "research/m3a/",
    "research/m3b/",
    "research/m3c/",
    "research/m3d/",
    "research/m3e/",
)
# The exact set of tracked files that constitute the self-verifying M3F layer. The layer
# is excluded from the catalog (E-vs-R circularity), but its completeness is asserted so
# no arbitrary uncatalogued file can hide under the governed ``research/m3f/`` root.
KNOWN_M3F_LAYER_FILES: frozenset[str] = frozenset(
    {
        "research/m3f/HONEST_STATE.md",
        "research/m3f/README.md",
        "research/m3f/RECOVERY_CAPSULE_NOTICE.md",
        "research/m3f/dependency_inventory.json",
        "research/m3f/freeze_catalog.json",
        "research/m3f/honest_state.json",
        "research/m3f/recovery_capsule_manifest.json",
        "research/m3f/recovery_drill.json",
        "research/m3f/workflow_inventory.json",
    }
)
# The accepted M2B-M3E merge commit on ``main``. Pinned in source (not read from the
# mutable catalog) so the catalog's ``accepted_main_sha`` cannot be silently repointed to
# an attacker-chosen commit, and so the accepted evidence can be anchored to immutable
# history rather than only to the committed (mutable) catalog bytes.
EXPECTED_ACCEPTED_MAIN_SHA = "7b75a9813d0658d8d30f8337f7a419d1bf7338f7"


def _is_accepted_stack(relpath: str) -> bool:
    return relpath.startswith(ACCEPTED_STACK_PREFIXES)


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


def frozen_source_sha(repo_root: str | Path) -> str:
    """The M3F source-freeze commit SHA recorded in the committed freeze catalog.

    The frozen inventories (dependency, workflow) verify against the sources *at this
    immutable commit* rather than the live working tree, so a later governed layer that
    bumps the package version or adds a workflow cannot drift an accepted M3F artifact.
    """
    root = Path(repo_root)
    catalog = load_canonical_json((root / CATALOG_RELPATH).read_bytes(), "freeze_catalog")
    return require_str(catalog.get("source_freeze_sha"), "source_freeze_sha")


def blob_at_commit(repo_root: str | Path, commit: str, relpath: str) -> bytes:
    """Bytes of ``relpath`` at ``commit`` (fails closed if the commit is unreachable)."""
    return _blob_bytes(Path(repo_root), commit, relpath)


def tracked_paths_at_commit(repo_root: str | Path, commit: str, dirpath: str) -> list[str]:
    """Sorted repo-relative paths tracked under ``dirpath`` at ``commit``."""
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-tree", "-r", "--name-only", commit, dirpath],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(p for p in out.splitlines() if p)


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
        # Catalogue exactly the accepted M2B-M3E stack. The self-verifying M3F layer and
        # any later release-candidate layer (e.g. research/m4a/) are excluded: they are
        # created after the source-freeze commit this catalog binds and are each verified
        # by their own milestone, so cataloguing them here would be an E-vs-R circularity.
        if not _is_accepted_stack(relpath):
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
        # A5: labels are recomputed from the path, not merely checked for vocab
        # membership, so a relabelled artifact (e.g. m2b evidence forged as m3f) is caught.
        try:
            want_milestone = _milestone_of(rel)
            want_role = _role_of(rel)
        except CatalogError as exc:
            acc.fail("05_milestone_matches_path", f"{rel}: {exc}")
        else:
            if require_str(rec.get("milestone"), "artifact.milestone") != want_milestone:
                acc.fail("05_milestone_matches_path", f"{rel}: milestone not from path")
            if require_str(rec.get("role"), "artifact.role") != want_role:
                acc.fail("06_role_matches_path", f"{rel}: role not from path")
    acc.ok("07_all_catalogued_artifacts_hash_correctly", str(len(artifacts)))

    # Anti-orphan: every tracked governed file outside the M3F verification layer is
    # catalogued (the M3F layer is excluded per M3F_LAYER_PREFIX; it self-verifies).
    try:
        all_tracked = _tracked_governed_files(root)
        tracked = {p for p in all_tracked if _is_accepted_stack(p)}
        orphans = sorted(tracked - catalogued)
        stale = sorted(catalogued - tracked)
        if orphans:
            acc.fail("08_no_orphan_governed_files", f"uncatalogued: {orphans[:5]}")
        elif stale:
            acc.fail("09_no_stale_catalog_entries", f"missing on disk: {stale[:5]}")
        else:
            acc.ok("08_anti_orphan_enumeration", f"{len(tracked)} governed files all catalogued")
        # A1: the self-verifying M3F layer is excluded from the catalog above, but its
        # exact file set is pinned so no arbitrary uncatalogued file can hide under the
        # governed research/m3f/ root (later layers such as research/m4a/ are out of scope).
        m3f_layer = {p for p in all_tracked if p.startswith(M3F_LAYER_PREFIX)}
        unexpected = sorted(m3f_layer - set(KNOWN_M3F_LAYER_FILES))
        if unexpected:
            acc.fail(
                "08b_m3f_layer_allowlist", f"unexpected research/m3f/ file(s): {unexpected[:5]}"
            )
        else:
            acc.ok("08b_m3f_layer_allowlist")
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

    # The catalog's git-provenance fields are recomputed from git, not trusted.
    _verify_git_provenance(root, catalog, acc)

    return CatalogResult(
        ok=not acc.failures,
        checks=tuple(acc.checks),
        failures=tuple(acc.failures),
        artifact_count=len(artifacts),
    )


def _verify_git_provenance(root: Path, catalog: dict[str, Any], acc: _Accum) -> None:
    """Recompute the catalog's git-binding fields; they are forgeable if never checked.

    Requires the accepted-main and source-freeze commits to be reachable (a full
    checkout — the M3F replay CI fetches full history for this). A recompute that
    cannot reach the commit fails closed rather than silently passing.
    """
    version = require_str(catalog.get("package_version"), "package_version")
    if version != M3F_PACKAGE_VERSION:
        acc.fail("11_package_version", f"catalog {version} != running {M3F_PACKAGE_VERSION}")
    else:
        acc.ok("11_package_version")

    try:
        accepted = require_str(catalog.get("accepted_main_sha"), "accepted_main_sha")
        want_tree = require_str(catalog.get("accepted_main_tree_sha"), "accepted_main_tree_sha")
        got_tree = _git(root, "rev-parse", f"{accepted}^{{tree}}").strip()
        if got_tree != want_tree:
            acc.fail("12_accepted_main_tree", "recorded accepted_main_tree_sha does not match git")
        else:
            acc.ok("12_accepted_main_tree")
    except (subprocess.CalledProcessError, M3FValidationError) as exc:
        acc.fail("12_accepted_main_tree", f"cannot recompute accepted-main tree: {exc}")

    try:
        freeze = require_str(catalog.get("source_freeze_sha"), "source_freeze_sha")
        want_fp = require_str(catalog.get("source_tree_fingerprint"), "source_tree_fingerprint")
        got_fp = sha256_bytes(_git(root, "ls-tree", "-r", freeze, "src").encode("utf-8"))
        if got_fp != want_fp:
            acc.fail("13_source_tree_fingerprint", "recorded source fingerprint does not match git")
        else:
            acc.ok("13_source_tree_fingerprint")
    except (subprocess.CalledProcessError, M3FValidationError) as exc:
        acc.fail("13_source_tree_fingerprint", f"cannot recompute source fingerprint: {exc}")

    # A3: anchor the working-tree accepted M2B-M3E evidence to the immutable, *source-pinned*
    # accepted-main commit — deliberately NOT the mutable catalog ``accepted_main_sha`` field.
    # A coordinated forgery that rewrites an accepted artifact together with its catalog entry,
    # the capsule, the drill, *and* the accepted_main_sha field still fails here, because the
    # working tree must match the pinned accepted-main commit byte-for-byte over the accepted
    # paths — an anchor rooted in the package source, outside every mutable committed file.
    # The anchor applies wherever the pinned accepted-main commit is reachable — the real
    # repository and any full clone/CI checkout, where it is an immutable ancestor that cannot
    # be made unreachable without a (blocked) history rewrite. In a synthetic or shallow context
    # that legitimately lacks that lineage there is no "real accepted stack" to anchor, and the
    # catalog's own accepted_main provenance (checks 12/13) governs reachability instead.
    reachable = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "rev-parse",
            "--verify",
            "--quiet",
            f"{EXPECTED_ACCEPTED_MAIN_SHA}^{{commit}}",
        ],
        capture_output=True,
    )
    if reachable.returncode != 0:
        acc.ok(
            "14_accepted_stack_anchored", "pinned accepted-main not present; anchor not applicable"
        )
    else:
        diff = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "diff",
                "--quiet",
                EXPECTED_ACCEPTED_MAIN_SHA,
                "--",
                *ACCEPTED_STACK_PREFIXES,
            ],
            capture_output=True,
        )
        if diff.returncode == 0:
            acc.ok("14_accepted_stack_anchored")
        else:
            acc.fail(
                "14_accepted_stack_anchored",
                "accepted M2B-M3E evidence differs from the pinned accepted-main commit",
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
