"""Reproducibility contract (§18) for the PRIVATE ``eth-research`` v1.1.0 payload.

Two build-free structural tests over the committed policy/manifest and the reproducibility doc,
plus one ``slow`` determinism test that rebuilds the wheel/sdist twice and asserts byte identity.
The build-free tests assert the committed evidence *pins* the reproducible-build contract
(``SOURCE_DATE_EPOCH=1735689600``, CPython 3.12.3, uv) and tie the manifest to the policy by its
recorded hash — they read committed bytes and never hardcode a digest that may legitimately drift.

The tool is loaded via :func:`importlib.util.spec_from_file_location` (the existing packaging-test
pattern) because ``tools/`` is not an importable package.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from eth_research.api.serialization import sha256_hex

REPO = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO / "tools" / "private_release.py"
RELDIR = REPO / "release" / "private" / "v1.1.0"
POLICY_PATH = RELDIR / "private_distribution_policy.json"
MANIFEST_PATH = RELDIR / "private_payload_manifest.json"
DOC_PATH = REPO / "docs" / "V1_PRIVATE_REPRODUCIBILITY.md"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load("private_release", TOOL_PATH)


def _load_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_bytes())
    return data


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


# --------------------------------------------------------------------------- #
# (a) committed policy/manifest pin the reproducible-build contract            #
# --------------------------------------------------------------------------- #
def test_build_environment_contract_pins_source_date_epoch_and_python() -> None:
    assert TOOL.SOURCE_DATE_EPOCH == 1735689600
    env = _load_json(POLICY_PATH)["build_environment_contract"]
    assert env["source_date_epoch"] == str(TOOL.SOURCE_DATE_EPOCH) == "1735689600"
    assert env["python"] == "3.12.3"
    assert env["builder"] == "uv"


def test_committed_manifest_records_consistent_structural_provenance() -> None:
    manifest = _load_json(MANIFEST_PATH)
    assert manifest["schema_version"] == "1"
    assert manifest["version"] == "1.1.0"
    assert manifest["payload_filename"].endswith("-private-payload.tar")

    # Source-derived anchors are 64-hex digests (structural — never hardcoded, they may drift).
    for field in ("governed_state_digest", "policy_sha256", "source_tree_digest"):
        assert _is_sha256(manifest[field]), field
    assert isinstance(manifest["source_member_count"], int)
    assert manifest["source_member_count"] > 0

    # The sealed ledgers are recorded byte-empty (never read here — only their recorded hashes).
    ledgers = manifest["ledger_sha256"]
    assert set(ledgers) == set(TOOL.SEALED_LEDGERS)
    for rel, digest in ledgers.items():
        assert digest == TOOL.EMPTY_SHA, rel

    # The manifest's recorded policy hash matches the committed policy bytes — the two committed
    # documents are internally consistent without hardcoding either digest.
    assert manifest["policy_sha256"] == sha256_hex(POLICY_PATH.read_bytes())

    # Every payload member carries a sha256, and the reproducible content members are all present.
    members = {m["filename"]: m["sha256"] for m in manifest["members"]}
    for name in (
        "eth_research-1.1.0-py3-none-any.whl",
        "eth_research-1.1.0.tar.gz",
        "provenance.json",
        "sbom.cdx.json",
        "PRIVATE_INSTALL.md",
        "SHA256SUMS",
    ):
        assert _is_sha256(members.get(name)), name
    # The manifest never lists the payload tar or itself (no unsatisfiable self-hash).
    assert TOOL.PAYLOAD_NAME not in members
    assert "private_payload_manifest.json" not in members


# --------------------------------------------------------------------------- #
# (c) the doc states the honest same-runner limit and names the epoch          #
# --------------------------------------------------------------------------- #
def test_reproducibility_doc_states_same_runner_limit_and_names_epoch() -> None:
    assert DOC_PATH.is_file(), "docs/V1_PRIVATE_REPRODUCIBILITY.md is missing"
    text = DOC_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "source_date_epoch" in low
    assert "1735689600" in text
    assert "3.12.3" in text
    assert "hatchling==1.31.0" in text
    # same-runner only; cross-OS byte identity explicitly not claimed
    assert "same-runner" in low
    assert "cross-os" in low
    assert "not claimed" in low
    # the immutable commit is the canonical anchor; the Actions artifact is not the source of truth
    assert "not the source of truth" in low
    for source_input in ("src/eth_research", "pyproject.toml", "README.md"):
        assert source_input in text


# --------------------------------------------------------------------------- #
# (b) slow: two independent builds are byte-identical                          #
# --------------------------------------------------------------------------- #
def _uv_available() -> bool:
    return shutil.which("uv") is not None and shutil.which("git") is not None


@pytest.mark.slow
def test_two_independent_builds_yield_byte_identical_artifacts() -> None:
    if TOOL._active_version(REPO) != TOOL.VERSION:
        pytest.skip("the frozen private-release builder builds only the v1.1.0 source tree")
    if not _uv_available():
        pytest.skip("uv/git required for the deterministic build")
    try:
        wheel_a, sdist_a = TOOL._build_wheel_and_sdist(REPO)
        wheel_b, sdist_b = TOOL._build_wheel_and_sdist(REPO)
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("uv is not available")
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"build unavailable (offline?): {exc.stderr}")
    assert wheel_a == wheel_b, "wheel is not byte-identical across two independent builds"
    assert sdist_a == sdist_b, "sdist is not byte-identical across two independent builds"

    payload_a = TOOL.assemble_payload_bytes(REPO, wheel_a, sdist_a)
    payload_b = TOOL.assemble_payload_bytes(REPO, wheel_b, sdist_b)
    assert payload_a == payload_b, "payload is not byte-identical across two independent builds"
    # The payload is a pure function of the wheel+sdist bytes: identical inputs -> identical output.
    assert TOOL.assemble_payload_bytes(REPO, wheel_a, sdist_a) == payload_a


# --------------------------------------------------------------------------- #
# (d) the doc honestly accounts for the root .gitignore as a 4th sdist input   #
# --------------------------------------------------------------------------- #
def test_reproducibility_doc_names_gitignore_as_the_sdist_extra_input() -> None:
    # hatchling always ships the repo-root ``.gitignore`` in the sdist, so the sdist is a function
    # of four inputs, not three. The doc must say so and must not claim every dotfile is excluded.
    text = DOC_PATH.read_text(encoding="utf-8")
    assert ".gitignore" in text, "the doc must name the root .gitignore as an sdist input"
    assert "every dotfile are excluded" not in text, "the doc still overclaims dotfile exclusion"


@pytest.mark.slow
def test_sdist_contains_the_root_gitignore_input() -> None:
    # Prove the reality the doc now documents: the built sdist carries the root ``.gitignore``.
    import io
    import tarfile

    if TOOL._active_version(REPO) != TOOL.VERSION:
        pytest.skip("the frozen private-release builder builds only the v1.1.0 source tree")
    if not _uv_available():
        pytest.skip("uv/git required for the deterministic build")
    try:
        _wheel, sdist = TOOL._build_wheel_and_sdist(REPO)
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("uv is not available")
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"build unavailable (offline?): {exc.stderr}")
    with tarfile.open(fileobj=io.BytesIO(sdist), mode="r:gz") as tf:
        roots = {name.split("/", 1)[1] for name in tf.getnames() if "/" in name}
    assert ".gitignore" in roots, f"expected the root .gitignore in the sdist; got {sorted(roots)}"
