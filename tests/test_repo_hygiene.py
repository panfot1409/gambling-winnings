"""Repository-level guarantees: no networking imports, no committed data."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

RAW_ROOT = REPO_ROOT / "research" / "m2b" / "raw" / "coinbase"
RAW_AGGREGATE_CAP_BYTES: int = 10 * 1024 * 1024  # 10 MiB
LEDGER = REPO_ROOT / "research" / "m2b" / "test_evaluations.jsonl"


def _tracked_files(prefix: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", prefix],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


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


# The single, narrow V2E exception to the networking ban: the private, read-only,
# loopback-first operations dashboard (stdlib ``http.server``) and its loopback test
# client. It serves committed governance state on 127.0.0.1 by default, has no mutation
# endpoints, and performs no outbound requests; the only authorized market-data egress
# remains the m3e update workflow. Nothing else may import a forbidden root, and these
# files may import only ``http`` (test_v2e_hygiene_exemption_is_exactly_this_narrow).
DASHBOARD_SERVER_EXEMPT: dict[str, frozenset[str]] = {
    "src/eth_research/v2e/server.py": frozenset({"http"}),
    "tests/test_v2e_server_security.py": frozenset({"http"}),
}


def test_no_network_exchange_or_wallet_imports_anywhere() -> None:
    """src, tests, and examples must never import networking or exchange code.

    The scan is AST-based (real import statements, not string matches), so
    this test file's own forbidden-name list does not trip it. The sole
    exception is the V2E loopback dashboard server (see
    ``DASHBOARD_SERVER_EXEMPT``), which may import ``http`` and nothing else
    from the forbidden list.
    """
    offenders: dict[str, set[str]] = {}
    for path in _python_files():
        rel = str(path.relative_to(REPO_ROOT))
        forbidden = _import_roots(path) & FORBIDDEN_IMPORT_ROOTS
        forbidden -= DASHBOARD_SERVER_EXEMPT.get(rel, frozenset())
        if forbidden:
            offenders[rel] = forbidden
    assert offenders == {}, f"forbidden imports found: {offenders}"


def test_v2e_hygiene_exemption_is_exactly_this_narrow() -> None:
    """The dashboard exemption stays pinned: two files, the ``http`` root only."""
    assert set(DASHBOARD_SERVER_EXEMPT) == {
        "src/eth_research/v2e/server.py",
        "tests/test_v2e_server_security.py",
    }
    for rel, allowed in DASHBOARD_SERVER_EXEMPT.items():
        assert allowed == frozenset({"http"})
        path = REPO_ROOT / rel
        assert path.is_file(), f"exempt file vanished: {rel}"
        # The exempt files must not smuggle any other forbidden root.
        others = (_import_roots(path) & FORBIDDEN_IMPORT_ROOTS) - allowed
        assert others == set(), f"{rel} imports beyond its exemption: {others}"
    # The exemption is server-side only: every other v2e module stays network-free.
    for path in sorted((REPO_ROOT / "src/eth_research/v2e").glob("*.py")):
        rel = str(path.relative_to(REPO_ROOT))
        if rel in DASHBOARD_SERVER_EXEMPT:
            continue
        assert not (_import_roots(path) & FORBIDDEN_IMPORT_ROOTS), rel


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


# --- Milestone 2B raw-data allowlist and holdout hygiene ---------------------


def test_tracked_raw_bodies_are_allowlisted_json() -> None:
    """Only .json candle bodies + receipts under the raw coinbase tree."""
    tracked = _tracked_files("research/m2b/raw")
    assert tracked, "expected committed raw acquisition bodies"
    for rel in tracked:
        path = REPO_ROOT / rel
        # under research/m2b/raw/coinbase/<attempt>/, .json only, no traversal
        assert rel.startswith("research/m2b/raw/coinbase/"), rel
        assert rel.endswith(".json"), f"unexpected non-JSON tracked raw file: {rel}"
        assert ".." not in rel
        assert not path.is_symlink(), f"raw file is a symlink: {rel}"
        head = path.read_bytes()[:64]
        assert not head.startswith(b"version https://git-lfs"), f"LFS pointer masquerading: {rel}"


def test_raw_bodies_match_their_receipts() -> None:
    """Every tracked raw body is named in its plan and hashes to its receipt."""
    from eth_research.data.acquisition_plan import (
        load_acquisition_plan,
        load_acquisition_receipt,
    )
    from eth_research.data.provenance import sha256_file

    attempts = sorted(p for p in RAW_ROOT.iterdir() if p.is_dir())
    assert attempts, "expected at least one acquisition attempt"
    plan_for = {
        "discovery-001": "research/m2b/discovery_plan.json",
        "coinbase-eth-usd-001": "research/m2b/acquisition_request_plan.json",
        # The independent integrity reacquisition fulfils the unchanged
        # canonical plan under its own attempt id (closure section H).
        "coinbase-eth-usd-audit-002": "research/m2b/acquisition_request_plan.json",
    }
    for attempt in attempts:
        receipt = load_acquisition_receipt(attempt / "acquisition_receipt.json")
        plan = load_acquisition_plan(REPO_ROOT / plan_for[attempt.name])
        assert receipt.plan_sha256 == plan.plan_sha256()
        planned = {window.filename for window in plan.windows}
        bodies = {p.name for p in attempt.glob("*.json") if p.name != "acquisition_receipt.json"}
        assert bodies == planned, f"{attempt.name}: bodies {bodies} != planned {planned}"
        for response in receipt.responses:
            assert sha256_file(attempt / response.filename) == response.sha256


def test_raw_aggregate_size_is_bounded() -> None:
    total = sum((REPO_ROOT / rel).stat().st_size for rel in _tracked_files("research/m2b/raw"))
    assert total <= RAW_AGGREGATE_CAP_BYTES, f"raw aggregate {total} exceeds the 10 MiB cap"


# --- V2B cross-asset (BTC-USD) raw-data allowlist -----------------------------
# The V2B milestone acquires a genuinely new BTC-USD daily research dataset. Any
# committed raw body must be an allowlisted JSON candle body or receipt under the
# closed research/v2b/raw/coinbase/<attempt>/ tree — never a CSV/Parquet, symlink,
# LFS pointer, or traversal. This is a no-op before acquisition (no tracked files)
# and enforcing once the genesis/audit bundles are committed.


def test_v2b_tracked_raw_bodies_are_allowlisted_json() -> None:
    for rel in _tracked_files("research/v2b/raw"):
        path = REPO_ROOT / rel
        assert rel.startswith("research/v2b/raw/coinbase/"), rel
        assert rel.endswith(".json"), f"unexpected non-JSON tracked raw file: {rel}"
        assert ".." not in rel
        assert not path.is_symlink(), f"raw file is a symlink: {rel}"
        head = path.read_bytes()[:64]
        assert not head.startswith(b"version https://git-lfs"), f"LFS pointer masquerading: {rel}"


def test_v2b_raw_aggregate_size_is_bounded() -> None:
    total = sum((REPO_ROOT / rel).stat().st_size for rel in _tracked_files("research/v2b/raw"))
    assert total <= RAW_AGGREGATE_CAP_BYTES, f"v2b raw aggregate {total} exceeds the 10 MiB cap"


def test_frozen_dossier_anchors_every_committed_artifact() -> None:
    """The committed frozen dossier must hash-anchor every committed artifact.

    Version-independent: every ``*_sha256`` the dossier records for a
    tracked ``research/m2b`` artifact must equal that committed file's
    actual SHA-256. This holds regardless of the running package version
    (a later milestone bumps ``__version__`` while the frozen 0.3.0 dossier
    stays byte-identical). The full *semantic* graph — raw re-derivation,
    holdout recompute, evidence self-consistency, both raw-bundle
    fingerprints — runs in ``test_dossier.py`` and inside every shared-gate
    preparation. The version-coupled root ``uv.lock`` / ``pyproject.toml``
    anchors pin the frozen-snapshot lockfiles and are recognized as frozen
    when a later milestone advances the package version.
    """
    from eth_research.data.provenance import sha256_file
    from eth_research.dossier import DISCOVERY_ATTEMPT_ID, load_frozen_dossier

    dossier_path = REPO_ROOT / "research/m2b/frozen_dossier.json"
    dossier = load_frozen_dossier(dossier_path)
    # Byte-stable: the committed dossier round-trips exactly.
    assert dossier.to_json_bytes() == dossier_path.read_bytes()
    research = REPO_ROOT / "research/m2b"
    canonical_attempt = research / "raw/coinbase" / dossier.selected_attempt_id
    discovery_attempt = research / "raw/coinbase" / DISCOVERY_ATTEMPT_ID
    anchored = {
        "discovery_request_plan_sha256": research / "discovery_plan.json",
        "discovery_receipt_sha256": discovery_attempt / "acquisition_receipt.json",
        "discovery_decision_sha256": research / "discovery_decision.json",
        "discovery_decision_markdown_sha256": research / "EARLIEST_CONTINUOUS_DECISION.md",
        "acquisition_request_plan_sha256": research / "acquisition_request_plan.json",
        "acquisition_receipt_sha256": canonical_attempt / "acquisition_receipt.json",
        "acquisition_evidence_sha256": research / "acquisition_evidence.json",
        "dataset_manifest_sha256": research / "dataset_manifest.json",
        "quality_report_sha256": research / "quality_report.json",
        "dataset_lock_sha256": research / "dataset_lock.json",
        "runtime_contract_sha256": research / "runtime_contract.json",
        "protocol_sha256": research / "protocol.json",
        "holdout_identity_sha256": research / "holdout_identity.json",
        "train_validation_results_sha256": research / "train_validation_results.json",
        "train_validation_report_sha256": research / "train_validation_report.md",
        "validation_decision_sha256": research / "validation_decision.json",
        "validation_decision_markdown_sha256": research / "validation_decision.md",
    }
    for field, path in anchored.items():
        assert path.is_file(), f"{field} artifact {path} missing"
        assert sha256_file(path) == getattr(dossier, field), f"{field} anchor mismatch"


def test_exactly_one_graph_manifest_is_tracked() -> None:
    """The frozen dossier is the single graph file — no competing anchors."""
    assert _tracked_files("research/m2b/frozen_dossier.json")
    assert not (REPO_ROOT / "research/m2b/provenance_v2.json").exists()
    assert _tracked_files("research/m2b/provenance_v2.json") == []


def test_committed_manifest_and_quality_anchor_the_lock() -> None:
    """The tracked manifest/quality byte anchors must hash to the dataset lock.

    The lock already binds their SHA-256; committing the exact bytes lets a
    reviewer verify the dossier's identity without regenerating anything.
    """
    from eth_research.data.lock import load_dataset_lock
    from eth_research.data.provenance import DatasetManifest, sha256_file

    lock = load_dataset_lock(REPO_ROOT / "research/m2b/dataset_lock.json")
    manifest_path = REPO_ROOT / "research/m2b/dataset_manifest.json"
    quality_path = REPO_ROOT / "research/m2b/quality_report.json"
    assert _tracked_files("research/m2b/dataset_manifest.json")
    assert _tracked_files("research/m2b/quality_report.json")
    assert sha256_file(manifest_path) == lock.manifest_sha256
    assert sha256_file(quality_path) == lock.quality_report_sha256
    # The committed manifest anchor must strictly parse and name the quality file.
    manifest = DatasetManifest.from_json_bytes(manifest_path.read_bytes())
    assert manifest.quality_report_sha256 == lock.quality_report_sha256
    assert manifest.content_fingerprint == lock.content_fingerprint


def test_no_derived_or_canonical_artifacts_are_tracked() -> None:
    """The derived CSV and canonical Parquet must never be committed."""
    for pattern in ("*.csv", "*.parquet", "*.pq"):
        assert _tracked_files(pattern) == [], f"tracked {pattern} artifact found"
    # the derived CSV name specifically must not appear anywhere tracked
    assert _tracked_files("data") == []


def test_test_access_ledger_is_byte_empty() -> None:
    assert LEDGER.is_file()
    assert LEDGER.read_bytes() == b""


def test_no_real_test_reports_are_committed() -> None:
    for name in ("benchmark_results.json", "benchmark_report.md"):
        assert _tracked_files(name) == [], f"a real test report {name} is committed"


def test_train_validation_report_has_no_test_performance_row() -> None:
    report = REPO_ROOT / "research" / "m2b" / "train_validation_report.md"
    if not report.exists():
        return
    text = report.read_text(encoding="utf-8")
    assert "has **not** been evaluated" in text
    for line in text.splitlines():
        if line.startswith("| buy_and_hold |") or line.startswith("| sma_20_50 |"):
            assert "| test |" not in line


def test_no_private_key_material_in_tracked_tree() -> None:
    """No PEM private key blocks or committed .env files."""
    assert _tracked_files("*.env") == []
    for rel in _tracked_files("research") + _tracked_files("src") + _tracked_files("examples"):
        path = REPO_ROOT / rel
        if path.suffix in {".parquet", ".pq"}:
            continue
        raw = path.read_bytes()
        assert b"-----BEGIN" not in raw, f"PEM key block in {rel}"
