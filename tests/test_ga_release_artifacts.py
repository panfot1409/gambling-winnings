"""The committed v1.1.0 release evidence is current, neutral, and honestly unpublished.

``tools/release_evidence.py`` deterministically regenerates ``release/v1.1.0/`` from the committed
source; these tests prove the committed bytes match, that GA hardening changed no ``research/``
artifact (the governed-state digest reproduces), that the sealed ledgers stay byte-empty, and that
the release state records the package as built/hardened but **not** published, with the three
external gates open.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def _load_tool() -> object:
    spec = importlib.util.spec_from_file_location(
        "release_evidence", REPO_ROOT / "tools" / "release_evidence.py"
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_TOOL = _load_tool()


def test_release_evidence_is_current() -> None:
    assert _TOOL.check(REPO_ROOT) == []  # type: ignore[attr-defined]


def test_ga_hardening_changed_no_governed_artifact() -> None:
    # The pre-GA governed-state baseline (every research/ artifact) must reproduce byte-for-byte.
    assert _TOOL.governed_baseline_digest(REPO_ROOT) == _TOOL.GOVERNED_BASELINE_DIGEST  # type: ignore[attr-defined]


def test_manifest_identity() -> None:
    manifest = json.loads((REPO_ROOT / "release/v1.1.0/release_manifest.json").read_bytes())
    assert manifest["name"] == "eth-research"
    assert manifest["version"] == "1.1.0" == eth_research.__version__
    assert manifest["publication"]["published"] is False
    assert manifest["distribution_source"]["member_count"] >= 100


def test_state_is_honestly_unpublished_with_open_gates() -> None:
    state = json.loads((REPO_ROOT / "release/v1.1.0/release_state.json").read_bytes())
    assert state["published"] is False
    assert state["distribution_built"] is True
    gate_ids = {g["id"] for g in state["publication_gates"]}
    assert gate_ids == {"license", "pypi_trusted_publisher", "governance_no_id_token_invariant"}
    assert all(g["cleared"] is False for g in state["publication_gates"])


def test_sbom_covers_the_runtime_dependencies() -> None:
    sbom = json.loads((REPO_ROOT / "release/v1.1.0/sbom.cdx.json").read_bytes())
    assert sbom["bomFormat"] == "CycloneDX"
    # The subject is metadata.component; components[] are the locked dependencies (not the root).
    assert sbom["metadata"]["component"]["name"] == "eth-research"
    names = {c["name"] for c in sbom["components"]}
    for dep in ("numpy", "pandas", "pyarrow"):
        assert dep in names, dep
    assert "eth-research" not in names  # the root is not double-listed as its own dependency
