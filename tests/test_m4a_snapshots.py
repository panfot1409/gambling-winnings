"""The public-API and CLI-reference drift guards."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import eth_research
from eth_research.m4a import M4A_PACKAGE_VERSION, cli_reference, public_api

REPO = Path(eth_research.__file__).resolve().parents[2]
# The RC snapshots (argparse help text especially) are rendered by a specific CPython; the
# committed artifacts are pinned to the authoritative interpreter.
_PINNED = sys.version_info[:2] == cli_reference.PINNED_PYTHON
# The frozen M4A public-API / CLI snapshots capture the *1.0.0* release candidate. A later
# milestone stacked on M4A (e.g. M4B at 1.1.0) additively extends the public surface and the
# CLI, so a rebuild-vs-frozen check is expected to differ there — it is a development snapshot
# governed by its own milestone, not a re-verification of the frozen M4A RC. Guard on both the
# interpreter and the running version so these drift checks assert only where they apply.
_IS_M4A_RC = eth_research.__version__ == M4A_PACKAGE_VERSION
_skip = pytest.mark.skipif(
    not (_PINNED and _IS_M4A_RC),
    reason="M4A RC snapshots are pinned to CPython 3.12 and the 1.0.0 release candidate",
)


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
