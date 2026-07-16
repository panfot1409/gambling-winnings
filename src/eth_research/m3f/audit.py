"""The whole-graph repository freeze verifier for Milestone 3F.

``verify_repository_freeze`` runs the entire M3F integrity graph in one call — no
optional argument can silently skip a check. It never computes a strategy signal,
calls a backtest, computes a return/metric, evaluates a sealed partition, mutates a
ledger, publishes a proposal, opens a network connection, or consults the wall clock
to decide integrity. When the committed M3F artifacts are present it verifies their
byte reproduction; the always-available governance derivation fails closed on the
three forever-invariants regardless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from eth_research.m3f.catalog import CATALOG_RELPATH, verify_catalog
from eth_research.m3f.dependency_inventory import INVENTORY_RELPATH as DEP_RELPATH
from eth_research.m3f.dependency_inventory import verify_inventory as verify_dep_inventory
from eth_research.m3f.honest_state import (
    HONEST_STATE_RELPATH,
    derive_honest_state,
    verify_honest_state,
)
from eth_research.m3f.state_machine import verify_state
from eth_research.m3f.validation import M3FValidationError
from eth_research.m3f.workflow_inventory import INVENTORY_RELPATH as WF_RELPATH
from eth_research.m3f.workflow_inventory import build_and_check
from eth_research.m3f.workflow_inventory import verify_inventory as verify_wf_inventory


@dataclass
class FreezeResult:
    checks: list[tuple[str, str]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def _ok(self, name: str, detail: str = "ok") -> None:
        self.checks.append((name, detail))

    def _fail(self, name: str, detail: str) -> None:
        self.checks.append((name, detail))
        self.failures.append(f"{name}: {detail}")

    def raise_for_status(self) -> None:
        if self.failures:
            raise M3FValidationError(
                "repository freeze verification failed: " + "; ".join(self.failures)
            )


def verify_repository_freeze(repo_root: str | Path) -> FreezeResult:
    """Run the complete read-only integrity graph; collect every failure."""
    root = Path(repo_root)
    result = FreezeResult()

    # 1. Governance derivation — fails closed on the three forever-invariants.
    try:
        honest = derive_honest_state(root)
        result._ok("01_honest_state_invariants")
    except (OSError, M3FValidationError) as exc:
        result._fail("01_honest_state_invariants", str(exc))
        return result  # nothing else is trustworthy if the governance state is wrong

    # 2. Governance state machine — impossible combinations refused.
    try:
        verify_state(honest)
        result._ok("02_governance_state_legal")
    except M3FValidationError as exc:
        result._fail("02_governance_state_legal", str(exc))

    # 3. Workflow supply-chain check (no committed inventory needed).
    _inv, wf_failures = build_and_check(root)
    if wf_failures:
        result._fail("03_workflow_supply_chain", "; ".join(wf_failures[:5]))
    else:
        result._ok("03_workflow_supply_chain")

    # 4-6. Committed-artifact verifications (present post-registration).
    if (root / CATALOG_RELPATH).is_file():
        try:
            verify_catalog(root).raise_for_status()
            result._ok("04_freeze_catalog")
        except M3FValidationError as exc:
            result._fail("04_freeze_catalog", str(exc))
    else:
        result._fail("04_freeze_catalog", "freeze_catalog.json is not committed")

    if (root / HONEST_STATE_RELPATH).is_file():
        try:
            verify_honest_state(root)
            result._ok("05_honest_state_reproduces")
        except M3FValidationError as exc:
            result._fail("05_honest_state_reproduces", str(exc))
    else:
        result._fail("05_honest_state_reproduces", "honest_state.json is not committed")

    if (root / DEP_RELPATH).is_file():
        try:
            verify_dep_inventory(root)
            result._ok("06_dependency_inventory")
        except M3FValidationError as exc:
            result._fail("06_dependency_inventory", str(exc))
    else:
        result._fail("06_dependency_inventory", "dependency_inventory.json is not committed")

    if (root / WF_RELPATH).is_file():
        try:
            verify_wf_inventory(root)
            result._ok("07_workflow_inventory")
        except M3FValidationError as exc:
            result._fail("07_workflow_inventory", str(exc))
    else:
        result._fail("07_workflow_inventory", "workflow_inventory.json is not committed")

    return result


def _audit_payload(repo_root: str | Path) -> dict[str, object]:
    result = verify_repository_freeze(repo_root)
    return {
        "ok": result.ok,
        "checks": [name for name, _ in result.checks],
        "failures": result.failures,
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    from eth_research.m3f.cli import repo_root_parser, run_guarded

    args = repo_root_parser("M3F whole-graph repository-freeze audit (read-only)").parse_args(argv)
    return run_guarded(lambda: _audit_payload(args.repo_root), as_json=args.json or args.deep)


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
