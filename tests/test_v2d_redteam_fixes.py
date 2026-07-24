"""Regression tests for the V2D pre-activation red-team fixes (five-auditor pass).

Each test pins a specific finding's fix so it cannot silently regress. Every mutation is
performed on a throwaway copy under ``tmp_path``; the audited repository is never touched.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# A4-B1 — the m3d runtime import firewall resolves relative imports            #
# --------------------------------------------------------------------------- #
def test_m3d_import_scanner_resolves_relative_imports(tmp_path: Path) -> None:
    from eth_research.m3d.verify_m3d_program import _module_targets

    src_root = tmp_path / "src"
    mod = src_root / "eth_research/m3d/probe.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("from ..portfolio import engine\nfrom .. import metrics\nimport os\n")
    targets = _module_targets(mod, src_root)
    # A relative import is resolved to its absolute from-module (not left invisible): both
    # `eth_research.portfolio` and the bare parent `eth_research` are non-allowlisted and so
    # would be flagged by the scanner. Plain absolute imports are preserved too.
    assert "eth_research.portfolio" in targets
    assert "eth_research" in targets
    assert "os" in targets


def test_m3d_scanner_rejects_a_relative_forbidden_import(tmp_path: Path) -> None:
    from eth_research.m3d.validation import M3DValidationError
    from eth_research.m3d.verify_m3d_program import _scan_prohibited_imports

    pkg = tmp_path / "src/eth_research/m3d"
    shutil.copytree(REPO_ROOT / "src/eth_research/m3d", pkg)
    # A relatively-spelled evaluation-engine import must be refused (it was invisible to the
    # pre-fix scanner, which only inspected level==0 ImportFrom nodes).
    (pkg / "maturity.py").write_text(
        (pkg / "maturity.py").read_text() + "\nfrom ..portfolio import engine  # noqa\n"
    )
    with pytest.raises(M3DValidationError, match="non-allowlisted"):
        _scan_prohibited_imports(tmp_path)


# --------------------------------------------------------------------------- #
# A3-C1 — the shared read primitive rejects an in-repo symlink                 #
# --------------------------------------------------------------------------- #
def test_upstream_resolve_rejects_an_in_repo_symlink(tmp_path: Path) -> None:
    from eth_research.m3d import _upstream as up
    from eth_research.m3d.validation import M3DValidationError

    (tmp_path / "real.json").write_bytes(b"[[1,2,3]]")
    os.symlink(tmp_path / "real.json", tmp_path / "link.json")
    # The guard runs on the un-resolved component chain, so an in-repo symlink is refused
    # even though its resolved target is a regular file inside the root.
    with pytest.raises(M3DValidationError, match="not a regular file"):
        up.read_bytes(tmp_path, "link.json")
    # A plain regular file still reads.
    assert up.read_bytes(tmp_path, "real.json") == b"[[1,2,3]]"


# --------------------------------------------------------------------------- #
# A1-C2 — content-type is an exact media token, not a prefix                   #
# --------------------------------------------------------------------------- #
def test_receipt_content_type_is_exact_token() -> None:
    from eth_research.m3d.receipt import _require_content_type
    from eth_research.m3d.validation import M3DValidationError

    assert _require_content_type("content_type", "application/json") == "application/json"
    assert _require_content_type("content_type", "application/json; charset=utf-8").startswith(
        "application/json"
    )
    for bad in ("application/jsonx", "application/json-patch", "text/html", ""):
        with pytest.raises(M3DValidationError, match="application/json"):
            _require_content_type("content_type", bad)


# --------------------------------------------------------------------------- #
# A5-C3 — the staging rollback snapshot covers every published path            #
# --------------------------------------------------------------------------- #
def test_staging_snapshot_covers_every_published_path() -> None:
    from eth_research.m3d.cohort import build_prospective_publication_blobs
    from eth_research.m3e.staging import DERIVED_RELPATHS

    published = {relpath for relpath, _ in build_prospective_publication_blobs(REPO_ROOT)}
    # Every artifact the publication bundle writes must be in the rollback snapshot set, or a
    # drifting rebuild of an omitted path would survive the "full rollback" contract.
    assert published <= set(DERIVED_RELPATHS), published - set(DERIVED_RELPATHS)
    assert "research/m3d/reacquisition_audit.json" in DERIVED_RELPATHS


# --------------------------------------------------------------------------- #
# A1-C1 / A1-C3 — m3d raw-bundle replay binds byte-length and full coverage    #
# --------------------------------------------------------------------------- #
_GENESIS = "coinbase-eth-usd-prospective-genesis-001"


def _copy_genesis_attempt(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    src = REPO_ROOT / "research/m3d/raw/coinbase" / _GENESIS
    dst = root / "research/m3d/raw/coinbase" / _GENESIS
    dst.parent.mkdir(parents=True)
    shutil.copytree(src, dst)
    return root


def _rewrite_receipt(root: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    from eth_research.m3d.validation import canonical_json_bytes, strict_json_loads

    path = root / "research/m3d/raw/coinbase" / _GENESIS / "acquisition_receipt.json"
    obj = strict_json_loads(path.read_bytes())
    mutate(obj)
    path.write_bytes(canonical_json_bytes(obj))  # canonical form the loader re-verifies


def test_raw_bundle_replay_is_clean_then_rejects_a_byte_length_lie(tmp_path: Path) -> None:
    from eth_research.m3d.raw_bundle import build_raw_bundles
    from eth_research.m3d.validation import M3DValidationError

    root = _copy_genesis_attempt(tmp_path)
    assert build_raw_bundles(root, _GENESIS)  # baseline: rebuilds cleanly

    def lie(obj: dict[str, Any]) -> None:
        obj["responses"][0]["response_byte_length"] = 1  # correct sha, wrong length

    _rewrite_receipt(root, lie)
    with pytest.raises(M3DValidationError, match="byte length"):
        build_raw_bundles(root, _GENESIS)


def test_raw_bundle_replay_rejects_incomplete_plan_coverage(tmp_path: Path) -> None:
    from eth_research.m3d.raw_bundle import build_raw_bundles
    from eth_research.m3d.validation import M3DValidationError

    root = _copy_genesis_attempt(tmp_path)

    def unknown_ordinal(obj: dict[str, Any]) -> None:
        obj["responses"][0]["ordinal"] = 7  # absent from the plan

    _rewrite_receipt(root, unknown_ordinal)
    # A typed M3DValidationError (not a bare KeyError), from the coverage-equality check.
    with pytest.raises(M3DValidationError, match="cover"):
        build_raw_bundles(root, _GENESIS)


# --------------------------------------------------------------------------- #
# A4-C3 — the status active flag derives from the committed activation anchor  #
# --------------------------------------------------------------------------- #
def test_status_active_derives_from_the_activation_anchor(tmp_path: Path) -> None:
    from eth_research.m3e.status import _activation_anchor_present

    assert _activation_anchor_present(REPO_ROOT) is True  # anchor committed at this HEAD
    assert _activation_anchor_present(tmp_path) is False  # absent in an empty tree
