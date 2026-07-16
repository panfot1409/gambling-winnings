"""M3F isolation guarantees (commit: independent verifier).

Two structural firewalls, enforced by parsing source rather than trusting a
comment:

1. ``tools/m3f_independent_verify.py`` imports only the Python standard library —
   never ``eth_research`` and never a third-party package — so it cannot share a
   common-mode parser/logic defect with the packaged verifiers it shadows.

2. The ``eth_research.m3f`` package's entire dependency on the rest of
   ``eth_research`` is a tiny, explicit allowlist routed through one strict module,
   and it imports no third-party package. M3F verifies the accepted stack; it must
   not import the strategy/evaluation logic it is judging.

The independent verifier is also exercised end-to-end: it passes on the real
repository and independently detects the tampering the packaged verifiers detect.
"""

from __future__ import annotations

import ast
import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
INDEPENDENT_TOOL = REPO_ROOT / "tools/m3f_independent_verify.py"
M3F_PACKAGE_DIR = Path(eth_research.__file__).resolve().parent / "m3f"

# The complete allowlist of non-m3f eth_research modules the m3f package may import.
_ALLOWED_ETH_RESEARCH = frozenset(
    {
        "eth_research._json",
        "eth_research.data.provenance",
        "eth_research.m3d.validation",
    }
)


def _imported_modules(source: str) -> set[str]:
    """Every absolute module name referenced by an import statement in ``source``."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


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
    modules = _imported_modules(INDEPENDENT_TOOL.read_text(encoding="utf-8"))
    assert modules, "expected at least one import"
    for module in modules:
        assert not module.startswith("eth_research"), f"independent tool imports {module}"
        assert _top(module) in sys.stdlib_module_names, f"non-stdlib import: {module}"


def test_independent_verifier_has_no_eth_research_import_statement() -> None:
    # Belt-and-suspenders beyond the AST walk: no import statement mentions it.
    # (The docstring names eth_research only to explain that it is *not* imported.)
    source = INDEPENDENT_TOOL.read_text(encoding="utf-8")
    assert "import eth_research" not in source
    assert "from eth_research" not in source


# --------------------------------------------------------------------------- #
# firewall 2 — the m3f package's import scope                                 #
# --------------------------------------------------------------------------- #
def test_m3f_package_source_scope_firewall() -> None:
    offenders: list[str] = []
    for path in sorted(M3F_PACKAGE_DIR.glob("*.py")):
        for module in _imported_modules(path.read_text(encoding="utf-8")):
            if module.startswith("eth_research"):
                if module.startswith("eth_research.m3f"):
                    continue  # internal package imports are always fine
                if module not in _ALLOWED_ETH_RESEARCH:
                    offenders.append(f"{path.name}: {module} (not in the allowlist)")
            elif _top(module) not in sys.stdlib_module_names:
                offenders.append(f"{path.name}: third-party import {module}")
    assert offenders == [], f"m3f import-scope firewall breached: {offenders}"


# --------------------------------------------------------------------------- #
# the independent verifier actually works                                     #
# --------------------------------------------------------------------------- #
def test_independent_verifier_passes_on_real_repo() -> None:
    tool = _load_independent_tool()
    payload = tool.verify(REPO_ROOT)
    assert payload["ok"], payload["failures"]
    assert payload["facts"]["m3c_verdict"] == "rejected_for_development_gate_promotion"
    assert payload["facts"]["m3e_production_proposal_count"] == 0
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
