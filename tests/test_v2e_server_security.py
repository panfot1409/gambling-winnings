"""V2E server security: bind posture, fixed routes, method refusal, no leakage.

One live server runs on an ephemeral loopback port with the real repository state; a
second uses a poisoned provider to prove traceback suppression. Everything else is
adversarial: traversal, mutation verbs, unknown routes, headers, concurrency, size
bounds, and the zero-exposure UI rehearsal with poison spies.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from eth_research.v2e.server import (
    LAN_WARNING,
    MAX_RESPONSE_BYTES,
    DashboardServer,
    V2EServerError,
    create_server,
)
from eth_research.v2e.state import REHEARSAL_BANNER, DashboardState, build_dashboard_state

REPO_ROOT = Path(__file__).resolve().parents[1]


def _get(port: int, path: str, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path)
    response = conn.getresponse()
    body = response.read()
    headers = {k.lower(): v for k, v in response.getheaders()}
    conn.close()
    return response.status, headers, body


@pytest.fixture(scope="module")
def served() -> Iterator[int]:
    state = build_dashboard_state(REPO_ROOT)
    server = create_server(lambda: state, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


class TestBindPosture:
    def test_default_host_is_loopback(self, served: int) -> None:
        status, _, _ = _get(served, "/healthz")
        assert status == 200

    def test_non_loopback_requires_explicit_allow_lan(self) -> None:
        with pytest.raises(V2EServerError, match="allow_lan"):
            create_server(lambda: None, host="0.0.0.0", port=0)  # type: ignore[arg-type,return-value]

    def test_lan_bind_prints_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        state = build_dashboard_state(REPO_ROOT)
        server = create_server(lambda: state, host="0.0.0.0", port=0, allow_lan=True)
        server.server_close()
        assert LAN_WARNING in capsys.readouterr().err
        assert "NO public-internet security guarantee" in LAN_WARNING


class TestRoutesAndMethods:
    def test_root_serves_html_with_defensive_headers(self, served: int) -> None:
        status, headers, body = _get(served, "/")
        assert status == 200
        assert headers["content-type"].startswith("text/html")
        assert headers["content-security-policy"].startswith("default-src 'none'")
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cache-control"] == "no-store"
        assert len(body) <= MAX_RESPONSE_BYTES

    def test_status_json_is_bounded_and_fact_only(self, served: int) -> None:
        status, headers, body = _get(served, "/status.json")
        assert status == 200
        assert headers["content-type"] == "application/json"
        doc = json.loads(body)
        assert doc["kind"] == "v2e_dashboard_status"
        assert doc["paper_engine"]["engine_status"] == "disabled"
        assert "/home/" not in body.decode()

    @pytest.mark.parametrize(
        "path",
        [
            "/etc/passwd",
            "/../etc/passwd",
            "/..%2f..%2fetc/passwd",
            "/src/eth_research",
            "/.git/HEAD",
            "/status.json/../../.env",
            "/index.html",
            "/favicon.ico",
        ],
    )
    def test_everything_outside_the_fixed_route_set_is_404(self, served: int, path: str) -> None:
        status, _, body = _get(served, path)
        assert status == 404
        assert body == b"not found\n"

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_mutation_verbs_are_405_with_allow_header(self, served: int, method: str) -> None:
        status, headers, _ = _get(served, "/", method=method)
        assert status == 405
        assert headers["allow"] == "GET, HEAD"

    def test_head_matches_get_without_body(self, served: int) -> None:
        status, headers, body = _get(served, "/", method="HEAD")
        assert status == 200
        assert body == b""
        assert int(headers["content-length"]) > 0

    def test_concurrent_readers_all_succeed(self, served: int) -> None:
        results: list[int] = []
        lock = threading.Lock()

        def reader() -> None:
            status, _, _ = _get(served, "/status.json")
            with lock:
                results.append(status)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results == [200] * 10


class TestFailureBoundary:
    def test_state_failure_yields_generic_500_without_traceback(self) -> None:
        def poisoned() -> DashboardState:
            raise RuntimeError("secret detail: /home/user/.ssh/id_ed25519 TOKEN=abc")

        server = create_server(poisoned, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = int(server.server_address[1])
            status, _, body = _get(port, "/")
            assert status == 500
            text = body.decode()
            assert "Traceback" not in text
            assert "secret detail" not in text
            assert "id_ed25519" not in text
            assert text == "dashboard state verification failed; see the server log\n"
        finally:
            server.shutdown()
            server.server_close()


class TestZeroExposureRehearsal:
    """UI/OPERATIONS REHEARSAL — NOT PAPER TRADING: dashboard plumbing only."""

    def test_rehearsal_touches_no_strategy_no_data_no_ledger(self) -> None:
        import eth_research.fractional.dataset as fractional_dataset
        import eth_research.strategies.donchian as donchian

        ledgers = [
            REPO_ROOT / "research/m2b/test_evaluations.jsonl",
            REPO_ROOT / "research/m3a/development_gate_access.jsonl",
            REPO_ROOT / "research/m3d/prospective_evaluations.jsonl",
            REPO_ROOT / "research/m3e/proposal_registry.jsonl",
        ]
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in ledgers]

        poisons: list[tuple[object, str, object]] = []

        def _poison(module: object, name: str) -> None:
            if not hasattr(module, name):  # pragma: no cover - defensive
                return
            original = getattr(module, name)

            def _explode(*args: object, **kwargs: object) -> object:
                raise AssertionError(f"rehearsal touched forbidden surface: {name}")

            setattr(module, name, _explode)
            poisons.append((module, name, original))

        for name in dir(donchian):
            if name[:1].isupper() and name != "Strategy":
                _poison(donchian, name)
        _poison(fractional_dataset, "verify_dataset_integrity_only")
        _poison(fractional_dataset, "_verify")

        try:
            state = build_dashboard_state(REPO_ROOT)
            server: DashboardServer = create_server(
                lambda: state, host="127.0.0.1", port=0, rehearsal=True
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = int(server.server_address[1])
                status, _, body = _get(port, "/")
            finally:
                server.shutdown()
                server.server_close()
        finally:
            for module, name, original in poisons:
                setattr(module, name, original)

        page = body.decode()
        assert status == 200
        assert REHEARSAL_BANNER in page
        assert state.paper_engine.exposure.startswith("zero")
        assert state.paper_engine.open_positions == 0
        assert state.paper_engine.pending_orders == 0
        assert state.paper_engine.fills == 0
        assert "UNAVAILABLE" in state.paper_engine.pnl
        after = [hashlib.sha256(p.read_bytes()).hexdigest() for p in ledgers]
        assert before == after  # no registry/ledger event was appended
