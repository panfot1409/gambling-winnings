"""Read-only CLI for the Fable 5 system inventory and paper-readiness gate.

    python -m eth_research.v2.fable5 build            --repo-root . [--write]
    python -m eth_research.v2.fable5 verify           --repo-root .
    python -m eth_research.v2.fable5 paper-readiness  --repo-root . [--write]
    python -m eth_research.v2.fable5 verify-paper     --repo-root .
    python -m eth_research.v2.fable5 freeze-build     --repo-root . [--write]
    python -m eth_research.v2.fable5 freeze-verify    --repo-root .

``build`` prints (or, with ``--write``, canonically writes) the inventory; ``verify`` rebuilds the
inventory and proves it matches the committed snapshot, exiting non-zero on any drift or structural
red flag. ``paper-readiness`` derives the paper-activation gate vector from committed bytes (with
``--write`` it canonically writes the committed state file); ``verify-paper`` re-derives and proves
the committed ``paper_readiness_state.json`` matches, and fails closed if authorization / active
trading / sell-readiness ever derive true. ``freeze-build`` / ``freeze-verify`` build and re-check
the Fable 5 source freeze (audit tooling + remediated files + governance artifacts + sealed-ledger
emptiness). No subcommand mutates governed state beyond writing the single artifact it owns, opens a
sealed value, or evaluates any strategy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eth_research.v2.fable5.freeze import (
    FABLE5_SOURCE_FREEZE_RELPATH,
    Fable5FreezeError,
    build_source_freeze,
    load_committed_freeze,
    verify_source_freeze,
)
from eth_research.v2.fable5.inventory import (
    FABLE5_INVENTORY_RELPATH,
    Fable5InventoryError,
    build_system_inventory,
    verify_system_inventory,
)
from eth_research.v2.fable5.paper_readiness import (
    PAPER_READINESS_RELPATH,
    PaperReadinessError,
    derive_paper_readiness,
    verify_paper_readiness,
)
from eth_research.v2.strict import canonical_json_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eth_research.v2.fable5")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "build",
        "verify",
        "paper-readiness",
        "verify-paper",
        "freeze-build",
        "freeze-verify",
    ):
        p = sub.add_parser(name)
        p.add_argument("--repo-root", default=".")
        if name in ("build", "paper-readiness", "freeze-build"):
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

    if args.command == "paper-readiness":
        state = derive_paper_readiness(root)
        payload = canonical_json_bytes(state.to_canonical())
        if args.write:
            out = root / PAPER_READINESS_RELPATH
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload + b"\n")
            print(
                f"wrote {PAPER_READINESS_RELPATH} "
                f"(paper_activation_authorized={state.paper_activation_authorized}, "
                f"blocking={len(state.blocking_gates)} gates)"
            )
        else:
            sys.stdout.write(payload.decode() + "\n")
        return 0

    if args.command == "verify-paper":
        committed_path = root / PAPER_READINESS_RELPATH
        if not committed_path.exists():
            print(
                f"missing committed paper-readiness state: {PAPER_READINESS_RELPATH}",
                file=sys.stderr,
            )
            return 2
        committed = json.loads(committed_path.read_text())
        try:
            verify_paper_readiness(root, committed)
        except PaperReadinessError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps({"ok": True, "paper_activation_authorized": False}))
        return 0

    if args.command == "freeze-build":
        freeze = build_source_freeze(root)
        payload = canonical_json_bytes(freeze)
        if args.write:
            out = root / FABLE5_SOURCE_FREEZE_RELPATH
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload + b"\n")
            frozen_source = freeze["frozen_source_sha256"]
            frozen_gov = freeze["frozen_governance_sha256"]
            n_src = len(frozen_source) if isinstance(frozen_source, dict) else 0
            n_gov = len(frozen_gov) if isinstance(frozen_gov, dict) else 0
            print(f"wrote {FABLE5_SOURCE_FREEZE_RELPATH} ({n_src} source, {n_gov} governance)")
        else:
            sys.stdout.write(payload.decode() + "\n")
        return 0

    if args.command == "freeze-verify":
        try:
            committed = load_committed_freeze(root)
            checks = verify_source_freeze(root, committed)
        except Fable5FreezeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps({"ok": True, "checks": checks}))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
