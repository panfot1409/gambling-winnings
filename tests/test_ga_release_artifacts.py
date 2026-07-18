"""The committed v1.1.0 release evidence is current, neutral, and honestly unpublished.

``tools/release_evidence.py`` deterministically regenerates ``release/v1.1.0/`` from the committed
source; these tests prove the committed bytes match, that hardening changed no ``research/``
artifact (the governed-state digest reproduces), that the sealed ledgers stay byte-empty, and that
the release state records the **private** posture — the public-GA route abandoned, built/hardened
but **not** publicly published, every public channel closed, on the ordered private lifecycle.
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


def test_state_is_private_and_honestly_unpublished() -> None:
    state = json.loads((REPO_ROOT / "release/v1.1.0/release_state.json").read_bytes())
    # The public-GA route was abandoned; the posture is private and not publicly published.
    assert state["schema_version"] == 2
    assert state["distribution_classification"] == "private"
    assert state["repository_visibility_required"] == "private"
    assert state["public_ga_abandoned"] is True
    assert state["published"] is False
    assert state["distribution_built"] is True
    assert state["private_distribution"] is True
    # Every public channel is closed and no license is present.
    for closed in state["public_channels_closed"].values():
        assert closed is False
    # The lifecycle is the ordered private machine and the current state is a member of it.
    assert state["release_lifecycle"] == [
        "public_ga_abandoned",
        "private_ga_in_progress",
        "ready",
        "shipped",
    ]
    lifecycle = state["release_lifecycle"]
    assert state["release_state"] in lifecycle
    assert state["release_state_index"] == lifecycle.index(state["release_state"])
    # The payload is only marked delivered in the terminal `shipped` state.
    assert state["private_payload_delivered"] == (state["release_state"] == "shipped")
    # No public-publication gates remain; the gates are the fail-closed private ones.
    assert "publication_gates" not in state
    gate_ids = {g["id"] for g in state["private_gates"]}
    assert gate_ids == {
        "repository_private",
        "sealed_ledgers_byte_empty",
        "governed_state_unchanged",
        "no_public_publication_vector",
    }
    assert all(g["required"] is True for g in state["private_gates"])


def test_sbom_covers_the_runtime_dependencies() -> None:
    sbom = json.loads((REPO_ROOT / "release/v1.1.0/sbom.cdx.json").read_bytes())
    assert sbom["bomFormat"] == "CycloneDX"
    # The subject is metadata.component; components[] are the locked dependencies (not the root).
    assert sbom["metadata"]["component"]["name"] == "eth-research"
    names = {c["name"] for c in sbom["components"]}
    for dep in ("numpy", "pandas", "pyarrow"):
        assert dep in names, dep
    assert "eth-research" not in names  # the root is not double-listed as its own dependency
