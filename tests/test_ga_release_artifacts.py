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

import pytest

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


def test_the_repository_has_moved_past_the_frozen_release_version() -> None:
    """Documents why the historical path below is the one that runs here, not a hypothetical."""
    assert _TOOL._active_version(REPO_ROOT) != _TOOL.VERSION  # type: ignore[attr-defined]


def _stub_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the artifact table for trivial builders.

    These tests are about which artifacts ``write`` chooses to rebuild, not about what the real
    builders produce. Stubbing keeps them from needing a whole repository under ``tmp_path`` — and,
    more importantly, from writing into the checkout and leaving it dirty for the suites that
    assert a clean tree.
    """
    monkeypatch.setattr(
        _TOOL,
        "_ARTIFACTS",
        {name: (lambda _root: {"stub": True}) for name in _TOOL._ARTIFACTS},  # type: ignore[attr-defined]
    )


def test_write_keeps_the_historical_manifest_under_a_later_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--write`` must not rebuild the v1.1.0 manifest from a tree that is no longer v1.1.0.

    ``check`` stops reproducing the manifest once the active version moves past the frozen release
    and validates its recorded identity instead. ``write`` has to make the same distinction, or the
    command that ``check``'s own "regenerate with --write" message points at would replace a v1.1.0
    record with one that still claims 1.1.0 while listing a later tree's files.
    """
    monkeypatch.setattr(_TOOL, "_active_version", lambda _root: "2.0.0.dev2")
    _stub_artifacts(monkeypatch)
    outdir = tmp_path / _TOOL.RELDIR  # type: ignore[attr-defined]
    outdir.mkdir(parents=True)
    manifest = outdir / "release_manifest.json"
    historical = b'{"version":"1.1.0","recorded":"from the v1.1.0 tree"}'
    manifest.write_bytes(historical)

    written = _TOOL.write(tmp_path)  # type: ignore[attr-defined]

    assert "release_manifest.json" not in written
    assert set(written) == {"sbom.cdx.json", "release_state.json"}
    assert manifest.read_bytes() == historical, "the historical manifest was rewritten"


def test_write_rebuilds_everything_at_the_release_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At the release version itself nothing is historical, so the manifest is rebuilt too."""
    monkeypatch.setattr(_TOOL, "_active_version", lambda _root: _TOOL.VERSION)  # type: ignore[attr-defined]
    _stub_artifacts(monkeypatch)

    written = _TOOL.write(tmp_path)  # type: ignore[attr-defined]

    assert set(written) == {"release_manifest.json", "sbom.cdx.json", "release_state.json"}
    assert (tmp_path / _TOOL.RELDIR / "release_manifest.json").is_file()  # type: ignore[attr-defined]


def test_manifest_identity() -> None:
    manifest = json.loads((REPO_ROOT / "release/v1.1.0/release_manifest.json").read_bytes())
    assert manifest["name"] == "eth-research"
    # The manifest records the *frozen* v1.1.0 release version (== the release_evidence VERSION
    # constant), which is independent of the live running package version once it bumps past 1.1.0.
    assert manifest["version"] == "1.1.0" == _TOOL.VERSION  # type: ignore[attr-defined]
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
