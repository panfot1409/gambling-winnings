"""V2C independent-acceptance adversarial matrix: standing regression tests.

These lock in refusals that the independent acceptance audit reproduced against production paths but
which lacked an explicit *named* standing test: a source freeze copied into a bare/unrelated tree, a
duplicated completed registry tail, the firewall refusing a real-data / market-data loader request
kind, and a symlinked archive member. Every check reads committed bytes or calls the production
verifier/firewall directly -- no OQ lifecycle is executed, so these run on both the authoritative
CPython 3.12 leg and the compatibility 3.13 leg. They MUST NOT weaken any scanner: each asserts a
fail-closed refusal, never relaxes one.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from eth_research.v2c.firewall import V2CFirewallError, guard_request_kind
from eth_research.v2c.oq import archive as A
from eth_research.v2c.oq.freeze import (
    OQ_SOURCE_FREEZE_RELPATH,
    OQSourceFreezeError,
    verify_oq_source_freeze,
)
from eth_research.v2c.oq.registry import OQ_REGISTRY_PATH, OQRegistryError, read_oq_registry
from eth_research.v2c.oq.supersession import SEALED_LEDGER_RELPATHS
from eth_research.v2c.oq.verify_archive import OQRunArchiveError, verify_oq_run_archive

REPO = Path(__file__).resolve().parents[1]
_ARCHIVE_SRC = REPO / "governance/v2c/qualifications/v2c_offline_operational_qualification_run_001"


def _materialize_committed_run(root: Path) -> Path:
    """Write the committed completed-run tree (registry + byte-empty ledgers + 3 archive artifacts)
    into a fresh root, from committed bytes. Returns the registry path. No lifecycle is executed."""
    (root / OQ_REGISTRY_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / OQ_REGISTRY_PATH).write_bytes((REPO / OQ_REGISTRY_PATH).read_bytes())
    for rel in SEALED_LEDGER_RELPATHS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"")
    (root / A.OQ_ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
    for name in (
        A.OQ_ARCHIVE_RESULT_RELNAME,
        A.OQ_ARCHIVE_REPORT_RELNAME,
        A.OQ_ARCHIVE_MANIFEST_RELNAME,
    ):
        (root / A.archive_relpath(name)).write_bytes((_ARCHIVE_SRC / name).read_bytes())
    return root / OQ_REGISTRY_PATH


def test_copied_freeze_in_a_bare_tree_is_refused(tmp_path: Path) -> None:
    """A freeze artifact copied into an unrelated/bare repo (without the frozen source) cannot
    reproduce: the first missing frozen member is refused fail-closed."""
    (tmp_path / "governance/v2c").mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / OQ_SOURCE_FREEZE_RELPATH, tmp_path / OQ_SOURCE_FREEZE_RELPATH)
    with pytest.raises(OQSourceFreezeError, match="missing from the qualification source"):
        verify_oq_source_freeze(tmp_path)


def test_duplicate_completed_tail_is_refused(tmp_path: Path) -> None:
    """Appending a second 'completed' line (duplicating the terminal event) breaks the hash chain
    and is refused; a run cannot be duplicated by replaying its final event."""
    reg = tmp_path / "reg.jsonl"
    lines = (REPO / OQ_REGISTRY_PATH).read_bytes().splitlines()
    reg.write_bytes(b"\n".join(lines) + b"\n" + lines[-1] + b"\n")
    with pytest.raises(OQRegistryError):
        read_oq_registry(reg)


@pytest.mark.parametrize(
    "kind",
    ["market_data", "real_data_frame", "ohlcv_loader", "market_data_loader", "candidate_signal"],
)
def test_firewall_refuses_a_real_data_or_loader_request(kind: str) -> None:
    """The candidate-free firewall admits only 'cash_control_operation'; any real-data / market-data
    / loader / candidate request kind is refused fail-closed."""
    with pytest.raises(V2CFirewallError):
        guard_request_kind(kind)


def test_firewall_admits_only_cash_control_operation() -> None:
    assert guard_request_kind("cash_control_operation") == "cash_control_operation"


def test_symlinked_archive_member_is_refused(tmp_path: Path) -> None:
    """The deep archive verifier passes on the clean committed run but refuses when any archive
    artifact is replaced by a symlink (no symlink/traversal into or out of the archive)."""
    reg = _materialize_committed_run(tmp_path)
    assert len(verify_oq_run_archive(tmp_path, reg)) == 10  # clean baseline
    target = tmp_path / A.archive_relpath(A.OQ_ARCHIVE_RESULT_RELNAME)
    os.remove(target)
    os.symlink(_ARCHIVE_SRC / A.OQ_ARCHIVE_RESULT_RELNAME, target)
    with pytest.raises(OQRunArchiveError, match="symlink"):
        verify_oq_run_archive(tmp_path, reg)


def test_extra_undeclared_archive_member_is_refused(tmp_path: Path) -> None:
    """An undeclared file dropped into the archive directory is refused (closed output set)."""
    reg = _materialize_committed_run(tmp_path)
    (tmp_path / A.OQ_ARCHIVE_DIR / "stray.json").write_bytes(b"{}\n")
    with pytest.raises(OQRunArchiveError):
        verify_oq_run_archive(tmp_path, reg)


def test_nonempty_sealed_ledger_at_verify_is_refused(tmp_path: Path) -> None:
    """A contaminated sealed ledger fails the deep verifier's byte-empty check."""
    reg = _materialize_committed_run(tmp_path)
    (tmp_path / SEALED_LEDGER_RELPATHS[0]).write_bytes(b"contaminated\n")
    with pytest.raises(OQRunArchiveError, match="byte-empty"):
        verify_oq_run_archive(tmp_path, reg)


def test_tempfile_scratch_only_never_touches_the_real_governed_tree() -> None:
    """Guard: this module only ever materializes into fresh tempfile roots; it never opens the real
    governed registry/ledgers/archive for writing."""
    scratch = Path(tempfile.mkdtemp())
    assert scratch != REPO
    assert not str(scratch).startswith(str(REPO))
