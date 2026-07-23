"""V2C sections 24-27: the process-isolated buyer-evaluation boundary.

Covers the length-prefixed framing, the vendor request/response server (redacted-only, quota
bounded), the deterministic source-free harness (byte-identical double build + source-free scan),
and the end-to-end isolated buyer run that proves the child sees only redacted artifacts, cannot
perturb the vendor, and writes nothing outside its temp root but a transcript.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from eth_research.buyer.redaction import RedactionPolicy
from eth_research.v2.strict import V2ValidationError
from eth_research.v2c.buyer.boundary import (
    BuyerRequest,
    open_vendor_gateway,
    parse_request,
    serve_request,
    serve_session,
)
from eth_research.v2c.buyer.framing import FramingError, read_frame, write_frame
from eth_research.v2c.buyer.harness import (
    CLIENT_FILENAME,
    CLIENT_STDLIB_ALLOWLIST,
    DYNAMIC_IMPORT_SENTINEL,
    build_harness,
    client_import_modules,
    double_build_is_identical,
    scan_source_free,
)
from eth_research.v2c.buyer.isolation import ISOLATION_FLAGS, run_isolated_buyer_evaluation


# --------------------------------------------------------------------------- #
# Section 24: framing                                                         #
# --------------------------------------------------------------------------- #
def test_frame_roundtrips() -> None:
    buffer = io.BytesIO()
    write_frame(buffer, {"kind": "serve", "item": "factsheet"})
    buffer.seek(0)
    assert read_frame(buffer) == {"kind": "serve", "item": "factsheet"}
    assert read_frame(buffer) is None  # clean EOF


def test_frame_rejects_oversized_write() -> None:
    buffer = io.BytesIO()
    with pytest.raises(FramingError, match="exceeds"):
        write_frame(buffer, {"blob": "x" * 100}, max_bytes=16)


def test_frame_rejects_oversized_declared_length() -> None:
    buffer = io.BytesIO((10_000).to_bytes(4, "big") + b"{}")
    with pytest.raises(FramingError, match="exceeds"):
        read_frame(buffer, max_bytes=8)


def test_frame_rejects_truncated_body() -> None:
    buffer = io.BytesIO((50).to_bytes(4, "big") + b"{}")  # header claims 50, body is 2
    with pytest.raises(FramingError):
        read_frame(buffer)


# --------------------------------------------------------------------------- #
# Sections 24-25: vendor server + quota                                       #
# --------------------------------------------------------------------------- #
def test_parse_request_requires_item_for_serve() -> None:
    assert parse_request({"kind": "available"}) == BuyerRequest("available", None)
    assert parse_request({"kind": "serve", "item": "contract"}) == BuyerRequest("serve", "contract")
    with pytest.raises(V2ValidationError):
        parse_request({"kind": "serve"})


def test_serve_request_serves_redacted_and_refuses_withheld() -> None:
    gateway = open_vendor_gateway()
    policy = RedactionPolicy.current()
    available = serve_request(gateway, policy, BuyerRequest("available", None))
    assert available["kind"] == "available_response"
    artifact = serve_request(gateway, policy, BuyerRequest("serve", "factsheet"))
    assert artifact["kind"] == "artifact"
    withheld = serve_request(gateway, policy, BuyerRequest("serve", "source_code"))
    assert withheld["kind"] == "refused"


def test_serve_session_serves_only_redacted() -> None:
    gateway = open_vendor_gateway()
    inp = io.BytesIO()
    for req in (
        {"kind": "available"},
        {"kind": "serve", "item": "factsheet"},
        {"kind": "serve", "item": "source_code"},
    ):
        write_frame(inp, req)
    inp.seek(0)
    out = io.BytesIO()
    summary = serve_session(gateway, inp, out, max_requests=32)
    assert summary.artifacts_served == 1
    assert summary.refusals == 1
    assert summary.quota_exceeded is False


def test_serve_session_enforces_quota() -> None:
    gateway = open_vendor_gateway()
    inp = io.BytesIO()
    for _ in range(5):
        write_frame(inp, {"kind": "available"})
    inp.seek(0)
    summary = serve_session(gateway, inp, io.BytesIO(), max_requests=3)
    assert summary.quota_exceeded is True


# --------------------------------------------------------------------------- #
# Section 27: source-free harness                                             #
# --------------------------------------------------------------------------- #
def test_harness_is_source_free_and_double_builds_identically(tmp_path: Path) -> None:
    harness = build_harness(tmp_path / "harness")
    assert scan_source_free(harness) == []
    assert double_build_is_identical(tmp_path / "double")


def test_client_imports_only_stdlib() -> None:
    assert client_import_modules() <= CLIENT_STDLIB_ALLOWLIST
    assert client_import_modules() == frozenset({"json", "pathlib", "sys"})


def test_client_import_modules_flags_a_dynamic_import() -> None:
    # A dynamic import (``__import__`` / ``importlib``) hides its target from a static scan; it must
    # surface as the sentinel so a client that dynamically imports fails the stdlib-only gate.
    via_importlib = "import importlib\nmod = importlib.import_module('eth_research')\n"
    via_builtin = "mod = __import__('eth_research')\n"
    assert DYNAMIC_IMPORT_SENTINEL in client_import_modules(via_importlib)
    assert DYNAMIC_IMPORT_SENTINEL in client_import_modules(via_builtin)
    assert not (client_import_modules(via_importlib) <= CLIENT_STDLIB_ALLOWLIST)


def test_isolation_flags_block_importing_the_repository_package(tmp_path: Path) -> None:
    # The ``-S`` in the isolation argv disables site.py so the editable-install ``.pth`` is never
    # processed: a child run with these flags genuinely cannot import the repository package, while
    # the same child WITHOUT ``-S`` can -- proving ``-S`` is the flag that makes the isolation real.
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, sys\n"
        "try:\n"
        "    import eth_research  # noqa: F401\n"
        "    sys.stdout.write('IMPORTED')\n"
        "except Exception:\n"
        "    sys.stdout.write('BLOCKED')\n",
        encoding="utf-8",
    )
    minimal_env = {"PATH": os.environ.get("PATH", "")}
    blocked = subprocess.run(
        [sys.executable, *ISOLATION_FLAGS, str(probe)],
        capture_output=True,
        text=True,
        env=minimal_env,
        check=False,
    )
    assert blocked.stdout == "BLOCKED", f"stdout={blocked.stdout!r} stderr={blocked.stderr!r}"
    # Control: the same run WITHOUT ``-S`` reaches the package; ``-S`` is the isolating flag.
    without_s = tuple(flag for flag in ISOLATION_FLAGS if flag != "-S")
    imported = subprocess.run(
        [sys.executable, *without_s, str(probe)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.stdout == "IMPORTED", f"stdout={imported.stdout!r} stderr={imported.stderr!r}"


def test_scan_flags_planted_source_and_forbidden_types(tmp_path: Path) -> None:
    harness = build_harness(tmp_path / "harness")
    (harness / "leak.txt").write_text("import eth_research.v2.candidates\n", encoding="utf-8")
    (harness / "model.whl").write_bytes(b"PK")
    problems = scan_source_free(harness)
    assert any("forbidden token" in p for p in problems)
    assert any("forbidden artifact type" in p for p in problems)


# --------------------------------------------------------------------------- #
# Sections 24 & 26: end-to-end isolated buyer evaluation                      #
# --------------------------------------------------------------------------- #
def test_isolated_buyer_evaluation_passes(tmp_path: Path) -> None:
    report = run_isolated_buyer_evaluation(workdir=tmp_path)
    failed = [c.name for c in report.checks if not c.passed]
    assert report.passed, failed
    # The withheld probe was refused, and the client wrote only its transcript.
    names = {c.name for c in report.checks}
    assert "buyer_got_only_redacted" in names
    assert "vendor_non_interference" in names
    assert "buyer_writes_confined_to_temp_root" in names
    assert report.session.artifacts_served > 0
    assert report.session.refusals >= 1


def test_isolated_client_is_named_and_present(tmp_path: Path) -> None:
    harness = build_harness(tmp_path / "harness")
    assert (harness / CLIENT_FILENAME).is_file()
