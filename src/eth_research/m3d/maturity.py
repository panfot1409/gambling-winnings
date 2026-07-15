"""Prospective maturity and evaluation-prohibition firewall.

Maturity (>= 365 completed observations, fixed start, continuous daily cadence,
zero structural errors, matching reacquisition) is a **necessary** condition for
any future eligibility review — and never a **sufficient** one. M3D authorizes
nothing: it contains no evaluation function, and ``evaluation_authorized`` is
false whether the cohort is mature or not. This module also fails closed on any
attempt to perform a non-data-only operation or to smuggle an evaluation
capability or artifact into the milestone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.m3d.cohort import assess_prospective_maturity
from eth_research.m3d.protocol import (
    MINIMUM_MATURITY_ROWS,
    require_prospective_evaluation_ledger_empty,
)
from eth_research.m3d.validation import M3DValidationError

# Operations a data-only, governance-only milestone may perform.
DATA_ONLY_OPERATIONS = frozenset(
    {
        "acquire",
        "transform",
        "fingerprint",
        "quality_audit",
        "segment",
        "publish",
        "maturity_assess",
        "status",
        "replay",
        "verify",
    }
)
# Operations that would evaluate, rank, tune, promote, or report performance.
FORBIDDEN_OPERATIONS = frozenset(
    {
        "evaluate",
        "backtest",
        "score",
        "rank",
        "tune",
        "optimize",
        "promote",
        "select",
        "compute_returns",
        "compute_metrics",
        "compare_performance",
        "declare_candidate",
        "decide",
    }
)
# Filename markers that would indicate an evaluation output artifact.
_FORBIDDEN_ARTIFACT_MARKERS = (
    "results",
    "decision",
    "ranking",
    "promotion",
    "performance",
    "backtest",
    "returns",
    "sharpe",
    "pnl",
    "equity",
)


@dataclass(frozen=True)
class ProspectiveMaturityState:
    row_count: int
    minimum_maturity_rows: int
    remaining_rows: int
    maturity_state: str
    evaluation_authorized: bool
    conditions: dict[str, bool]

    @property
    def is_mature(self) -> bool:
        return self.maturity_state == "mature"


def evaluate_maturity(repo_root: str | Path) -> ProspectiveMaturityState:
    """Assess maturity from committed evidence; assert evaluation stays unauthorized."""
    facts = assess_prospective_maturity(repo_root)
    state = ProspectiveMaturityState(
        row_count=int(facts["row_count"]),
        minimum_maturity_rows=int(facts["minimum_maturity_rows"]),
        remaining_rows=int(facts["remaining_rows"]),
        maturity_state=str(facts["maturity_state"]),
        evaluation_authorized=bool(facts["evaluation_authorized"]),
        conditions=dict(facts["maturity_conditions"]),
    )
    if state.minimum_maturity_rows != MINIMUM_MATURITY_ROWS:
        raise M3DValidationError("maturity floor was tampered (must be 365)")
    if state.evaluation_authorized:
        raise M3DValidationError("M3D never authorizes evaluation (HARD STOP)")
    return state


def require_data_only_operation(operation: str) -> str:
    """Fail closed unless ``operation`` is on the data-only allowlist."""
    if operation in FORBIDDEN_OPERATIONS:
        raise M3DValidationError(
            f"operation {operation!r} evaluates/ranks/promotes and is forbidden here"
        )
    if operation not in DATA_ONLY_OPERATIONS:
        raise M3DValidationError(f"operation {operation!r} is not on the data-only allowlist")
    return operation


def require_no_evaluation_capability(repo_root: str | Path) -> dict[str, Any]:
    """Fail closed if any evaluation capability, artifact, or authorization exists.

    The prospective evaluation ledger stays byte-empty; no evaluation-output
    artifact (results, decision, ranking, promotion, performance, returns, P&L,
    equity, Sharpe) exists under ``research/m3d``; and the cohort is not evaluation
    authorized even if mature.
    """
    ledger = require_prospective_evaluation_ledger_empty(repo_root)
    m3d = Path(repo_root) / "research/m3d"
    offenders: list[str] = []
    for path in sorted(m3d.rglob("*")):
        if not path.is_file():
            continue
        name = path.name.lower()
        if any(marker in name for marker in _FORBIDDEN_ARTIFACT_MARKERS):
            offenders.append(str(path.relative_to(Path(repo_root))))
    if offenders:
        raise M3DValidationError(f"forbidden evaluation-output artifacts present: {offenders}")
    state = evaluate_maturity(repo_root)
    return {
        "evaluation_ledger_byte_count": ledger["byte_count"],
        "maturity_state": state.maturity_state,
        "evaluation_authorized": state.evaluation_authorized,
    }
