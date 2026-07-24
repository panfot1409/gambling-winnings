"""Whole-program graph verifier for Milestone 3D.

``verify_m3d_program`` always runs the complete governance + evidence chain — no
parameter can skip a check. It re-derives every artifact from committed bytes,
proves the two sealed ledgers and the prospective evaluation ledger are
byte-empty, proves the M3C candidate is still rejected, reconstructs the primary
and audit cohorts and proves they match, verifies the segment chain, quality
report, cohort manifest, and publication manifest, proves the m3d package imports
only its allow-listed strategy-free utilities, proves no evaluation artifact or
smuggled performance field (key OR value) exists in any published artifact,
proves the cohort is immature and unauthorized, and proves NO workflow can write
repository contents or contact Coinbase at the final HEAD.
"""

from __future__ import annotations

import ast
import re
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
from eth_research.m3d.publication import PUBLICATION_MANIFEST_PATH
from eth_research.m3d.quality import verify_prospective_quality
from eth_research.m3d.raw_bundle import build_raw_bundles, cohort_canonical_fingerprint
from eth_research.m3d.reacquisition_audit import (
    REACQUISITION_AUDIT_PATH,
    verify_reacquisition_audit,
)
from eth_research.m3d.segment import SEGMENTS_PATH, verify_prospective_segments
from eth_research.m3d.validation import M3DValidationError

# The isolated m3d package may import only these strategy-free eth_research
# modules (plus eth_research.m3d.* internals and any stdlib/third-party). This is
# an ALLOW-list — the robust dual of a deny-list — so a newly-added engine module
# cannot slip through a gap. It mirrors tests/test_m3d_architecture.py.
_ALLOWED_ETH_RESEARCH_IMPORTS = frozenset(
    {
        "eth_research",
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
# Substrings (matched against BOTH keys and string values) that would betray a
# smuggled strategy/performance quantity. None is representable inside a 64-hex
# digest or an ISO-8601 timestamp, so scanning values does not false-positive on
# the provenance hashes and open-times the artifacts legitimately carry.
_FORBIDDEN_FIELD_SUBSTRINGS = (
    "sharpe",
    "sortino",
    "calmar",
    "cagr",
    "drawdown",
    "volatility",
    "turnover",
    "profit_factor",
    "win_rate",
    "hit_rate",
    "information_ratio",
    "pnl",
    "equity_curve",
    "return",
    "signal",
    "position",
    "weight",
    "ranking",
    "alpha",
    "beta",
    "exposure",
    "leverage",
)
_COINBASE_HOST_RE = re.compile(r"https?://[^\s\"']*coinbase", re.IGNORECASE)


def _module_targets(path: Path, src_root: Path) -> list[str]:
    """Absolute dotted module names imported by ``path`` (relative imports resolved).

    Relative imports (``from .. import metrics``) must be resolved to their absolute
    dotted target, or a relatively-spelled forbidden dependency would slip past this
    runtime firewall (the m3e twin ``verify_m3e_program._module_targets`` does the same).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    self_pkg = ".".join(path.relative_to(src_root).with_suffix("").parts[:-1])
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — resolve against the module's package
                base_parts = self_pkg.split(".")
                if node.level > 1:
                    base_parts = base_parts[: -(node.level - 1)]
                base = ".".join(base_parts)
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            if module:
                modules.append(module)
    return modules


def _scan_prohibited_imports(repo_root: str | Path) -> None:
    src_root = Path(repo_root) / "src"
    package = src_root / "eth_research/m3d"
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        for module in _module_targets(path, src_root):
            if not module.startswith("eth_research"):
                continue  # stdlib / third-party
            if module == "eth_research.m3d" or module.startswith("eth_research.m3d."):
                continue  # internal
            if module not in _ALLOWED_ETH_RESEARCH_IMPORTS:
                offenders.append(f"{path.name}: {module}")
    if offenders:
        raise M3DValidationError(f"m3d imports non-allowlisted eth_research modules: {offenders}")


def _scan_forbidden_fields(*documents: Any) -> None:
    def check(token: str, trail: str) -> None:
        lowered = token.lower()
        for sub in _FORBIDDEN_FIELD_SUBSTRINGS:
            if sub in lowered:
                raise M3DValidationError(f"smuggled evaluation token {sub!r} at {trail}")

    def walk(node: Any, trail: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                check(str(key), f"{trail}.{key}")
                walk(value, f"{trail}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{trail}[{index}]")
        elif isinstance(node, str):
            check(node, trail)

    for document in documents:
        walk(document, "root")


def _no_write_or_coinbase_workflow(repo_root: str | Path) -> None:
    workflows = Path(repo_root) / ".github/workflows"
    files = sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")])
    for path in files:
        text = path.read_text(encoding="utf-8")
        # The V2D-anchored update workflow alone holds one job-scoped contents:
        # write (bot-branch push); its shape is pinned by verify_m3e_program
        # check 10 and the workflow-security suites. Everything else stays read-only.
        if path.name != "m3e-prospective-update.yml" and (
            "contents: write" in text or "contents:write" in text
        ):
            raise M3DValidationError(f"{path.name} grants contents: write at the final HEAD")
        if _COINBASE_HOST_RE.search(text):
            raise M3DValidationError(f"{path.name} contacts a Coinbase host at the final HEAD")
        if "secrets." in text:
            raise M3DValidationError(f"{path.name} references a repository secret")
        if "--force" in text:
            raise M3DValidationError(f"{path.name} force-pushes")


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
    if up.ledger_facts(root, up.PROSPECTIVE_EVALUATION_LEDGER)["byte_count"] != 0:
        raise M3DValidationError("prospective evaluation ledger is non-empty (HARD STOP)")
    record("04_prospective_ledger_empty")

    # 5. M3C candidate still rejected.
    decision = up.load_json(root, up.ANCHORS["m3c"]["candidate_decision"])
    outcome = decision.get("outcome") if isinstance(decision, dict) else None
    if outcome != up.M3C_REJECTED_OUTCOME:
        raise M3DValidationError(f"M3C candidate outcome changed to {outcome!r} (HARD STOP)")
    record("05_m3c_still_rejected", str(outcome))

    # 6-11. Governance artifacts rebuild + verify.
    verify_research_program_snapshot(root)
    record("06_program_snapshot")
    verify_research_specification_catalog(root)
    record("07_specification_catalog")
    verify_research_multiplicity(root)
    record("08_multiplicity_ledger")
    verify_research_data_use(root)
    record("09_data_use_ledger")
    verify_research_train_exhaustion(root)
    record("10_exhaustion_decision")
    verify_prospective_protocol(root)
    record("11_prospective_protocol")

    # 12-14. Acquisition plans + primary/audit raw bundles rebuild.
    for attempt in (GENESIS_ATTEMPT_ID, AUDIT_ATTEMPT_ID):
        load_prospective_acquisition_plan(
            root / f"research/m3d/raw/coinbase/{attempt}/acquisition_plan.json"
        )
    record("12_acquisition_plans")
    genesis_fp = cohort_canonical_fingerprint(build_raw_bundles(root, GENESIS_ATTEMPT_ID))
    record("13_primary_canonical", genesis_fp[:16])
    audit_fp = cohort_canonical_fingerprint(build_raw_bundles(root, AUDIT_ATTEMPT_ID))
    record("14_audit_canonical", audit_fp[:16])

    # 15-16. Canonical match + reacquisition audit (independence enforced there).
    if genesis_fp != audit_fp:
        raise M3DValidationError("primary and audit canonical content differ (HARD STOP)")
    record("15_canonical_match")
    audit_doc = verify_reacquisition_audit(root)
    record("16_reacquisition_audit")

    # 17-20. Segment chain, quality, cohort manifest, publication bundle.
    verify_prospective_segments(root)
    record("17_segment_chain")
    quality = verify_prospective_quality(root)
    record("18_quality_report")
    manifest = verify_cohort_manifest(root)
    record("19_cohort_manifest")
    verify_prospective_publication(root)
    record("20_publication_bundle")

    # 21. Only allow-listed imports in the isolated m3d package.
    _scan_prohibited_imports(root)
    record("21_allowlisted_imports_only")

    # 22. No evaluation capability or artifact.
    require_no_evaluation_capability(root)
    record("22_no_evaluation_capability")

    # 23. The cohort is immature and never evaluation authorized.
    state = evaluate_maturity(root)
    if state.is_mature or state.evaluation_authorized:
        raise M3DValidationError("cohort must be immature and unauthorized (HARD STOP)")
    record("23_immature_and_unauthorized", f"{state.row_count}/{state.minimum_maturity_rows}")

    # 24. No smuggled strategy/candidate/performance field (key OR value) in ANY
    #     published artifact.
    segments = up.jsonl_events(root, SEGMENTS_PATH)
    _scan_forbidden_fields(
        manifest,
        quality,
        audit_doc,
        segments,
        up.load_json(root, REACQUISITION_AUDIT_PATH),
        up.load_json(root, PUBLICATION_MANIFEST_PATH),
    )
    record("24_no_smuggled_performance_fields")

    # 25. No workflow may write repository contents or contact Coinbase at HEAD.
    _no_write_or_coinbase_workflow(root)
    record("25_no_write_or_coinbase_workflow")

    return checks
