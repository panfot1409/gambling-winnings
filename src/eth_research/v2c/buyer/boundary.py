"""V2C sections 24-25: the buyer request/response envelope, vendor server, and session quota.

The vendor server reads length-prefixed JSON requests and answers with length-prefixed JSON
responses that carry **only redacted artifacts** from the existing reference evaluation gateway
(re-scanned per response as defense in depth). A withheld or unknown item is *refused*, never
served; a request over the per-session quota ends the session. The server holds the private
implementation; the buyer only ever sees the redacted surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from eth_research.buyer.gateway import GatewayError, ReferenceEvaluationGateway
from eth_research.buyer.redaction import RedactionPolicy
from eth_research.v2.strict import (
    V2ValidationError,
    require_choice,
    require_nonempty_str,
)
from eth_research.v2c.buyer.framing import FramingError, read_frame, write_frame
from eth_research.v2c.firewall import KNOWN_LEGACY_CANDIDATE_IDS

#: A conservative per-session request budget; a buyer needs only a handful of artifacts.
MAX_REQUESTS_PER_SESSION: int = 32

REQUEST_KIND_AVAILABLE: str = "available"
REQUEST_KIND_SERVE: str = "serve"
_REQUEST_KINDS: frozenset[str] = frozenset({REQUEST_KIND_AVAILABLE, REQUEST_KIND_SERVE})

RESPONSE_AVAILABLE: str = "available_response"
RESPONSE_ARTIFACT: str = "artifact"
RESPONSE_REFUSED: str = "refused"
RESPONSE_ERROR: str = "error"
RESPONSE_QUOTA_EXCEEDED: str = "quota_exceeded"


class BoundaryError(V2ValidationError):
    """A buyer request was malformed or violated the boundary protocol."""


@dataclass(frozen=True, slots=True)
class BuyerRequest:
    """A parsed buyer request: list the available artifacts, or serve one by name."""

    kind: str
    item: str | None


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """What one vendor session served (used to prove redacted-only, quota-bounded behaviour)."""

    requests_received: int
    artifacts_served: int
    refusals: int
    errors: int
    quota_exceeded: bool
    response_bytes: int


def parse_request(frame: dict[str, object]) -> BuyerRequest:
    """Strictly parse a request frame; unknown kinds and missing items are refused."""
    kind = require_choice("request.kind", frame.get("kind"), _REQUEST_KINDS)
    item: str | None = None
    if kind == REQUEST_KIND_SERVE:
        item = require_nonempty_str("request.item", frame.get("item"))
    return BuyerRequest(kind=kind, item=item)


def open_vendor_gateway() -> ReferenceEvaluationGateway:
    """Open the reference evaluation gateway (assembles + fail-closed scans the bundle)."""
    return ReferenceEvaluationGateway.open()


def serve_request(
    gateway: ReferenceEvaluationGateway, policy: RedactionPolicy, request: BuyerRequest
) -> dict[str, object]:
    """Answer one request with a redacted-only response. Never emits a withheld artifact."""
    if request.kind == REQUEST_KIND_AVAILABLE:
        return {"kind": RESPONSE_AVAILABLE, "available": list(gateway.available())}
    name = request.item
    if name is None or name not in gateway.available():
        return {"kind": RESPONSE_REFUSED, "item": name, "reason": "withheld_or_unknown"}
    try:
        text = gateway.serve(name)
    except GatewayError:
        return {"kind": RESPONSE_REFUSED, "item": name, "reason": "withheld_or_unknown"}
    # Defense in depth: re-scan the served text; refuse to emit if anything trips the scanner. For a
    # gateway artifact the item name is also its redaction kind (both are drawn from the same
    # allowlist), so the kind check is exact rather than coincidental.
    if policy.scan_artifact(name, name, text):
        return {"kind": RESPONSE_REFUSED, "item": name, "reason": "redaction_violation"}
    # Extra defense in depth: a redacted artifact may name a provenance path, but must never carry a
    # legacy candidate *id* (a strategy slug). Refuse if one leaks (the RedactionPolicy does not
    # know candidate ids).
    if any(candidate_id in text for candidate_id in KNOWN_LEGACY_CANDIDATE_IDS):
        return {"kind": RESPONSE_REFUSED, "item": name, "reason": "candidate_id_leak"}
    return {"kind": RESPONSE_ARTIFACT, "item": name, "text": text}


def serve_session(
    gateway: ReferenceEvaluationGateway,
    in_stream: BinaryIO,
    out_stream: BinaryIO,
    *,
    max_requests: int = MAX_REQUESTS_PER_SESSION,
    policy: RedactionPolicy | None = None,
) -> SessionSummary:
    """Serve a whole buyer session over the length-prefixed streams; enforce the request quota."""
    active_policy = policy if policy is not None else RedactionPolicy.current()
    received = artifacts = refusals = errors = response_bytes = 0
    quota_exceeded = False
    while True:
        try:
            frame = read_frame(in_stream)
        except FramingError:
            # A malformed or truncated frame desyncs the stream; answer once and end the session
            # rather than let the error propagate out of the vendor loop.
            errors += 1
            response_bytes += write_frame(
                out_stream, {"kind": RESPONSE_ERROR, "reason": "malformed_frame"}
            )
            break
        if frame is None:
            break
        received += 1
        if received > max_requests:
            response_bytes += write_frame(
                out_stream, {"kind": RESPONSE_QUOTA_EXCEEDED, "limit": max_requests}
            )
            quota_exceeded = True
            break
        try:
            request = parse_request(frame)
        except V2ValidationError:
            errors += 1
            response_bytes += write_frame(
                out_stream, {"kind": RESPONSE_ERROR, "reason": "malformed_request"}
            )
            continue
        response = serve_request(gateway, active_policy, request)
        if response["kind"] == RESPONSE_ARTIFACT:
            artifacts += 1
        elif response["kind"] == RESPONSE_REFUSED:
            refusals += 1
        response_bytes += write_frame(out_stream, response)
    return SessionSummary(
        requests_received=received,
        artifacts_served=artifacts,
        refusals=refusals,
        errors=errors,
        quota_exceeded=quota_exceeded,
        response_bytes=response_bytes,
    )


__all__ = [
    "MAX_REQUESTS_PER_SESSION",
    "REQUEST_KIND_AVAILABLE",
    "REQUEST_KIND_SERVE",
    "RESPONSE_ARTIFACT",
    "RESPONSE_AVAILABLE",
    "RESPONSE_ERROR",
    "RESPONSE_QUOTA_EXCEEDED",
    "RESPONSE_REFUSED",
    "BoundaryError",
    "BuyerRequest",
    "SessionSummary",
    "open_vendor_gateway",
    "parse_request",
    "serve_request",
    "serve_session",
]
