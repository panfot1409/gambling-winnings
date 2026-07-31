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
    main,
    verify_runtime_contract,
    verify_runtime_snapshot,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def make_contract() -> RuntimeContract:
    return RuntimeContract.for_current_runtime(REPO_ROOT)


def copy_lockfiles(dst: Path) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "uv.lock").write_bytes((REPO_ROOT / "uv.lock").read_bytes())
    (dst / "pyproject.toml").write_bytes((REPO_ROOT / "pyproject.toml").read_bytes())
    return dst


#: Every interpreter-observable field that must be compared exactly.
IDENTITY_FIELDS: tuple[str, ...] = (
    "python_version",
    "python_implementation",
    "python_cache_tag",
    "os_family",
    "machine",
    "package_version",
    "numpy_version",
    "pandas_version",
    "pyarrow_version",
)

#: The identity fields ``verify_runtime_snapshot`` compares. It deliberately ignores
#: ``package_version`` so a later package over the same frozen runtime still verifies.
SNAPSHOT_FIELDS: tuple[str, ...] = tuple(f for f in IDENTITY_FIELDS if f != "package_version")


def differing(field: str) -> str:
    """A value for ``field`` that cannot equal this host's value, on any host.

    These parametrizations used to hard-code the "wrong" value — ``os_family="Darwin"``,
    ``machine="arm64"``, ``python_version="3.11.9"``. That works only until the suite runs on
    a host where the hard-coded wrong value is the *right* one. On an arm64 Mac,
    ``os_family="Darwin"`` and ``machine="arm64"`` are what ``current_runtime_snapshot()``
    already reports, so replacing the field changed nothing, the guard correctly saw no
    mismatch, and four tests failed while the code under test was behaving perfectly.

    A test whose outcome depends on which machine it runs on gives false assurance in one
    direction or the other, so the wrong value is now derived from the live one.

    The derived value must stay *shape-valid*, because some fields are validated on
    construction — ``python_version`` must be an exact ``X.Y.Z``, so a plain suffix raises
    ``ValueError`` before the identity comparison under test is ever reached. Version-shaped
    values therefore get their last component bumped, which is unequal by construction while
    remaining a legal version; everything else gets a suffix.
    """
    live = str(getattr(current_runtime_snapshot(), field))
    parts = live.split(".")
    if len(parts) >= 2 and all(p.isdigit() for p in parts):
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return f"{live}-not-the-authoritative-runtime"


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

    @pytest.mark.parametrize("field", IDENTITY_FIELDS)
    def test_mismatched_field_is_rejected(self, field: str) -> None:
        contract = make_contract()
        wrong = dataclasses.replace(current_runtime_snapshot(), **{field: differing(field)})
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
        # Inject a duplicate "machine" key that json.dumps could never emit. The line is
        # rebuilt from the value this host actually reports: it used to be spelled with a
        # literal "x86_64", so on an arm64 host str.replace matched nothing and the test
        # failed at its own setup. That it failed rather than passing vacuously is down to
        # the `dup != raw` assertion below, which is why it stays.
        machine = current_runtime_snapshot().machine
        original = f'  "machine": "{machine}",'
        assert original in raw, f"contract JSON no longer contains {original!r}"
        dup = raw.replace(original, f'{original}\n  "machine": "{machine}-duplicate",', 1)
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


class TestRuntimeSnapshotVerification:
    """The version-independent numerical runtime identity check."""

    def test_snapshot_passes_for_current_runtime(self) -> None:
        verify_runtime_snapshot(make_contract())

    def test_snapshot_ignores_package_version_drift(self) -> None:
        # A later package over the same frozen contract: the identity still
        # matches even though the package version differs.
        contract = make_contract()
        drifted = dataclasses.replace(current_runtime_snapshot(), package_version="9.9.9")
        verify_runtime_snapshot(contract, snapshot=drifted)

    def test_snapshot_also_ignores_a_drifted_contract_version(self) -> None:
        contract = dataclasses.replace(make_contract(), package_version="9.9.9")
        verify_runtime_snapshot(contract)

    @pytest.mark.parametrize("field", SNAPSHOT_FIELDS)
    def test_snapshot_rejects_interpreter_mismatch(self, field: str) -> None:
        contract = make_contract()
        wrong = dataclasses.replace(current_runtime_snapshot(), **{field: differing(field)})
        with pytest.raises(RuntimeVerificationError, match=f"runtime mismatch on {field}"):
            verify_runtime_snapshot(contract, snapshot=wrong)

    def test_snapshot_rejects_non_authoritative_role(self) -> None:
        good = make_contract()
        rogue = object.__new__(RuntimeContract)
        for f in dataclasses.fields(good):
            object.__setattr__(rogue, f.name, getattr(good, f.name))
        object.__setattr__(rogue, "runtime_role", "compatibility")
        with pytest.raises(RuntimeVerificationError, match="not the authoritative"):
            verify_runtime_snapshot(rogue)


class TestEnvironmentCli:
    """``main()`` snapshot-awareness, exercised interpreter-independently via a
    synthetic contract built from — and matching — the current runtime."""

    def _repo_with_contract(self, tmp_path: Path, *, package_version: str | None) -> Path:
        repo = copy_lockfiles(tmp_path / "repo")
        contract = make_contract()
        if package_version is not None:
            contract = dataclasses.replace(contract, package_version=package_version)
        contract_path = repo / CANONICAL_RUNTIME_CONTRACT_RELPATH
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_bytes(contract.to_json_bytes())
        return repo

    def test_compat_parses_even_when_version_drifts(self, tmp_path: Path) -> None:
        repo = self._repo_with_contract(tmp_path, package_version="9.9.9")
        assert main(["--repo-root", str(repo), "--compat"]) == 0

    def test_default_verifies_the_exact_frozen_runtime(self, tmp_path: Path) -> None:
        # Contract package == live package: the full contract verifies.
        repo = self._repo_with_contract(tmp_path, package_version=None)
        assert main(["--repo-root", str(repo)]) == 0

    def test_default_snapshot_verifies_a_superseded_contract(self, tmp_path: Path) -> None:
        repo = self._repo_with_contract(tmp_path, package_version="9.9.9")
        assert main(["--repo-root", str(repo)]) == 0

    def test_production_refuses_a_superseded_contract(self, tmp_path: Path) -> None:
        repo = self._repo_with_contract(tmp_path, package_version="9.9.9")
        assert main(["--repo-root", str(repo), "--production"]) == 1

    def test_production_verifies_the_exact_frozen_runtime(self, tmp_path: Path) -> None:
        repo = self._repo_with_contract(tmp_path, package_version=None)
        assert main(["--repo-root", str(repo), "--production"]) == 0

    def test_missing_contract_reports_active_snapshot(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert main(["--repo-root", str(empty)]) == 0


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
