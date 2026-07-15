"""Whole-program graph verifier for Milestone 3D.

``verify_m3d_program`` always runs the complete governance + evidence chain — no
parameter can skip a check. It re-derives every artifact from committed bytes,
proves the two sealed ledgers and the prospective evaluation ledger are
byte-empty, proves the M3C candidate is still rejected, reconstructs the primary
and audit cohorts and proves they match, verifies the segment chain, quality
report, cohort manifest, and publication manifest, proves the m3d package imports
no prohibited engine/strategy/evaluation module, proves no evaluation artifact or
smuggled performance field exists, proves the cohort is immature and unauthorized,
and proves no workflow other than the temporary acquisition workflow can write
repository contents.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from eth_research.m3d import _upstream as up
from eth_research.m3d.acquisition_plan import (
    AUDIT_ATTEMPT_ID,
    GENESIS_ATTEMPT_ID,
    load_prospective_acquisition_plan,
)
from eth_research.m3d.candidate_catalog import verify_research_specification_catalog
from eth_research.m3d.cohort import verify_cohort_manifest, verify_prospective_publication
from eth_research.m3d.data_use import verify_research_data_use
from eth_research.m3d.exhaustion import verify_research_train_exhaustion
from eth_research.m3d.maturity import evaluate_maturity, require_no_evaluation_capability
from eth_research.m3d.multiplicity import verify_research_multiplicity
from eth_research.m3d.program_history import verify_research_program_snapshot
from eth_research.m3d.protocol import verify_prospective_protocol
from eth_research.m3d.quality import verify_prospective_quality
from eth_research.m3d.raw_bundle import build_raw_bundles, cohort_canonical_fingerprint
from eth_research.m3d.reacquisition_audit import verify_reacquisition_audit
from eth_research.m3d.segment import verify_prospective_segments
from eth_research.m3d.validation import M3DValidationError

# Prohibited import prefixes for the isolated m3d package (engine/strategy/eval).
_PROHIBITED_IMPORT_PREFIXES = (
    "eth_research.strategies",
    "eth_research.backtest",
    "eth_research.metrics",
    "eth_research.accounting",
    "eth_research.evaluation",
    "eth_research.experiment",
    "eth_research.report",
    "eth_research.decision",
    "eth_research.walkforward",
    "eth_research.bootstrap",
    "eth_research.fractional.engine",
    "eth_research.m3c.orchestrator",
    "eth_research.m3c.experiment",
    "eth_research.m3c.pipeline",
    "eth_research.m3c.statistics",
    "eth_research.m3c.decision",
    "eth_research.m3c.results",
    "eth_research.m3c.candidate",
)
# Manifest/quality keys that would betray a smuggled evaluation.
_FORBIDDEN_FIELD_SUBSTRINGS = (
    "sharpe",
    "return",
    "pnl",
    "equity",
    "signal",
    "position",
    "weight",
    "ranking",
    "score",
    "alpha",
)
_ACQUIRE_WORKFLOW = "m3d-acquire.yml"


def _scan_prohibited_imports(repo_root: str | Path) -> None:
    package = Path(repo_root) / "src/eth_research/m3d"
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.append(node.module)
        for module in modules:
            if any(module == p or module.startswith(p + ".") for p in _PROHIBITED_IMPORT_PREFIXES):
                offenders.append(f"{path.name}: {module}")
    if offenders:
        raise M3DValidationError(f"m3d imports prohibited modules: {offenders}")


def _scan_forbidden_fields(*documents: Any) -> None:
    def walk(node: Any, trail: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).lower()
                if any(sub in lowered for sub in _FORBIDDEN_FIELD_SUBSTRINGS):
                    raise M3DValidationError(f"smuggled evaluation field {trail}.{key!r}")
                walk(value, f"{trail}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{trail}[{index}]")

    for document in documents:
        walk(document, "root")


def _no_other_write_capable_workflow(repo_root: str | Path) -> None:
    workflows = Path(repo_root) / ".github/workflows"
    for path in sorted(workflows.glob("*.yml")):
        if path.name == _ACQUIRE_WORKFLOW:
            continue  # the single temporary acquisition workflow (retired at section 25)
        text = path.read_text(encoding="utf-8")
        if "contents: write" in text or "contents:write" in text:
            raise M3DValidationError(f"{path.name} grants contents: write")


def verify_m3d_program(repo_root: str | Path) -> list[tuple[str, str]]:
    """Run the complete M3D verification chain; raise on the first failure."""
    root = Path(repo_root)
    checks: list[tuple[str, str]] = []

    def record(name: str, detail: str = "ok") -> None:
        checks.append((name, detail))

    # 1. Upstream anchors resolve and hash (drift on any anchor raises here).
    for milestone in ("m2b", "m3a", "m3b", "m3c"):
        up.anchor_hashes(root, milestone)
    record("01_upstream_anchors")

    # 2-4. The two sealed ledgers and the prospective evaluation ledger are empty.
    sealed = up.sealed_ledger_facts(root)
    for logical, check_name in (
        ("development_gate", "02_development_gate_ledger_empty"),
        ("final_holdout", "03_final_holdout_ledger_empty"),
    ):
        if sealed[logical]["byte_count"] != 0:
            raise M3DValidationError(f"sealed ledger {logical} is non-empty (HARD STOP)")
        record(check_name)
    prospective_ledger = up.ledger_facts(root, up.PROSPECTIVE_EVALUATION_LEDGER)
    if prospective_ledger["byte_count"] != 0:
        raise M3DValidationError("prospective evaluation ledger is non-empty (HARD STOP)")
    record("04_prospective_ledger_empty")

    # 5. M3C candidate still rejected.
    decision = up.load_json(root, up.ANCHORS["m3c"]["candidate_decision"])
    outcome = decision.get("outcome") if isinstance(decision, dict) else None
    if outcome != up.M3C_REJECTED_OUTCOME:
        raise M3DValidationError(f"M3C candidate outcome changed to {outcome!r} (HARD STOP)")
    record("04_m3c_still_rejected", str(outcome))

    # 6-11. Governance artifacts rebuild + verify.
    verify_research_program_snapshot(root)
    record("05_program_snapshot")
    verify_research_specification_catalog(root)
    record("06_specification_catalog")
    verify_research_multiplicity(root)
    record("07_multiplicity_ledger")
    verify_research_data_use(root)
    record("08_data_use_ledger")
    verify_research_train_exhaustion(root)
    record("09_exhaustion_decision")
    verify_prospective_protocol(root)
    record("10_prospective_protocol")

    # 12-14. Acquisition plans + primary/audit raw bundles rebuild.
    for attempt in (GENESIS_ATTEMPT_ID, AUDIT_ATTEMPT_ID):
        load_prospective_acquisition_plan(
            root / f"research/m3d/raw/coinbase/{attempt}/acquisition_plan.json"
        )
    record("11_acquisition_plans")
    genesis_fp = cohort_canonical_fingerprint(build_raw_bundles(root, GENESIS_ATTEMPT_ID))
    record("12_primary_canonical", genesis_fp[:16])
    audit_fp = cohort_canonical_fingerprint(build_raw_bundles(root, AUDIT_ATTEMPT_ID))
    record("13_audit_canonical", audit_fp[:16])

    # 15-17. Canonical match + reacquisition audit.
    if genesis_fp != audit_fp:
        raise M3DValidationError("primary and audit canonical content differ (HARD STOP)")
    record("14_canonical_match")
    verify_reacquisition_audit(root)
    record("15_reacquisition_audit")

    # 18-21. Segment chain, quality, cohort manifest, publication bundle.
    verify_prospective_segments(root)
    record("16_segment_chain")
    quality = verify_prospective_quality(root)
    record("17_quality_report")
    manifest = verify_cohort_manifest(root)
    record("18_cohort_manifest")
    verify_prospective_publication(root)
    record("19_publication_bundle")

    # 22. No prohibited imports in the isolated m3d package.
    _scan_prohibited_imports(root)
    record("20_no_prohibited_imports")

    # 23. No evaluation capability or artifact.
    require_no_evaluation_capability(root)
    record("21_no_evaluation_capability")

    # 24. The cohort is immature and never evaluation authorized.
    state = evaluate_maturity(root)
    if state.is_mature or state.evaluation_authorized:
        raise M3DValidationError("cohort must be immature and unauthorized (HARD STOP)")
    record("22_immature_and_unauthorized", f"{state.row_count}/{state.minimum_maturity_rows}")

    # 25. No smuggled strategy/candidate/performance field in the published evidence.
    _scan_forbidden_fields(manifest, quality)
    record("23_no_smuggled_performance_fields")

    # No write-capable workflow other than the temporary acquisition workflow.
    _no_other_write_capable_workflow(root)
    record("24_no_unexpected_write_workflow")

    return checks
