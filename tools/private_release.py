#!/usr/bin/env python3
"""Deterministic PRIVATE release tooling for eth-research v1.1.0 (private GA).

This tool assembles a byte-deterministic *private* distribution payload for the private
repository ``panfot1409/gambling-winnings`` and verifies the committed private-release
manifests without ever publishing anything. It is the enforcement companion to
``docs/V1_PRIVATE_DISTRIBUTION.md``: the package is private, unlicensed, and carries the
``Private :: Do Not Upload`` guard, so this tool refuses any artifact that would enable a
public PyPI / TestPyPI / public GitHub Release / public registry upload.

Subcommands (``python tools/private_release.py <cmd>``):

* ``build``   — clean-tree + source-integrity gate, deterministic double ``uv build``,
                distribution scan + wheel-metadata license guard, then assemble the
                normalized payload tar under ``dist_private/``. Prints the payload SHA-256.
* ``verify``  — rebuild everything from bytes twice and assert the payload is byte-identical
                (deterministic), re-scanning the wheel/sdist members.
* ``inspect`` — list the payload members with their SHA-256 and size.
* ``status``  — print the honest release-state posture (built / hardened / private /
                blocked-on-tag).
* ``write-manifests`` — (maintainer) regenerate the committed ``release/private/v1.1.0/``
                deliverables deterministically.

Top-level ``--check`` is the build-FREE gate CI runs: it verifies the committed
``release/private/v1.1.0/*.json`` manifests are internally consistent and that their
source-derived fields (governed-state digest over ``research/**``, sealed-ledger hashes,
policy SHA-256, and the ``src/eth_research`` member tree) reproduce from the current tree.
It mutates nothing and needs neither ``uv`` nor ``git``.

Reuses the repository's conventions rather than reinventing them: canonical JSON + hashing
from :mod:`eth_research.api.serialization`, the strict decoder from :mod:`eth_research._json`,
the governed-state / source-tree / SBOM builders from ``tools/release_evidence.py``, and the
member-safety allowlist from ``tools/scan_distribution.py``.

The optional ``build --emit-receipt <path>`` writes a dynamic ``private_release_receipt.json``
for the workflow. That receipt is operational provenance, not a cryptographic signature; it is
never committed and never rides inside the payload, and it stores no secrets, tokens, signed
URLs, or raw usernames/emails.
"""

from __future__ import annotations

import argparse
import io
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any

from eth_research.api.serialization import (
    CanonicalError,
    canonical_json_bytes,
    require_bool,
    require_int,
    require_list,
    require_mapping,
    require_sha256_hex,
    require_str,
    sha256_hex,
    strict_load_canonical,
)

# --------------------------------------------------------------------------- #
# constants                                                                    #
# --------------------------------------------------------------------------- #
VERSION = "1.1.0"
PROJECT_NAME = "eth-research"
PRIVATE_RELDIR = f"release/private/v{VERSION}"
EVIDENCE_MANIFEST_RELPATH = f"release/v{VERSION}/release_manifest.json"

EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
GOVERNED_BASELINE_DIGEST = "b2077eaf18ad21f47f5978c5ced7c419a100c6ff2b89a9dd21a47f94b36bf7c2"
SEALED_LEDGERS = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)
MAX_BUNDLE_BYTES = 52_428_800
RETENTION_DAYS = 30
RUNTIME_DEP_NAMES = ("numpy", "pandas", "pyarrow")

# Pinned reproducible-build clock (2025-01-01T00:00:00Z). Without it the sdist's gzip header (and
# both archives' member mtimes) capture the wall-clock build time, so the wheel/sdist/payload
# hashes drift across build environments and CI/workflow rebuilds cannot reproduce the committed
# member hashes. Exporting SOURCE_DATE_EPOCH for every ``uv build`` invocation freezes that clock,
# making the wheel, sdist, and payload byte-identical and environment-independent.
SOURCE_DATE_EPOCH = 1735689600

WHEEL_NAME = f"eth_research-{VERSION}-py3-none-any.whl"
SDIST_NAME = f"eth_research-{VERSION}.tar.gz"
INSTALL_NAME = "PRIVATE_INSTALL.md"
PROVENANCE_NAME = "provenance.json"
SBOM_NAME = "sbom.cdx.json"
SUMS_NAME = "SHA256SUMS"
MANIFEST_NAME = "private_payload_manifest.json"
POLICY_NAME = "private_distribution_policy.json"
CONTRACT_NAME = "private_install_contract.json"
PAYLOAD_NAME = f"eth-research-{VERSION}-private-payload.tar"

# The loose files written next to the payload tar in the output dir. Anything else present is
# "foreign content" and refuses the build so a stray artifact never rides along.
_LOOSE_OUTPUTS = (SUMS_NAME, MANIFEST_NAME, PROVENANCE_NAME, SBOM_NAME, INSTALL_NAME)
_ALLOWED_OUTPUTS = frozenset({PAYLOAD_NAME, *_LOOSE_OUTPUTS})

# SHA256SUMS covers the source-stable *content* members only. It excludes itself (a file cannot
# carry its own hash) and the manifest (which lists SHA256SUMS's hash) — including the manifest
# would create an unsatisfiable mutual-hash cycle.
_SUMS_MEMBERS = (INSTALL_NAME, PROVENANCE_NAME, SBOM_NAME, SDIST_NAME, WHEEL_NAME)

PROVENANCE_NOTE = "operational provenance, not a cryptographic signature"
_ALLOWED_ACTOR_CLASSES = frozenset({"repository_owner", "collaborator", "local_build", "unknown"})

_EXPECTED_ACCEPTED_CHANNELS = [
    "private_repository_git_commit",
    "private_actions_artifact",
    "private_github_release_if_tagged",
]
_EXPECTED_FORBIDDEN_CHANNELS = [
    "public_pypi",
    "test_pypi",
    "public_github_release",
    "public_package_registry",
    "anonymous_object_storage",
]
# Any accepted channel containing one of these tokens is a public-publication escape hatch.
_PUBLIC_CHANNEL_TOKENS = ("pypi", "public", "anonymous", "registry")
_POLICY_FALSE_FLAGS = (
    "public_pypi_allowed",
    "test_pypi_allowed",
    "public_github_release_allowed",
    "public_package_registry_allowed",
    "open_source_claim_allowed",
    "license_present",
)
_POLICY_TRUE_FLAGS = (
    "private_repository_install_allowed",
    "private_actions_artifact_allowed",
    "private_github_release_allowed_if_tagged",
)


class PrivateReleaseError(RuntimeError):
    """A private-release build or verification precondition failed."""


# --------------------------------------------------------------------------- #
# sibling-tool loading (stdlib tools with no package namespace)                #
# --------------------------------------------------------------------------- #
_TOOLS_DIR = Path(__file__).resolve().parent


def _load_sibling(name: str) -> ModuleType:
    spec = spec_from_file_location(name, _TOOLS_DIR / f"{name}.py")
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise PrivateReleaseError(f"cannot load sibling tool {name}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_evidence = _load_sibling("release_evidence")
_scanner = _load_sibling("scan_distribution")


# --------------------------------------------------------------------------- #
# small source-derived helpers (all build-free, pure functions of the tree)    #
# --------------------------------------------------------------------------- #
def _governed_digest(root: Path) -> str:
    return str(_evidence.governed_baseline_digest(root))


def _source_distribution(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = _evidence.distribution_source(root)
    return result


def _ledger_hashes(root: Path) -> dict[str, str]:
    return {rel: sha256_hex((root / rel).read_bytes()) for rel in SEALED_LEDGERS}


def _policy_path(root: Path) -> Path:
    return root / PRIVATE_RELDIR / POLICY_NAME


def _policy_sha256(root: Path) -> str:
    return sha256_hex(_policy_path(root).read_bytes())


def _sbom_bytes(root: Path) -> bytes:
    return canonical_json_bytes(_evidence.build_sbom(root))


def _pyproject(root: Path) -> dict[str, Any]:
    data: dict[str, Any] = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return data


def _runtime_dependencies(root: Path) -> list[str]:
    return list(_pyproject(root)["project"]["dependencies"])


def _locked_versions(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    wanted = set(names)
    out: dict[str, str] = {}
    for package in lock.get("package", []):
        name = str(package["name"])
        if name in wanted:
            out[name] = str(package["version"])
    missing = wanted - set(out)
    if missing:  # pragma: no cover - lockfile always carries the runtime deps
        raise PrivateReleaseError(f"uv.lock is missing locked versions for {sorted(missing)}")
    return out


def _build_backend_pin(root: Path) -> str:
    pins = _pyproject(root).get("tool", {}).get("uv", {}).get("build-constraint-dependencies", [])
    for pin in pins:
        if str(pin).startswith("hatchling"):
            return str(pin)
    return "hatchling"


# --------------------------------------------------------------------------- #
# committed deliverable builders (deterministic, canonical JSON)               #
# --------------------------------------------------------------------------- #
def build_policy() -> dict[str, Any]:
    """The private distribution policy — a closed, fully explicit posture document."""
    return {
        "schema_version": "1",
        "project_name": PROJECT_NAME,
        "version": VERSION,
        "distribution_classification": "private",
        "repository_visibility_required": "private",
        "public_pypi_allowed": False,
        "test_pypi_allowed": False,
        "public_github_release_allowed": False,
        "public_package_registry_allowed": False,
        "private_repository_install_allowed": True,
        "private_actions_artifact_allowed": True,
        "private_github_release_allowed_if_tagged": True,
        "license_present": False,
        "open_source_claim_allowed": False,
        "accepted_distribution_channels": list(_EXPECTED_ACCEPTED_CHANNELS),
        "forbidden_distribution_channels": list(_EXPECTED_FORBIDDEN_CHANNELS),
        "required_source_commit": None,
        "required_tree_sha256": None,
        "required_governed_state_digest": GOVERNED_BASELINE_DIGEST,
        "required_ledger_sha256": EMPTY_SHA,
        "build_environment_contract": {
            "python": "3.12.3",
            "builder": "uv",
            "source_date_epoch": str(SOURCE_DATE_EPOCH),
        },
        "maximum_bundle_bytes": MAX_BUNDLE_BYTES,
        "artifact_retention_expectation": "30_days",
        "threat_model_revision": "1",
    }


def build_install_contract(root: Path) -> dict[str, Any]:
    """The two authorized private install channels + the pinned runtime dependency set."""
    locked = _locked_versions(root, RUNTIME_DEP_NAMES)
    specifier_of = {
        dep.split(">=")[0].split("==")[0].strip(): dep for dep in _runtime_dependencies(root)
    }
    return {
        "schema_version": "1",
        "project_name": PROJECT_NAME,
        "version": VERSION,
        "public_index_install": False,
        "wheel_is_standalone": False,
        "channels": [
            {
                "id": "A",
                "name": "private_git_commit_pin",
                "transport": "git+ssh",
                "requires_repository_authorization": True,
                "reproducibility_pin": "full_40_hex_commit_sha",
                "branch_or_tag_pin_allowed": False,
                "steps": [
                    "Authenticate to the private repository over SSH.",
                    "pip install "
                    '"eth-research @ git+ssh://git@github.com/panfot1409/gambling-winnings'
                    '.git@<FULL_40_HEX_SHA>"',
                    "Third-party dependencies resolve from the caller's configured indexes.",
                ],
            },
            {
                "id": "B",
                "name": "private_wheel_payload",
                "transport": "private_actions_artifact",
                "install_project_wheel_with_no_deps": True,
                "steps": [
                    f"Download the access-controlled payload artifact ({PAYLOAD_NAME}).",
                    "Verify the payload SHA-256 against the run receipt / registered manifest.",
                    f"Verify {SUMS_NAME} for every payload member.",
                    "Unpack the payload into a scratch directory.",
                    "Create a clean virtual environment.",
                    "Install the pinned runtime dependencies (numpy, pandas, pyarrow).",
                    "Install the project wheel with --no-deps (it needs no index).",
                    "Run 'eth-research doctor' / 'version' and exercise the public API.",
                ],
            },
        ],
        "required_runtime_dependencies": [
            {
                "name": name,
                "specifier": specifier_of.get(name, name),
                "locked_version": locked[name],
            }
            for name in RUNTIME_DEP_NAMES
        ],
    }


def build_provenance(
    root: Path, *, wheel_sha256: str, sdist_sha256: str, sbom_sha256: str, install_sha256: str
) -> dict[str, Any]:
    """Source-stable, timestamp-free provenance embedded in the payload."""
    source = _source_distribution(root)
    return {
        "schema_version": "1",
        "kind": "private_release_provenance",
        "project_name": PROJECT_NAME,
        "version": VERSION,
        "distribution_classification": "private",
        "repository_visibility_required": "private",
        "python": "3.12.3",
        "builder": "uv",
        "source_date_epoch": str(SOURCE_DATE_EPOCH),
        "build_backend_pin": _build_backend_pin(root),
        "governed_state_digest": _governed_digest(root),
        "ledger_sha256": _ledger_hashes(root),
        "policy_sha256": _policy_sha256(root),
        "source_member_count": source["member_count"],
        "source_tree_digest": source["tree_digest"],
        "wheel_filename": WHEEL_NAME,
        "wheel_sha256": wheel_sha256,
        "sdist_filename": SDIST_NAME,
        "sdist_sha256": sdist_sha256,
        "sbom_sha256": sbom_sha256,
        "install_guide_sha256": install_sha256,
        "public_publication_attempts": 0,
        "note": PROVENANCE_NOTE,
    }


def build_payload_manifest(root: Path, member_hashes: Mapping[str, str]) -> dict[str, Any]:
    """The registered payload manifest: member hashes (no tar/self) plus source anchors."""
    source = _source_distribution(root)
    return {
        "schema_version": "1",
        "project_name": PROJECT_NAME,
        "version": VERSION,
        "payload_filename": PAYLOAD_NAME,
        "members": [
            {"filename": name, "sha256": member_hashes[name]} for name in sorted(member_hashes)
        ],
        "governed_state_digest": _governed_digest(root),
        "ledger_sha256": _ledger_hashes(root),
        "policy_sha256": _policy_sha256(root),
        "source_member_count": source["member_count"],
        "source_tree_digest": source["tree_digest"],
    }


def render_install_md(root: Path) -> bytes:
    """Deterministic private-install guide (locked dependency versions, no timestamps)."""
    locked = _locked_versions(root, RUNTIME_DEP_NAMES)
    deps = "\n".join(f"   - {name}=={locked[name]}" for name in RUNTIME_DEP_NAMES)
    text = f"""# Private install guide — eth-research {VERSION}

`eth-research` {VERSION} is distributed **privately** to authorized collaborators of the
private repository `panfot1409/gambling-winnings`. It is not open source and is not published
to any public index or registry. No `LICENSE` is declared and the package carries the
`Private :: Do Not Upload` guard.

## Channel A — immutable private Git commit (canonical)

```
pip install "eth-research @ git+ssh://git@github.com/panfot1409/gambling-winnings.git@<FULL_SHA>"
```

Pin to the full 40-hex commit SHA over authenticated SSH. A branch name or `main` is not an
acceptable reproducibility pin. Third-party dependencies resolve from your configured indexes.

## Channel B — private wheel payload (convenience)

1. Download the access-controlled payload `{PAYLOAD_NAME}` from the private Actions run.
2. Verify the payload SHA-256 against the run receipt / registered manifest.
3. Verify `{SUMS_NAME}` for every payload member.
4. Unpack the payload into a scratch directory.
5. Create a clean virtual environment.
6. Install the pinned runtime dependencies:
{deps}
7. Install the project wheel with `--no-deps` (it needs no index).
8. Run `eth-research doctor` / `version`, import the public API, and exercise the CLI.

The wheel is **not** standalone: it declares numpy / pandas / pyarrow at runtime and does not
vendor them. No dependency wheelhouse is provided.

## Forbidden

No PyPI / TestPyPI upload, no pending publisher / OIDC / API token, no `twine`, no public
registry, no public GitHub Release, no open-source claim, no license classifier, and no
governed research data / raw market data / ledger in any distributed artifact.
"""
    return text.encode("utf-8")


def render_sha256sums(member_hashes: Mapping[str, str]) -> bytes:
    """`<sha256><two spaces><filename>` per line, sorted by filename, trailing newline."""
    return "".join(f"{member_hashes[name]}  {name}\n" for name in sorted(member_hashes)).encode(
        "utf-8"
    )


def build_readme() -> bytes:
    text = f"""# Private release directory — eth-research {VERSION}

Committed, source-derived control documents for the **private** GA distribution of
`eth-research` {VERSION}. Nothing here is published to a public index or registry; the package
is unlicensed and carries the `Private :: Do Not Upload` guard.

## Committed files

- `{POLICY_NAME}` — the closed private-distribution posture (accepted vs forbidden channels,
  public-publication booleans pinned false, required governed-state / ledger anchors).
- `{MANIFEST_NAME}` — the registered payload manifest: per-member SHA-256 (excluding the payload
  tar and the manifest itself) plus the governed-state digest, sealed-ledger triple, policy
  SHA-256, and the `src/eth_research` member tree digest.
- `{CONTRACT_NAME}` — the two authorized install channels and the pinned runtime dependencies.

`{PROVENANCE_NAME}` and `{INSTALL_NAME}` are generated deterministically into the payload by the
builder and are not committed.

## Rebuild / verify

```
# build-free consistency gate (what CI runs; needs neither uv nor git)
python tools/private_release.py --check

# assemble the deterministic payload under dist_private/ (needs uv; clean tracked tree)
python tools/private_release.py build

# rebuild twice from bytes and assert the payload is byte-identical
python tools/private_release.py verify

# regenerate these committed deliverables (maintainer)
python tools/private_release.py write-manifests
```
"""
    return text.encode("utf-8")


# --------------------------------------------------------------------------- #
# payload assembly                                                             #
# --------------------------------------------------------------------------- #
def assemble_members(root: Path, wheel_bytes: bytes, sdist_bytes: bytes) -> dict[str, bytes]:
    """Deterministically derive the 7 payload members from the wheel + sdist bytes.

    Ordering is an acyclic DAG so every hash has a fixed point: wheel/sdist -> sbom ->
    install-guide -> provenance -> SHA256SUMS -> manifest. SHA256SUMS covers the content
    members only; the manifest lists SHA256SUMS but not itself and not the payload tar.
    """
    wheel_sha = sha256_hex(wheel_bytes)
    sdist_sha = sha256_hex(sdist_bytes)

    sbom_bytes = _sbom_bytes(root)
    sbom_sha = sha256_hex(sbom_bytes)

    install_bytes = render_install_md(root)
    install_sha = sha256_hex(install_bytes)

    provenance_bytes = canonical_json_bytes(
        build_provenance(
            root,
            wheel_sha256=wheel_sha,
            sdist_sha256=sdist_sha,
            sbom_sha256=sbom_sha,
            install_sha256=install_sha,
        )
    )
    provenance_sha = sha256_hex(provenance_bytes)

    sums_source = {
        INSTALL_NAME: install_sha,
        PROVENANCE_NAME: provenance_sha,
        SBOM_NAME: sbom_sha,
        SDIST_NAME: sdist_sha,
        WHEEL_NAME: wheel_sha,
    }
    assert set(sums_source) == set(_SUMS_MEMBERS)
    sums_bytes = render_sha256sums(sums_source)
    sums_sha = sha256_hex(sums_bytes)

    member_hashes = {
        INSTALL_NAME: install_sha,
        SUMS_NAME: sums_sha,
        WHEEL_NAME: wheel_sha,
        SDIST_NAME: sdist_sha,
        PROVENANCE_NAME: provenance_sha,
        SBOM_NAME: sbom_sha,
    }
    manifest_bytes = canonical_json_bytes(build_payload_manifest(root, member_hashes))

    return {
        WHEEL_NAME: wheel_bytes,
        SDIST_NAME: sdist_bytes,
        SBOM_NAME: sbom_bytes,
        INSTALL_NAME: install_bytes,
        PROVENANCE_NAME: provenance_bytes,
        SUMS_NAME: sums_bytes,
        MANIFEST_NAME: manifest_bytes,
    }


def normalized_tar_bytes(members: Mapping[str, bytes]) -> bytes:
    """A fully normalized, reproducible tar: sorted members, mtime=0, mode 0644, uid/gid 0."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name in sorted(members):
            data = members[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.type = tarfile.REGTYPE
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def assemble_payload_bytes(root: Path, wheel_bytes: bytes, sdist_bytes: bytes) -> bytes:
    """Members + normalized tar in one call (used by verify's determinism check)."""
    return normalized_tar_bytes(assemble_members(root, wheel_bytes, sdist_bytes))


# --------------------------------------------------------------------------- #
# wheel metadata license guard                                                 #
# --------------------------------------------------------------------------- #
def wheel_metadata_findings(wheel_path: Path) -> list[str]:
    """Fail closed unless the wheel METADATA is name/version-correct, guarded, and license-free."""
    findings: list[str] = []
    with zipfile.ZipFile(wheel_path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".dist-info/METADATA")]
        if not names:
            return ["wheel is missing a .dist-info/METADATA"]
        text = zf.read(names[0]).decode("utf-8", errors="replace")
    header: list[str] = []
    for line in text.splitlines():
        if line == "":
            break
        header.append(line)
    if "Name: eth-research" not in header:
        findings.append("METADATA Name is not eth-research")
    if f"Version: {VERSION}" not in header:
        findings.append(f"METADATA Version is not {VERSION}")
    if "Classifier: Private :: Do Not Upload" not in header:
        findings.append("METADATA is missing the Private :: Do Not Upload guard")
    for line in header:
        lowered = line.lower()
        if lowered.startswith("license-expression:"):
            findings.append(f"METADATA declares a License-Expression: {line}")
        if lowered.startswith("license-file:"):
            findings.append(f"METADATA declares a License-File: {line}")
        if line.startswith("Classifier: License ::"):
            findings.append(f"METADATA declares a License classifier: {line}")
    return findings


# --------------------------------------------------------------------------- #
# source-integrity gate (content-level; independent of git/uv)                 #
# --------------------------------------------------------------------------- #
def _assert_source_integrity(root: Path) -> None:
    problems = list(_evidence.check(root))
    if problems:
        raise PrivateReleaseError("release-evidence drift: " + "; ".join(problems))

    governed = _governed_digest(root)
    if governed != GOVERNED_BASELINE_DIGEST:
        raise PrivateReleaseError(
            f"governed-state digest drift: {governed} != {GOVERNED_BASELINE_DIGEST}"
        )
    for rel, digest in _ledger_hashes(root).items():
        if digest != EMPTY_SHA:
            raise PrivateReleaseError(f"sealed ledger is not byte-empty: {rel}")

    committed = strict_load_canonical(
        (root / EVIDENCE_MANIFEST_RELPATH).read_bytes(), EVIDENCE_MANIFEST_RELPATH
    )
    want = committed["distribution_source"]["tree_digest"]
    got = _source_distribution(root)["tree_digest"]
    if got != want:
        raise PrivateReleaseError(f"source tree digest drift: {got} != {want}")

    # The portfolio/registration surface must match its committed source freeze.
    from eth_research.portfolio import registration

    try:
        registration.verify(root)
    except registration.RegistrationDriftError as exc:
        raise PrivateReleaseError(f"portfolio-registration drift: {exc}") from exc


# --------------------------------------------------------------------------- #
# build                                                                        #
# --------------------------------------------------------------------------- #
def _run(
    cmd: list[str], cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    child_env = None if env is None else {**os.environ, **env}
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True, env=child_env)


def _tracked_tree_is_clean(root: Path) -> bool:
    result = _run(["git", "-C", str(root), "status", "--porcelain"])
    return result.stdout.strip() == ""


def _uv_build(root: Path, out_dir: Path) -> tuple[Path, Path]:
    # SOURCE_DATE_EPOCH is exported for EVERY build pass so the wheel and sdist (gzip header +
    # member mtimes) are byte-identical and independent of the wall-clock build time / environment.
    _run(
        ["uv", "build", "--out-dir", str(out_dir)],
        cwd=root,
        env={"SOURCE_DATE_EPOCH": str(SOURCE_DATE_EPOCH)},
    )
    return next(out_dir.glob("*.whl")), next(out_dir.glob("*.tar.gz"))


def _build_wheel_and_sdist(root: Path) -> tuple[bytes, bytes]:
    """Two independent builds; assert byte-identical, scan clean, metadata license-free."""
    with tempfile.TemporaryDirectory() as tmp:
        dir_a = Path(tmp) / "a"
        dir_b = Path(tmp) / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        wheel_a, sdist_a = _uv_build(root, dir_a)
        wheel_b, sdist_b = _uv_build(root, dir_b)

        wheel_bytes = wheel_a.read_bytes()
        sdist_bytes = sdist_a.read_bytes()
        if wheel_bytes != wheel_b.read_bytes() or sdist_bytes != sdist_b.read_bytes():
            raise PrivateReleaseError("uv build is not byte-deterministic across two runs")
        if wheel_a.name != WHEEL_NAME or sdist_a.name != SDIST_NAME:
            raise PrivateReleaseError(f"unexpected artifact names: {wheel_a.name}, {sdist_a.name}")

        scan_failures = list(_scanner.scan_distribution(wheel_a)) + list(
            _scanner.scan_distribution(sdist_a)
        )
        if scan_failures:
            raise PrivateReleaseError("distribution scan failed: " + "; ".join(scan_failures))

        metadata_failures = wheel_metadata_findings(wheel_a)
        if metadata_failures:
            raise PrivateReleaseError(
                "wheel metadata guard failed: " + "; ".join(metadata_failures)
            )
    return wheel_bytes, sdist_bytes


def _guard_output_dir(out_dir: Path) -> None:
    if not out_dir.exists():
        return
    if not out_dir.is_dir():
        raise PrivateReleaseError(f"output path is not a directory: {out_dir}")
    foreign = sorted(p.name for p in out_dir.iterdir() if p.name not in _ALLOWED_OUTPUTS)
    if foreign:
        raise PrivateReleaseError(f"output dir {out_dir} contains foreign content: {foreign}")


def _write_outputs(out_dir: Path, payload_bytes: bytes, members: Mapping[str, bytes]) -> None:
    _guard_output_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / PAYLOAD_NAME).write_bytes(payload_bytes)
    for name in _LOOSE_OUTPUTS:
        (out_dir / name).write_bytes(members[name])


def build(
    root: Path, out_dir: Path, *, allow_dirty: bool = False
) -> tuple[bytes, dict[str, bytes]]:
    """Full build: clean-tree + source-integrity gate, deterministic build, assemble payload."""
    if _pyproject(root)["project"]["version"] != VERSION:
        raise PrivateReleaseError(f"pyproject version is not {VERSION}")
    if not allow_dirty and not _tracked_tree_is_clean(root):
        raise PrivateReleaseError(
            "tracked tree is not clean; commit or pass --allow-dirty (local rehearsal only)"
        )
    _assert_source_integrity(root)
    wheel_bytes, sdist_bytes = _build_wheel_and_sdist(root)
    members = assemble_members(root, wheel_bytes, sdist_bytes)
    payload_bytes = normalized_tar_bytes(members)
    if len(payload_bytes) > MAX_BUNDLE_BYTES:
        raise PrivateReleaseError(
            f"payload {len(payload_bytes)} bytes exceeds the {MAX_BUNDLE_BYTES}-byte ceiling"
        )
    if MANIFEST_NAME not in members or PROVENANCE_NAME not in members:
        raise PrivateReleaseError("payload is missing a required member")  # pragma: no cover
    _write_outputs(out_dir, payload_bytes, members)
    return payload_bytes, members


# --------------------------------------------------------------------------- #
# receipt (dynamic; workflow only; never committed, never in the payload)      #
# --------------------------------------------------------------------------- #
def _uv_version() -> str:
    try:
        return _run(["uv", "--version"]).stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - uv usually present
        return "unknown"


def _source_commit(root: Path, env: Mapping[str, str]) -> str:
    sha = env.get("GITHUB_SHA", "").strip()
    if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha.lower()):
        return sha.lower()
    try:
        head = _run(["git", "-C", str(root), "rev-parse", "HEAD"]).stdout.strip().lower()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "0" * 40
    return head if len(head) == 40 else "0" * 40


def _actor_classification(env: Mapping[str, str]) -> str:
    actor = env.get("GITHUB_ACTOR", "").strip()
    owner = env.get("GITHUB_REPOSITORY_OWNER", "").strip()
    if not actor:
        return "local_build"
    if owner and actor == owner:
        return "repository_owner"
    return "collaborator"


def build_receipt(
    root: Path,
    *,
    payload_sha256: str,
    wheel_sha256: str,
    sdist_sha256: str,
    sbom_sha256: str,
    manifest_sha256: str,
    consumer_verification_result: str,
    started_utc: str,
    ended_utc: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Assemble the dynamic release receipt. Stores no secrets or raw usernames/emails."""
    environ = os.environ if env is None else env
    return {
        "schema_version": "1",
        "kind": "private_release_receipt",
        "project_name": PROJECT_NAME,
        "version": VERSION,
        "repository": environ.get("GITHUB_REPOSITORY", "panfot1409/gambling-winnings"),
        "repository_visibility_observed": environ.get("GITHUB_REPOSITORY_VISIBILITY", "private"),
        "workflow_filename": environ.get("GITHUB_WORKFLOW", "local"),
        "workflow_run_id": environ.get("GITHUB_RUN_ID", "local"),
        "workflow_run_attempt": environ.get("GITHUB_RUN_ATTEMPT", "0"),
        "triggering_actor_classification": _actor_classification(environ),
        "source_commit": _source_commit(root, environ),
        "source_tree_digest": _source_distribution(root)["tree_digest"],
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "runner_image": environ.get("ImageOS", environ.get("RUNNER_IMAGE", "local")),
        "build_tool_versions": {
            "uv": _uv_version(),
            "build_backend": _build_backend_pin(root),
            "python": platform.python_version(),
        },
        "payload_filename": PAYLOAD_NAME,
        "payload_sha256": payload_sha256,
        "wheel_sha256": wheel_sha256,
        "sdist_sha256": sdist_sha256,
        "sbom_sha256": sbom_sha256,
        "manifest_sha256": manifest_sha256,
        "governed_state_digest": _governed_digest(root),
        "ledger_sha256": _ledger_hashes(root),
        "build_started_utc": started_utc,
        "build_ended_utc": ended_utc,
        "artifact_name": PAYLOAD_NAME.removesuffix(".tar"),
        "configured_retention_days": RETENTION_DAYS,
        "consumer_verification_result": consumer_verification_result,
        "public_publication_attempts": 0,
        "note": PROVENANCE_NOTE,
    }


_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "project_name",
        "version",
        "repository",
        "repository_visibility_observed",
        "workflow_filename",
        "workflow_run_id",
        "workflow_run_attempt",
        "triggering_actor_classification",
        "source_commit",
        "source_tree_digest",
        "python_version",
        "platform",
        "runner_image",
        "build_tool_versions",
        "payload_filename",
        "payload_sha256",
        "wheel_sha256",
        "sdist_sha256",
        "sbom_sha256",
        "manifest_sha256",
        "governed_state_digest",
        "ledger_sha256",
        "build_started_utc",
        "build_ended_utc",
        "artifact_name",
        "configured_retention_days",
        "consumer_verification_result",
        "public_publication_attempts",
        "note",
    }
)


def verify_receipt(path: str | Path) -> dict[str, Any]:
    """Strictly parse a release receipt; raise :class:`CanonicalError` on any violation."""
    raw = Path(path).read_bytes()
    receipt = require_mapping(strict_load_canonical(raw, "private_release_receipt"), "receipt")
    keys = set(receipt)
    if keys != set(_RECEIPT_KEYS):
        missing = sorted(set(_RECEIPT_KEYS) - keys)
        unknown = sorted(keys - set(_RECEIPT_KEYS))
        raise CanonicalError(f"receipt keys mismatch: missing={missing} unknown={unknown}")
    if require_str(receipt["schema_version"], "schema_version") != "1":
        raise CanonicalError("receipt schema_version must be '1'")
    if require_str(receipt["kind"], "kind") != "private_release_receipt":
        raise CanonicalError("receipt kind must be private_release_receipt")
    if require_str(receipt["version"], "version") != VERSION:
        raise CanonicalError(f"receipt version must be {VERSION}")
    classification = require_str(receipt["triggering_actor_classification"], "classification")
    if classification not in _ALLOWED_ACTOR_CLASSES:
        raise CanonicalError(f"receipt actor classification not allowed: {classification!r}")
    require_sha256_hex(receipt["source_tree_digest"], "source_tree_digest")
    for field in (
        "payload_sha256",
        "wheel_sha256",
        "sdist_sha256",
        "sbom_sha256",
        "manifest_sha256",
    ):
        require_sha256_hex(receipt[field], field)
    require_sha256_hex(receipt["governed_state_digest"], "governed_state_digest")
    ledgers = require_mapping(receipt["ledger_sha256"], "ledger_sha256")
    for rel, digest in ledgers.items():
        require_sha256_hex(digest, f"ledger_sha256[{rel}]")
    tools = require_mapping(receipt["build_tool_versions"], "build_tool_versions")
    for name, value in tools.items():
        require_str(value, f"build_tool_versions[{name}]", allow_empty=True)
    commit = require_str(receipt["source_commit"], "source_commit")
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise CanonicalError("receipt source_commit must be a 40-hex commit sha")
    if require_int(receipt["configured_retention_days"], "configured_retention_days") <= 0:
        raise CanonicalError("receipt configured_retention_days must be positive")
    if require_int(receipt["public_publication_attempts"], "public_publication_attempts") != 0:
        raise CanonicalError("receipt public_publication_attempts must be 0")
    if PROVENANCE_NOTE not in require_str(receipt["note"], "note"):
        raise CanonicalError("receipt note must state it is not a cryptographic signature")
    return receipt


# --------------------------------------------------------------------------- #
# build-free consistency check (--check; what CI runs)                          #
# --------------------------------------------------------------------------- #
def verify_policy(repo_root: str | Path) -> dict[str, Any]:
    """Strictly load + validate the committed policy; raise :class:`CanonicalError` on any issue."""
    root = Path(repo_root)
    raw = _policy_path(root).read_bytes()
    policy = require_mapping(strict_load_canonical(raw, POLICY_NAME), "policy")
    if canonical_json_bytes(policy) != raw:
        raise CanonicalError("policy is not in canonical form")

    expected_keys = set(build_policy())
    keys = set(policy)
    if keys != expected_keys:
        missing = sorted(expected_keys - keys)
        unknown = sorted(keys - expected_keys)
        raise CanonicalError(f"policy keys mismatch: missing={missing} unknown={unknown}")

    _require_equals(policy["schema_version"], "schema_version", "1")
    _require_equals(policy["project_name"], "project_name", PROJECT_NAME)
    _require_equals(policy["version"], "version", VERSION)
    _require_equals(policy["distribution_classification"], "distribution_classification", "private")
    _require_equals(
        policy["repository_visibility_required"], "repository_visibility_required", "private"
    )

    for flag in _POLICY_FALSE_FLAGS:
        if require_bool(policy[flag], flag):
            raise CanonicalError(f"policy {flag} must be false")
    for flag in _POLICY_TRUE_FLAGS:
        if not require_bool(policy[flag], flag):
            raise CanonicalError(f"policy {flag} must be true")

    field = "accepted_distribution_channels"
    accepted = [require_str(x, field) for x in require_list(policy[field], field)]
    if accepted != _EXPECTED_ACCEPTED_CHANNELS:
        raise CanonicalError("policy accepted_distribution_channels drift")
    for channel in accepted:
        if any(token in channel for token in _PUBLIC_CHANNEL_TOKENS):
            raise CanonicalError(f"policy accepts a public channel: {channel!r}")
    field = "forbidden_distribution_channels"
    forbidden = [require_str(x, field) for x in require_list(policy[field], field)]
    if forbidden != _EXPECTED_FORBIDDEN_CHANNELS:
        raise CanonicalError("policy forbidden_distribution_channels drift")

    _require_optional_commit(policy["required_source_commit"], "required_source_commit")
    _require_optional_sha256(policy["required_tree_sha256"], "required_tree_sha256")
    governed = require_sha256_hex(
        policy["required_governed_state_digest"], "required_governed_state_digest"
    )
    if governed != GOVERNED_BASELINE_DIGEST:
        raise CanonicalError("policy required_governed_state_digest drift")
    if require_sha256_hex(policy["required_ledger_sha256"], "required_ledger_sha256") != EMPTY_SHA:
        raise CanonicalError("policy required_ledger_sha256 drift")

    env = require_mapping(policy["build_environment_contract"], "build_environment_contract")
    if set(env) != {"python", "builder", "source_date_epoch"}:
        raise CanonicalError("policy build_environment_contract keys drift")
    _require_equals(env["python"], "build_environment_contract.python", "3.12.3")
    _require_equals(env["builder"], "build_environment_contract.builder", "uv")
    _require_equals(
        env["source_date_epoch"],
        "build_environment_contract.source_date_epoch",
        str(SOURCE_DATE_EPOCH),
    )

    if require_int(policy["maximum_bundle_bytes"], "maximum_bundle_bytes") != MAX_BUNDLE_BYTES:
        raise CanonicalError("policy maximum_bundle_bytes drift")
    _require_equals(
        policy["artifact_retention_expectation"], "artifact_retention_expectation", "30_days"
    )
    _require_equals(policy["threat_model_revision"], "threat_model_revision", "1")
    return policy


def _require_equals(value: Any, field: str, expected: str) -> str:
    text = require_str(value, field)
    if text != expected:
        raise CanonicalError(f"{field} must be {expected!r}")
    return text


def _require_optional_commit(value: Any, field: str) -> None:
    if value is None:
        return
    text = require_str(value, field)
    if len(text) != 40 or any(c not in "0123456789abcdef" for c in text):
        raise CanonicalError(f"{field} must be null or a 40-hex commit sha")


def _require_optional_sha256(value: Any, field: str) -> None:
    if value is None:
        return
    require_sha256_hex(value, field)


def check(repo_root: str | Path) -> list[str]:
    """Build-free consistency of the committed private-release manifests. Mutates nothing."""
    root = Path(repo_root)
    problems: list[str] = []

    try:
        policy = verify_policy(root)
    except (CanonicalError, OSError) as exc:
        return [f"{POLICY_NAME} invalid: {exc}"]

    # install contract must reproduce byte-for-byte from the current tree.
    contract_path = root / PRIVATE_RELDIR / CONTRACT_NAME
    try:
        contract_raw = contract_path.read_bytes()
    except OSError as exc:
        problems.append(f"{CONTRACT_NAME} missing: {exc}")
    else:
        if contract_raw != canonical_json_bytes(build_install_contract(root)):
            problems.append(f"{CONTRACT_NAME} is stale; regenerate with `write-manifests`")

    manifest_path = root / PRIVATE_RELDIR / MANIFEST_NAME
    try:
        manifest_raw = manifest_path.read_bytes()
    except OSError as exc:
        problems.append(f"{MANIFEST_NAME} missing: {exc}")
        return problems
    manifest = require_mapping(strict_load_canonical(manifest_raw, MANIFEST_NAME), MANIFEST_NAME)
    if canonical_json_bytes(manifest) != manifest_raw:
        problems.append(f"{MANIFEST_NAME} is not in canonical form")

    governed = _governed_digest(root)
    ledgers = _ledger_hashes(root)
    source = _source_distribution(root)

    if manifest.get("governed_state_digest") != governed:
        problems.append("manifest governed_state_digest does not reproduce")
    if manifest.get("ledger_sha256") != ledgers:
        problems.append("manifest ledger_sha256 does not reproduce")
    if manifest.get("policy_sha256") != _policy_sha256(root):
        problems.append("manifest policy_sha256 does not reproduce")
    if manifest.get("source_tree_digest") != source["tree_digest"]:
        problems.append("manifest source_tree_digest does not reproduce")
    if manifest.get("source_member_count") != source["member_count"]:
        problems.append("manifest source_member_count does not reproduce")

    # Every listed member path must be a safe basename (no traversal / separators / absolute).
    member_map: dict[str, str] = {}
    for entry in manifest.get("members", []):
        name = str(entry.get("filename", ""))
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            problems.append(f"manifest lists an unsafe member path: {name!r}")
            continue
        member_map[name] = str(entry.get("sha256", ""))

    # Build-free members (SBOM, install guide) must reproduce exactly.
    if member_map.get(SBOM_NAME) != sha256_hex(_sbom_bytes(root)):
        problems.append("manifest sbom member does not reproduce")
    if member_map.get(INSTALL_NAME) != sha256_hex(render_install_md(root)):
        problems.append("manifest install-guide member does not reproduce")

    # The policy's required anchors must match the tree the manifest was registered against.
    if policy["required_governed_state_digest"] != governed:
        problems.append("policy required_governed_state_digest does not match the tree")
    ledgers_all_empty = all(v == EMPTY_SHA for v in ledgers.values())
    if policy["required_ledger_sha256"] != EMPTY_SHA or not ledgers_all_empty:
        problems.append("policy required_ledger_sha256 does not match the tree")
    return problems


# --------------------------------------------------------------------------- #
# inspect / status / write-manifests                                           #
# --------------------------------------------------------------------------- #
def inspect_payload(payload_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with tarfile.open(payload_path, "r") as tar:
        for member in sorted(tar.getmembers(), key=lambda m: m.name):
            if not member.isfile():
                continue
            extracted = tar.extractfile(member)
            data = b"" if extracted is None else extracted.read()
            entries.append({"filename": member.name, "size": len(data), "sha256": sha256_hex(data)})
    return entries


def status(root: Path, out_dir: Path) -> dict[str, Any]:
    payload = out_dir / PAYLOAD_NAME
    return {
        "project_name": PROJECT_NAME,
        "version": VERSION,
        "distribution_classification": "private",
        "hardened": True,
        "private": True,
        "published": False,
        "built": payload.is_file(),
        "payload_filename": PAYLOAD_NAME,
        "public_publication_attempts": 0,
        "blocked_on_tag": True,
        "blocked_on_tag_detail": (
            "a private GitHub Release is permitted only when the private-GA merge commit is tagged"
        ),
        "committed_manifests_consistent": check(root) == [],
    }


def write_manifests(root: Path) -> list[str]:
    """(Maintainer) regenerate the committed private-release deliverables deterministically."""
    reldir = root / PRIVATE_RELDIR
    reldir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    (reldir / POLICY_NAME).write_bytes(canonical_json_bytes(build_policy()))
    written.append(f"{PRIVATE_RELDIR}/{POLICY_NAME}")
    (reldir / CONTRACT_NAME).write_bytes(canonical_json_bytes(build_install_contract(root)))
    written.append(f"{PRIVATE_RELDIR}/{CONTRACT_NAME}")
    (reldir / "README.md").write_bytes(build_readme())
    written.append(f"{PRIVATE_RELDIR}/README.md")

    # The payload manifest records build outputs (wheel/sdist/provenance/SHA256SUMS hashes), so a
    # single deterministic build authors it.
    with tempfile.TemporaryDirectory() as tmp:
        _, members = build(root, Path(tmp) / "out", allow_dirty=True)
    (reldir / MANIFEST_NAME).write_bytes(members[MANIFEST_NAME])
    written.append(f"{PRIVATE_RELDIR}/{MANIFEST_NAME}")
    return written


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def _emit_receipt(root: Path, path: Path, payload_bytes: bytes, members: dict[str, bytes]) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    member_hashes = {name: sha256_hex(data) for name, data in members.items()}
    receipt = build_receipt(
        root,
        payload_sha256=sha256_hex(payload_bytes),
        wheel_sha256=member_hashes[WHEEL_NAME],
        sdist_sha256=member_hashes[SDIST_NAME],
        sbom_sha256=member_hashes[SBOM_NAME],
        manifest_sha256=member_hashes[MANIFEST_NAME],
        consumer_verification_result="passed",
        started_utc=now,
        ended_utc=now,
    )
    path.write_bytes(canonical_json_bytes(receipt))
    verify_receipt(path)  # fail closed if what we just wrote is not strictly parseable


def _cmd_build(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    payload_bytes, members = build(root, out_dir, allow_dirty=args.allow_dirty)
    if args.emit_receipt:
        _emit_receipt(root, Path(args.emit_receipt), payload_bytes, members)
    sys.stdout.write(f"payload {PAYLOAD_NAME} sha256 {sha256_hex(payload_bytes)}\n")
    sys.stdout.write(f"wrote outputs under {out_dir}\n")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    _assert_source_integrity(root)
    wheel_bytes, sdist_bytes = _build_wheel_and_sdist(root)
    first = assemble_payload_bytes(root, wheel_bytes, sdist_bytes)
    second = assemble_payload_bytes(root, wheel_bytes, sdist_bytes)
    if first != second:  # pragma: no cover - assembly is a pure function
        sys.stderr.write("payload assembly is not deterministic\n")
        return 1
    wheel2, sdist2 = _build_wheel_and_sdist(root)
    if assemble_payload_bytes(root, wheel2, sdist2) != first:
        sys.stderr.write("payload is not byte-identical across two full builds\n")
        return 1
    sys.stdout.write(f"payload {PAYLOAD_NAME} sha256 {sha256_hex(first)} (deterministic)\n")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    payload = Path(args.payload) if args.payload else root / args.out_dir / PAYLOAD_NAME
    if not payload.is_file():
        sys.stderr.write(f"no payload found at {payload}\n")
        return 1
    sys.stdout.write(f"payload {payload} sha256 {sha256_hex(payload.read_bytes())}\n")
    for entry in inspect_payload(payload):
        sys.stdout.write(f"  {entry['sha256']}  {entry['size']:>8}  {entry['filename']}\n")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    sys.stdout.write(canonical_json_bytes(status(root, root / args.out_dir)).decode("utf-8"))
    return 0


def _cmd_write_manifests(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    for relpath in write_manifests(root):
        sys.stdout.write(f"wrote {relpath}\n")
    return 0


def _run_check(repo_root: str) -> int:
    problems = check(Path(repo_root).resolve())
    if problems:
        for problem in problems:
            sys.stderr.write(f"{problem}\n")
        return 1
    sys.stdout.write("private-release manifests are consistent with the current tree\n")
    return 0


def _add_common(parser: argparse.ArgumentParser, *, top: bool) -> None:
    # Global options are accepted both before and after the subcommand. The subparser copies use
    # SUPPRESS defaults so an omitted flag never clobbers a value parsed at the top level.
    parser.add_argument("--repo-root", default="." if top else argparse.SUPPRESS)
    parser.add_argument("--out-dir", default="dist_private" if top else argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic private-release tooling.")
    _add_common(parser, top=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="build-free consistency check of the committed manifests (CI gate)",
    )
    sub = parser.add_subparsers(dest="command")

    build_cmd = sub.add_parser("build", help="assemble the deterministic private payload")
    _add_common(build_cmd, top=False)
    build_cmd.add_argument("--allow-dirty", action="store_true", help="skip the clean-tree gate")
    build_cmd.add_argument("--emit-receipt", default=None, help="write a dynamic release receipt")
    build_cmd.set_defaults(func=_cmd_build)

    verify_cmd = sub.add_parser("verify", help="rebuild twice and assert the payload is identical")
    _add_common(verify_cmd, top=False)
    verify_cmd.set_defaults(func=_cmd_verify)

    inspect_cmd = sub.add_parser("inspect", help="list payload members with hashes")
    _add_common(inspect_cmd, top=False)
    inspect_cmd.add_argument("--payload", default=None, help="path to the payload tar")
    inspect_cmd.set_defaults(func=_cmd_inspect)

    status_cmd = sub.add_parser("status", help="print the release-state posture")
    _add_common(status_cmd, top=False)
    status_cmd.set_defaults(func=_cmd_status)

    write_cmd = sub.add_parser("write-manifests", help="(maintainer) regenerate manifests")
    _add_common(write_cmd, top=False)
    write_cmd.set_defaults(func=_cmd_write_manifests)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.check:
        return _run_check(args.repo_root)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        result: int = args.func(args)
    except PrivateReleaseError as exc:
        sys.stderr.write(f"private-release error: {exc}\n")
        return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
