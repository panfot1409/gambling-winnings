"""Repository-level guarantees: no networking imports, no committed data."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        # HTTP / generic networking
        "requests",
        "httpx",
        "aiohttp",
        "urllib",
        "urllib3",
        "http",
        "socket",
        "socketserver",
        "ssl",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "xmlrpc",
        "websocket",
        "websockets",
        # exchange SDKs / clients
        "ccxt",
        "coinbase",
        "cbpro",
        "binance",
        "krakenex",
        # wallets / signing / on-chain
        "web3",
        "eth_account",
        "eth_keys",
        "bitcoinlib",
    }
)

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "data",
        "outputs",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        "node_modules",
    }
)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for directory in ("src", "tests", "examples"):
        files.extend(sorted((REPO_ROOT / directory).rglob("*.py")))
    assert files, "expected to find python files to scan"
    return files


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_network_exchange_or_wallet_imports_anywhere() -> None:
    """src, tests, and examples must never import networking or exchange code.

    The scan is AST-based (real import statements, not string matches), so
    this test file's own forbidden-name list does not trip it.
    """
    offenders: dict[str, set[str]] = {}
    for path in _python_files():
        forbidden = _import_roots(path) & FORBIDDEN_IMPORT_ROOTS
        if forbidden:
            offenders[str(path.relative_to(REPO_ROOT))] = forbidden
    assert offenders == {}, f"forbidden imports found: {offenders}"


def _walk_repo() -> list[Path]:
    found: list[Path] = []
    stack = [REPO_ROOT]
    while stack:
        current = stack.pop()
        for entry in current.iterdir():
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS:
                    stack.append(entry)
            else:
                found.append(entry)
    return found


def test_no_market_data_files_are_committed() -> None:
    """No CSV/Parquet market data may live in the tracked tree.

    Datasets belong under the git-ignored ``data/`` directory; tests use
    temporary directories. The tracked tree must contain no data files at
    all, so nothing can be committed by accident.
    """
    data_files = [
        str(path.relative_to(REPO_ROOT))
        for path in _walk_repo()
        if path.suffix.lower() in {".csv", ".parquet", ".pq"}
    ]
    assert data_files == []


def test_data_and_outputs_directories_are_gitignored() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/data/" in ignored
    assert "/outputs/" in ignored
