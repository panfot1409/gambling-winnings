"""Frozen numerical-runtime contract for the authorized benchmark.

The C1 package-source binding proves the *code* executing an evaluation is
the code committed at the authorized ``HEAD``. It does not prove anything
about the *numerical* environment that code runs in: the same clean source
executed against a different NumPy, pandas, PyArrow, Python implementation,
or lockfile can parse, round, serialize, or reconcile differently.

This module closes that gap with a strict, immutable runtime contract:

* :class:`RuntimeContract` records the one authoritative benchmark runtime
  — CPython patch version, cache tag, OS family, architecture, the exact
  ``numpy``/``pandas``/``pyarrow`` versions, the ``eth_research`` version,
  and the SHA-256 of ``uv.lock`` and ``pyproject.toml``;
* :func:`current_runtime_snapshot` recomputes the live environment from
  the standard library and :mod:`importlib.metadata`;
* :func:`verify_runtime_contract` requires the live snapshot to equal the
  contract exactly and the working ``uv.lock``/``pyproject.toml`` to hash
  to the contract's recorded digests.

Scope and honesty: this is a **local, single-repository reproducibility
control**, not a cryptographic attestation. It proves the active
interpreter, numerical stack, and lockfiles match a committed contract; it
cannot attest a remote, a CI provider, or a hardware root of trust. The
existing Python 3.12 and 3.13 CI matrix stays as *compatibility* coverage;
the authorized benchmark runs only under the exact authoritative contract.
"""

from __future__ import annotations

import json
import platform
import re
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from pathlib import Path
from typing import Any

from eth_research import __version__
from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.provenance import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
    sha256_bytes,
)

ENVIRONMENT_SCHEMA_VERSION: int = 1

AUTHORITATIVE_RUNTIME_ROLE: str = "authoritative-benchmark-runtime"
"""The one role a contract used by the authorized evaluator may declare."""

REQUIRED_PYTHON_IMPLEMENTATION: str = "CPython"
"""The benchmark runtime must be CPython; alternative implementations differ
in float and hashing behaviour and are refused."""

CANONICAL_RUNTIME_CONTRACT_RELPATH: str = "research/m2b/runtime_contract.json"
"""The one authoritative, tracked location of the runtime contract."""

PINNED_DEPENDENCIES: tuple[str, ...] = ("numpy", "pandas", "pyarrow")
"""The numerical dependencies whose exact versions the contract pins."""

_UV_LOCK_RELPATH: str = "uv.lock"
_PYPROJECT_RELPATH: str = "pyproject.toml"

_PY_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

_CONTRACT_KEYS: frozenset[str] = frozenset(
    {
        "environment_schema_version",
        "runtime_role",
        "package_version",
        "python_implementation",
        "python_version",
        "python_cache_tag",
        "os_family",
        "machine",
        "numpy_version",
        "pandas_version",
        "pyarrow_version",
        "uv_lock_sha256",
        "pyproject_sha256",
    }
)


class RuntimeVerificationError(RuntimeError):
    """The active runtime does not match the authoritative contract."""


@dataclass(frozen=True)
class RuntimeSnapshot:
    """The live numerical runtime, recomputed from the standard library.

    Carries only the fields an interpreter can observe about itself; the
    lockfile digests live on :class:`RuntimeContract` and are checked
    against files on disk, not recomputed here.
    """

    python_implementation: str
    python_version: str
    python_cache_tag: str
    os_family: str
    machine: str
    package_version: str
    numpy_version: str
    pandas_version: str
    pyarrow_version: str

    def __post_init__(self) -> None:
        for label in (
            "python_implementation",
            "python_version",
            "python_cache_tag",
            "os_family",
            "machine",
            "package_version",
            "numpy_version",
            "pandas_version",
            "pyarrow_version",
        ):
            require_nonempty_str(label, getattr(self, label))
        if not _PY_VERSION_RE.match(self.python_version):
            raise ValueError(
                f"python_version must be an exact X.Y.Z patch release, got {self.python_version!r}"
            )


def _dist(label: str, name: str) -> str:
    try:
        return _dist_version(name)
    except PackageNotFoundError as exc:  # pragma: no cover - defensive
        raise RuntimeVerificationError(
            f"{label} distribution {name!r} is not installed in the active environment"
        ) from exc


def current_runtime_snapshot() -> RuntimeSnapshot:
    """The active runtime, from :mod:`sys`, :mod:`platform`, metadata."""
    cache_tag = sys.implementation.cache_tag
    if cache_tag is None:  # pragma: no cover - only exotic implementations
        raise RuntimeVerificationError(
            "the active interpreter has no import cache tag; refusing to attest it"
        )
    return RuntimeSnapshot(
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        python_cache_tag=cache_tag,
        os_family=platform.system(),
        machine=platform.machine(),
        package_version=__version__,
        numpy_version=_dist("numpy", "numpy"),
        pandas_version=_dist("pandas", "pandas"),
        pyarrow_version=_dist("pyarrow", "pyarrow"),
    )


@dataclass(frozen=True)
class RuntimeContract:
    """Immutable pin of the one authoritative benchmark runtime.

    Every field is validated in ``__post_init__`` — the single shared
    validation path for constructed and parsed contracts alike.
    """

    environment_schema_version: int
    runtime_role: str
    package_version: str
    python_implementation: str
    python_version: str
    python_cache_tag: str
    os_family: str
    machine: str
    numpy_version: str
    pandas_version: str
    pyarrow_version: str
    uv_lock_sha256: str
    pyproject_sha256: str

    def __post_init__(self) -> None:
        version = require_int("environment_schema_version", self.environment_schema_version)
        if version != ENVIRONMENT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported environment schema version {version!r}; "
                f"this package reads version {ENVIRONMENT_SCHEMA_VERSION}"
            )
        if require_str("runtime_role", self.runtime_role) != AUTHORITATIVE_RUNTIME_ROLE:
            raise ValueError(
                f"runtime_role must be {AUTHORITATIVE_RUNTIME_ROLE!r} (the only role the "
                f"authorized evaluator accepts), got {self.runtime_role!r}"
            )
        if require_str("python_implementation", self.python_implementation) != (
            REQUIRED_PYTHON_IMPLEMENTATION
        ):
            raise ValueError(
                f"python_implementation must be {REQUIRED_PYTHON_IMPLEMENTATION!r}; the benchmark "
                f"runtime is CPython-only, got {self.python_implementation!r}"
            )
        for label in (
            "package_version",
            "python_version",
            "python_cache_tag",
            "os_family",
            "machine",
            "numpy_version",
            "pandas_version",
            "pyarrow_version",
        ):
            require_nonempty_str(label, getattr(self, label))
        if not _PY_VERSION_RE.match(self.python_version):
            raise ValueError(
                f"python_version must be an exact X.Y.Z patch release, got {self.python_version!r}"
            )
        require_hex64("uv_lock_sha256", self.uv_lock_sha256)
        require_hex64("pyproject_sha256", self.pyproject_sha256)

    @property
    def snapshot(self) -> RuntimeSnapshot:
        """The interpreter-observable subset this contract requires."""
        return RuntimeSnapshot(
            python_implementation=self.python_implementation,
            python_version=self.python_version,
            python_cache_tag=self.python_cache_tag,
            os_family=self.os_family,
            machine=self.machine,
            package_version=self.package_version,
            numpy_version=self.numpy_version,
            pandas_version=self.pandas_version,
            pyarrow_version=self.pyarrow_version,
        )

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "environment_schema_version": self.environment_schema_version,
            "runtime_role": self.runtime_role,
            "package_version": self.package_version,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "python_cache_tag": self.python_cache_tag,
            "os_family": self.os_family,
            "machine": self.machine,
            "numpy_version": self.numpy_version,
            "pandas_version": self.pandas_version,
            "pyarrow_version": self.pyarrow_version,
            "uv_lock_sha256": self.uv_lock_sha256,
            "pyproject_sha256": self.pyproject_sha256,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> RuntimeContract:
        """Strict parse feeding the shared constructor validation."""
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"runtime contract is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("runtime contract JSON must be an object")
        keys = set(payload)
        if keys != _CONTRACT_KEYS:
            unknown = sorted(keys - _CONTRACT_KEYS)
            missing = sorted(_CONTRACT_KEYS - keys)
            raise ValueError(
                f"runtime contract keys do not match schema: unknown={unknown}, missing={missing}"
            )
        return cls(
            environment_schema_version=payload["environment_schema_version"],
            runtime_role=payload["runtime_role"],
            package_version=payload["package_version"],
            python_implementation=payload["python_implementation"],
            python_version=payload["python_version"],
            python_cache_tag=payload["python_cache_tag"],
            os_family=payload["os_family"],
            machine=payload["machine"],
            numpy_version=payload["numpy_version"],
            pandas_version=payload["pandas_version"],
            pyarrow_version=payload["pyarrow_version"],
            uv_lock_sha256=payload["uv_lock_sha256"],
            pyproject_sha256=payload["pyproject_sha256"],
        )

    @classmethod
    def for_current_runtime(cls, repo_root: str | Path) -> RuntimeContract:
        """Build the authoritative contract from the active runtime and repo.

        Offline generator: reads the current interpreter/metadata and hashes
        the repository's ``uv.lock`` and ``pyproject.toml``. Used once to
        create the tracked contract; never trusted as verification input.
        """
        root = Path(repo_root)
        snapshot = current_runtime_snapshot()
        return cls(
            environment_schema_version=ENVIRONMENT_SCHEMA_VERSION,
            runtime_role=AUTHORITATIVE_RUNTIME_ROLE,
            package_version=snapshot.package_version,
            python_implementation=snapshot.python_implementation,
            python_version=snapshot.python_version,
            python_cache_tag=snapshot.python_cache_tag,
            os_family=snapshot.os_family,
            machine=snapshot.machine,
            numpy_version=snapshot.numpy_version,
            pandas_version=snapshot.pandas_version,
            pyarrow_version=snapshot.pyarrow_version,
            uv_lock_sha256=sha256_bytes(_read_required(root, _UV_LOCK_RELPATH)),
            pyproject_sha256=sha256_bytes(_read_required(root, _PYPROJECT_RELPATH)),
        )


def _read_required(repo_root: Path, relpath: str) -> bytes:
    path = repo_root / relpath
    if not path.is_file():
        raise RuntimeVerificationError(f"required file {relpath!r} is missing under {repo_root}")
    return path.read_bytes()


def load_runtime_contract(path: str | Path) -> RuntimeContract:
    """Strictly parse a runtime contract file."""
    try:
        return RuntimeContract.from_json_bytes(Path(path).read_bytes())
    except ValueError as exc:
        raise RuntimeVerificationError(
            f"invalid runtime contract {Path(path).name!r}: {exc}"
        ) from exc


def verify_runtime_contract(
    contract: RuntimeContract,
    *,
    repo_root: str | Path,
    snapshot: RuntimeSnapshot | None = None,
) -> None:
    """Require the active runtime to match ``contract`` exactly.

    Recomputes the live snapshot (unless one is supplied for testing),
    compares every interpreter-observable field, and requires the working
    ``uv.lock`` and ``pyproject.toml`` to hash to the contract's recorded
    digests. Raises :class:`RuntimeVerificationError` on any mismatch.

    The git binding — that those lockfiles equal their committed ``HEAD``
    blobs — is enforced by the evaluator alongside the other tracked
    inputs; this function proves the *active* runtime and *working*
    lockfiles agree with the contract.
    """
    if contract.runtime_role != AUTHORITATIVE_RUNTIME_ROLE:
        raise RuntimeVerificationError(
            f"runtime contract role {contract.runtime_role!r} is not the authoritative "
            "benchmark runtime; refusing to attest it"
        )
    active = snapshot if snapshot is not None else current_runtime_snapshot()
    expected = contract.snapshot
    for label in (
        "python_implementation",
        "python_version",
        "python_cache_tag",
        "os_family",
        "machine",
        "package_version",
        "numpy_version",
        "pandas_version",
        "pyarrow_version",
    ):
        want = getattr(expected, label)
        got = getattr(active, label)
        if want != got:
            raise RuntimeVerificationError(
                f"runtime mismatch on {label}: contract requires {want!r}, active runtime is "
                f"{got!r} — the authorized benchmark runs only under the frozen runtime"
            )
    root = Path(repo_root)
    for relpath, expected_sha in (
        (_UV_LOCK_RELPATH, contract.uv_lock_sha256),
        (_PYPROJECT_RELPATH, contract.pyproject_sha256),
    ):
        actual_sha = sha256_bytes(_read_required(root, relpath))
        if actual_sha != expected_sha:
            raise RuntimeVerificationError(
                f"{relpath} SHA-256 {actual_sha} does not match the contract's {expected_sha} — "
                "the locked dependency environment differs from the frozen runtime"
            )


def main(argv: list[str] | None = None) -> int:
    """CLI: verify (or compatibility-parse) the committed runtime contract.

    ``python -m eth_research.environment --repo-root .`` is the authoritative
    check: it requires the active runtime to match the committed contract. In
    ``--compat`` mode it only strictly parses the contract (a non-authoritative
    runtime may confirm the contract is well-formed without claiming to be the
    benchmark runtime). Before a contract is committed it prints the active
    snapshot and confirms the interpreter is CPython.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="eth_research.environment")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--compat",
        action="store_true",
        help="only parse the contract; do not require the active runtime to match",
    )
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    contract_path = root / CANONICAL_RUNTIME_CONTRACT_RELPATH
    snapshot = current_runtime_snapshot()
    label = (
        f"{snapshot.python_implementation} {snapshot.python_version} "
        f"({snapshot.python_cache_tag}, {snapshot.os_family}/{snapshot.machine}); "
        f"numpy {snapshot.numpy_version}, pandas {snapshot.pandas_version}, "
        f"pyarrow {snapshot.pyarrow_version}"
    )
    if not contract_path.exists():
        if snapshot.python_implementation != REQUIRED_PYTHON_IMPLEMENTATION:
            print(
                f"active runtime is {snapshot.python_implementation}, not "
                f"{REQUIRED_PYTHON_IMPLEMENTATION}",
                file=sys.stderr,
            )
            return 1
        print(f"no committed runtime contract yet; active runtime: {label}")
        return 0
    try:
        contract = load_runtime_contract(contract_path)
        if args.compat:
            print(f"runtime contract parses (compatibility runtime {label})")
        else:
            verify_runtime_contract(contract, repo_root=root)
            print(f"runtime contract verified against the active runtime: {label}")
    except RuntimeVerificationError as exc:
        print(f"runtime verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
