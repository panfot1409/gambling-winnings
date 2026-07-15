"""Architectural firewall for the Milestone 3E package.

M3E is data-only, governance-only, and review-only: no module under
``eth_research.m3e`` may import a strategy, backtest engine, fractional/accounting
engine, result metric, promotion decision, experiment-executor, or any
network/wallet module. This is enforced two ways:

* **Static (AST):** every ``import``/``from`` in every ``m3e`` module is parsed;
  each ``eth_research.*`` target must be on a tight **allowlist** of strategy-free
  shared utilities and the **data-only / governance-only** M3D modules M3E
  legitimately reads (or another ``m3e`` module), and none of the assignment's
  explicitly **prohibited** module prefixes may appear anywhere.
* **Dynamic (subprocess):** importing ``eth_research.m3e`` in a fresh interpreter
  must not pull any prohibited module into ``sys.modules``.

The allowlist is intentionally tight — every cross-package import M3E takes is a
deliberate governance decision, so widening it requires editing this test.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_M3E_DIR = _REPO_ROOT / "src" / "eth_research" / "m3e"

# The only ``eth_research`` modules/prefixes M3E code may import. Two groups, both
# strategy-free: (1) the low-level shared utilities (strict JSON decoder, atomic
# publication helper, data-provenance/validation layer, reviewed Coinbase adapter
# contract); (2) the specific data-only / governance-only M3D modules M3E reads to
# anchor on the accepted prospective cohort. Every other module — including any
# hypothetical future engine module in any package — is off-limits to M3E.
_ALLOWED_ETH_RESEARCH: frozenset[str] = frozenset(
    {
        # top-level, for __version__ only
        "eth_research",
        # shared low-level utilities
        "eth_research._json",
        "eth_research._atomic",
        "eth_research.data",
        "eth_research.data.provenance",
        "eth_research.data.validation",
        "eth_research.data.coinbase",
        "eth_research.data.schema",
        "eth_research.data.quality",
        # data-only / governance-only M3D modules the accepted base is read from
        "eth_research.m3d",
        "eth_research.m3d.validation",
        "eth_research.m3d._upstream",
        "eth_research.m3d.chain",
        "eth_research.m3d.acquisition_plan",
        "eth_research.m3d.receipt",
        "eth_research.m3d.raw_bundle",
        "eth_research.m3d.segment",
        "eth_research.m3d.cohort",
        "eth_research.m3d.protocol",
        "eth_research.m3d.quality",
        "eth_research.m3d.publication",
        "eth_research.m3d.maturity",
    }
)

# In-package ``eth_research`` prefixes the assignment names as prohibited. Any
# import whose dotted path equals one of these or starts with it + "." is a hard
# failure. Checked in BOTH the static AST scan and the dynamic ``sys.modules``
# probe: no legitimate transitive dependency loads these.
_PROHIBITED_ETH_RESEARCH_PREFIXES: tuple[str, ...] = (
    "eth_research.strategies",
    "eth_research.backtest",
    "eth_research.metrics",
    "eth_research.fractional.engine",
    "eth_research.fractional.accounting",
    "eth_research.fractional.experiment",
    "eth_research.fractional.evaluation",
    "eth_research.fractional.report",
    "eth_research.development_evaluation",
    "eth_research.development_orchestrator",
    "eth_research.development_completion",
    "eth_research.development_publication",
    "eth_research.develop_m3a",
    "eth_research.walkforward",
    "eth_research.evaluation",
    "eth_research.bootstrap",
    "eth_research.bootstrap_v2",
    "eth_research.decision",
    "eth_research.m3c.orchestrator",
    "eth_research.m3c.experiment",
    "eth_research.m3c.pipeline",
    "eth_research.m3c.statistics",
    "eth_research.m3c.decision",
    "eth_research.m3c.results",
    "eth_research.m3c.candidate",
    "eth_research.m3c.replay",
)

# Network / wallet client prefixes — M3E opens no socket and holds no key, so its
# own SOURCE must never import one. These are checked in the STATIC AST scan only:
# a legitimate third-party dependency (pandas) imports ``socket``/``urllib`` at
# import time, so a dynamic ``sys.modules`` probe would false-positive on them.
# The static scan is the right control — it proves no M3E module *itself* reaches
# for the network, independent of what pandas pulls in transitively.
_PROHIBITED_NETWORK_MODULES: tuple[str, ...] = (
    "urllib",
    "urllib.request",
    "http",
    "http.client",
    "socket",
    "ssl",
    "requests",
    "aiohttp",
    "httpx",
    "websocket",
    "websockets",
    "web3",
    "eth_account",
    "ccxt",
)

_PROHIBITED_PREFIXES: tuple[str, ...] = (
    _PROHIBITED_ETH_RESEARCH_PREFIXES + _PROHIBITED_NETWORK_MODULES
)


def _m3e_modules() -> list[Path]:
    files = sorted(_M3E_DIR.rglob("*.py"))
    assert files, "no M3E modules found — package missing?"
    return files


def _imported_modules(path: Path) -> set[str]:
    """Absolute dotted module names imported by ``path`` (relative resolved)."""
    tree = ast.parse(path.read_bytes(), filename=str(path))
    rel = path.relative_to(_REPO_ROOT / "src").with_suffix("")
    self_pkg = ".".join(rel.parts[:-1])  # parent package of the module
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import
                base_parts = self_pkg.split(".")
                if node.level > 1:
                    base_parts = base_parts[: -(node.level - 1)]
                base = ".".join(base_parts)
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            if module:
                names.add(module)
    return names


def test_m3e_modules_only_import_allowlisted_eth_research() -> None:
    offenders: list[str] = []
    for path in _m3e_modules():
        for module in _imported_modules(path):
            if not module.startswith("eth_research"):
                continue  # stdlib / third-party is unrestricted (except prohibited below)
            if module.startswith("eth_research.m3e"):
                continue  # intra-package imports are always fine
            if module not in _ALLOWED_ETH_RESEARCH:
                offenders.append(f"{path.name}: imports non-allowlisted {module!r}")
    assert not offenders, "M3E imported a non-allowlisted eth_research module:\n" + "\n".join(
        offenders
    )


def test_m3e_modules_never_import_prohibited_prefixes() -> None:
    offenders: list[str] = []
    for path in _m3e_modules():
        for module in _imported_modules(path):
            for prefix in _PROHIBITED_PREFIXES:
                if module == prefix or module.startswith(prefix + "."):
                    offenders.append(f"{path.name}: imports prohibited {module!r}")
    assert not offenders, "M3E imported a prohibited strategy/engine/network module:\n" + "\n".join(
        offenders
    )


def test_importing_m3e_pulls_no_engine_into_sys_modules() -> None:
    """A fresh interpreter importing ``eth_research.m3e`` loads no prohibited engine.

    Only the in-package ``eth_research.*`` engine prefixes are probed here: a
    legitimate dependency (pandas) imports ``socket``/``urllib`` transitively, so
    those are enforced by the static AST source scan above, not this dynamic probe.
    """
    prohibited_literal = json.dumps(list(_PROHIBITED_ETH_RESEARCH_PREFIXES))
    probe = (
        "import importlib, sys\n"
        "importlib.import_module('eth_research.m3e')\n"
        "importlib.import_module('eth_research.m3e.validation')\n"
        "prohibited = " + prohibited_literal + "\n"
        "hit = sorted(m for m in sys.modules "
        "if any(m == p or m.startswith(p + '.') for p in prohibited))\n"
        "print(chr(10).join(hit))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    hits = [line for line in result.stdout.splitlines() if line.strip()]
    assert not hits, "importing eth_research.m3e loaded prohibited modules: " + ", ".join(hits)
