"""The whole-stack V2A-V2B acceptance verifier (section 22).

One offline, read-only entry point that chains every acceptance verifier this package provides:
the immutable freeze table, the independent V2A and V2B result-reconstruction oracles, the BTC
acquisition audit, the raw-to-result provenance graph (optionally deep), the cumulative
family-catalog enumeration, the hash-chained negative-evidence index, the research-debt register,
the legacy-research moratorium closure, the commercial-truth pack, the sales-material scanner, and
the three byte-empty sealed access ledgers. It never evaluates a candidate, reads a sealed
partition, or mutates any artifact; it only runs the committed verifiers and aggregates problems.
"""

from __future__ import annotations

import json
from pathlib import Path

from eth_research.v2.strict import sha256_bytes
from eth_research.v2ab import SEALED_LEDGER_RELPATHS
from eth_research.v2ab.acquisition_audit import verify_btc_acquisition
from eth_research.v2ab.commercial_truth import scan_repo_sales_material, verify_commercial_truth
from eth_research.v2ab.family_catalog_audit import verify_family_catalog
from eth_research.v2ab.freeze_table import verify_freeze_table
from eth_research.v2ab.moratorium import verify_closure
from eth_research.v2ab.negative_evidence import verify_negative_evidence
from eth_research.v2ab.provenance_graph import verify_provenance_graph
from eth_research.v2ab.research_debt import verify_research_debt
from eth_research.v2ab.v2a_oracle import verify_v2a_reconstruction
from eth_research.v2ab.v2b_oracle import verify_v2b_reconstruction

_EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _verify_sealed_ledgers(repo_root: str | Path) -> list[str]:
    root = Path(repo_root)
    problems: list[str] = []
    for relpath in SEALED_LEDGER_RELPATHS:
        path = root / relpath
        if not path.exists():
            problems.append(f"sealed ledger missing: {relpath}")
            continue
        data = path.read_bytes()
        if data != b"" or sha256_bytes(data) != _EMPTY_SHA256:
            problems.append(f"sealed ledger is not byte-empty: {relpath}")
    return problems


def verify_stack_acceptance(repo_root: str | Path, *, deep: bool = False) -> list[str]:
    """Run every acceptance verifier; return the aggregated source-prefixed problems (empty=OK)."""
    checks: list[tuple[str, list[str]]] = [
        ("freeze_table", verify_freeze_table(repo_root)),
        ("v2a_oracle", verify_v2a_reconstruction(repo_root)),
        ("v2b_oracle", verify_v2b_reconstruction(repo_root)),
        ("btc_acquisition", verify_btc_acquisition(repo_root)),
        ("provenance_graph", verify_provenance_graph(repo_root, deep=deep)),
        ("family_catalog", verify_family_catalog(repo_root)),
        ("negative_evidence", verify_negative_evidence(repo_root)),
        ("research_debt", verify_research_debt(repo_root)),
        ("moratorium_closure", verify_closure(repo_root)),
        ("commercial_truth", verify_commercial_truth(repo_root)),
        ("sales_material", scan_repo_sales_material(repo_root)),
        ("sealed_ledgers", _verify_sealed_ledgers(repo_root)),
    ]
    problems: list[str] = []
    for source, found in checks:
        problems.extend(f"{source}: {p}" for p in found)
    return problems


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify the whole V2A-V2B stacked acceptance (offline)."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--deep", action="store_true", help="Run the deep provenance reconstruction too."
    )
    parser.add_argument("--check", action="store_true", help="Verify (the only mode).")
    args = parser.parse_args(argv)
    problems = verify_stack_acceptance(args.repo_root, deep=args.deep)
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["verify_stack_acceptance"]
