"""Loopback-first, GET/HEAD-only HTTP server for the private dashboard.

Security posture (all enforced by tests):

* binds ``127.0.0.1`` by default; any non-loopback bind demands ``allow_lan=True`` and
  prints an explicit warning that LAN mode carries no public-internet security guarantee;
* the route table is a fixed exact-match set (``/``, ``/status.json``, ``/healthz``) —
  there is no filesystem mapping, so path traversal has nothing to traverse;
* mutation verbs (POST/PUT/PATCH/DELETE) answer ``405`` with ``Allow: GET, HEAD`` — with
  no mutating endpoint at all, CSRF has no target;
* every response carries a restrictive CSP and defensive headers, is capped at
  :data:`MAX_RESPONSE_BYTES`, and a state-build failure yields a generic ``500`` body
  with no traceback, path, or environment detail (the exception is logged server-side).
"""

from __future__ import annotations

import ipaddress
import json
import sys
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from eth_research.v2e.render import render_html
from eth_research.v2e.state import DashboardState, to_status_document

MAX_RESPONSE_BYTES = 1_500_000

LAN_WARNING = (
    "WARNING: binding a non-loopback address exposes this dashboard to your local "
    "network. It is read-only, but LAN mode carries NO public-internet security "
    "guarantee — never port-forward it or run it on an untrusted network."
)

_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    (
        "Content-Security-Policy",
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'",
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
)


class V2EServerError(RuntimeError):
    """The server was configured outside its safe envelope."""


def _is_loopback(host: str) -> bool:
    # An empty host is INADDR_ANY (bind ALL interfaces) to Python sockets, so it is
    # explicitly NOT loopback here (auditor finding: silent all-interface bind).
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class DashboardServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the state provider for its handler."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        state_provider: Callable[[], DashboardState],
        *,
        rehearsal: bool = False,
    ) -> None:
        super().__init__(address, _Handler)
        self.state_provider = state_provider
        self.rehearsal = rehearsal


class _Handler(BaseHTTPRequestHandler):
    server_version = "eth-research-v2e"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        if len(body) > MAX_RESPONSE_BYTES:
            code, content_type, body = (
                500,
                "text/plain; charset=utf-8",
                b"response exceeded the configured size bound\n",
            )
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in _SECURITY_HEADERS:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _refuse_mutation(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        for name, value in _SECURITY_HEADERS:
            self.send_header(name, value)
        self.end_headers()

    do_POST = _refuse_mutation
    do_PUT = _refuse_mutation
    do_PATCH = _refuse_mutation
    do_DELETE = _refuse_mutation
    # Not mutations, but refused identically so every common verb gets the defensive
    # headers instead of the stdlib 501 page (defense-in-depth, auditor finding).
    do_OPTIONS = _refuse_mutation
    do_TRACE = _refuse_mutation

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        server = self.server
        assert isinstance(server, DashboardServer)
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send(200, "application/json", b'{"ok": true}\n')
            return
        if path not in {"/", "/status.json"}:
            self._send(404, "text/plain; charset=utf-8", b"not found\n")
            return
        try:
            state = server.state_provider()
            if path == "/":
                body = render_html(state, rehearsal=server.rehearsal).encode("utf-8")
                self._send(200, "text/html; charset=utf-8", body)
            else:
                document = to_status_document(state)
                payload = json.dumps(document, sort_keys=True).encode("utf-8") + b"\n"
                self._send(200, "application/json", payload)
        except Exception as exc:
            print(f"v2e dashboard state refusal: {exc.__class__.__name__}", file=sys.stderr)
            self._send(
                500,
                "text/plain; charset=utf-8",
                b"dashboard state verification failed; see the server log\n",
            )

    def log_message(self, format: str, *args: object) -> None:
        print(f"v2e {self.address_string()} {format % args}", file=sys.stderr)


def create_server(
    state_provider: Callable[[], DashboardState],
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    allow_lan: bool = False,
    rehearsal: bool = False,
) -> DashboardServer:
    """Create (without starting) the dashboard server inside the safe envelope."""
    if not _is_loopback(host):
        if not allow_lan:
            raise V2EServerError(
                f"refusing to bind non-loopback address {host!r} without allow_lan=True"
            )
        print(LAN_WARNING, file=sys.stderr)
    return DashboardServer((host, port), state_provider, rehearsal=rehearsal)
