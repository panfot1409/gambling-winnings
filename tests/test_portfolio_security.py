"""Source-level security firewall over the M4B portfolio package (Milestone 4B, §37).

The portfolio milestone is a *pure, offline simulation library*. This firewall combines two guards,
never grepping docstrings (which legitimately say "no leverage, no shorting"):

* a **best-effort AST lint** — a static allow/deny scan for direct imports, forbidden builtin calls
  (``eval``/``exec``/``compile``/``__import__``), and a fixed set of dangerous dotted attribute
  calls (``os.system``, ``subprocess.run``, ``importlib.import_module``, …), plus a check for the
  indirection patterns (``getattr`` on a sensitive module, ``__dict__[...]``, ``__builtins__``) that
  a pure import/attr scan would miss. A lexical lint cannot *prove* the absence of capability
  against a determined obfuscator; it raises the bar and documents intent, and stays quiet on the
  shipped source (whose only ``getattr`` targets are dataclass instances);
* the **stronger, structural import-closure** — actually importing the package's public surface and
  asserting its transitive first-party closure pulls in no network / exchange / wallet /
  dynamic-exec / ML / optimizer client. This is the load-bearing proof; the lint is defense in depth
  on top of it.

A ``Fill`` is additionally shown to be an inert simulation *record* with no method that could route
it anywhere, and the read-only M4B replay workflow is checked for write/publish capability.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import sys
from pathlib import Path

import eth_research
from eth_research.portfolio.accounting import Fill, PortfolioState

_REPO = Path(eth_research.__file__).resolve().parents[2]
_PORTFOLIO = _REPO / "src" / "eth_research" / "portfolio"
_TESTS = _REPO / "tests"

# Top-level module names the offline portfolio runtime must never import: network / exchange /
# wallet clients, dynamic-execution / serialization risks, and every ML / numeric-optimizer library
# (the simulator fits no model and runs no optimizer).
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
        "runpy",
        "selenium",
        "playwright",
        "keyring",
        "sklearn",
        "scipy",
        "torch",
        "tensorflow",
        "keras",
        "xgboost",
        "lightgbm",
        "statsmodels",
        "cvxpy",
    }
)
# The subset that is specifically a network / exchange / wallet CLIENT — a capability that could
# reach a venue or the internet.
_NETWORK_CLIENT_IMPORTS = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "ftplib",
        "smtplib",
        "telnetlib",
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
        "selenium",
        "playwright",
        "keyring",
    }
)
_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__"})
_FORBIDDEN_ATTR_CALLS = frozenset(
    {
        "os.system",
        "os.popen",
        "os.execv",
        "os.execve",
        "os.execvp",
        "os.execvpe",
        "os.spawnv",
        "os.spawnve",
        "importlib.import_module",
        "importlib.util.spec_from_file_location",
        "runpy.run_path",
        "runpy.run_module",
        "builtins.__import__",
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
    }
)
_FORBIDDEN_FROM_IMPORTS = frozenset(
    {
        ("os", "system"),
        ("os", "popen"),
        ("os", "execv"),
        ("os", "execvp"),
        ("importlib", "import_module"),
        ("importlib.util", "spec_from_file_location"),
        ("runpy", "run_path"),
        ("runpy", "run_module"),
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
# Function / class NAME tokens that would betray an order-routing, leverage, shorting, margin, or
# borrowing *code surface*. Matched against defined names only (never docstrings/comments), so a
# docstring that says "long-only, no shorting" does not trip the guard.
_FORBIDDEN_NAME_TOKENS = (
    "place_order",
    "submit_order",
    "route_order",
    "send_order",
    "cancel_order",
    "create_order",
    "post_order",
    "open_position",
    "short_sell",
    "sell_short",
    "open_short",
    "go_short",
    "set_leverage",
    "open_margin",
    "borrow_cash",
    "borrow_asset",
    "margin_call",
)

_ALLOWED_THIRD_PARTY = {"numpy", "pandas", "pyarrow", "dateutil", "pytz", "tzdata", "six"}

# Modules whose attributes could reach the OS / network / dynamic execution. The lint flags a
# ``getattr`` whose target is one of these (e.g. ``getattr(os, "sys" + "tem")``), catching the
# name-concatenation / value-indirection dodge that a direct ``os.system`` attr scan would miss.
_SENSITIVE_MODULES = frozenset(
    {"os", "sys", "subprocess", "importlib", "builtins", "runpy", "ctypes"}
)

# Test modules that exercise the portfolio package but legitimately need an otherwise-forbidden
# import, mapped to the exact top-level names they may import. The consumer proofs shell out via
# ``subprocess`` to build and install the wheel/sdist (``test_m4b_consumer_e2e.py`` runs the
# portfolio reference from an installed wheel; ``test_private_consumer_matrix.py`` runs the same
# reference across the private install-channel matrix). ``test_v2c_firewall.py`` and
# ``test_v2c_prospective.py`` spawn a fresh interpreter via ``subprocess`` for the opposite reason:
# to *prove non-import* -- that importing the V2C firewall / governance modules loads no
# candidate/engine module (they name the portfolio engine as a tripwire, which is why they are swept
# in here). Each may import ``subprocess`` and nothing else from the forbidden set -- a network /
# exchange / ML client would still trip the scan.
_TEST_IMPORT_ALLOWLIST = {
    "test_m4b_consumer_e2e.py": frozenset({"subprocess"}),
    "test_private_consumer_matrix.py": frozenset({"subprocess"}),
    "test_v2c_firewall.py": frozenset({"subprocess"}),
    "test_v2c_prospective.py": frozenset({"subprocess"}),
}


def _portfolio_files() -> list[Path]:
    return sorted(_PORTFOLIO.rglob("*.py"))


def _imports_portfolio(tree: ast.AST) -> bool:
    """Whether a parsed test module exercises the portfolio package.

    True if it imports an ``eth_research.portfolio`` module *or* carries a string literal naming one
    (an out-of-process driver, as the installed-consumer E2E does). A mere comment mention is not an
    AST node and so does not count — a governance test that only names the path in a comment is not
    swept in.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "eth_research.portfolio"
        ):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name.startswith("eth_research.portfolio") for alias in node.names
        ):
            return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "eth_research.portfolio" in node.value
        ):
            return True
    return False


def _portfolio_importing_tests() -> list[Path]:
    """Every ``tests/test_*.py`` that exercises the portfolio package, regardless of filename.

    Detected structurally (see :func:`_imports_portfolio`), not by a ``test_portfolio_*`` filename
    prefix — so a portfolio test added under any other name (e.g. ``test_m4b_consumer_e2e.py``) is
    scanned too, and the offline guarantee cannot be evaded by naming.
    """
    hits: list[Path] = []
    for path in sorted(_TESTS.glob("test_*.py")):
        if _imports_portfolio(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            hits.append(path)
    return hits


def _scan_indirection(path: Path) -> list[str]:
    """Best-effort lint for capability reached through indirection rather than a direct import/attr.

    Flags ``getattr`` on a sensitive module, and any ``__dict__[...]`` or ``__builtins__`` access —
    the dodges (``getattr(os, "sys"+"tem")``, ``importlib.__dict__["import_module"]``) that the
    direct allow/deny scan cannot model. The shipped source uses none of these (its only ``getattr``
    targets are dataclass instances), so this stays quiet unless capability is smuggled in.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in _SENSITIVE_MODULES
        ):
            findings.append(f"{path.name}: getattr on sensitive module {node.args[0].id!r}")
        if isinstance(node, ast.Attribute) and node.attr in ("__dict__", "__builtins__"):
            findings.append(f"{path.name}: dynamic '{node.attr}' access")
        if isinstance(node, ast.Name) and node.id == "__builtins__":
            findings.append(f"{path.name}: reference to __builtins__")
    return findings


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
    module_aliases: dict[str, str] = {}
    forbidden_bindings: set[str] = set()
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


def test_portfolio_runtime_has_no_forbidden_capability() -> None:
    findings: list[str] = []
    for path in _portfolio_files():
        findings.extend(_scan_file(path))
    assert findings == [], "\n".join(findings)


def test_portfolio_runtime_has_no_capability_indirection() -> None:
    # Defense in depth over the direct scan: no getattr-on-a-sensitive-module, __dict__[...], or
    # __builtins__ dodge anywhere in the shipped package.
    findings: list[str] = []
    for path in _portfolio_files():
        findings.extend(_scan_indirection(path))
    assert findings == [], "\n".join(findings)


def test_portfolio_tests_import_no_network_or_ml_client() -> None:
    # Every test that exercises the portfolio package must be offline too — no network / exchange /
    # wallet / ML client — scanned by portfolio-import, not by filename prefix, so a differently
    # named portfolio test (e.g. the installed-consumer E2E) cannot slip the guard. A narrow,
    # explicit per-file allowlist covers the one test that must shell out to install a wheel.
    scanned = _portfolio_importing_tests()
    assert scanned, "expected to find portfolio-importing test modules"
    findings: list[str] = []
    for path in scanned:
        allowed = _TEST_IMPORT_ALLOWLIST.get(path.name, frozenset())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in _FORBIDDEN_IMPORTS and top not in allowed:
                        findings.append(f"{path.name}: forbidden import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                top = (node.module or "").split(".")[0]
                if top in _FORBIDDEN_IMPORTS and top not in allowed:
                    findings.append(f"{path.name}: forbidden import-from {node.module}")
    assert findings == [], "\n".join(findings)


def test_portfolio_defines_no_order_routing_or_leverage_surface() -> None:
    # Structural: scan defined function/class NAMES only. A docstring that says "no shorting" is ok;
    # a function actually named to route an order or open leverage is not.
    findings: list[str] = []
    for path in _portfolio_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                lowered = node.name.lower()
                for token in _FORBIDDEN_NAME_TOKENS:
                    if token in lowered:
                        findings.append(f"{path.name}: {node.name} looks like a {token} surface")
    assert findings == [], "\n".join(findings)


def test_portfolio_import_closure_is_offline_and_dependency_bounded() -> None:
    # Importing the public surface must pull in only eth_research + the declared numeric deps + the
    # standard library. Any network / exchange / ML / optimizer library would show up here.
    saved = {name: mod for name, mod in sys.modules.items() if name.startswith("eth_research")}
    try:
        for name in list(sys.modules):
            if name.startswith("eth_research"):
                del sys.modules[name]
        before = set(sys.modules)
        importlib.import_module("eth_research.portfolio.public_api")
        newly = set(sys.modules) - before
        stdlib = set(sys.stdlib_module_names)
        for name in newly:
            top = name.split(".")[0]
            if top == "eth_research" or top in _ALLOWED_THIRD_PARTY or top in stdlib:
                continue
            if top.startswith("_"):  # C accelerators such as _hashlib
                continue
            raise AssertionError(f"unexpected import pulled in by eth_research.portfolio: {name}")
    finally:
        for name in [n for n in sys.modules if n.startswith("eth_research")]:
            del sys.modules[name]
        sys.modules.update(saved)


def _network_client_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _NETWORK_CLIENT_IMPORTS:
                    findings.append(f"{path.name}: network-client import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in (
            _NETWORK_CLIENT_IMPORTS
        ):
            findings.append(f"{path.name}: network-client import-from {node.module}")
    return findings


def test_first_party_portfolio_closure_reaches_no_network_client() -> None:
    # No first-party module reachable from importing the portfolio public API imports a network /
    # exchange / wallet client — so a "fill" has nowhere it could be routed to.
    saved = {name: mod for name, mod in sys.modules.items() if name.startswith("eth_research")}
    try:
        for name in list(sys.modules):
            if name.startswith("eth_research"):
                del sys.modules[name]
        importlib.import_module("eth_research.portfolio.public_api")
        findings: list[str] = []
        for name, module in sorted(sys.modules.items()):
            if not name.startswith("eth_research"):
                continue
            file = getattr(module, "__file__", None)
            if file and file.endswith(".py"):
                findings.extend(_network_client_imports(Path(file)))
        assert findings == [], "\n".join(findings)
    finally:
        for name in [n for n in sys.modules if n.startswith("eth_research")]:
            del sys.modules[name]
        sys.modules.update(saved)


def test_fills_are_inert_simulation_records() -> None:
    # A Fill (and the PortfolioState it flows into) is an immutable record, not an action: it is a
    # frozen dataclass and carries no method whose name could route / submit / send / execute it.
    routing_verbs = (
        "route",
        "submit",
        "send",
        "execute",
        "place",
        "cancel",
        "post",
        "fetch",
        "connect",
        "order",
        "trade_live",
        "broadcast",
        "sign",
    )
    for model in (Fill, PortfolioState):
        assert dataclasses.is_dataclass(model)
        params = getattr(model, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen, f"{model.__name__} must be frozen"
        for method_name, _member in inspect.getmembers(model, callable):
            if method_name.startswith("_"):
                continue
            lowered = method_name.lower()
            for verb in routing_verbs:
                assert verb not in lowered, f"{model.__name__}.{method_name} looks like a {verb}"


def test_m4b_replay_workflow_is_read_only() -> None:
    workflow = (_REPO / ".github" / "workflows" / "m4b-replay.yml").read_text(encoding="utf-8")
    assert "permissions:" in workflow
    assert "contents: read" in workflow
    # No write/publish/secret capability of any kind.
    for banned in (
        "contents: write",
        "packages: write",
        "id-token:",
        "secrets.",
        "upload-artifact",
        "gh release",
        "git push",
        "git tag",
        "twine",
        "pypi",
    ):
        assert banned not in workflow, f"m4b-replay.yml must not contain {banned!r}"
