"""The public-API and CLI-reference drift guards."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import eth_research
from eth_research.m4a import cli_reference, public_api

REPO = Path(eth_research.__file__).resolve().parents[2]
# The RC snapshots (argparse help text especially) are rendered by a specific CPython; the
# committed artifacts are pinned to the authoritative interpreter.
_PINNED = sys.version_info[:2] == cli_reference.PINNED_PYTHON
_skip = pytest.mark.skipif(not _PINNED, reason="RC snapshots are pinned to CPython 3.12")


def test_public_api_snapshot_is_self_consistent() -> None:
    snapshot = public_api.build_snapshot()
    assert snapshot["api_version"] == eth_research.api.API_VERSION
    assert set(snapshot["symbols"]) == set(eth_research.api.__all__)


@_skip
def test_public_api_snapshot_is_current() -> None:
    public_api.verify(REPO)


@_skip
def test_cli_reference_is_current() -> None:
    cli_reference.verify(REPO)


def test_public_api_drift_is_detected(tmp_path: Path) -> None:
    target = tmp_path / public_api.SNAPSHOT_RELPATH
    target.parent.mkdir(parents=True)
    target.write_bytes(b'{"snapshot_schema_version": 1, "api_version": "9.9", "symbols": {}}\n')
    with pytest.raises(public_api.PublicAPIDriftError):
        public_api.verify(tmp_path)


def test_cli_reference_drift_is_detected(tmp_path: Path) -> None:
    target = tmp_path / cli_reference.REFERENCE_RELPATH
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not the real reference\n")
    with pytest.raises(cli_reference.CLIReferenceDriftError):
        cli_reference.verify(tmp_path)


def test_missing_snapshot_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(public_api.PublicAPIDriftError):
        public_api.verify(tmp_path)
    with pytest.raises(cli_reference.CLIReferenceDriftError):
        cli_reference.verify(tmp_path)
