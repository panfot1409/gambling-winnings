"""Read-only V2D activation-gate CLI.

``python -m eth_research.v2d verify --workflow-basename <name> --repository <owner/repo>``
runs the full fail-closed activation gate (:func:`eth_research.v2d.activation.verify_activation`)
against the repository root and exits 0 only when every gate holds. The standing
update workflow runs this **before any network step**; a nonzero exit refuses the run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eth_research.v2d.activation import V2DActivationError, verify_activation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V2D activation gate (read-only)")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="run the fail-closed activation gate")
    verify.add_argument("--repo-root", default=".")
    verify.add_argument("--workflow-basename", required=True)
    verify.add_argument("--repository", required=True)
    args = parser.parse_args(argv)

    try:
        anchor, base = verify_activation(
            Path(args.repo_root),
            workflow_basename=args.workflow_basename,
            repository=args.repository,
        )
    except V2DActivationError as exc:
        print(f"ACTIVATION GATE REFUSED: {exc}", file=sys.stderr)
        return 1
    print("V2D ACTIVATION GATE PASSED")
    print(f"  anchor: {anchor['anchor_sha256'][:16]}  authorized_on: {anchor['authorized_on']}")
    print(
        f"  base: rows={base.row_count} last_open={base.last_open} "
        f"fingerprint={base.canonical_content_fingerprint[:16]}"
    )
    print("  evaluation_authorized: False  sealed_ledgers: byte-empty")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
