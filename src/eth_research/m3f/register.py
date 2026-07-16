"""Registration (R) and post-drill (P) artifact writer for Milestone 3F.

This is the single build-and-write path of the milestone: it derives the M3F
verification artifacts from the frozen source and committed bytes and writes them
under ``research/m3f/``. Everything it writes is deterministic and independently
re-derivable, so the whole-graph audit and the CI replay reproduce it byte-for-byte.

It never fetches data, evaluates a strategy, mutates an accepted ledger, or
publishes a proposal — it only serializes derivations of already-committed state.
The registration (R) set is the freeze catalog, the honest state (JSON + Markdown),
the dependency and workflow inventories, and the recovery capsule manifest + notice.
The post-drill (P) artifact is the recovery drill record.
"""

from __future__ import annotations

from pathlib import Path

from eth_research.m3f import M3F_PACKAGE_VERSION
from eth_research.m3f.bundle import (
    CAPSULE_MANIFEST_RELPATH,
    CAPSULE_NOTICE_RELPATH,
    build_manifest,
    render_capsule_notice,
    render_manifest_bytes,
)
from eth_research.m3f.catalog import CATALOG_RELPATH, build_catalog, render_catalog_bytes
from eth_research.m3f.dependency_inventory import INVENTORY_RELPATH as DEP_RELPATH
from eth_research.m3f.dependency_inventory import build_inventory as build_dep_inventory
from eth_research.m3f.dependency_inventory import render_inventory_bytes as render_dep_bytes
from eth_research.m3f.honest_state import (
    HONEST_STATE_MD_RELPATH,
    HONEST_STATE_RELPATH,
    derive_honest_state,
    render_honest_state_bytes,
    render_honest_state_md,
)
from eth_research.m3f.recovery import DRILL_RELPATH, build_drill_record, render_drill_bytes
from eth_research.m3f.workflow_inventory import INVENTORY_RELPATH as WF_RELPATH
from eth_research.m3f.workflow_inventory import build_inventory as build_wf_inventory
from eth_research.m3f.workflow_inventory import render_inventory_bytes as render_wf_bytes


def _build_registration_pairs(
    root: Path, *, source_freeze_sha: str, accepted_main_sha: str
) -> list[tuple[str, bytes]]:
    """Derive every R-set artifact in memory. Any derivation failure aborts here,
    before a single byte is written, so publication is all-or-nothing."""
    catalog = build_catalog(
        root,
        source_freeze_sha=source_freeze_sha,
        accepted_main_sha=accepted_main_sha,
        package_version=M3F_PACKAGE_VERSION,
    )
    state = derive_honest_state(root)
    return [
        (CATALOG_RELPATH, render_catalog_bytes(catalog)),
        (HONEST_STATE_RELPATH, render_honest_state_bytes(state)),
        (HONEST_STATE_MD_RELPATH, render_honest_state_md(state)),
        (DEP_RELPATH, render_dep_bytes(build_dep_inventory(root))),
        (WF_RELPATH, render_wf_bytes(build_wf_inventory(root))),
        (CAPSULE_MANIFEST_RELPATH, render_manifest_bytes(build_manifest(root))),
        (CAPSULE_NOTICE_RELPATH, render_capsule_notice()),
    ]


def _publish_atomically(root: Path, pairs: list[tuple[str, bytes]]) -> list[str]:
    """Write every (relpath, bytes) pair, rolling back all writes on any failure.

    Files that already existed are left untouched by rollback (only newly created
    paths are removed), so a re-registration that fails cannot corrupt prior state.
    """
    created: list[Path] = []
    try:
        for relpath, data in pairs:
            path = root / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            existed = path.exists()
            path.write_bytes(data)
            if not existed:
                created.append(path)
    except OSError:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return sorted(relpath for relpath, _ in pairs)


def write_registration_artifacts(
    repo_root: str | Path,
    *,
    source_freeze_sha: str,
    accepted_main_sha: str,
) -> list[str]:
    """Transactionally write the R-set artifacts. Returns the sorted relpaths.

    Every artifact is derived in full before anything is written; if any derivation
    raises, nothing is published. If a later write fails, the newly created files are
    rolled back.
    """
    root = Path(repo_root)
    pairs = _build_registration_pairs(
        root, source_freeze_sha=source_freeze_sha, accepted_main_sha=accepted_main_sha
    )
    return _publish_atomically(root, pairs)


def write_drill_record(repo_root: str | Path) -> str:
    """Write the P-set recovery drill record. Returns its relpath."""
    root = Path(repo_root)
    data = render_drill_bytes(build_drill_record(root))  # derive fully before writing
    path = root / DRILL_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return DRILL_RELPATH
