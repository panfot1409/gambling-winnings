"""Source-level security firewall over the M4A public surface (api / cli / m4a).

An AST scan asserts the runtime public layer imports no networking, exchange, wallet, or
dynamic-execution capability, and that ``eth_research.api``'s import closure stays within the
package plus its three declared numeric dependencies and the standard library.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import eth_research

REPO = Path(eth_research.__file__).resolve().parents[2]
_RUNTIME_DIRS = [
    REPO / "src" / "eth_research" / "api",
    REPO / "src" / "eth_research" / "cli",
    REPO / "src" / "eth_research" / "m4a",
]

# Top-level module names a runtime file must never import.
_FORBIDDEN_IMPORTS = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "ftplib",
        "smtplib",
        "telnetlib",
        "asyncio",
        "requests",
        "httpx",
        "aiohttp",
        "websocket",
        "websockets",
        "web3",
        "eth_account",
        "ccxt",
        "binance",
        "coinbase",
        "kraken",
        "boto3",
        "paramiko",
        "pickle",
        "marshal",
        "ctypes",
        "selenium",
        "playwright",
        "keyring",
    }
)
# Bare call names a runtime file must never make.
_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__"})
# Attribute-call spellings (module.attr) a runtime file must never make.
_FORBIDDEN_ATTR_CALLS = frozenset(
    {"os.system", "os.popen", "importlib.import_module", "subprocess.run", "subprocess.Popen"}
)


def _iter_runtime_files() -> list[Path]:
    files: list[Path] = []
    for directory in _RUNTIME_DIRS:
        files.extend(sorted(directory.rglob("*.py")))
    return files


def _attr_path(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _scan_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _FORBIDDEN_IMPORTS:
                    findings.append(f"{path.name}: forbidden import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in _FORBIDDEN_IMPORTS:
                findings.append(f"{path.name}: forbidden import-from {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALLS:
                findings.append(f"{path.name}: forbidden call {func.id}()")
            elif isinstance(func, ast.Attribute):
                dotted = _attr_path(func)
                if dotted in _FORBIDDEN_ATTR_CALLS:
                    findings.append(f"{path.name}: forbidden call {dotted}()")
    return findings


def test_runtime_layer_has_no_forbidden_capability() -> None:
    findings: list[str] = []
    for path in _iter_runtime_files():
        findings.extend(_scan_file(path))
    assert findings == [], "\n".join(findings)


def test_api_import_closure_is_offline_and_dependency_bounded() -> None:
    import importlib

    for name in list(sys.modules):
        if name.startswith("eth_research.api"):
            del sys.modules[name]
    before = set(sys.modules)
    importlib.import_module("eth_research.api")
    newly = set(sys.modules) - before

    allowed_third_party = {"numpy", "pandas", "pyarrow", "dateutil", "pytz", "tzdata", "six"}
    stdlib = set(sys.stdlib_module_names)
    for name in newly:
        top = name.split(".")[0]
        if top == "eth_research" or top in allowed_third_party or top in stdlib:
            continue
        if top.startswith("_"):  # C accelerators such as _hashlib
            continue
        raise AssertionError(f"unexpected import pulled in by eth_research.api: {name}")
