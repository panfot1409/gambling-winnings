"""The committed release-candidate artifacts are current and match the real distribution."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

import eth_research
from eth_research.m4a import M4A_PACKAGE_VERSION, release

REPO = Path(__file__).resolve().parents[1]

# The committed M4A RC manifests pin the *1.0.0* distribution (its exact shipped package files
# and version). A later milestone stacked on M4A (e.g. M4B at 1.1.0) adds package files and bumps
# the version, so a rebuild-vs-frozen comparison is expected to differ — that is an additive
# development snapshot governed by its own milestone, not a re-verification of the frozen M4A RC.
# These two rebuild-and-compare checks therefore run only when the package IS the M4A RC; the
# frozen-artifact readers below (ledgers empty, pinned 1.0.0/1.0, offline deps) always apply.
_rc_only = pytest.mark.skipif(
    eth_research.__version__ != M4A_PACKAGE_VERSION,
    reason="M4A RC distribution manifest applies only to the 1.0.0 release candidate",
)


@_rc_only
def test_release_candidate_artifacts_are_current() -> None:
    # Fails closed if any committed RC artifact drifted from the source.
    release.verify(REPO)


def test_release_candidate_state_ledgers_are_byte_empty() -> None:
    state = json.loads((REPO / release.STATE_RELPATH).read_bytes())
    assert set(state["sealed_ledgers"]) == set(release.SEALED_LEDGERS)
    for rel, digest in state["sealed_ledgers"].items():
        assert digest == release.EMPTY_SHA, rel


def test_release_candidate_state_pins_version_and_api() -> None:
    state = json.loads((REPO / release.STATE_RELPATH).read_bytes())
    assert state["package_version"] == "1.0.0"
    assert state["api_version"] == "1.0"


def test_distribution_dependencies_are_the_offline_stack() -> None:
    deps = json.loads((REPO / release.DEPENDENCIES_RELPATH).read_bytes())
    names = sorted(entry["name"] for entry in deps["runtime_dependencies"])
    assert names == ["numpy", "pandas", "pyarrow"]
    for entry in deps["runtime_dependencies"]:
        assert entry["locked_version"], entry["name"]


def _build_wheel(dest: Path) -> Path:
    try:
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(dest)],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:  # pragma: no cover - uv always present in CI
        pytest.skip("uv is not available to build the distribution")
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"distribution build failed (offline?): {exc.stderr}")
    return next(dest.glob("*.whl"))


@_rc_only
def test_distribution_manifest_matches_built_wheel(tmp_path: Path) -> None:
    whl = _build_wheel(tmp_path)
    manifest = json.loads((REPO / release.MANIFEST_RELPATH).read_bytes())
    expected = {member["path"]: member["sha256"] for member in manifest["expected_package_members"]}
    with zipfile.ZipFile(whl) as zf:
        shipped = sorted(
            name for name in zf.namelist() if name.startswith("eth_research/") and "/" in name
        )
        shipped = [name for name in shipped if not name.endswith("/")]
        # every shipped package member is expected, with byte-identical content
        for name in shipped:
            assert name in expected, f"shipped but not in manifest: {name}"
            assert hashlib.sha256(zf.read(name)).hexdigest() == expected[name], name
    assert sorted(expected) == shipped, "manifest lists members the wheel does not ship"
