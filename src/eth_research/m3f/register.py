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


def _write(root: Path, relpath: str, data: bytes) -> str:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return relpath


def write_registration_artifacts(
    repo_root: str | Path,
    *,
    source_freeze_sha: str,
    accepted_main_sha: str,
) -> list[str]:
    """Write the R-set artifacts. Returns the sorted list of written relpaths."""
    root = Path(repo_root)
    written: list[str] = []

    catalog = build_catalog(
        root,
        source_freeze_sha=source_freeze_sha,
        accepted_main_sha=accepted_main_sha,
        package_version=M3F_PACKAGE_VERSION,
    )
    written.append(_write(root, CATALOG_RELPATH, render_catalog_bytes(catalog)))

    state = derive_honest_state(root)
    written.append(_write(root, HONEST_STATE_RELPATH, render_honest_state_bytes(state)))
    written.append(_write(root, HONEST_STATE_MD_RELPATH, render_honest_state_md(state)))

    written.append(_write(root, DEP_RELPATH, render_dep_bytes(build_dep_inventory(root))))
    written.append(_write(root, WF_RELPATH, render_wf_bytes(build_wf_inventory(root))))

    manifest_bytes = render_manifest_bytes(build_manifest(root))
    written.append(_write(root, CAPSULE_MANIFEST_RELPATH, manifest_bytes))
    written.append(_write(root, CAPSULE_NOTICE_RELPATH, render_capsule_notice()))

    return sorted(written)


def write_drill_record(repo_root: str | Path) -> str:
    """Write the P-set recovery drill record. Returns its relpath."""
    root = Path(repo_root)
    return _write(root, DRILL_RELPATH, render_drill_bytes(build_drill_record(root)))
