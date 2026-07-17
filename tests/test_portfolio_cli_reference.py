"""The committed M4B CLI reference is current, and its drift guard fails closed.

The rendered ``--help`` text depends on the exact CPython version's argparse formatting, so the
byte-equality drift check is pinned to the authoritative interpreter (CPython 3.12) and skipped
elsewhere; the fail-closed behavior is exercised on every interpreter.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from eth_research.portfolio import cli_reference

REPO = Path(__file__).resolve().parents[1]
_PINNED = sys.version_info[:2] == cli_reference.PINNED_PYTHON


@pytest.mark.skipif(not _PINNED, reason="argparse help text is pinned to CPython 3.12")
def test_cli_reference_is_current() -> None:
    cli_reference.verify(REPO)


@pytest.mark.skipif(not _PINNED, reason="argparse help text is pinned to CPython 3.12")
def test_cli_reference_covers_every_command_group() -> None:
    text = (REPO / cli_reference.REFERENCE_RELPATH).read_text(encoding="utf-8")
    # The read-only offline groups and their subcommands must all render into the document.
    for token in ("universe", "portfolio", "inspect", "validate", "demo", "verify"):
        assert token in text


def test_cli_reference_drift_is_detected(tmp_path: Path) -> None:
    target = tmp_path / cli_reference.REFERENCE_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"not the real reference\n")
    with pytest.raises(cli_reference.CLIReferenceDriftError):
        cli_reference.verify(tmp_path)


def test_cli_reference_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(cli_reference.CLIReferenceDriftError):
        cli_reference.verify(tmp_path)
