"""The committed v1.1.0 release evidence is current, neutral, and honestly unpublished.

``tools/release_evidence.py`` deterministically regenerates ``release/v1.1.0/`` from the committed
source; these tests prove the committed bytes match, that hardening changed no ``research/``
artifact (the governed-state digest reproduces), that the sealed ledgers stay byte-empty, and that
the release state records the **private** posture — the public-GA route abandoned, built/hardened
but **not** publicly published, every public channel closed, on the ordered private lifecycle.

Two of the three artifacts are *historical* records of release v1.1.0 rather than descriptions of
the live tree: ``release_manifest.json`` (built from the v1.1.0 source tree) and ``sbom.cdx.json``
(built from the v1.1.0 ``uv.lock``). Once the active version moves past ``VERSION`` they are never
rebuilt and are validated against their own recorded identity; the tests below pin that, including
that declaring a dependency — which necessarily rewrites ``uv.lock`` — cannot mutate the frozen
SBOM. Current-tree dependency coverage lives in the *live* private SBOM at
``governance/v2c/commercial/sbom.cdx.json``, which is covered here too.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.v2c.commercial import evidence as v2c_evidence
from eth_research.v2c.commercial.sbom import V2C_DEV_VERSION, build_private_sbom

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

FROZEN_SBOM_PATH = REPO_ROOT / "release/v1.1.0/sbom.cdx.json"
#: The frozen v1.1.0 SBOM's byte identity, recorded here as an independent regression anchor. It is
#: the same digest the V2A-V2B stack freeze table and the Fable 5 system inventory pin for this
#: path. Nothing in an ordinary development change — least of all a dependency declaration — may
#: move it; if this constant ever needs editing, a historical release record has been falsified.
FROZEN_SBOM_SHA256 = "7fd0396afbf4e642d724ea2a90ae3d25d108de5540f472fc1e73eecc11fa2731"

LIVE_SBOM_PATH = REPO_ROOT / "governance/v2c/commercial/sbom.cdx.json"


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
    assert set(written) == {"release_state.json"}
    assert manifest.read_bytes() == historical, "the historical manifest was rewritten"


def test_write_keeps_the_historical_sbom_under_a_later_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--write`` must not rebuild the v1.1.0 SBOM from a lock that is no longer v1.1.0's.

    The SBOM's ``components[]`` are read out of ``uv.lock``. A document whose subject is stamped
    ``eth-research 1.1.0`` but whose dependency list is regenerated from today's lock describes no
    release that ever existed, and rewriting it also falsifies the ``"immutability": "immutable"``
    identity the V2A-V2B stack freeze table records for this path.
    """
    monkeypatch.setattr(_TOOL, "_active_version", lambda _root: "2.0.0.dev2")
    _stub_artifacts(monkeypatch)
    outdir = tmp_path / _TOOL.RELDIR  # type: ignore[attr-defined]
    outdir.mkdir(parents=True)
    sbom = outdir / "sbom.cdx.json"
    historical = FROZEN_SBOM_PATH.read_bytes()
    sbom.write_bytes(historical)

    written = _TOOL.write(tmp_path)  # type: ignore[attr-defined]

    assert "sbom.cdx.json" not in written
    assert set(written) == {"release_state.json"}
    assert sbom.read_bytes() == historical, "the historical SBOM was rewritten"
    assert hashlib.sha256(sbom.read_bytes()).hexdigest() == FROZEN_SBOM_SHA256


def test_write_rebuilds_everything_at_the_release_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At the release version itself nothing is historical, so the manifest is rebuilt too."""
    monkeypatch.setattr(_TOOL, "_active_version", lambda _root: _TOOL.VERSION)  # type: ignore[attr-defined]
    _stub_artifacts(monkeypatch)

    written = _TOOL.write(tmp_path)  # type: ignore[attr-defined]

    assert set(written) == {"release_manifest.json", "sbom.cdx.json", "release_state.json"}
    assert (tmp_path / _TOOL.RELDIR / "release_manifest.json").is_file()  # type: ignore[attr-defined]
    assert (tmp_path / _TOOL.RELDIR / "sbom.cdx.json").is_file()  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# the frozen v1.1.0 SBOM is historical: a dependency change cannot move it     #
# --------------------------------------------------------------------------- #
def _diverged_tree(tmp_path: Path, *, extra_packages: tuple[tuple[str, str], ...] = ()) -> bytes:
    """A minimal repo root that is past v1.1.0, holding the real frozen SBOM and a mutated lock.

    Returns the frozen SBOM bytes that were planted. ``extra_packages`` are appended to a copy of
    the live ``uv.lock`` — this is what declaring a dependency does to the lock, and therefore to
    anything that rebuilds a bill of materials from it.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "eth-research"\nversion = "2.0.0.dev2"\ndependencies = []\n',
        encoding="utf-8",
    )
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    for name, version in extra_packages:
        lock += (
            f'\n[[package]]\nname = "{name}"\nversion = "{version}"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
        )
    (tmp_path / "uv.lock").write_text(lock, encoding="utf-8")
    outdir = tmp_path / _TOOL.RELDIR  # type: ignore[attr-defined]
    outdir.mkdir(parents=True)
    frozen = FROZEN_SBOM_PATH.read_bytes()
    (outdir / "sbom.cdx.json").write_bytes(frozen)
    return frozen


def test_a_declared_dependency_cannot_mutate_the_frozen_sbom(tmp_path: Path) -> None:
    """The regression this whole treatment exists for, driven through the real builders.

    Adding one package to ``uv.lock`` is enough to make :func:`build_sbom` emit different bytes.
    ``write`` must not put those bytes on disk: the artifact describes release v1.1.0, and the
    stack freeze table records its byte identity as immutable with no writer that could reissue it.
    """
    frozen = _diverged_tree(tmp_path, extra_packages=(("nardis-telemetry", "1.4.2"),))
    sbom_path = tmp_path / _TOOL.RELDIR / "sbom.cdx.json"  # type: ignore[attr-defined]

    # The generator genuinely would have produced something else — this is not a no-op test.
    regenerated = _TOOL.build_sbom(tmp_path)  # type: ignore[attr-defined]
    assert "nardis-telemetry" in {c["name"] for c in regenerated["components"]}
    assert _TOOL._canonical_json(regenerated) != frozen  # type: ignore[attr-defined]

    written = _TOOL.write(tmp_path)  # type: ignore[attr-defined]

    assert written == ["release_state.json"]
    assert sbom_path.read_bytes() == frozen
    assert hashlib.sha256(sbom_path.read_bytes()).hexdigest() == FROZEN_SBOM_SHA256


def test_check_does_not_call_the_frozen_sbom_stale_after_a_dependency_change(
    tmp_path: Path,
) -> None:
    """...and ``check`` must not report it stale either, or ``--write`` gets invoked to "fix" it.

    ``check``'s drift message is literally "regenerate with --write". If a dependency change made
    the frozen SBOM look stale, the remedy the tool prints is the one that falsifies it. (The other
    problems this stub tree reports — no ``research/``, no sealed ledgers, no manifest — are
    expected; only the SBOM's silence is under test.)
    """
    _diverged_tree(tmp_path, extra_packages=(("nardis-telemetry", "1.4.2"),))

    problems = _TOOL.check(tmp_path)  # type: ignore[attr-defined]

    assert not [p for p in problems if "sbom" in p], problems


def test_frozen_sbom_recorded_identity_validates() -> None:
    """The committed artifact passes the historical check it is now verified by."""
    assert _TOOL._check_sbom_historical(FROZEN_SBOM_PATH, REPO_ROOT) == []  # type: ignore[attr-defined]


def _bump_subject_version(doc: dict[str, Any]) -> None:
    doc["metadata"]["component"]["version"] = "2.0.0.dev2"


def _bump_spec_version(doc: dict[str, Any]) -> None:
    doc["specVersion"] = "1.6"


def _drop_scope_property(doc: dict[str, Any]) -> None:
    doc["metadata"]["properties"] = []


def _relabel_a_component_purl(doc: dict[str, Any]) -> None:
    doc["components"][0]["purl"] = "pkg:pypi/numpy@99.0.0"


def _retype_a_component(doc: dict[str, Any]) -> None:
    doc["components"][0]["type"] = "application"


def _strip_a_component_version(doc: dict[str, Any]) -> None:
    del doc["components"][0]["version"]


def _list_the_subject_as_a_dependency(doc: dict[str, Any]) -> None:
    doc["components"].append(
        {
            "type": "library",
            "name": "eth-research",
            "version": "1.1.0",
            "purl": "pkg:pypi/eth-research@1.1.0",
        }
    )


def _duplicate_a_component(doc: dict[str, Any]) -> None:
    doc["components"].append(dict(doc["components"][0]))


def _reorder_components(doc: dict[str, Any]) -> None:
    doc["components"].reverse()


def _empty_the_components(doc: dict[str, Any]) -> None:
    doc["components"] = []


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        (_bump_subject_version, "metadata drifted"),
        (_bump_spec_version, "specVersion drifted"),
        (_drop_scope_property, "metadata drifted"),
        (_relabel_a_component_purl, "purl does not bind its name and version"),
        (_retype_a_component, "is not typed as a library"),
        (_strip_a_component_version, "component with no name or version"),
        (_list_the_subject_as_a_dependency, "lists its own subject"),
        (_duplicate_a_component, "duplicate component identity"),
        (_reorder_components, "canonical (sorted) name order"),
        (_empty_the_components, "records no components"),
    ],
)
def test_historical_sbom_check_rejects_a_tampered_record(
    tmp_path: Path, tamper: Callable[[dict[str, Any]], None], expected: str
) -> None:
    """Not reproducing from the live lock is not the same as not checking anything.

    Everything that is a function of the frozen ``VERSION`` must still rebuild byte-for-byte, and
    ``components[]`` — the one lock-derived field — is held to its own recorded identity.
    """
    doc: dict[str, Any] = json.loads(FROZEN_SBOM_PATH.read_bytes())
    tamper(doc)
    path = tmp_path / "sbom.cdx.json"
    path.write_bytes(_TOOL._canonical_json(doc))  # type: ignore[attr-defined]

    problems = _TOOL._check_sbom_historical(path, REPO_ROOT)  # type: ignore[attr-defined]

    assert [p for p in problems if expected in p], problems


def test_frozen_sbom_stays_byte_pinned_by_the_stack_freeze_table() -> None:
    """Provenance is not weakened by going historical: the bytes are still pinned, immutably.

    ``research/v2ab/stack_freeze_table.json`` records this path as ``immutable`` and ships no
    writer. Making the artifact genuinely immutable is what makes that recorded claim true.
    """
    table = json.loads((REPO_ROOT / "research/v2ab/stack_freeze_table.json").read_bytes())
    entry = next(e for e in table["entries"] if e["path"] == "release/v1.1.0/sbom.cdx.json")
    data = FROZEN_SBOM_PATH.read_bytes()
    assert entry["immutability"] == "immutable"
    assert entry["byte_count"] == len(data)
    assert entry["sha256"] == hashlib.sha256(data).hexdigest() == FROZEN_SBOM_SHA256


# --------------------------------------------------------------------------- #
# the live SBOM is what still tracks the current tree                          #
# --------------------------------------------------------------------------- #
def test_the_live_private_sbom_covers_the_current_locked_tree() -> None:
    """Dependency coverage is kept — by the artifact whose job it is.

    ``governance/v2c/commercial/sbom.cdx.json`` is derived from the live ``uv.lock`` by
    ``eth_research.v2c.commercial.sbom`` and rewritten by that package's own writer
    (``evidence.write_all``). It sits outside the frozen ``research/``/``release/`` roots precisely
    so it *may* move, which is why the frozen v1.1.0 SBOM does not have to.
    """
    live: dict[str, Any] = build_private_sbom(REPO_ROOT)
    locked = {p["name"] for p in _TOOL._locked_packages(REPO_ROOT)} - {"eth-research"}  # type: ignore[attr-defined]
    assert {c["name"] for c in live["components"]} == locked
    for dep in ("numpy", "pandas", "pyarrow"):
        assert dep in locked, dep
    # The committed bytes are current, and they are the writer's output — never hand-edited.
    assert v2c_evidence.check(REPO_ROOT) == []
    assert LIVE_SBOM_PATH.read_bytes() == v2c_evidence.build_all(REPO_ROOT)["sbom.cdx.json"]


def test_the_two_sboms_are_different_documents_about_different_subjects() -> None:
    """The frozen one is stamped v1.1.0 forever; the live one is stamped for the V2C distribution.

    They are not redundant copies with a stale one to fix — they are bills of materials for two
    different releases, which is why only one of them is allowed to follow ``uv.lock``.
    """
    frozen = json.loads(FROZEN_SBOM_PATH.read_bytes())
    live = json.loads(LIVE_SBOM_PATH.read_bytes())
    assert frozen["metadata"]["component"]["version"] == _TOOL.VERSION == "1.1.0"  # type: ignore[attr-defined]
    assert live["metadata"]["component"]["version"] == V2C_DEV_VERSION
    assert frozen["metadata"]["component"]["version"] != live["metadata"]["component"]["version"]
    assert _TOOL._active_version(REPO_ROOT) != _TOOL.VERSION  # type: ignore[attr-defined]


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
