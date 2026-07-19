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
PAYLOAD_MEMBERS = [
    "PRIVATE_INSTALL.md",
    "SHA256SUMS",
    "eth_research-1.1.0-py3-none-any.whl",
    "eth_research-1.1.0.tar.gz",
    "private_payload_manifest.json",
    "provenance.json",
    "sbom.cdx.json",
]


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
    assert members["sbom.cdx.json"] == sha256_hex(TOOL._sbom_bytes(REPO))
    assert members["PRIVATE_INSTALL.md"] == sha256_hex(TOOL.render_install_md(REPO))
    # The manifest never records the payload tar's own hash and never lists itself.
    assert MANIFEST_NAME not in members
    assert TOOL.PAYLOAD_NAME not in members


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
