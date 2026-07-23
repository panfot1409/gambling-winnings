"""V2C section 27: the deterministic, source-free buyer harness builder.

Builds a self-contained buyer harness directory containing only **public** material: a stdlib-only
client, a request plan, a response-schema description, a README stating the honest limitation, and a
checksums manifest. It is deterministic (:func:`build_harness` writes byte-identical files every
time, proven by :func:`double_build_is_identical`) and source-free (:func:`scan_source_free` refuses
any strategy source, wheel, bytecode, raw data, or private URL). The harness is never uploaded or
published; V2C only stages it into a temp root to run the isolated buyer client.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from eth_research.buyer.redaction import scan_text
from eth_research.m3d.validation import M3DValidationError
from eth_research.v2c.firewall import KNOWN_LEGACY_CANDIDATE_IDS

#: The only top-level modules the source-free client may import (all standard library).
CLIENT_STDLIB_ALLOWLIST: frozenset[str] = frozenset({"json", "pathlib", "sys"})

HARNESS_SCHEMA_VERSION: int = 1
CLIENT_FILENAME: str = "buyer_client.py"
REQUEST_PLAN_FILENAME: str = "request_plan.json"
RESPONSE_SCHEMA_FILENAME: str = "response_schema.json"
README_FILENAME: str = "README.md"
CHECKSUMS_FILENAME: str = "checksums.json"


class HarnessError(M3DValidationError):
    """The buyer harness was malformed, non-deterministic, or not source-free."""


# The buyer client: stdlib-only (json, sys, pathlib), no network, no pickle, no eval. It connects to
# a vendor gateway over the length-prefixed JSON protocol, requests only public/redacted items, and
# writes a transcript. This string is the single source of truth for the harness client.
_CLIENT_SOURCE = '''"""Source-free V2C buyer client (public).

Connects to a vendor evaluation gateway over a length-prefixed JSON protocol, requests only the
public/redacted artifacts named in request_plan.json, and writes buyer_transcript.json. Contains no
strategy source, no raw data, and no private URLs. Uses only the standard library; it opens no
socket, imports no pickle, and evaluates nothing.
"""

import json
import pathlib
import sys

_MAX_FRAME_BYTES = 256 * 1024


def _fail(message):
    sys.stderr.write("buyer_client error: " + message + "\\n")
    raise SystemExit(3)


def _read_exactly(stream, count):
    buffer = b""
    while len(buffer) < count:
        chunk = stream.read(count - len(buffer))
        if not chunk:
            if not buffer:
                return None
            _fail("truncated frame")
        buffer += chunk
    return buffer


def read_frame(stream):
    header = _read_exactly(stream, 4)
    if header is None:
        return None
    length = int.from_bytes(header, "big")
    if length <= 0 or length > _MAX_FRAME_BYTES:
        _fail("frame length out of bounds")
    body = _read_exactly(stream, length)
    if body is None:
        _fail("missing frame body")
    return json.loads(body.decode("utf-8"))


def write_frame(stream, payload):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(body) > _MAX_FRAME_BYTES:
        _fail("outgoing frame too large")
    stream.write(len(body).to_bytes(4, "big"))
    stream.write(body)
    stream.flush()


def main():
    root = pathlib.Path(__file__).resolve().parent
    plan = json.loads((root / "request_plan.json").read_text(encoding="utf-8"))
    transcript = []
    artifacts = 0
    refusals = 0
    for request in plan["requests"]:
        write_frame(sys.stdout.buffer, request)
        response = read_frame(sys.stdin.buffer)
        if response is None:
            _fail("vendor closed the stream early")
        kind = response.get("kind")
        transcript.append({"request": request, "response_kind": kind, "item": response.get("item")})
        if kind == "artifact":
            artifacts += 1
        elif kind == "refused":
            refusals += 1
    (root / "buyer_transcript.json").write_text(
        json.dumps(
            {"artifacts": artifacts, "refusals": refusals, "transcript": transcript},
            sort_keys=True,
            indent=2,
        )
        + "\\n",
        encoding="utf-8",
    )
    sys.stdout.close()


if __name__ == "__main__":
    main()
'''

_REQUEST_PLAN = (
    "{\n"
    '  "requests": [\n'
    '    {"kind": "available"},\n'
    '    {"kind": "serve", "item": "contract"},\n'
    '    {"kind": "serve", "item": "factsheet"},\n'
    '    {"kind": "serve", "item": "claims_catalog"},\n'
    '    {"kind": "serve", "item": "readiness_scorecard"},\n'
    '    {"kind": "serve", "item": "source_code"}\n'
    "  ]\n"
    "}\n"
)

_RESPONSE_SCHEMA = (
    "{\n"
    '  "schema_version": 1,\n'
    '  "description": "Public response envelope for the V2C buyer boundary.",\n'
    '  "response_kinds": ["available_response", "artifact", "refused", '
    '"error", "quota_exceeded"],\n'
    '  "artifact": {"kind": "artifact", "item": "string", "text": "canonical-json string"},\n'
    '  "refused": {"kind": "refused", "item": "string", "reason": "string"},\n'
    '  "note": "Only redacted artifacts are ever served; withheld items are refused."\n'
    "}\n"
)

_README = (
    "# V2C source-free buyer harness\n\n"
    "This directory is a **public, source-free** buyer harness. It contains a stdlib-only "
    "client, a request plan, a response-schema description, and a checksums manifest -- and "
    "nothing else. It "
    "carries no strategy source, no wheel or bytecode, no raw market data, and no private URLs.\n\n"
    "## Honest limitation\n\n"
    "Running this harness reads only the redacted evaluation surface a vendor chooses to "
    "serve. The vendor still runs the private implementation; this is process isolation and "
    "redaction, **not** "
    "independent deployment, and it does not prove the core IP cannot be reverse engineered.\n"
)


#: Sentinel returned by :func:`client_import_modules` when the client uses a dynamic import
#: (``__import__`` / ``importlib``), which hides the imported module from a static scan. It is never
#: in the stdlib allowlist, so a client that dynamically imports fails the stdlib-only check.
DYNAMIC_IMPORT_SENTINEL: str = "<dynamic-import>"


def client_import_modules(source: str | None = None) -> frozenset[str]:
    """The set of top-level modules the client imports (AST-parsed; proves stdlib-only, no repo).

    Static ``import``/``from`` targets are returned by their top-level name. A dynamic import
    (``__import__(...)`` or any ``importlib`` reference) is reported as
    :data:`DYNAMIC_IMPORT_SENTINEL` so it cannot hide a non-stdlib import from the stdlib-only gate.
    ``source`` defaults to the built-in client constant; pass the on-disk client text to bind the
    proof to the artifact that will actually run.
    """
    tree = ast.parse(_CLIENT_SOURCE if source is None else source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "__import__":
                modules.add(DYNAMIC_IMPORT_SENTINEL)
        elif (isinstance(node, ast.Name) and node.id == "importlib") or (
            isinstance(node, ast.Attribute) and node.attr in {"import_module", "__import__"}
        ):
            modules.add(DYNAMIC_IMPORT_SENTINEL)
    return frozenset(modules)


def _harness_files() -> dict[str, str]:
    return {
        CLIENT_FILENAME: _CLIENT_SOURCE,
        REQUEST_PLAN_FILENAME: _REQUEST_PLAN,
        RESPONSE_SCHEMA_FILENAME: _RESPONSE_SCHEMA,
        README_FILENAME: _README,
    }


def build_harness(dest: str | Path) -> Path:
    """Write the deterministic source-free harness into ``dest`` (created if missing)."""
    root = Path(dest)
    root.mkdir(parents=True, exist_ok=True)
    files = _harness_files()
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    checksums = {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in sorted(files.items())
    }
    manifest = "{\n" + ",\n".join(f'  "{k}": "{v}"' for k, v in checksums.items()) + "\n}\n"
    (root / CHECKSUMS_FILENAME).write_text(manifest, encoding="utf-8")
    return root


def double_build_is_identical(tmp_root: str | Path) -> bool:
    """Build the harness twice into sibling dirs and confirm every file is byte-identical."""
    base = Path(tmp_root)
    first = build_harness(base / "build_a")
    second = build_harness(base / "build_b")
    names = sorted(p.name for p in first.iterdir())
    if names != sorted(p.name for p in second.iterdir()):
        return False
    return all((first / name).read_bytes() == (second / name).read_bytes() for name in names)


# The PEM private-key header, assembled so this source file does not itself trip the repo's
# private-key hygiene scan; it still matches a real PEM header at scan time.
_PEM_PRIVATE_KEY_MARKER: str = "-" * 5 + "BEGIN"

# The only files a freshly built source-free harness may contain. Anything else -- a planted
# strategy module, a pickled model, a raw-data table, a wheel -- is an unexpected file and a
# violation regardless of its content or extension. This allowlist is the primary gate; the token
# and suffix denylists below are defense in depth for the expected files themselves.
EXPECTED_HARNESS_FILES: frozenset[str] = frozenset(
    {
        CLIENT_FILENAME,
        REQUEST_PLAN_FILENAME,
        RESPONSE_SCHEMA_FILENAME,
        README_FILENAME,
        CHECKSUMS_FILENAME,
    }
)

# Tokens that must never appear in a source-free harness file.
_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "eth_research.v2.candidates",
    "eth_research.v2b.candidates",
    "eth_research.portfolio.engine",
    "eth_research.fractional.engine",
    "_signal_at",
    "git+ssh",
    "coinbase",
    _PEM_PRIVATE_KEY_MARKER,
)
# Only these suffixes are ever expected; any other on-disk artifact type is refused by name below,
# but the explicit binary/data suffixes are kept so a mis-named payload is still caught by type.
_ALLOWED_SUFFIXES: frozenset[str] = frozenset({".py", ".json", ".md"})
_FORBIDDEN_SUFFIXES: tuple[str, ...] = (
    ".whl",
    ".pyc",
    ".pyd",
    ".so",
    ".csv",
    ".parquet",
    ".pkl",
    ".pickle",
    ".npy",
    ".npz",
    ".pt",
    ".h5",
    ".bin",
)


def scan_source_free(root: str | Path) -> list[str]:
    """Return the list of source-free violations (empty == OK) over every file in the harness.

    The gate is an allowlist: only :data:`EXPECTED_HARNESS_FILES` may be present, so any planted
    file (strategy source, a pickled model, a raw-data table, a wheel) is refused by name whatever
    its content. The token/suffix denylists and the redaction content scan add defense in depth for
    the expected files themselves. Note this proves the *built* harness is source-free; it is not a
    guarantee that a determined vendor could not construct a harness that leaks.
    """
    base = Path(root)
    problems: list[str] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if path.name not in EXPECTED_HARNESS_FILES:
            problems.append(f"{path.name}: unexpected file (not a source-free harness member)")
        if suffix in _FORBIDDEN_SUFFIXES or suffix not in _ALLOWED_SUFFIXES:
            problems.append(f"{path.name}: forbidden artifact type {path.suffix!r}")
        # A known-binary payload is flagged by type and not decoded; every other file -- including a
        # mis-suffixed text leak like ``leak.txt`` -- is still content-scanned, so a planted source
        # is caught by its forbidden token even when its extension is also refused.
        if suffix in _FORBIDDEN_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for candidate_id in KNOWN_LEGACY_CANDIDATE_IDS:
            if candidate_id in text:
                problems.append(f"{path.name}: contains legacy candidate id {candidate_id!r}")
        for token in _FORBIDDEN_SUBSTRINGS:
            if token in text:
                problems.append(f"{path.name}: contains forbidden token {token!r}")
        # Content scan for secrets / raw data / private-key blocks (not embedded_source, since the
        # client file is legitimately Python source). Applied only to non-client files.
        if path.name != CLIENT_FILENAME:
            for violation in scan_text(path.name, text):
                if violation.category != "embedded_source":
                    problems.append(f"{path.name}: {violation.category} ({violation.detail})")
    return problems


__all__ = [
    "CHECKSUMS_FILENAME",
    "CLIENT_FILENAME",
    "CLIENT_STDLIB_ALLOWLIST",
    "DYNAMIC_IMPORT_SENTINEL",
    "EXPECTED_HARNESS_FILES",
    "HARNESS_SCHEMA_VERSION",
    "README_FILENAME",
    "REQUEST_PLAN_FILENAME",
    "RESPONSE_SCHEMA_FILENAME",
    "HarnessError",
    "build_harness",
    "client_import_modules",
    "double_build_is_identical",
    "scan_source_free",
]
