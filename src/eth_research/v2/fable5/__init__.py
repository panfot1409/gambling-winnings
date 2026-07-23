"""V2 Fable 5 full-system audit support.

This subpackage holds the Fable 5 audit's *machine-readable system inventory* and its fail-closed
verifier. It is audit tooling: it enumerates the merged V2 platform's surfaces (package modules,
public API, CLIs, workflows, governed artifacts, registries, ledgers, archives, freezes, runtime
contracts, inactive templates) from committed bytes and refuses a tree that has drifted from the
frozen inventory or that exhibits a structural red flag (symlink, path traversal, duplicate
normalized path, unexpected executable, ungoverned workflow write-permission, unregistered CLI,
public-API drift).

It evaluates **no strategy**, reads **no** sealed value, and mutates **no** governed artifact.
"""

from __future__ import annotations

from eth_research.v2.fable5.inventory import (
    FABLE5_INVENTORY_RELPATH,
    Fable5InventoryError,
    build_system_inventory,
    verify_system_inventory,
)
from eth_research.v2.fable5.paper_readiness import (
    PAPER_ACTIVATION_GATES,
    PAPER_READINESS_RELPATH,
    PaperReadinessError,
    PaperReadinessState,
    derive_paper_readiness,
    verify_paper_readiness,
)

__all__ = [
    "FABLE5_INVENTORY_RELPATH",
    "PAPER_ACTIVATION_GATES",
    "PAPER_READINESS_RELPATH",
    "Fable5InventoryError",
    "PaperReadinessError",
    "PaperReadinessState",
    "build_system_inventory",
    "derive_paper_readiness",
    "verify_paper_readiness",
    "verify_system_inventory",
]
