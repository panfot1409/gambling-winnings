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
_SRC = REPO / "src" / "eth_research"
# The offline research runtime: the public surface plus the first-party helpers it imports.
# The accepted governance/tooling modules (``m3*``, ``gitcheck``, ``*_register``, ``*_report``)
# legitimately shell out to git via ``subprocess`` and are *not* part of this offline runtime;
# they carry their own accepted import firewalls (M3D/M3E/M3F) and are out of scope here.
_RUNTIME_DIRS = [
    _SRC / "api",
    _SRC / "cli",
    _SRC / "m4a",
    _SRC / "data",
    _SRC / "strategies",
    _SRC / "fractional",
]
_RUNTIME_FILES = [
    _SRC / "_atomic.py",
    _SRC / "_json.py",
    _SRC / "costs.py",
    _SRC / "metrics.py",
    _SRC / "splits.py",
    _SRC / "backtest.py",
]

# Top-level module names a runtime file must never import (``subprocess`` included: the offline
# runtime shells out to nothing).
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
        "subprocess",
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
# Attribute-call spellings (``module.attr``) a runtime file must never make.
_FORBIDDEN_ATTR_CALLS = frozenset(
    {
        "os.system",
        "os.popen",
        "importlib.import_module",
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
    }
)
# (module, imported-name) pairs that bind a forbidden callable into the local namespace, e.g.
# ``from os import system`` or ``from importlib import import_module``.
_FORBIDDEN_FROM_IMPORTS = frozenset(
    {
        ("os", "system"),
        ("os", "popen"),
        ("importlib", "import_module"),
        ("subprocess", "run"),
        ("subprocess", "Popen"),
        ("subprocess", "call"),
        ("subprocess", "check_call"),
        ("subprocess", "check_output"),
        ("subprocess", "getoutput"),
        ("builtins", "eval"),
        ("builtins", "exec"),
        ("builtins", "compile"),
        ("builtins", "__import__"),
    }
)


def _iter_runtime_files() -> list[Path]:
    files: list[Path] = list(_RUNTIME_FILES)
    for directory in _RUNTIME_DIRS:
        files.extend(directory.rglob("*.py"))
    return sorted(set(files))


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
    module_aliases: dict[str, str] = {}  # local name -> the module it aliases
    forbidden_bindings: set[str] = set()  # local names bound directly to a forbidden callable

    # Pass 1: imports — flag forbidden module imports and record aliases / dangerous bindings,
    # resolving ``import x as y`` and ``from m import n as b`` rather than only literal spellings.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _FORBIDDEN_IMPORTS:
                    findings.append(f"{path.name}: forbidden import {alias.name}")
                module_aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] in _FORBIDDEN_IMPORTS:
                findings.append(f"{path.name}: forbidden import-from {module}")
            for alias in node.names:
                if (module, alias.name) in _FORBIDDEN_FROM_IMPORTS:
                    forbidden_bindings.add(alias.asname or alias.name)

    # Pass 2: calls — catch bare forbidden calls, calls through a dangerous binding, and
    # attribute calls whose root resolves (through an alias) to a forbidden ``module.attr``.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in _FORBIDDEN_CALLS or func.id in forbidden_bindings:
                findings.append(f"{path.name}: forbidden call {func.id}()")
        elif isinstance(func, ast.Attribute):
            dotted = _attr_path(func)
            candidates = {dotted}
            root, _, rest = dotted.partition(".")
            if rest and root in module_aliases:
                candidates.add(f"{module_aliases[root]}.{rest}")
            if candidates & _FORBIDDEN_ATTR_CALLS:
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
