"""Read-only CLI for the Fable 5 system inventory.

    python -m eth_research.v2.fable5 build  --repo-root . [--write]
    python -m eth_research.v2.fable5 verify --repo-root .

``build`` prints (or, with ``--write``, canonically writes) the inventory; ``verify`` rebuilds the
inventory and proves it matches the committed snapshot, exiting non-zero on any drift or structural
red flag. Neither subcommand mutates governed state (``build --write`` writes only the inventory
file itself) or evaluates any strategy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eth_research.v2.fable5.inventory import (
    FABLE5_INVENTORY_RELPATH,
    Fable5InventoryError,
    build_system_inventory,
    verify_system_inventory,
)
from eth_research.v2.strict import canonical_json_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eth_research.v2.fable5")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--repo-root", default=".")
        if name == "build":
            p.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)

    if args.command == "build":
        inv = build_system_inventory(root)
        payload = canonical_json_bytes(inv)
        if args.write:
            out = root / FABLE5_INVENTORY_RELPATH
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload + b"\n")
            print(
                f"wrote {FABLE5_INVENTORY_RELPATH} ({len(inv['governed_artifacts'])} governed, "
                f"{len(inv['package_modules'])} modules)"
            )
        else:
            sys.stdout.write(payload.decode() + "\n")
        return 0

    if args.command == "verify":
        committed_path = root / FABLE5_INVENTORY_RELPATH
        if not committed_path.exists():
            print(f"missing committed inventory: {FABLE5_INVENTORY_RELPATH}", file=sys.stderr)
            return 2
        committed = json.loads(committed_path.read_text())
        try:
            checks = verify_system_inventory(root, committed)
        except Fable5InventoryError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps({"ok": True, "checks": checks}))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
