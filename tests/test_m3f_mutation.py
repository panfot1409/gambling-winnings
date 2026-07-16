"""M3F mutation matrix + transactional publication (commit: mutation matrix).

Every committed artifact is mutated in turn against a registered clone, and the
verifier responsible for it must detect the mutation. This proves the freeze
graph has no blind spot: each artifact is actually covered by a check that fails
closed when its bytes change. Mutations are applied through a restoring context
manager so the shared clone stays clean between cases.

The registration writer is also shown to be transactional: a derivation failure
publishes nothing, and a write failure rolls back every newly created file.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import eth_research
from eth_research.m3f import register
from eth_research.m3f.audit import verify_repository_freeze
from eth_research.m3f.bundle import CAPSULE_MANIFEST_RELPATH, verify_manifest
from eth_research.m3f.catalog import CATALOG_RELPATH, verify_catalog
from eth_research.m3f.dependency_inventory import INVENTORY_RELPATH as DEP_RELPATH
from eth_research.m3f.dependency_inventory import verify_inventory as verify_dep
from eth_research.m3f.honest_state import (
    HONEST_STATE_RELPATH,
    derive_honest_state,
    verify_honest_state,
)
from eth_research.m3f.oracle import run_oracles
from eth_research.m3f.recovery import DRILL_RELPATH, verify_drill_record
from eth_research.m3f.validation import M3FValidationError
from eth_research.m3f.workflow_inventory import INVENTORY_RELPATH as WF_RELPATH
from eth_research.m3f.workflow_inventory import verify_inventory as verify_wf

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture(scope="module")
def registered_clone(tmp_path_factory: pytest.TempPathFactory) -> Path:
    clone = tmp_path_factory.mktemp("m3f-mutation") / "clone"
    subprocess.run(["git", "clone", "--quiet", "--local", str(REPO_ROOT), str(clone)], check=True)
    _git(clone, "config", "user.email", "a@b.c")
    _git(clone, "config", "user.name", "T")
    freeze = _git(clone, "rev-parse", "HEAD").strip()
    register.write_registration_artifacts(clone, source_freeze_sha=freeze, accepted_main_sha=freeze)
    _git(clone, "add", "-A")
    _git(clone, "commit", "--quiet", "-m", "R")
    register.write_drill_record(clone)
    _git(clone, "add", "-A")
    _git(clone, "commit", "--quiet", "-m", "P")
    return clone


@contextmanager
def _mutated(path: Path, new_bytes: bytes) -> Iterator[None]:
    original = path.read_bytes()
    try:
        path.write_bytes(new_bytes)
        yield
    finally:
        path.write_bytes(original)


# Each detector runs the single verifier responsible for the mutated artifact and
# returns True iff it caught the tamper.
def _catalog_detects(root: Path) -> bool:
    try:
        return not verify_catalog(root).ok
    except M3FValidationError:
        return True  # a catalog that cannot even parse into a result is detected


def _raises(fn: Callable[[Path], object], root: Path) -> bool:
    try:
        fn(root)
    except M3FValidationError:
        return True
    return False


def _oracle_detects(root: Path) -> bool:
    return not run_oracles(root).ok


_TAMPER = b'{"schema_version": 1}\n'

# (case name, mutated relpath, replacement bytes, detector)
_MUTATIONS: list[tuple[str, str, bytes, Callable[[Path], bool]]] = [
    ("accepted_artifact", "research/m2b/README.md", b"# tampered\n", _catalog_detects),
    ("freeze_catalog_self", CATALOG_RELPATH, _TAMPER, _catalog_detects),
    ("honest_state", HONEST_STATE_RELPATH, _TAMPER, lambda r: _raises(verify_honest_state, r)),
    ("dependency_inventory", DEP_RELPATH, _TAMPER, lambda r: _raises(verify_dep, r)),
    ("workflow_inventory", WF_RELPATH, _TAMPER, lambda r: _raises(verify_wf, r)),
    ("capsule_manifest", CAPSULE_MANIFEST_RELPATH, _TAMPER, lambda r: _raises(verify_manifest, r)),
    ("recovery_drill", DRILL_RELPATH, _TAMPER, lambda r: _raises(verify_drill_record, r)),
    (
        "m3d_provenance",
        "research/m3d/prospective_manifest.json",
        b'{"tampered": true}\n',
        _oracle_detects,
    ),
    (
        "sealed_ledger",
        "research/m2b/test_evaluations.jsonl",
        b'{"leak": true}\n',
        lambda r: _raises(derive_honest_state, r),
    ),
]


@pytest.mark.parametrize("case", _MUTATIONS, ids=[m[0] for m in _MUTATIONS])
def test_mutation_is_detected(
    registered_clone: Path, case: tuple[str, str, bytes, Callable[[Path], bool]]
) -> None:
    _name, relpath, replacement, detector = case
    target = registered_clone / relpath
    with _mutated(target, replacement):
        assert detector(registered_clone) is True


def test_clean_registered_clone_verifies(registered_clone: Path) -> None:
    # Sanity: with no mutation active, the whole graph is green.
    result = verify_repository_freeze(registered_clone)
    result.raise_for_status()
    assert result.ok


def test_whole_graph_surfaces_honest_state_mutation(registered_clone: Path) -> None:
    target = registered_clone / HONEST_STATE_RELPATH
    with _mutated(target, b'{"schema_version": 1}\n'):
        result = verify_repository_freeze(registered_clone)
        assert not result.ok
        assert any(f.startswith("05_honest_state_reproduces") for f in result.failures)


# --------------------------------------------------------------------------- #
# transactional publication                                                    #
# --------------------------------------------------------------------------- #
def test_registration_publishes_nothing_on_derivation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", "--local", str(REPO_ROOT), str(clone)], check=True)
    freeze = _git(clone, "rev-parse", "HEAD").strip()

    def boom(_root: Path) -> dict[str, object]:
        raise M3FValidationError("synthetic derivation failure")

    monkeypatch.setattr(register, "derive_honest_state", boom)
    with pytest.raises(M3FValidationError, match="synthetic"):
        register.write_registration_artifacts(
            clone, source_freeze_sha=freeze, accepted_main_sha=freeze
        )
    # No R artifact was written — publication is all-or-nothing.
    assert not (clone / "research/m3f").exists() or not any((clone / "research/m3f").iterdir())


def test_publish_rolls_back_newly_created_files_on_write_error(tmp_path: Path) -> None:
    root = tmp_path
    good = "research/m3f/a.json"
    # The second entry's parent is the first entry (a file), so mkdir raises OSError.
    pairs = [(good, b"{}\n"), ("research/m3f/a.json/child", b"x")]
    with pytest.raises((FileExistsError, NotADirectoryError)):
        register._publish_atomically(root, pairs)
    assert not (root / good).exists()  # the first write was rolled back


def test_publish_restores_preexisting_files_on_reregistration_failure(tmp_path: Path) -> None:
    # B5: a failed re-registration must not corrupt already-committed artifacts.
    (tmp_path / "research/m3f").mkdir(parents=True)
    (tmp_path / "research/m3f/a.json").write_bytes(b"OLD-A")
    (tmp_path / "research/m3f/b.json").write_bytes(b"OLD-B")
    pairs = [
        ("research/m3f/a.json", b"NEW-A"),
        ("research/m3f/b.json", b"NEW-B"),
        ("research/m3f/a.json/child", b"x"),  # parent is now a file -> OSError mid-run
    ]
    with pytest.raises((FileExistsError, NotADirectoryError)):
        register._publish_atomically(tmp_path, pairs)
    assert (tmp_path / "research/m3f/a.json").read_bytes() == b"OLD-A"
    assert (tmp_path / "research/m3f/b.json").read_bytes() == b"OLD-B"
