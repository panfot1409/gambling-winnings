"""CLI for the private operations dashboard: ``python -m eth_research.v2e.dashboard``.

Defaults are the safe envelope: loopback bind, ephemeral-free fixed port, no proposal
checkout. ``--once`` renders one HTML snapshot to stdout and exits, which is what the
documentation and smoke tests use; ``--allow-lan`` is the single, explicit opt-in for
non-loopback binding and always prints the LAN warning first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eth_research.v2e.render import render_html
from eth_research.v2e.server import LAN_WARNING, V2EServerError, create_server
from eth_research.v2e.state import DashboardState, build_dashboard_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eth_research.v2e.dashboard",
        description="Private, read-only operations dashboard (loopback by default).",
    )
    parser.add_argument("--repo-root", default=".", help="repository root (default: .)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8377, help="TCP port (default: 8377)")
    parser.add_argument(
        "--allow-lan",
        action="store_true",
        help="explicitly permit a non-loopback bind (prints a warning; LAN has no "
        "public-internet security guarantee)",
    )
    parser.add_argument(
        "--proposal-checkout",
        default=None,
        help="optional local read-only checkout of the pending bot proposal branch",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="render one HTML snapshot to stdout and exit (no server)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    checkout = Path(args.proposal_checkout) if args.proposal_checkout else None

    def provider() -> DashboardState:
        return build_dashboard_state(repo_root, proposal_checkout=checkout)

    if args.once:
        sys.stdout.write(render_html(provider()))
        return 0

    try:
        server = create_server(provider, host=args.host, port=args.port, allow_lan=args.allow_lan)
    except V2EServerError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        print(f"(pass --allow-lan to accept: {LAN_WARNING})", file=sys.stderr)
        return 2
    host, port = str(server.server_address[0]), int(server.server_address[1])
    print(
        f"eth-research v2e dashboard: http://{host}:{port}/ (read-only; Ctrl-C stops it)",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive stop
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
