"""Runtime-environment contract: strict identity + lockfile hash binding."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

import eth_research
from eth_research.environment import (
    AUTHORITATIVE_RUNTIME_ROLE,
    CANONICAL_RUNTIME_CONTRACT_RELPATH,
    ENVIRONMENT_SCHEMA_VERSION,
    RuntimeContract,
    RuntimeVerificationError,
    current_runtime_snapshot,
    load_runtime_contract,
    verify_runtime_contract,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def make_contract() -> RuntimeContract:
    return RuntimeContract.for_current_runtime(REPO_ROOT)


def copy_lockfiles(dst: Path) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "uv.lock").write_bytes((REPO_ROOT / "uv.lock").read_bytes())
    (dst / "pyproject.toml").write_bytes((REPO_ROOT / "pyproject.toml").read_bytes())
    return dst


class TestRuntimeContractRoundTrip:
    def test_valid_contract_round_trips_and_verifies(self) -> None:
        contract = make_contract()
        raw = contract.to_json_bytes()
        assert RuntimeContract.from_json_bytes(raw).to_json_bytes() == raw
        # exact valid round trip against the live runtime and repo lockfiles
        verify_runtime_contract(contract, repo_root=REPO_ROOT)

    def test_canonical_path_constant(self) -> None:
        assert CANONICAL_RUNTIME_CONTRACT_RELPATH == "research/m2b/runtime_contract.json"

    def test_snapshot_matches_contract_snapshot(self) -> None:
        contract = make_contract()
        assert contract.snapshot == current_runtime_snapshot()


class TestRuntimeIdentityMismatches:
    """Each interpreter-observable field must match exactly."""

    @pytest.mark.parametrize(
        ("field", "bad"),
        [
            ("python_version", "3.11.9"),
            ("python_implementation", "PyPy"),
            ("python_cache_tag", "pypy37"),
            ("os_family", "Darwin"),
            ("machine", "arm64"),
            ("package_version", "0.0.1"),
            ("numpy_version", "1.26.4"),
            ("pandas_version", "2.2.2"),
            ("pyarrow_version", "15.0.0"),
        ],
    )
    def test_mismatched_field_is_rejected(self, field: str, bad: str) -> None:
        contract = make_contract()
        wrong = dataclasses.replace(current_runtime_snapshot(), **{field: bad})
        with pytest.raises(RuntimeVerificationError, match=f"runtime mismatch on {field}"):
            verify_runtime_contract(contract, repo_root=REPO_ROOT, snapshot=wrong)


class TestLockfileBinding:
    def test_changed_uv_lock_is_rejected(self, tmp_path: Path) -> None:
        contract = make_contract()
        repo = copy_lockfiles(tmp_path / "repo")
        (repo / "uv.lock").write_bytes((repo / "uv.lock").read_bytes() + b"\n# tampered\n")
        with pytest.raises(RuntimeVerificationError, match=r"uv.lock SHA-256"):
            verify_runtime_contract(contract, repo_root=repo)

    def test_changed_pyproject_is_rejected(self, tmp_path: Path) -> None:
        contract = make_contract()
        repo = copy_lockfiles(tmp_path / "repo")
        (repo / "pyproject.toml").write_bytes(
            (repo / "pyproject.toml").read_bytes() + b"\n# tampered\n"
        )
        with pytest.raises(RuntimeVerificationError, match=r"pyproject.toml SHA-256"):
            verify_runtime_contract(contract, repo_root=repo)

    def test_missing_uv_lock_is_rejected(self, tmp_path: Path) -> None:
        contract = make_contract()
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_bytes((REPO_ROOT / "pyproject.toml").read_bytes())
        with pytest.raises(RuntimeVerificationError, match=r"required file 'uv.lock' is missing"):
            verify_runtime_contract(contract, repo_root=repo)


class TestContractConstructionValidation:
    def test_non_cpython_contract_is_rejected(self) -> None:
        good = make_contract()
        with pytest.raises(ValueError, match="python_implementation must be 'CPython'"):
            dataclasses.replace(good, python_implementation="PyPy")

    def test_non_authoritative_role_is_rejected(self) -> None:
        good = make_contract()
        with pytest.raises(ValueError, match="runtime_role must be"):
            dataclasses.replace(good, runtime_role="compatibility")

    def test_verify_rejects_non_authoritative_role_defensively(self) -> None:
        # A contract can only be built with the authoritative role, so force a
        # role mismatch through the parse path is impossible; assert the guard
        # in verify still exists by constructing via object.__setattr__ bypass.
        good = make_contract()
        rogue = object.__new__(RuntimeContract)
        for f in dataclasses.fields(good):
            object.__setattr__(rogue, f.name, getattr(good, f.name))
        object.__setattr__(rogue, "runtime_role", "compatibility")
        with pytest.raises(RuntimeVerificationError, match="not the authoritative"):
            verify_runtime_contract(rogue, repo_root=REPO_ROOT)

    @pytest.mark.parametrize("bad", ["3.12", "3", "3.12.3.1", "3.12.x", "cpython-3.12.3"])
    def test_bad_python_version_format_is_rejected(self, bad: str) -> None:
        good = make_contract()
        with pytest.raises(ValueError, match=r"exact X.Y.Z patch release"):
            dataclasses.replace(good, python_version=bad)

    def test_wrong_schema_version_is_rejected(self) -> None:
        good = make_contract()
        with pytest.raises(ValueError, match="unsupported environment schema version"):
            dataclasses.replace(good, environment_schema_version=ENVIRONMENT_SCHEMA_VERSION + 1)

    def test_bad_hash_is_rejected(self) -> None:
        good = make_contract()
        with pytest.raises(ValueError, match="uv_lock_sha256"):
            dataclasses.replace(good, uv_lock_sha256="nothex")


class TestStrictJSONParsing:
    def _mutate(self, **changes: Any) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(make_contract().to_json_bytes())
        payload.update(changes)
        return payload

    def test_unknown_key_is_rejected(self) -> None:
        payload = self._mutate(unexpected="x")
        with pytest.raises(ValueError, match="unknown=\\['unexpected'\\]"):
            RuntimeContract.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_missing_key_is_rejected(self) -> None:
        payload = json.loads(make_contract().to_json_bytes())
        del payload["machine"]
        with pytest.raises(ValueError, match="missing=\\['machine'\\]"):
            RuntimeContract.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_duplicate_key_is_rejected(self) -> None:
        raw = make_contract().to_json_bytes().decode("utf-8")
        # inject a duplicate "machine" key that json.dumps could never emit
        dup = raw.replace(
            '  "machine": "x86_64",',
            '  "machine": "x86_64",\n  "machine": "aarch64",',
            1,
        )
        assert dup != raw
        with pytest.raises(ValueError, match="duplicate JSON object key"):
            RuntimeContract.from_json_bytes(dup.encode("utf-8"))

    def test_non_finite_json_value_is_rejected(self) -> None:
        raw = make_contract().to_json_bytes().decode("utf-8")
        bad = raw.replace('"environment_schema_version": 1', '"environment_schema_version": NaN', 1)
        assert bad != raw
        with pytest.raises(ValueError, match="non-finite JSON constant"):
            RuntimeContract.from_json_bytes(bad.encode("utf-8"))

    def test_bool_in_int_field_is_rejected(self) -> None:
        payload = self._mutate(environment_schema_version=True)
        with pytest.raises(ValueError, match="environment_schema_version"):
            RuntimeContract.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_load_runtime_contract_wraps_errors(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime_contract.json"
        path.write_bytes(b"{ not json")
        with pytest.raises(RuntimeVerificationError, match="invalid runtime contract"):
            load_runtime_contract(path)


class TestRuntimeSnapshot:
    def test_current_snapshot_is_cpython(self) -> None:
        snap = current_runtime_snapshot()
        assert snap.python_implementation == "CPython"
        assert snap.package_version == eth_research.__version__

    def test_role_constant(self) -> None:
        assert AUTHORITATIVE_RUNTIME_ROLE == "authoritative-benchmark-runtime"

    def test_snapshot_rejects_bad_version_format(self) -> None:
        good = current_runtime_snapshot()
        with pytest.raises(ValueError, match=r"exact X.Y.Z patch release"):
            dataclasses.replace(good, python_version="3.12")
