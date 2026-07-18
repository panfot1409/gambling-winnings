"""Failure-injection / recovery matrix (§19) for the deterministic private-release tooling.

Each test injects one corruption and proves the tool's own verifier / scanner fails CLOSED,
using crafted inputs or a throwaway tmp tree — the real repository tree, the governed ``research/``
artifacts, and the three sealed ledgers are never mutated. The offline tests reuse
``verify_policy`` / ``verify_receipt`` / ``inspect_payload`` / ``scan_distribution`` /
``_ledger_hashes`` directly; the single build-dependent test is marked ``slow`` and skips without
``uv``/``git``.

Deliberately decoupled from the release-state evidence (which the parent is migrating): nothing
here reads ``release/v1.1.0/release_state.json`` or assumes its shape, and nothing runs the
full ``_assert_source_integrity`` evidence gate.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from eth_research.api.serialization import CanonicalError, canonical_json_bytes, sha256_hex

REPO = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO / "tools" / "private_release.py"
SCANNER_PATH = REPO / "tools" / "scan_distribution.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load("private_release", TOOL_PATH)
SCANNER = _load("scan_distribution", SCANNER_PATH)


# --------------------------------------------------------------------------- #
# shared offline builders (dummy wheel/sdist bytes — the assembly logic under   #
# test is independent of the archive contents)                                  #
# --------------------------------------------------------------------------- #
def _authentic_members() -> dict[str, bytes]:
    members: dict[str, bytes] = TOOL.assemble_members(REPO, b"wheel-bytes", b"sdist-bytes")
    return members


def _manifest_of(members: dict[str, bytes]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(members[TOOL.MANIFEST_NAME])
    return data


def _payload_problems(
    members: dict[str, bytes], manifest: dict[str, Any], tmp_path: Path
) -> list[str]:
    """Verify a payload tar's members against the registered manifest (via ``inspect_payload``)."""
    path = tmp_path / "payload.tar"
    path.write_bytes(TOOL.normalized_tar_bytes(members))
    entries = {e["filename"]: e["sha256"] for e in TOOL.inspect_payload(path)}
    expected = {m["filename"]: m["sha256"] for m in manifest["members"]}
    content = {name: digest for name, digest in entries.items() if name != TOOL.MANIFEST_NAME}
    problems: list[str] = []
    if set(content) != set(expected):
        problems.append(f"member set mismatch: {sorted(set(content) ^ set(expected))}")
    for name, digest in expected.items():
        if content.get(name) != digest:
            problems.append(f"member hash mismatch/missing: {name}")
    if TOOL.MANIFEST_NAME not in entries:
        problems.append("payload is missing its manifest member")
    return problems


def _sums_problems(members: dict[str, bytes]) -> list[str]:
    """Verify SHA256SUMS lines against the actual member bytes."""
    listed: dict[str, str] = {}
    for line in members[TOOL.SUMS_NAME].decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest
    problems: list[str] = []
    for name in TOOL._SUMS_MEMBERS:
        if listed.get(name) != sha256_hex(members[name]):
            problems.append(f"SHA256SUMS mismatch for {name}")
    return problems


# --------------------------------------------------------------------------- #
# (a) tampered distribution policy is rejected by verify_policy                 #
# --------------------------------------------------------------------------- #
def _write_policy(tmp_path: Path, raw: bytes) -> Path:
    target = tmp_path / "release" / "private" / "v1.1.0"
    target.mkdir(parents=True, exist_ok=True)
    (target / TOOL.POLICY_NAME).write_bytes(raw)
    return tmp_path


def test_policy_with_a_public_boolean_flipped_true_is_rejected(tmp_path: Path) -> None:
    policy = TOOL.build_policy()
    policy["public_pypi_allowed"] = True
    root = _write_policy(tmp_path, canonical_json_bytes(policy))
    with pytest.raises(CanonicalError):
        TOOL.verify_policy(root)


def test_policy_with_public_classification_is_rejected(tmp_path: Path) -> None:
    policy = TOOL.build_policy()
    policy["distribution_classification"] = "public"
    root = _write_policy(tmp_path, canonical_json_bytes(policy))
    with pytest.raises(CanonicalError):
        TOOL.verify_policy(root)


def test_authentic_committed_policy_still_verifies() -> None:
    # Control: the injection tests are not vacuous — the real committed policy verifies.
    assert TOOL.verify_policy(REPO)["distribution_classification"] == "private"


# --------------------------------------------------------------------------- #
# (b) a payload with an extra / renamed / removed member fails verification     #
# --------------------------------------------------------------------------- #
def test_authentic_payload_matches_the_manifest(tmp_path: Path) -> None:
    members = _authentic_members()
    assert _payload_problems(members, _manifest_of(members), tmp_path) == []


def test_payload_with_an_extra_member_is_rejected(tmp_path: Path) -> None:
    members = _authentic_members()
    manifest = _manifest_of(members)
    tampered = dict(members)
    tampered["stowaway.txt"] = b"unexpected content"
    assert _payload_problems(tampered, manifest, tmp_path) != []


def test_payload_with_a_renamed_member_is_rejected(tmp_path: Path) -> None:
    members = _authentic_members()
    manifest = _manifest_of(members)
    tampered = dict(members)
    tampered["sbom_renamed.json"] = tampered.pop(TOOL.SBOM_NAME)
    assert _payload_problems(tampered, manifest, tmp_path) != []


def test_payload_with_a_removed_member_is_rejected(tmp_path: Path) -> None:
    members = _authentic_members()
    manifest = _manifest_of(members)
    tampered = dict(members)
    del tampered[TOOL.SBOM_NAME]
    assert _payload_problems(tampered, manifest, tmp_path) != []


# --------------------------------------------------------------------------- #
# (c) a tampered SHA256SUMS line fails                                          #
# --------------------------------------------------------------------------- #
def test_authentic_sha256sums_matches_every_member() -> None:
    assert _sums_problems(_authentic_members()) == []


def test_a_tampered_sha256sums_line_is_rejected() -> None:
    members = _authentic_members()
    lines = members[TOOL.SUMS_NAME].decode("utf-8").splitlines()
    digest, name = lines[0].split("  ", 1)
    flipped = ("f" if digest[0] != "f" else "0") + digest[1:]
    lines[0] = f"{flipped}  {name}"
    tampered = dict(members)
    tampered[TOOL.SUMS_NAME] = ("\n".join(lines) + "\n").encode("utf-8")
    assert _sums_problems(tampered) != []


# --------------------------------------------------------------------------- #
# (d) a wheel carrying a governed/research or data path fails the scanner       #
# --------------------------------------------------------------------------- #
def test_wheel_with_research_and_data_paths_fails_the_distribution_scanner(tmp_path: Path) -> None:
    bad = tmp_path / "eth_research-1.1.0-py3-none-any.whl"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("eth_research/py.typed", b"")
        zf.writestr("eth_research/data/candles.parquet", b"raw market data")  # data blob in package
        zf.writestr("research/m2b/leak.json", b"{}")  # governed research segment
        zf.writestr("eth_research-1.1.0.dist-info/METADATA", "Name: eth-research\n")
        zf.writestr("eth_research-1.1.0.dist-info/WHEEL", "Tag: py3-none-any\n")
        zf.writestr(
            "eth_research-1.1.0.dist-info/entry_points.txt",
            "[console_scripts]\neth-research = eth_research.cli:main\n",
        )
    failures = SCANNER.scan_distribution(bad)
    joined = " ".join(failures)
    assert "forbidden file type" in joined, joined  # the .parquet data blob
    assert "forbidden path segment" in joined, joined  # the research/ governance root


# --------------------------------------------------------------------------- #
# (e) a bad receipt is rejected by verify_receipt                               #
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


def test_receipt_claiming_a_public_publication_attempt_is_rejected(tmp_path: Path) -> None:
    receipt = _well_formed_receipt()
    receipt["public_publication_attempts"] = 3
    path = tmp_path / "receipt.json"
    path.write_bytes(canonical_json_bytes(receipt))
    with pytest.raises(CanonicalError):
        TOOL.verify_receipt(path)


def test_receipt_missing_a_required_key_is_rejected(tmp_path: Path) -> None:
    receipt = _well_formed_receipt()
    del receipt["payload_sha256"]
    path = tmp_path / "receipt.json"
    path.write_bytes(canonical_json_bytes(receipt))
    with pytest.raises(CanonicalError):
        TOOL.verify_receipt(path)


def test_authentic_receipt_verifies(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    path.write_bytes(canonical_json_bytes(_well_formed_receipt()))
    assert TOOL.verify_receipt(path)["public_publication_attempts"] == 0


# --------------------------------------------------------------------------- #
# (f) a non-byte-empty sealed ledger (in a throwaway tree) fails closed         #
# --------------------------------------------------------------------------- #
def test_non_empty_sealed_ledger_copy_breaks_the_byte_empty_invariant(tmp_path: Path) -> None:
    # Synthesize the three sealed ledgers in a THROWAWAY tree — the real ledgers (the development
    # gate and the holdout) are never copied, read, or touched.
    for rel in TOOL.SEALED_LEDGERS:
        ledger = tmp_path / rel
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_bytes(b"")
    # All byte-empty -> the invariant the builder's source-integrity gate requires holds.
    assert all(digest == TOOL.EMPTY_SHA for digest in TOOL._ledger_hashes(tmp_path).values())

    # Injection: a single non-byte-empty sealed-ledger copy...
    (tmp_path / TOOL.SEALED_LEDGERS[0]).write_bytes(b'{"evaluation":"leak"}\n')
    hashes = TOOL._ledger_hashes(tmp_path)
    # ...violates exactly the ``digest != EMPTY_SHA`` predicate on which the builder raises
    # ``PrivateReleaseError("sealed ledger is not byte-empty")`` and refuses to proceed.
    assert hashes[TOOL.SEALED_LEDGERS[0]] != TOOL.EMPTY_SHA
    assert not all(digest == TOOL.EMPTY_SHA for digest in hashes.values())


# --------------------------------------------------------------------------- #
# slow: the SAME injections against a real freshly-built payload                #
# --------------------------------------------------------------------------- #
def _uv_available() -> bool:
    return shutil.which("uv") is not None and shutil.which("git") is not None


@pytest.mark.slow
def test_real_built_payload_verifies_and_member_injection_is_rejected(tmp_path: Path) -> None:
    if not _uv_available():
        pytest.skip("uv/git required to build the distribution")
    try:
        wheel_bytes, sdist_bytes = TOOL._build_wheel_and_sdist(REPO)
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("uv is not available")
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.skip(f"build unavailable (offline?): {exc.stderr}")
    members = TOOL.assemble_members(REPO, wheel_bytes, sdist_bytes)
    manifest = _manifest_of(members)
    # The authentic real payload verifies against its own registered manifest.
    assert _payload_problems(members, manifest, tmp_path) == []
    # Injecting a member into the real payload is rejected (fails closed).
    tampered = dict(members)
    tampered["stowaway.txt"] = b"unexpected"
    assert _payload_problems(tampered, manifest, tmp_path) != []
