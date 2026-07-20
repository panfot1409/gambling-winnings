"""V2C sections 24-27: the process-isolated buyer-evaluation boundary.

Covers the length-prefixed framing, the vendor request/response server (redacted-only, quota
bounded), the deterministic source-free harness (byte-identical double build + source-free scan),
and the end-to-end isolated buyer run that proves the child sees only redacted artifacts, cannot
perturb the vendor, and writes nothing outside its temp root but a transcript.
"""

from __future__ import annotations

import io
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
    build_harness,
    client_import_modules,
    double_build_is_identical,
    scan_source_free,
)
from eth_research.v2c.buyer.isolation import run_isolated_buyer_evaluation


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
