"""Architectural firewall for the Milestone 3D package.

M3D is data-only and governance-only: no module under ``eth_research.m3d`` may
import a strategy, backtest engine, fractional/accounting engine, result metric,
promotion decision, or experiment-executor module. This is enforced two ways:

* **Static (AST):** every ``import``/``from`` in every ``m3d`` module is parsed;
  each ``eth_research.*`` target must be on a small **allowlist** of strategy-free
  shared utilities (or another ``m3d`` module), and none of the assignment's
  explicitly **prohibited** module prefixes may appear anywhere.
* **Dynamic (subprocess):** importing ``eth_research.m3d`` in a fresh interpreter
  must not pull any prohibited module into ``sys.modules``.

The allowlist is intentionally tight — every cross-package import M3D takes is a
deliberate governance decision, so widening it requires editing this test.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_M3D_DIR = _REPO_ROOT / "src" / "eth_research" / "m3d"

# The only ``eth_research`` modules/prefixes M3D governance/data code may import.
# All are strategy-free: the strict JSON decoder, the atomic publication helper,
# the data-provenance/validation layer, and the already-reviewed Coinbase data
# adapter contract. Everything else in the package is off-limits to M3D.
_ALLOWED_ETH_RESEARCH: frozenset[str] = frozenset(
    {
        "eth_research",  # top-level, for __version__ only
        "eth_research._json",
        "eth_research._atomic",
        "eth_research.data",
        "eth_research.data.provenance",
        "eth_research.data.validation",
        "eth_research.data.coinbase",
        "eth_research.data.schema",
        "eth_research.data.quality",
    }
)

# Prefixes the assignment names as prohibited. Any import whose dotted path equals
# one of these or starts with it + "." is a hard failure.
_PROHIBITED_PREFIXES: tuple[str, ...] = (
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


def _m3d_modules() -> list[Path]:
    files = sorted(_M3D_DIR.rglob("*.py"))
    assert files, "no M3D modules found — package missing?"
    return files


def _imported_modules(path: Path) -> set[str]:
    """Absolute dotted module names imported by ``path`` (relative resolved)."""
    tree = ast.parse(path.read_bytes(), filename=str(path))
    # This module's own absolute package, e.g. ``eth_research.m3d``.
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


def test_m3d_modules_only_import_allowlisted_eth_research() -> None:
    offenders: list[str] = []
    for path in _m3d_modules():
        for module in _imported_modules(path):
            if not module.startswith("eth_research"):
                continue  # stdlib / third-party is unrestricted
            if module.startswith("eth_research.m3d"):
                continue  # intra-package imports are always fine
            if module not in _ALLOWED_ETH_RESEARCH:
                offenders.append(f"{path.name}: imports non-allowlisted {module!r}")
    assert not offenders, "M3D imported a non-allowlisted eth_research module:\n" + "\n".join(
        offenders
    )


def test_m3d_modules_never_import_prohibited_prefixes() -> None:
    offenders: list[str] = []
    for path in _m3d_modules():
        for module in _imported_modules(path):
            for prefix in _PROHIBITED_PREFIXES:
                if module == prefix or module.startswith(prefix + "."):
                    offenders.append(f"{path.name}: imports prohibited {module!r}")
    assert not offenders, "M3D imported a prohibited strategy/engine module:\n" + "\n".join(
        offenders
    )


def test_importing_m3d_pulls_no_engine_into_sys_modules() -> None:
    """A fresh interpreter importing ``eth_research.m3d`` loads no prohibited module."""
    # json.dumps of a list of strings is also a valid Python list literal.
    prohibited_literal = json.dumps(list(_PROHIBITED_PREFIXES))
    probe = (
        "import importlib, sys\n"
        "importlib.import_module('eth_research.m3d')\n"
        "importlib.import_module('eth_research.m3d.validation')\n"
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
    assert not hits, "importing eth_research.m3d loaded prohibited modules: " + ", ".join(hits)
