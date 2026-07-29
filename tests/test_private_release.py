"""Tests for the deterministic PRIVATE release tooling (``tools/private_release.py``).

Offline and fast by default: the policy strictness, ``--check`` consistency, manifest
reproduction, member-allowlist, payload-assembly determinism, and receipt strict-parse tests
need neither ``uv`` nor ``git``. The two tests that shell out to ``uv build`` are marked
``slow`` and skip cleanly when ``uv`` is unavailable, so the suite never hard-fails in a
restricted environment.

The tool is loaded via :func:`importlib.util.spec_from_file_location` (the same pattern the
existing packaging/evidence tests use) because ``tools/`` is not an importable package.
"""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from eth_research.api.serialization import CanonicalError, canonical_json_bytes, sha256_hex

REPO = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO / "tools" / "private_release.py"
RELDIR = REPO / "release" / "private" / "v1.1.0"
POLICY_NAME = "private_distribution_policy.json"
MANIFEST_NAME = "private_payload_manifest.json"
CONTRACT_NAME = "private_install_contract.json"
PAYLOAD_MEMBERS = [
    "PRIVATE_INSTALL.md",
    "SHA256SUMS",
    "eth_research-1.1.0-py3-none-any.whl",
    "eth_research-1.1.0.tar.gz",
    "private_payload_manifest.json",
    "provenance.json",
    "sbom.cdx.json",
]

FROZEN_SBOM_PATH = REPO / "release" / "v1.1.0" / "sbom.cdx.json"
#: Byte identities of the frozen v1.1.0 release records this tool verifies against, pinned here as
#: independent regression anchors. They are the same digests the V2A-V2B stack freeze table
#: (``research/v2ab/stack_freeze_table.json``) records as ``immutable`` and the Fable 5 system
#: inventory pins for these paths. No ordinary development change — least of all declaring or
#: upgrading a dependency — may move any of them; if one of these constants ever needs editing, a
#: historical release record has been falsified.
FROZEN_SBOM_SHA256 = "7fd0396afbf4e642d724ea2a90ae3d25d108de5540f472fc1e73eecc11fa2731"
FROZEN_MANIFEST_SHA256 = "d726eabe845bc92726fc0879ba2ac5f1639fe8f09b9831d79ebb7b209fdcac5b"
FROZEN_CONTRACT_SHA256 = "b8db651e26ad517381e5e15d2e9c27a05ecf44a0cd6d808ddf6e9d9021b36d51"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = _load("private_release", TOOL_PATH)
SCANNER = _load("scan_distribution", REPO / "tools" / "scan_distribution.py")


# --------------------------------------------------------------------------- #
# policy strictness                                                            #
# --------------------------------------------------------------------------- #
def _write_policy(tmp_path: Path, raw: bytes) -> Path:
    target = tmp_path / "release" / "private" / "v1.1.0"
    target.mkdir(parents=True, exist_ok=True)
    (target / POLICY_NAME).write_bytes(raw)
    return tmp_path


def _base_policy_bytes() -> bytes:
    return canonical_json_bytes(TOOL.build_policy())


def _bad_unknown_key() -> bytes:
    policy: dict[str, Any] = TOOL.build_policy()
    policy["surprise_channel"] = True
    return canonical_json_bytes(policy)


def _bad_non_bool() -> bytes:
    policy: dict[str, Any] = TOOL.build_policy()
    policy["public_pypi_allowed"] = 0  # an int is not a bool
    return canonical_json_bytes(policy)


def _bad_public_channel() -> bytes:
    policy: dict[str, Any] = TOOL.build_policy()
    policy["accepted_distribution_channels"] = [
        *policy["accepted_distribution_channels"],
        "public_pypi",
    ]
    return canonical_json_bytes(policy)


def _bad_license_present() -> bytes:
    policy: dict[str, Any] = TOOL.build_policy()
    policy["license_present"] = True
    return canonical_json_bytes(policy)


def _bad_public_flag() -> bytes:
    policy: dict[str, Any] = TOOL.build_policy()
    policy["public_pypi_allowed"] = True
    return canonical_json_bytes(policy)


def _bad_version() -> bytes:
    policy: dict[str, Any] = TOOL.build_policy()
    policy["version"] = "1.2.0"
    return canonical_json_bytes(policy)


def _bad_nan() -> bytes:
    # NaN cannot pass canonical serialization, so craft the raw token; the strict decoder rejects.
    return _base_policy_bytes().replace(b"52428800", b"NaN")


def _bad_duplicate_key() -> bytes:
    # A second "license_present" key: the strict decoder rejects duplicates.
    return _base_policy_bytes().replace(
        b'"license_present": false,',
        b'"license_present": false,\n  "license_present": true,',
        1,
    )


@pytest.mark.parametrize(
    "make_bad",
    [
        _bad_unknown_key,
        _bad_non_bool,
        _bad_public_channel,
        _bad_license_present,
        _bad_public_flag,
        _bad_version,
        _bad_nan,
        _bad_duplicate_key,
    ],
)
def test_verify_policy_rejects_tampered_policy(
    make_bad: Callable[[], bytes], tmp_path: Path
) -> None:
    root = _write_policy(tmp_path, make_bad())
    with pytest.raises(CanonicalError):
        TOOL.verify_policy(root)


def test_verify_policy_accepts_committed_policy() -> None:
    policy = TOOL.verify_policy(REPO)
    assert policy["version"] == "1.1.0"
    assert policy["distribution_classification"] == "private"
    assert policy["license_present"] is False
    assert policy["public_pypi_allowed"] is False
    assert policy["test_pypi_allowed"] is False
    assert policy["open_source_claim_allowed"] is False
    assert policy["required_governed_state_digest"] == TOOL.GOVERNED_BASELINE_DIGEST
    # The pinned reproducible-build clock is recorded so CI/workflow rebuilds are deterministic.
    assert policy["build_environment_contract"]["source_date_epoch"] == str(TOOL.SOURCE_DATE_EPOCH)


# --------------------------------------------------------------------------- #
# --check: passes on a clean tree and mutates nothing                          #
# --------------------------------------------------------------------------- #
def _reldir_snapshot() -> dict[str, str]:
    return {p.name: sha256_hex(p.read_bytes()) for p in sorted(RELDIR.iterdir()) if p.is_file()}


def test_check_passes_and_mutates_nothing() -> None:
    before = _reldir_snapshot()
    assert TOOL.check(REPO) == []
    proc = subprocess.run(
        [sys.executable, str(TOOL_PATH), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert _reldir_snapshot() == before


def test_committed_manifest_source_fields_reproduce() -> None:
    manifest = json.loads((RELDIR / MANIFEST_NAME).read_bytes())
    assert manifest["governed_state_digest"] == TOOL._governed_digest(REPO)
    assert manifest["ledger_sha256"] == TOOL._ledger_hashes(REPO)
    assert manifest["policy_sha256"] == TOOL._policy_sha256(REPO)
    # Source anchors reproduce from the live tree only at the frozen release version; under a later
    # development version the committed manifest is a historical artifact (its recorded anchors are
    # validated structurally instead of reproduced from the diverged tree).
    if TOOL._active_version(REPO) == TOOL.VERSION:
        source = TOOL._source_distribution(REPO)
        assert manifest["source_tree_digest"] == source["tree_digest"]
        assert manifest["source_member_count"] == source["member_count"]
    else:
        digest = manifest["source_tree_digest"]
        assert manifest["version"] == TOOL.VERSION
        assert isinstance(digest, str)
        assert len(digest) == 64
        assert TOOL._is_lower_hex(digest)
        assert isinstance(manifest["source_member_count"], int)
        assert manifest["source_member_count"] > 0
    members = {entry["filename"]: entry["sha256"] for entry in manifest["members"]}
    # Both build-free members still reproduce byte-exactly. What they reproduce *from* is version-
    # aware: the live ``uv.lock`` at the frozen release version, the committed v1.1.0 evidence past
    # it. The two are the same bytes today, which the pinned digests below assert outright rather
    # than leave implied — see test_the_payload_manifest_sbom_member_is_the_frozen_release_sbom.
    assert members["sbom.cdx.json"] == sha256_hex(TOOL._sbom_bytes(REPO))
    assert members["PRIVATE_INSTALL.md"] == sha256_hex(TOOL.render_install_md(REPO))
    assert members["sbom.cdx.json"] == FROZEN_SBOM_SHA256
    assert TOOL._release_locked_versions(REPO, TOOL.RUNTIME_DEP_NAMES) == _frozen_sbom_pins()
    # The manifest never records the payload tar's own hash and never lists itself.
    assert MANIFEST_NAME not in members
    assert TOOL.PAYLOAD_NAME not in members


# --------------------------------------------------------------------------- #
# the frozen v1.1.0 private deliverables are historical records of v1.1.0:      #
# an ordinary dependency change may not mutate or falsely invalidate them       #
# --------------------------------------------------------------------------- #
def _frozen_sbom_pins() -> dict[str, str]:
    """numpy/pandas/pyarrow as the committed v1.1.0 SBOM records them."""
    doc = json.loads(FROZEN_SBOM_PATH.read_bytes())
    return {
        c["name"]: c["version"]
        for c in doc["components"]
        if c["name"] in set(TOOL.RUNTIME_DEP_NAMES)
    }


def _mirror(tmp_path: Path) -> Path:
    """A throwaway repo root ``check`` runs against, so no test ever mutates the real tree.

    Carries exactly what ``check`` reads: the governed ``research/`` artifacts and sealed ledgers,
    the frozen ``release/`` records, ``pyproject.toml`` (the active version) and ``uv.lock``.
    """
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copytree(REPO / "research", root / "research")
    shutil.copytree(REPO / "release", root / "release")
    shutil.copy2(REPO / "pyproject.toml", root / "pyproject.toml")
    shutil.copy2(REPO / "uv.lock", root / "uv.lock")
    return root


def _frozen_snapshot(root: Path) -> dict[str, str]:
    rel = ("release/v1.1.0", "release/private/v1.1.0")
    return {
        f"{d}/{p.name}": sha256_hex(p.read_bytes())
        for d in rel
        for p in sorted((root / d).iterdir())
        if p.is_file()
    }


def _declare_a_dependency(root: Path) -> None:
    """What declaring one registry-sourced dependency does to the lock, and only that."""
    with (root / "uv.lock").open("a", encoding="utf-8") as fh:
        fh.write(
            '\n[[package]]\nname = "nardis-registry-extra"\nversion = "1.4.2"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
        )


def _upgrade_numpy(root: Path) -> str:
    """What upgrading a *pinned runtime* dependency does to the lock, and only that.

    Reads the version out of the lock rather than hard-coding it, so this fixture keeps working
    across exactly the numpy upgrades the historical treatment exists to allow.
    """
    lock = root / "uv.lock"
    current = TOOL._locked_versions(root, ("numpy",))["numpy"]
    bumped = f"{current}.post1"
    before = lock.read_text(encoding="utf-8")
    after = before.replace(
        f'name = "numpy"\nversion = "{current}"', f'name = "numpy"\nversion = "{bumped}"', 1
    )
    assert after != before, "the numpy lock entry is not in the expected shape"
    lock.write_text(after, encoding="utf-8")
    return bumped


def test_the_payload_manifest_sbom_member_is_the_frozen_release_sbom() -> None:
    """The byte identity the historical treatment rests on, asserted rather than assumed.

    The ``sbom.cdx.json`` the v1.1.0 payload carried *is* ``release/v1.1.0/sbom.cdx.json``. That is
    why comparing the frozen payload manifest's member against the committed record instead of
    against a rebuild from the live lock is a change of what the comparison targets and not a
    relaxation of it: today the two targets are the same bytes, and both ends are byte-pinned.
    """
    frozen = FROZEN_SBOM_PATH.read_bytes()
    manifest = json.loads((RELDIR / MANIFEST_NAME).read_bytes())
    members = {entry["filename"]: entry["sha256"] for entry in manifest["members"]}
    assert sha256_hex(frozen) == FROZEN_SBOM_SHA256
    assert members["sbom.cdx.json"] == FROZEN_SBOM_SHA256
    assert sha256_hex((RELDIR / MANIFEST_NAME).read_bytes()) == FROZEN_MANIFEST_SHA256
    assert sha256_hex((RELDIR / CONTRACT_NAME).read_bytes()) == FROZEN_CONTRACT_SHA256
    # Past the frozen release version the tool resolves the member to those very bytes.
    assert TOOL._is_historical(REPO)
    assert TOOL._sbom_bytes(REPO) == frozen


def test_the_install_contract_pins_the_versions_the_frozen_sbom_records() -> None:
    """The install guide and contract are anchored to a frozen record, not to nothing.

    Their only lock-derived content is numpy/pandas/pyarrow, and past the frozen release version
    those versions come from the committed v1.1.0 SBOM's ``components[]`` — an artifact the stack
    freeze table pins byte-exactly and ``tools/release_evidence.py --check`` identity-checks.
    """
    pins = _frozen_sbom_pins()
    assert set(pins) == set(TOOL.RUNTIME_DEP_NAMES)
    contract = json.loads((RELDIR / CONTRACT_NAME).read_bytes())
    recorded = {d["name"]: d["locked_version"] for d in contract["required_runtime_dependencies"]}
    assert recorded == pins
    assert TOOL._release_locked_versions(REPO, TOOL.RUNTIME_DEP_NAMES) == pins
    guide = TOOL.render_install_md(REPO)
    for name, version in pins.items():
        assert f"{name}=={version}".encode() in guide


def test_a_declared_dependency_cannot_invalidate_the_frozen_payload_manifest(
    tmp_path: Path,
) -> None:
    """The regression this treatment exists for, driven through the real ``check``.

    One registry-sourced entry in ``uv.lock`` is enough to change what ``build_sbom`` emits. The
    frozen payload manifest registered the hash of the SBOM release v1.1.0 shipped, so that
    difference is not drift in the manifest — and reporting it as drift sends an operator to
    ``write-manifests``, which reissues bytes the stack freeze table records as immutable.
    """
    root = _mirror(tmp_path)
    before = _frozen_snapshot(root)
    _declare_a_dependency(root)

    # Not a no-op test: a rebuild from the mutated lock genuinely differs from the frozen record.
    rebuilt = canonical_json_bytes(TOOL._evidence.build_sbom(root))
    assert "nardis-registry-extra" in {c["name"] for c in json.loads(rebuilt)["components"]}
    assert sha256_hex(rebuilt) != FROZEN_SBOM_SHA256

    assert TOOL.check(root) == []
    assert _frozen_snapshot(root) == before
    assert before["release/v1.1.0/sbom.cdx.json"] == FROZEN_SBOM_SHA256
    assert before[f"release/private/v1.1.0/{MANIFEST_NAME}"] == FROZEN_MANIFEST_SHA256


def test_a_runtime_dependency_upgrade_cannot_invalidate_the_frozen_payload_manifest(
    tmp_path: Path,
) -> None:
    """The same for the install contract and install guide, whose lock coupling is a version bump.

    Both embed the locked numpy/pandas/pyarrow versions, so upgrading one used to report the two
    frozen artifacts stale. They record release v1.1.0's pins; a later tree's pins are a different
    release's fact and belong to the live inventories that own the current lock.
    """
    root = _mirror(tmp_path)
    before = _frozen_snapshot(root)
    bumped = _upgrade_numpy(root)

    # Not a no-op test: the live lock really moved, and only the frozen record held still.
    assert TOOL._locked_versions(root, TOOL.RUNTIME_DEP_NAMES)["numpy"] == bumped
    assert TOOL._release_locked_versions(root, TOOL.RUNTIME_DEP_NAMES) == _frozen_sbom_pins()

    assert TOOL.check(root) == []
    assert _frozen_snapshot(root) == before
    assert before[f"release/private/v1.1.0/{CONTRACT_NAME}"] == FROZEN_CONTRACT_SHA256


def test_at_the_frozen_release_version_the_live_lock_is_still_what_reproduces(
    tmp_path: Path,
) -> None:
    """Nothing changed for a tree that *is* v1.1.0 — the strict live-reproduction path is intact.

    Stamping the mirror back to the release version puts every artifact back on the live rebuild,
    where a mutated lock is real drift and must be reported. (The source-anchor problems this stub
    also reports are expected: the mirror carries no ``src/``. Only the lock-derived gates are under
    test here.)
    """
    root = _mirror(tmp_path)
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            f'version = "{TOOL._active_version(root)}"', f'version = "{TOOL.VERSION}"', 1
        ),
        encoding="utf-8",
    )
    assert not TOOL._is_historical(root)
    _declare_a_dependency(root)
    _upgrade_numpy(root)

    problems = TOOL.check(root)

    assert "manifest sbom member does not reproduce" in problems
    assert "manifest install-guide member does not reproduce" in problems
    assert f"{CONTRACT_NAME} is stale; regenerate with `write-manifests`" in problems
    assert _frozen_snapshot(root)["release/v1.1.0/sbom.cdx.json"] == FROZEN_SBOM_SHA256


# --------------------------------------------------------------------------- #
# ...and the recorded identity is still validated strictly: tampering fails     #
# --------------------------------------------------------------------------- #
def _rewrite_manifest_member(root: Path, filename: str, digest: str) -> None:
    path = root / "release" / "private" / "v1.1.0" / MANIFEST_NAME
    manifest = json.loads(path.read_bytes())
    for entry in manifest["members"]:
        if entry["filename"] == filename:
            entry["sha256"] = digest
            break
    else:  # pragma: no cover - the member is always listed
        raise AssertionError(f"{filename} is not a registered member")
    path.write_bytes(canonical_json_bytes(manifest))


def test_check_still_fails_on_a_falsified_sbom_member_hash(tmp_path: Path) -> None:
    """Not rebuilding from the live lock is not the same as not checking."""
    root = _mirror(tmp_path)
    _rewrite_manifest_member(root, "sbom.cdx.json", "0" * 64)

    assert "manifest sbom member does not reproduce" in TOOL.check(root)


def test_check_still_fails_on_a_falsified_install_guide_member_hash(tmp_path: Path) -> None:
    root = _mirror(tmp_path)
    _rewrite_manifest_member(root, "PRIVATE_INSTALL.md", "0" * 64)

    assert "manifest install-guide member does not reproduce" in TOOL.check(root)


def test_check_still_fails_on_a_falsified_frozen_sbom(tmp_path: Path) -> None:
    """Coverage the live-rebuild comparison did not have, and the frozen comparison does.

    The committed ``release/v1.1.0/sbom.cdx.json`` is now the authority this gate reads, so it is
    also now something this gate can catch being edited: its bytes and the member hash the frozen
    payload manifest registered have to agree, and neither may be reissued.
    """
    root = _mirror(tmp_path)
    frozen = root / "release" / "v1.1.0" / "sbom.cdx.json"
    doc = json.loads(frozen.read_bytes())
    doc["components"].append(
        {
            "type": "library",
            "name": "zzz-smuggled",
            "version": "1.0.0",
            "purl": "pkg:pypi/zzz-smuggled@1.0.0",
        }
    )
    frozen.write_bytes(canonical_json_bytes(doc))

    assert "manifest sbom member does not reproduce" in TOOL.check(root)


def test_check_still_fails_when_a_falsified_frozen_sbom_moves_a_runtime_pin(
    tmp_path: Path,
) -> None:
    """Falsifying the pin source does not quietly become the new expectation.

    The install contract and the install guide hash are frozen too, so moving numpy's version in
    the record they are anchored to fails both of them rather than redefining them.
    """
    root = _mirror(tmp_path)
    frozen = root / "release" / "v1.1.0" / "sbom.cdx.json"
    doc = json.loads(frozen.read_bytes())
    for component in doc["components"]:
        if component["name"] == "numpy":
            component["version"] = "2.5.2"
            component["purl"] = "pkg:pypi/numpy@2.5.2"
    frozen.write_bytes(canonical_json_bytes(doc))

    problems = TOOL.check(root)

    assert f"{CONTRACT_NAME} is stale; regenerate with `write-manifests`" in problems
    assert "manifest install-guide member does not reproduce" in problems
    assert "manifest sbom member does not reproduce" in problems


def test_check_still_fails_on_a_falsified_install_contract_pin(tmp_path: Path) -> None:
    root = _mirror(tmp_path)
    path = root / "release" / "private" / "v1.1.0" / CONTRACT_NAME
    contract = json.loads(path.read_bytes())
    for entry in contract["required_runtime_dependencies"]:
        if entry["name"] == "numpy":
            entry["locked_version"] = "2.5.2"
    path.write_bytes(canonical_json_bytes(contract))

    assert f"{CONTRACT_NAME} is stale; regenerate with `write-manifests`" in TOOL.check(root)


def test_a_frozen_sbom_missing_a_pinned_runtime_dependency_fails_closed(tmp_path: Path) -> None:
    """The pin lookup refuses rather than defaulting if the record cannot answer."""
    root = _mirror(tmp_path)
    frozen = root / "release" / "v1.1.0" / "sbom.cdx.json"
    doc = json.loads(frozen.read_bytes())
    doc["components"] = [c for c in doc["components"] if c["name"] != "numpy"]
    frozen.write_bytes(canonical_json_bytes(doc))

    with pytest.raises(TOOL.PrivateReleaseError, match="no locked version for"):
        TOOL._release_locked_versions(root, TOOL.RUNTIME_DEP_NAMES)


def test_the_frozen_records_stay_byte_pinned_by_the_stack_freeze_table() -> None:
    """Provenance is not weakened by going historical: the bytes stay pinned, immutably.

    ``research/v2ab/stack_freeze_table.json`` records each of these paths as ``immutable`` and ships
    no writer. Making the artifacts genuinely immutable is what makes that recorded claim true.
    """
    table = json.loads((REPO / "research" / "v2ab" / "stack_freeze_table.json").read_bytes())
    entries = {e["path"]: e for e in table["entries"]}
    for relpath, expected in (
        ("release/v1.1.0/sbom.cdx.json", FROZEN_SBOM_SHA256),
        (f"release/private/v1.1.0/{MANIFEST_NAME}", FROZEN_MANIFEST_SHA256),
        (f"release/private/v1.1.0/{CONTRACT_NAME}", FROZEN_CONTRACT_SHA256),
    ):
        data = (REPO / relpath).read_bytes()
        assert entries[relpath]["immutability"] == "immutable"
        assert entries[relpath]["byte_count"] == len(data)
        assert entries[relpath]["sha256"] == sha256_hex(data) == expected


# --------------------------------------------------------------------------- #
# member allowlist (via scan_distribution)                                     #
# --------------------------------------------------------------------------- #
def test_scan_distribution_rejects_bad_wheel_members(tmp_path: Path) -> None:
    bad = tmp_path / "eth_research-1.1.0-py3-none-any.whl"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("eth_research/candles.parquet", b"raw data")  # data suffix inside the package
        zf.writestr("../evil.py", b"escape")  # path traversal
        zf.writestr("eth_research-1.1.0.dist-info/METADATA", "Name: eth-research\n")
    failures = SCANNER.scan_distribution(bad)
    assert failures, "scanner must reject the crafted wheel"
    joined = " ".join(failures)
    assert "forbidden file type" in joined
    assert "path traversal" in joined


def test_scan_distribution_rejects_bad_sdist_members(tmp_path: Path) -> None:
    bad = tmp_path / "eth_research-1.1.0.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        info = tarfile.TarInfo("eth_research-1.1.0/src/eth_research/candles.parquet")
        payload = b"raw data"
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
        link = tarfile.TarInfo("eth_research-1.1.0/evil")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
    failures = SCANNER.scan_distribution(bad)
    assert failures, "scanner must reject the crafted sdist"
    joined = " ".join(failures)
    assert "link in sdist" in joined
    assert "forbidden file type" in joined


# --------------------------------------------------------------------------- #
# payload assembly determinism (offline; no uv/git)                            #
# --------------------------------------------------------------------------- #
def test_payload_assembly_is_deterministic_and_normalized() -> None:
    first = TOOL.assemble_payload_bytes(REPO, b"wheel-bytes", b"sdist-bytes")
    second = TOOL.assemble_payload_bytes(REPO, b"wheel-bytes", b"sdist-bytes")
    assert first == second
    with tarfile.open(fileobj=io.BytesIO(first)) as tar:
        members = tar.getmembers()
        assert sorted(m.name for m in members) == sorted(PAYLOAD_MEMBERS)
        for member in members:
            assert member.mtime == 0
            assert member.uid == 0
            assert member.gid == 0
            assert member.mode == 0o644
            assert member.uname == ""
            assert member.gname == ""
            assert member.isfile()


def test_sha256sums_excludes_itself_and_the_manifest() -> None:
    members = TOOL.assemble_members(REPO, b"wheel-bytes", b"sdist-bytes")
    lines = members["SHA256SUMS"].decode("utf-8").splitlines()
    listed = {line.split("  ", 1)[1] for line in lines}
    assert "SHA256SUMS" not in listed
    assert MANIFEST_NAME not in listed
    # Every SHA256SUMS line is "<64-hex><two spaces><name>", sorted by name.
    names = [line.split("  ", 1)[1] for line in lines]
    assert names == sorted(names)


# --------------------------------------------------------------------------- #
# receipt strict parse                                                         #
# --------------------------------------------------------------------------- #
def _well_formed_receipt() -> dict[str, Any]:
    receipt: dict[str, Any] = TOOL.build_receipt(
        REPO,
        payload_sha256="a" * 64,
        wheel_sha256="b" * 64,
        sdist_sha256="c" * 64,
        sbom_sha256="d" * 64,
        manifest_sha256="e" * 64,
        consumer_verification_result="passed",
        started_utc="2026-07-18T00:00:00Z",
        ended_utc="2026-07-18T00:00:01Z",
        env={},
    )
    return receipt


def test_verify_receipt_accepts_well_formed(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    path.write_bytes(canonical_json_bytes(_well_formed_receipt()))
    parsed = TOOL.verify_receipt(path)
    assert parsed["public_publication_attempts"] == 0
    assert parsed["triggering_actor_classification"] == "local_build"
    assert "not a cryptographic signature" in parsed["note"]


def test_verify_receipt_rejects_public_publication_attempt(tmp_path: Path) -> None:
    receipt = _well_formed_receipt()
    receipt["public_publication_attempts"] = 1
    path = tmp_path / "receipt.json"
    path.write_bytes(canonical_json_bytes(receipt))
    with pytest.raises(CanonicalError):
        TOOL.verify_receipt(path)


def test_verify_receipt_rejects_missing_key(tmp_path: Path) -> None:
    receipt = _well_formed_receipt()
    del receipt["note"]
    path = tmp_path / "receipt.json"
    path.write_bytes(canonical_json_bytes(receipt))
    with pytest.raises(CanonicalError):
        TOOL.verify_receipt(path)


def test_receipt_never_stores_raw_actor(tmp_path: Path) -> None:
    receipt = TOOL.build_receipt(
        REPO,
        payload_sha256="a" * 64,
        wheel_sha256="b" * 64,
        sdist_sha256="c" * 64,
        sbom_sha256="d" * 64,
        manifest_sha256="e" * 64,
        consumer_verification_result="passed",
        started_utc="2026-07-18T00:00:00Z",
        ended_utc="2026-07-18T00:00:01Z",
        env={"GITHUB_ACTOR": "some-user", "GITHUB_REPOSITORY_OWNER": "panfot1409"},
    )
    assert receipt["triggering_actor_classification"] == "collaborator"
    assert "some-user" not in json.dumps(receipt)


# --------------------------------------------------------------------------- #
# slow: real uv build reproducibility + license-free wheel metadata            #
# --------------------------------------------------------------------------- #
def _uv_available() -> bool:
    return shutil.which("uv") is not None and shutil.which("git") is not None


@pytest.mark.slow
def test_real_build_payload_is_byte_identical() -> None:
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
    assert wheel_a == wheel_b
    assert sdist_a == sdist_b
    payload_a = TOOL.assemble_payload_bytes(REPO, wheel_a, sdist_a)
    payload_b = TOOL.assemble_payload_bytes(REPO, wheel_b, sdist_b)
    assert payload_a == payload_b


@pytest.mark.slow
def test_committed_manifest_binary_hashes_reproduce_from_build() -> None:
    # Guards the cross-environment reproducibility of the wheel and sdist: with SOURCE_DATE_EPOCH
    # pinned, a fresh build must reproduce the exact member hashes recorded in the committed
    # manifest (the sdist gzip header is otherwise wall-clock dependent).
    if TOOL._active_version(REPO) != TOOL.VERSION:
        pytest.skip("the frozen v1.1.0 payload reproduces only from the v1.1.0 source tree")
    if not _uv_available():
        pytest.skip("uv/git required for the deterministic build")
    try:
        wheel_bytes, sdist_bytes = TOOL._build_wheel_and_sdist(REPO)
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("uv is not available")
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"build unavailable (offline?): {exc.stderr}")
    manifest = json.loads((RELDIR / MANIFEST_NAME).read_bytes())
    recorded = {entry["filename"]: entry["sha256"] for entry in manifest["members"]}
    assert sha256_hex(wheel_bytes) == recorded["eth_research-1.1.0-py3-none-any.whl"]
    assert sha256_hex(sdist_bytes) == recorded["eth_research-1.1.0.tar.gz"]


@pytest.mark.slow
def test_built_wheel_metadata_is_license_free_and_guarded(tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv required to build the wheel")
    try:
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("uv is not available")
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"wheel build unavailable (offline?): {exc.stderr}")
    wheel = next(tmp_path.glob("*.whl"))
    # Validate the current wheel against its OWN active version: the frozen-release VERSION guard is
    # relaxed to the live version here, while every version-independent invariant (name, the
    # Private :: Do Not Upload guard, license-freeness) is still enforced.
    assert TOOL.wheel_metadata_findings(wheel, expected_version=TOOL._active_version(REPO)) == []
    assert SCANNER.scan_distribution(wheel) == []
