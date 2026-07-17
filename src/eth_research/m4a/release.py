"""Deterministic release-candidate manifests for the offline research platform.

Four source-derived artifacts pin the v1.0.0 distribution and release-candidate state without
committing a single binary: which pure-Python members ship, the pinned runtime dependency
graph, the frozen governance/schema state, and an attestation of the proofs that back the
distribution. Every artifact is canonical JSON keyed by a schema version, and ``--check`` fails
closed on drift so a freeze that silently perturbs the distribution is caught in review.

This module is pure, offline, and stdlib-only beyond the package itself: it reads the source
tree, ``pyproject.toml``, and ``uv.lock`` and never builds, uploads, or contacts the network.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.api.config import CONFIG_SCHEMA_VERSION
from eth_research.api.models import API_VERSION, VALIDATION_REPORT_SCHEMA_VERSION
from eth_research.api.orchestrate import MANIFEST_SCHEMA_VERSION
from eth_research.api.receipt import RECEIPT_SCHEMA_VERSION
from eth_research.api.results import RESULT_SCHEMA_VERSION
from eth_research.api.serialization import canonical_json_bytes, sha256_hex, strict_load_canonical
from eth_research.m4a.cli_reference import REFERENCE_RELPATH
from eth_research.m4a.public_api import SNAPSHOT_RELPATH, SNAPSHOT_SCHEMA_VERSION

RELEASE_SCHEMA_VERSION = 1

MANIFEST_RELPATH = "research/m4a/distribution_manifest.json"
DEPENDENCIES_RELPATH = "research/m4a/distribution_dependencies.json"
STATE_RELPATH = "research/m4a/release_candidate_state.json"
PROOF_RELPATH = "research/m4a/distribution_proof.json"

#: The three sealed governance ledgers that must stay byte-empty across the release.
SEALED_LEDGERS = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)
#: sha256 of the empty byte string — the required digest of every sealed ledger.
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

_BUILD_BACKEND_PIN = "hatchling==1.31.0"


class ReleaseDriftError(RuntimeError):
    """A committed release-candidate artifact no longer matches the running source."""


# --------------------------------------------------------------------------- #
# builders (each is a pure function of the source tree)                        #
# --------------------------------------------------------------------------- #
def _package_members(repo_root: Path) -> list[dict[str, Any]]:
    """The pure-Python files that ship inside the package, sorted, with content hashes."""
    pkg = repo_root / "src" / "eth_research"
    members: list[dict[str, Any]] = []
    for path in sorted(pkg.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if not (path.suffix in (".py", ".pyi") or path.name == "py.typed"):
            continue
        data = path.read_bytes()
        members.append(
            {
                "path": path.relative_to(pkg.parent).as_posix(),
                "sha256": sha256_hex(data),
                "size": len(data),
            }
        )
    return members


def build_distribution_manifest(repo_root: Path) -> dict[str, Any]:
    members = _package_members(repo_root)
    return {
        "release_schema_version": RELEASE_SCHEMA_VERSION,
        "package": "eth-research",
        "version": PACKAGE_VERSION,
        "distribution_kinds": ["sdist", "wheel"],
        "wheel_tag": "py3-none-any",
        "member_count": len(members),
        "expected_package_members": members,
        "package_tree_sha256": sha256_hex(canonical_json_bytes(members)),
        "sdist_extra_members": [".gitignore", "PKG-INFO", "README.md", "pyproject.toml"],
        "build_backend_pin": _BUILD_BACKEND_PIN,
    }


def _dependency_name(spec: str) -> str:
    match = re.match(r"[A-Za-z0-9._-]+", spec)
    if match is None:  # pragma: no cover - dependency specifiers always start with a name
        raise ReleaseDriftError(f"unparseable dependency specifier: {spec!r}")
    return match.group(0)


def _locked_versions(repo_root: Path, names: set[str]) -> dict[str, str]:
    lock = tomllib.loads((repo_root / "uv.lock").read_text(encoding="utf-8"))
    versions: dict[str, str] = {}
    for package in lock.get("package", []):
        name = package.get("name")
        if name in names:
            versions[name] = str(package.get("version"))
    return versions


def build_distribution_dependencies(repo_root: Path) -> dict[str, Any]:
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    specs = sorted(project["dependencies"])
    names = {_dependency_name(spec) for spec in specs}
    locked = _locked_versions(repo_root, names)
    entries = [
        {
            "name": _dependency_name(spec),
            "specifier": spec,
            "locked_version": locked.get(_dependency_name(spec)),
        }
        for spec in specs
    ]
    return {
        "release_schema_version": RELEASE_SCHEMA_VERSION,
        "package": "eth-research",
        "requires_python": project["requires-python"],
        "runtime_dependencies": entries,
        "build_backend_pin": _BUILD_BACKEND_PIN,
    }


def build_release_candidate_state(repo_root: Path) -> dict[str, Any]:
    ledgers = {rel: sha256_hex((repo_root / rel).read_bytes()) for rel in SEALED_LEDGERS}
    return {
        "release_schema_version": RELEASE_SCHEMA_VERSION,
        "package": "eth-research",
        "package_version": PACKAGE_VERSION,
        "api_version": API_VERSION,
        "requires_python": ">=3.12",
        "schema_versions": {
            "config": CONFIG_SCHEMA_VERSION,
            "manifest": MANIFEST_SCHEMA_VERSION,
            "public_api_snapshot": SNAPSHOT_SCHEMA_VERSION,
            "receipt": RECEIPT_SCHEMA_VERSION,
            "result": RESULT_SCHEMA_VERSION,
            "validation_report": VALIDATION_REPORT_SCHEMA_VERSION,
        },
        "sealed_ledgers": ledgers,
        "public_api_snapshot_sha256": sha256_hex((repo_root / SNAPSHOT_RELPATH).read_bytes()),
        "cli_reference_sha256": sha256_hex((repo_root / REFERENCE_RELPATH).read_bytes()),
    }


def build_distribution_proof(repo_root: Path) -> dict[str, Any]:
    """An attestation of the proofs that back the distribution (each names its test)."""
    return {
        "release_schema_version": RELEASE_SCHEMA_VERSION,
        "package": "eth-research",
        "version": PACKAGE_VERSION,
        "direct_third_party_dependencies": ["numpy", "pandas", "pyarrow"],
        "properties": {
            "consumer_e2e_out_of_tree": {"proven_by": "tests/test_consumer_e2e.py"},
            "distribution_scanner_clean": {
                "proven_by": "tests/test_packaging.py::test_scanner_reports_clean"
            },
            "double_build_byte_identical_linux": {
                "proven_by": "tests/test_packaging.py::test_double_build_is_byte_identical"
            },
            "manifest_matches_built_distribution": {
                "proven_by": (
                    "tests/test_m4a_release.py::test_distribution_manifest_matches_built_wheel"
                )
            },
            "no_network_or_exchange_import": {
                "proven_by": (
                    "tests/test_m4a_security.py::test_runtime_layer_has_no_forbidden_capability"
                )
            },
            "package_tree_is_pure_python": {
                "proven_by": "tests/test_packaging.py::test_sdist_contains_no_private_data"
            },
        },
        "forbidden_capabilities_absent": True,
    }


_BUILDERS = {
    MANIFEST_RELPATH: build_distribution_manifest,
    DEPENDENCIES_RELPATH: build_distribution_dependencies,
    STATE_RELPATH: build_release_candidate_state,
    PROOF_RELPATH: build_distribution_proof,
}


# --------------------------------------------------------------------------- #
# write / verify                                                              #
# --------------------------------------------------------------------------- #
def write(repo_root: str | Path) -> list[str]:
    root = Path(repo_root)
    written: list[str] = []
    for relpath, builder in _BUILDERS.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(builder(root)))
        written.append(relpath)
    return written


def verify(repo_root: str | Path) -> None:
    """Raise :class:`ReleaseDriftError` unless every committed RC artifact matches the source."""
    root = Path(repo_root)
    for relpath, builder in _BUILDERS.items():
        path = root / relpath
        try:
            committed = path.read_bytes()
        except OSError as exc:
            raise ReleaseDriftError(
                f"release-candidate artifact missing: {relpath}: {exc}"
            ) from exc
        fresh = canonical_json_bytes(builder(root))
        recanonical = canonical_json_bytes(strict_load_canonical(committed, relpath))
        if recanonical != fresh:
            raise ReleaseDriftError(
                f"{relpath} is stale; regenerate with `python -m eth_research.m4a.release --write`"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release-candidate manifests: --check or --write.")
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="verify the committed artifacts")
    group.add_argument("--write", action="store_true", help="(re)write the committed artifacts")
    args = parser.parse_args(argv)
    if args.write:
        for relpath in write(args.repo_root):
            sys.stdout.write(f"wrote {relpath}\n")
        return 0
    try:
        verify(args.repo_root)
    except ReleaseDriftError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write("release-candidate artifacts are current\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
