"""Generated CLI reference for ``eth-research``, with a drift ``--check`` guard.

Walks the argparse parser (top level plus every sub- and sub-sub-command) with a fixed
terminal width and concatenates each command's ``--help`` output into one deterministic
document. The rendered help text depends on the exact CPython version's argparse formatting,
so the committed reference and its ``--check`` are pinned to the authoritative interpreter
(CPython 3.12); callers on another version should skip the drift check.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path

from eth_research.cli.app import build_parser

REFERENCE_RELPATH = "research/m4a/cli_reference.txt"
PINNED_PYTHON = (3, 12)


class CLIReferenceDriftError(RuntimeError):
    """The committed CLI reference no longer matches the CLI."""


@contextlib.contextmanager
def _fixed_width(columns: int = 80) -> Iterator[None]:
    previous = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = str(columns)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = previous


def _collect(parser: argparse.ArgumentParser) -> list[str]:
    sections = [parser.format_help().rstrip()]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for subparser in action.choices.values():
                sections.extend(_collect(subparser))
    return sections


def build_reference() -> str:
    """Render the full CLI reference as one deterministic text document."""
    with _fixed_width():
        sections = _collect(build_parser())
    return "\n\n\n".join(sections) + "\n"


def reference_bytes() -> bytes:
    return build_reference().encode("utf-8")


def verify(repo_root: str | Path) -> None:
    """Raise :class:`CLIReferenceDriftError` unless the committed reference matches the CLI."""
    path = Path(repo_root) / REFERENCE_RELPATH
    try:
        committed = path.read_bytes()
    except OSError as exc:
        raise CLIReferenceDriftError(
            f"CLI reference missing at {REFERENCE_RELPATH}: {exc}"
        ) from exc
    if committed != reference_bytes():
        raise CLIReferenceDriftError(
            "the CLI changed but research/m4a/cli_reference.txt was not regenerated"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CLI reference: --check or --write.")
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.repo_root) / REFERENCE_RELPATH
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(reference_bytes())
        sys.stdout.write(f"wrote {REFERENCE_RELPATH}\n")
        return 0
    try:
        verify(args.repo_root)
    except CLIReferenceDriftError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write("CLI reference is current\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
