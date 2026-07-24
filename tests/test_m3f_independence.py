"""M3F isolation guarantees (commit: independent verifier).

Structural firewalls, enforced by parsing source (relative *and* dynamic imports,
not just absolute) rather than trusting a comment, and backstopped by a runtime
import-closure check:

1. ``tools/m3f_independent_verify.py`` imports only the Python standard library —
   never ``eth_research`` and never a third-party package — so it cannot share a
   common-mode parser/logic defect with the packaged verifiers it shadows.

2. The ``eth_research.m3f`` package's entire dependency on the rest of
   ``eth_research`` is a one-module allowlist (``eth_research._json``), and it
   imports no third-party package (hashing + canonical JSON are inlined). Above
   all, M3F must not import — directly, relatively, dynamically, or transitively —
   the strategy/evaluation/backtest logic it is judging; a subprocess import closes
   the case at runtime.

The independent verifier is also exercised end-to-end: it passes on the real
repository and independently detects the tampering the packaged verifiers detect.
"""

from __future__ import annotations

import ast
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
INDEPENDENT_TOOL = REPO_ROOT / "tools/m3f_independent_verify.py"
M3F_PACKAGE_DIR = Path(eth_research.__file__).resolve().parent / "m3f"

# The complete allowlist of non-m3f eth_research modules the m3f package may import.
_ALLOWED_ETH_RESEARCH = frozenset({"eth_research._json"})


def _resolve_relative(package: str | None, level: int, module: str | None) -> str:
    """Resolve a relative import (level>0) to an absolute module name."""
    if not package:
        return "<unresolved-relative-import>"
    parts = package.split(".")
    base = ".".join(parts[: len(parts) - (level - 1)]) if level >= 1 else package
    return f"{base}.{module}" if module else base


def _imported_modules(source: str, package: str | None = None) -> set[str]:
    """Every module referenced by an import statement — absolute AND relative."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    names.add(node.module)
            else:
                base = _resolve_relative(package, node.level, node.module)
                names.add(base)
                if node.module is None:
                    # `from . import x` / `from .. import x`: each name is a submodule.
                    for alias in node.names:
                        names.add(f"{base}.{alias.name}")
    return names


def _dynamic_import_calls(source: str) -> set[str]:
    """Targets of ``__import__(...)`` / ``importlib.import_module(...)`` calls."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_dunder = isinstance(func, ast.Name) and func.id == "__import__"
        is_ilib = isinstance(func, ast.Attribute) and func.attr == "import_module"
        if is_dunder or is_ilib:
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value)
            else:
                found.add("<dynamic-import>")
    return found


def _top(module: str) -> str:
    return module.split(".", 1)[0]


def _load_independent_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m3f_independent_verify", INDEPENDENT_TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# firewall 1 — the independent tool is standard-library-only                  #
# --------------------------------------------------------------------------- #
def test_independent_verifier_imports_only_stdlib() -> None:
    source = INDEPENDENT_TOOL.read_text(encoding="utf-8")
    modules = _imported_modules(source)  # a script has no package: relatives -> sentinel
    assert modules, "expected at least one import"
    for module in modules:
        assert not module.startswith("eth_research"), f"independent tool imports {module}"
        assert not module.startswith("<"), f"independent tool uses a relative import: {module}"
        assert _top(module) in sys.stdlib_module_names, f"non-stdlib import: {module}"
    assert _dynamic_import_calls(source) == set(), "independent tool uses a dynamic import"


def test_independent_verifier_has_no_eth_research_import_statement() -> None:
    # Belt-and-suspenders beyond the AST walk: no import statement mentions it.
    # (The docstring names eth_research only to explain that it is *not* imported.)
    source = INDEPENDENT_TOOL.read_text(encoding="utf-8")
    assert "import eth_research" not in source
    assert "from eth_research" not in source


# --------------------------------------------------------------------------- #
# firewall 2 — the m3f package's import scope                                 #
# --------------------------------------------------------------------------- #
def test_import_walker_resolves_relative_and_flags_dynamic() -> None:
    # C1: the firewall must see relative and dynamic imports, not only absolute ones.
    src = (
        "from ..evaluation import x\n"
        "from . import y\n"
        "import importlib\n"
        "importlib.import_module('eth_research.backtest')\n"
        "__import__('eth_research.strategies')\n"
    )
    modules = _imported_modules(src, package="eth_research.m3f")
    assert "eth_research.evaluation" in modules  # ``..evaluation`` resolved
    assert "eth_research.m3f.y" in modules  # ``. y`` resolved
    assert _dynamic_import_calls(src) == {"eth_research.backtest", "eth_research.strategies"}


def test_m3f_package_source_scope_firewall() -> None:
    offenders: list[str] = []
    for path in sorted(M3F_PACKAGE_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        # Relative imports are resolved against the package (an m3f module lives in
        # eth_research.m3f), so `from ..evaluation import x` resolves and is caught.
        for module in _imported_modules(source, package="eth_research.m3f"):
            if module.startswith("eth_research"):
                if module.startswith("eth_research.m3f"):
                    continue  # internal package imports are always fine
                if module not in _ALLOWED_ETH_RESEARCH:
                    offenders.append(f"{path.name}: {module} (not in the allowlist)")
            elif _top(module) not in sys.stdlib_module_names:
                offenders.append(f"{path.name}: third-party import {module}")
        for target in _dynamic_import_calls(source):
            offenders.append(f"{path.name}: dynamic import {target}")
    assert offenders == [], f"m3f import-scope firewall breached: {offenders}"


def test_m3f_package_loads_no_strategy_or_third_party_at_runtime() -> None:
    # Runtime backstop that also catches relative/dynamic/transitive imports: import
    # every m3f module in a subprocess and diff sys.modules against the forbidden set.
    modules = sorted(f"eth_research.m3f.{p.stem}" for p in M3F_PACKAGE_DIR.glob("*.py"))
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        + "".join(f"import {m}\n" for m in modules if not m.endswith("__init__"))
        + "print('\\n'.join(sorted(set(sys.modules) - before)))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    loaded = out.split()
    third_party = [m for m in loaded if m in {"pandas", "numpy", "pyarrow", "scipy"}]
    # C1: structural backstop — any loaded eth_research module outside the allowlist
    # {eth_research, eth_research._json, eth_research.m3f.*} is a breach, independent of any
    # substring blocklist (so a future eth_research.<name> with no "judged" token is caught).
    allowed = {"eth_research", "eth_research._json"}
    forbidden = [
        m
        for m in loaded
        if m.startswith("eth_research")
        and m not in allowed
        and not m.startswith("eth_research.m3f")
    ]
    assert third_party == [], f"m3f loaded third-party packages: {third_party}"
    assert forbidden == [], f"m3f loaded non-allowlisted eth_research modules: {forbidden}"


# --------------------------------------------------------------------------- #
# the independent verifier actually works                                     #
# --------------------------------------------------------------------------- #
def test_independent_verifier_passes_on_real_repo() -> None:
    tool = _load_independent_tool()
    payload = tool.verify(REPO_ROOT)
    assert payload["ok"], payload["failures"]
    assert payload["facts"]["m3c_verdict"] == "rejected_for_development_gate_promotion"
    # Every production proposal the registry records must be covered by the acceptance
    # chain the tool walks independently (check 09), so the count is the accepted count
    # rather than a pre-growth literal.
    created = payload["facts"]["m3e_created_proposal_ids"]
    assert payload["facts"]["m3e_production_proposal_count"] == len(created)
    assert "09_acceptance_chain" in set(payload["checks"])


def test_independent_verifier_fails_on_registered_repo_missing_catalog(tmp_path: Path) -> None:
    # A4: deleting the catalog from an otherwise-registered repo must fail, not be
    # silently skipped while the tool still reports ok.
    from eth_research.m3f.catalog import CATALOG_RELPATH
    from eth_research.m3f.register import write_registration_artifacts

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", "--local", str(REPO_ROOT), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "a@b.c"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "T"], check=True)
    # Reset to pre-registration so this holds whether or not REPO_ROOT is registered.
    subprocess.run(
        ["git", "-C", str(clone), "rm", "-r", "-q", "--ignore-unmatch", "research/m3f"], check=True
    )
    if subprocess.run(
        ["git", "-C", str(clone), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip():
        subprocess.run(["git", "-C", str(clone), "commit", "-q", "-m", "reset"], check=True)
    freeze = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    write_registration_artifacts(clone, source_freeze_sha=freeze, accepted_main_sha=freeze)
    tool = _load_independent_tool()
    assert tool.verify(clone)["ok"] is True
    (clone / CATALOG_RELPATH).unlink()
    payload = tool.verify(clone)
    assert payload["ok"] is False
    assert any("missing freeze_catalog" in f for f in payload["failures"])
    for name in (
        "01_governance_facts_derivable",
        "02_sealed_ledgers_byte_empty",
        "05_m3e_zero_proposals",
        "06_workflows_read_only",
    ):
        assert name in payload["checks"]


def _minimal_repo(tmp_path: Path, registry_body: str) -> Path:
    for sub in ("research/m3c", "research/m3e", "research/m2b", "research/m3a", "research/m3d"):
        (tmp_path / sub).mkdir(parents=True)
    shutil.copyfile(
        REPO_ROOT / "research/m3c/candidate_decision.json",
        tmp_path / "research/m3c/candidate_decision.json",
    )
    shutil.copyfile(
        REPO_ROOT / "research/m3e/accepted_base.json",
        tmp_path / "research/m3e/accepted_base.json",
    )
    (tmp_path / "research/m3e/proposal_registry.jsonl").write_text(registry_body, encoding="utf-8")
    for empty in (
        "research/m2b/test_evaluations.jsonl",
        "research/m3a/development_gate_access.jsonl",
        "research/m3d/prospective_evaluations.jsonl",
    ):
        (tmp_path / empty).write_bytes(b"")
    return tmp_path


def test_independent_verifier_detects_compact_proposal(tmp_path: Path) -> None:
    # The independent parser must catch a genuine compact proposal — the exact
    # fail-open the packaged substring scan missed (bug F1).
    tool = _load_independent_tool()
    prefix = (REPO_ROOT / "research/m3e/proposal_registry.jsonl").read_text(encoding="utf-8")
    body = prefix + '{"entry_kind":"proposal","proposal_created":true,"schema_version":1}\n'
    root = _minimal_repo(tmp_path, body)
    payload = tool.verify(root)
    assert payload["ok"] is False
    assert any(f.startswith("05_m3e_zero_proposals") for f in payload["failures"])


def test_independent_verifier_detects_nonempty_ledger(tmp_path: Path) -> None:
    tool = _load_independent_tool()
    prefix = (REPO_ROOT / "research/m3e/proposal_registry.jsonl").read_text(encoding="utf-8")
    root = _minimal_repo(tmp_path, prefix)
    ledger = root / "research/m2b/test_evaluations.jsonl"
    ledger.write_text('{"tampered":true}\n', encoding="utf-8")
    payload = tool.verify(root)
    assert payload["ok"] is False
    assert any(f.startswith("02_sealed_ledgers_byte_empty") for f in payload["failures"])
