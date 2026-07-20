"""Append-only, hash-chained cumulative negative-evidence index.

This module derives one record per cumulatively evaluated research family (the eight historical
families, the two V2B cross-asset families, and the two benchmark references) and binds, for each,
the exact governance evidence: family id, experiment id, partition, primary benchmark, primary
endpoint, cost scenarios, the pass/fail criteria vector, the committed decision, a closed
negative-evidence status, the result/report/archive digests where available, the limitations, an
explicit sealed-access disclosure (``sealed_data_touched`` is FALSE), and the exact evidence paths.
It writes ``research/v2/negative_evidence_index.jsonl`` as a canonical, deterministically
sorted, genesis-first hash chain (each line commits to the prior line's bytes), and verifies the
committed index reproduces byte-for-byte and refuses every tamper the task enumerates.

Decision semantics are preserved exactly, not collapsed to a binary "failed": the closed status set
distinguishes ``benchmark_only`` (a comparator, not a candidate), ``not_eligible`` (an exploratory
fixed rule with no promotion pathway), ``risk_reduction_observation`` (a volatility target that cut
drawdown without earning excess return), ``rejected_for_promotion`` (a candidate that failed its
mechanical gate), ``no_nomination`` (a V2B candidate that cleared no full eligibility gate), and the
reserved ``compatibility_only`` / ``invalidated`` / ``insufficient_evidence`` for completeness.

Read-only and result-neutral: it reads only already-committed evidence, never a sealed partition,
and never mutates any accepted artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.m3d.chain import (
    chained_line_bytes,
    load_and_verify_chain,
    render_ledger_bytes,
    split_ledger_lines,
)
from eth_research.v2.strict import (
    V2ValidationError,
    load_canonical_json,
    require_mapping,
    require_nonempty_str,
    sha256_bytes,
    strict_json_loads,
)
from eth_research.v2ab import family_catalog_audit as fca

NEGATIVE_EVIDENCE_SCHEMA_VERSION: int = 1
NEGATIVE_EVIDENCE_RELPATH: str = "research/v2/negative_evidence_index.jsonl"

#: Domain-separation tag carried by the genesis line (never reused by another ledger).
_DOMAIN: str = "eth_research.v2ab.negative_evidence.v1"

#: The closed negative-evidence status vocabulary. Every record's status must be a member; an
#: unknown status is rejected. Reserved members keep the vocabulary complete without being forced
#: onto a family that does not warrant them.
NEGATIVE_EVIDENCE_STATUSES: frozenset[str] = frozenset(
    {
        "benchmark_only",
        "rejected_for_promotion",
        "not_eligible",
        "no_nomination",
        "risk_reduction_observation",
        "compatibility_only",
        "invalidated",
        "insufficient_evidence",
    }
)

_DISCLOSURE: str = (
    "No sealed partition (development-gate, final-holdout, prospective) was read for this record."
)

# --------------------------------------------------------------------------- #
# canonical limitation strings (verbatim; softening is caught by byte-compare) #
# --------------------------------------------------------------------------- #
_LIMIT_IN_SAMPLE: str = (
    "In-sample research-train measurement only; not development-gate or final-holdout evidence."
)
_LIMIT_DOF: str = (
    "Family-wise multiplicity correction bounds Type-I error but not researcher degrees of freedom."
)
_LIMIT_NO_RESET: str = (
    "The cumulative alpha budget never resets across package version, new instrument, or benchmark."
)
_LIMIT_M3A: str = (
    "Fixed-rule out-of-sample diagnostic; paired excess-return intervals vs buy-and-hold span zero."
)
_LIMIT_M3B: str = (
    "Execution-risk characterization; the vol target cut drawdown without earning excess return."
)
_LIMIT_M3C: str = (
    "Adaptively motivated single candidate; a passing primary would yield only gate eligibility."
)
_LIMIT_V2A: str = (
    "Pre-registered ETH family; it cleared neither the primary lower-bound nor stressed gate."
)
_LIMIT_V2B: str = (
    "Pre-registered cross-asset family; it cleared no full eligibility gate under cumulative alpha."
)
_LIMIT_BENCHMARK: str = (
    "Benchmark reference only; it defines the comparator and is not a comparable candidate."
)

_SHARED_LIMITS: tuple[str, ...] = (_LIMIT_IN_SAMPLE, _LIMIT_DOF, _LIMIT_NO_RESET)

# Cost-scenario vocabularies (grounded in each milestone's committed protocol/decision structure).
_M3A_COSTS: tuple[str, ...] = ("base", "stressed", "severe")
_M3BC_COSTS: tuple[str, ...] = ("compatibility_v1", "causal_proxy_base", "causal_proxy_stressed")
_ROBUSTNESS_COSTS: tuple[str, ...] = ("primary", "stressed")

# Evidence relpaths per milestone experiment.
_M3A_DIR: str = "research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003"
_M3A_RESULT: str = f"{_M3A_DIR}/development_results.json"
_M3A_REPORT: str = f"{_M3A_DIR}/development_report.md"
_M3A_ARCHIVE: str = f"{_M3A_DIR}/artifact_manifest.json"
_M3B_RESULT: str = "research/m3b/fractional_results.json"
_M3B_REPORT: str = "research/m3b/fractional_report.md"
_M3B_ARCHIVE: str = "research/m3b/experiments/run-001/immutable-v2/archive_v2.json"
_M3C_RESULT: str = "research/m3c/candidate_results.json"
_M3C_REPORT: str = "research/m3c/candidate_report.md"
_M3C_ARCHIVE: str = "research/m3c/experiments/run-001/manifest.json"
_M3C_DECISION: str = "research/m3c/candidate_decision.json"
_V2A_RESULT: str = "research/v2a/results.json"
_V2A_ARCHIVE: str = "research/v2a/results_manifest.json"
_V2B_RESULT: str = "research/v2b/v2b_results.json"
_V2B_ARCHIVE: str = "research/v2b/v2b_results_manifest.json"
_BENCH_CATALOG: str = "research/v2b/research_family_catalog.json"
_BENCH_LEDGER: str = "research/v2b/research_exposure_ledger.jsonl"


class NegativeEvidenceError(V2ValidationError):
    """A negative-evidence artifact was malformed, drifted, or tampered."""


@dataclass(frozen=True, slots=True)
class NegativeEvidenceRecord:
    """One family's cumulative negative-evidence record (exact decision semantics preserved)."""

    family_id: str
    experiment_id: str
    partition: str
    primary_benchmark: str
    primary_endpoint: str
    cost_scenarios: tuple[str, ...]
    criteria: tuple[tuple[str, bool], ...]
    decision: str
    status: str
    result_digest: str
    report_digest: str
    archive_digest: str
    limitations: tuple[str, ...]
    sealed_data_touched: bool
    sealed_access_disclosure: str
    evidence_paths: tuple[str, ...]

    def to_ledger_dict(self) -> dict[str, object]:
        return {
            "kind": "negative_evidence_record",
            "family_id": self.family_id,
            "experiment_id": self.experiment_id,
            "partition": self.partition,
            "primary_benchmark": self.primary_benchmark,
            "primary_endpoint": self.primary_endpoint,
            "cost_scenarios": list(self.cost_scenarios),
            "criteria": dict(self.criteria),
            "decision": self.decision,
            "status": self.status,
            "result_digest": self.result_digest,
            "report_digest": self.report_digest,
            "archive_digest": self.archive_digest,
            "limitations": list(self.limitations),
            "sealed_data_touched": self.sealed_data_touched,
            "sealed_access_disclosure": self.sealed_access_disclosure,
            "evidence_paths": list(self.evidence_paths),
        }


# --------------------------------------------------------------------------- #
# strict readers for the file-backed decision / criteria vectors               #
# --------------------------------------------------------------------------- #
def _require_bool(label: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise NegativeEvidenceError(f"{label} must be a JSON boolean, got {type(value).__name__}")
    return value


def _bool_pairs(label: str, obj: dict[str, Any]) -> tuple[tuple[str, bool], ...]:
    return tuple((k, _require_bool(f"{label}.{k}", obj[k])) for k in sorted(obj))


def _m3c_decision_criteria(root: Path) -> tuple[str, tuple[tuple[str, bool], ...]]:
    obj = require_mapping("m3c_decision", load_canonical_json(root / _M3C_DECISION))
    outcome = require_nonempty_str("m3c_decision.outcome", obj["outcome"])
    criteria = obj["criteria"]
    if not isinstance(criteria, list):
        raise NegativeEvidenceError("m3c_decision.criteria must be a list")
    pairs: dict[str, bool] = {}
    for i, row in enumerate(criteria):
        crow = require_mapping(f"m3c_decision.criteria[{i}]", row)
        cid = require_nonempty_str("criterion_id", crow["criterion_id"])
        pairs[cid] = _require_bool(f"m3c_decision.criteria[{i}].passed", crow["passed"])
    return outcome, tuple(sorted(pairs.items()))


def _v2a_outcomes(root: Path) -> dict[str, tuple[str, tuple[tuple[str, bool], ...]]]:
    obj = require_mapping("v2a_results", load_canonical_json(root / _V2A_RESULT))
    decision = require_mapping("v2a_results.decision", obj["decision"])
    outcomes = decision["outcomes"]
    if not isinstance(outcomes, list):
        raise NegativeEvidenceError("v2a_results.decision.outcomes must be a list")
    resolved: dict[str, tuple[str, tuple[tuple[str, bool], ...]]] = {}
    for i, row in enumerate(outcomes):
        orow = require_mapping(f"v2a_results.decision.outcomes[{i}]", row)
        cid = require_nonempty_str("v2a candidate_id", orow["candidate_id"])
        status = require_nonempty_str("v2a status", orow["status"])
        criteria = require_mapping(f"v2a outcomes[{i}].criteria", orow["criteria"])
        resolved[cid] = (status, _bool_pairs("v2a criteria", criteria))
    return resolved


def _v2b_gates(root: Path) -> dict[str, tuple[str, str, tuple[tuple[str, bool], ...]]]:
    obj = require_mapping("v2b_results", load_canonical_json(root / _V2B_RESULT))
    result = require_mapping("v2b_results.result", obj["result"])
    candidates = result["candidates"]
    if not isinstance(candidates, list):
        raise NegativeEvidenceError("v2b_results.result.candidates must be a list")
    resolved: dict[str, tuple[str, str, tuple[tuple[str, bool], ...]]] = {}
    for i, row in enumerate(candidates):
        crow = require_mapping(f"v2b candidates[{i}]", row)
        evaluation = require_mapping(f"v2b candidates[{i}].evaluation", crow["evaluation"])
        gates_outer = require_mapping(f"v2b candidates[{i}].gates", crow["gates"])
        gates = require_mapping(f"v2b candidates[{i}].gates.gates", gates_outer["gates"])
        cid = require_nonempty_str("v2b candidate_id", evaluation["candidate_id"])
        benchmark = require_nonempty_str("v2b benchmark", evaluation["benchmark"])
        eligible = _require_bool(f"v2b candidates[{i}].gates.eligible", gates_outer["eligible"])
        decision = "not_nominated" if not eligible else "eligible_pending_review"
        resolved[cid] = (decision, benchmark, _bool_pairs("v2b gates", gates))
    return resolved


# --------------------------------------------------------------------------- #
# record assembly (one per cumulatively evaluated family)                      #
# --------------------------------------------------------------------------- #
def _digest(root: Path, relpath: str) -> str:
    """SHA-256 of a committed evidence file, or empty when the family has no such artifact."""
    if relpath == "":
        return ""
    return sha256_bytes((root / relpath).read_bytes())


def build_negative_evidence_index(repo_root: str | Path) -> list[NegativeEvidenceRecord]:
    """Derive the sorted list of cumulative negative-evidence records from committed evidence."""
    root = Path(repo_root)
    m3c_decision, m3c_criteria = _m3c_decision_criteria(root)
    v2a = _v2a_outcomes(root)
    v2b = _v2b_gates(root)

    records: list[NegativeEvidenceRecord] = []

    def add(rec: NegativeEvidenceRecord) -> None:
        records.append(rec)

    # Benchmarks -- comparator references, not comparable candidates.
    for family_id in ("cash_benchmark", "passive_eth_buy_and_hold_benchmark"):
        add(
            NegativeEvidenceRecord(
                family_id=family_id,
                experiment_id="benchmark_reference",
                partition="research_train",
                primary_benchmark="self",
                primary_endpoint="none",
                cost_scenarios=(),
                criteria=(),
                decision="benchmark_reference",
                status="benchmark_only",
                result_digest="",
                report_digest="",
                archive_digest="",
                limitations=(_LIMIT_BENCHMARK, _LIMIT_IN_SAMPLE),
                sealed_data_touched=False,
                sealed_access_disclosure=_DISCLOSURE,
                evidence_paths=(_BENCH_CATALOG, _BENCH_LEDGER),
            )
        )

    # M3A exploratory fixed rules -- no formal promotion pathway existed.
    for family_id in ("m3a_sma_crossover", "m3a_donchian_breakout"):
        add(
            NegativeEvidenceRecord(
                family_id=family_id,
                experiment_id="m3a-fixed-baseline-comparison-v2-run-003",
                partition="research_train",
                primary_benchmark="buy_and_hold",
                primary_endpoint="paired_log_excess_return",
                cost_scenarios=_M3A_COSTS,
                criteria=(
                    ("beats_buy_and_hold_fold_majority", False),
                    ("primary_excess_ci_excludes_zero", False),
                ),
                decision="not_promoted",
                status="not_eligible",
                result_digest=_digest(root, _M3A_RESULT),
                report_digest=_digest(root, _M3A_REPORT),
                archive_digest=_digest(root, _M3A_ARCHIVE),
                limitations=(*_SHARED_LIMITS, _LIMIT_M3A),
                sealed_data_touched=False,
                sealed_access_disclosure=_DISCLOSURE,
                evidence_paths=(_M3A_RESULT, _M3A_REPORT, _M3A_ARCHIVE),
            )
        )

    # M3B volatility-target overlays -- risk reduction without excess return.
    for family_id in (
        "m3b_vol_target_buy_and_hold_30d_50pct",
        "m3b_vol_target_donchian_55_20_30d_50pct",
    ):
        add(
            NegativeEvidenceRecord(
                family_id=family_id,
                experiment_id="m3b-fractional-execution-risk-v1-run-001",
                partition="research_train",
                primary_benchmark="buy_and_hold",
                primary_endpoint="paired_log_excess_return",
                cost_scenarios=_M3BC_COSTS,
                criteria=(
                    ("beats_buy_and_hold_fold_majority", False),
                    ("reduces_drawdown_vs_buy_and_hold", True),
                ),
                decision="not_promoted",
                status="risk_reduction_observation",
                result_digest=_digest(root, _M3B_RESULT),
                report_digest=_digest(root, _M3B_REPORT),
                archive_digest=_digest(root, _M3B_ARCHIVE),
                limitations=(*_SHARED_LIMITS, _LIMIT_M3B),
                sealed_data_touched=False,
                sealed_access_disclosure=_DISCLOSURE,
                evidence_paths=(_M3B_RESULT, _M3B_REPORT, _M3B_ARCHIVE),
            )
        )

    # M3C dual-horizon trend -- mechanical seven-part rule, rejected for promotion.
    add(
        NegativeEvidenceRecord(
            family_id="m3c_dual_horizon_trend_63_252_vol_target_30d_50pct",
            experiment_id="m3c-dual-horizon-trend-v1-run-001",
            partition="research_train",
            primary_benchmark="buy_and_hold",
            primary_endpoint="paired_log_excess_return",
            cost_scenarios=_M3BC_COSTS,
            criteria=m3c_criteria,
            decision=m3c_decision,
            status="rejected_for_promotion",
            result_digest=_digest(root, _M3C_RESULT),
            report_digest=_digest(root, _M3C_REPORT),
            archive_digest=_digest(root, _M3C_ARCHIVE),
            limitations=(*_SHARED_LIMITS, _LIMIT_M3C),
            sealed_data_touched=False,
            sealed_access_disclosure=_DISCLOSURE,
            evidence_paths=(_M3C_RESULT, _M3C_REPORT, _M3C_ARCHIVE, _M3C_DECISION),
        )
    )

    # V2A ETH families -- three pre-registered candidates, all research-stage rejected.
    _v2a_ids = {
        "v2a_meanrev_zscore_accumulation": "meanrev_zscore_accumulation",
        "v2a_trend_regime_single_horizon": "trend_regime_single_horizon",
        "v2a_vol_scaled_hold_drawdown_guard": "vol_scaled_hold_drawdown_guard",
    }
    for family_id, cid in _v2a_ids.items():
        if cid not in v2a:
            raise NegativeEvidenceError(f"v2a results omit candidate {cid!r}")
        status_decision, criteria = v2a[cid]
        add(
            NegativeEvidenceRecord(
                family_id=family_id,
                experiment_id="v2a_run_001",
                partition="research_train",
                primary_benchmark="buy_and_hold",
                primary_endpoint="paired_log_excess_return",
                cost_scenarios=_ROBUSTNESS_COSTS,
                criteria=criteria,
                decision=status_decision,
                status="rejected_for_promotion",
                result_digest=_digest(root, _V2A_RESULT),
                report_digest="",
                archive_digest=_digest(root, _V2A_ARCHIVE),
                limitations=(*_SHARED_LIMITS, _LIMIT_V2A),
                sealed_data_touched=False,
                sealed_access_disclosure=_DISCLOSURE,
                evidence_paths=(_V2A_RESULT, _V2A_ARCHIVE),
            )
        )

    # V2B cross-asset families -- two pre-registered candidates, no nomination.
    _v2b_ids = {
        "v2b_cross_asset_btc_confirmed_eth_trend": "cross_asset_btc_confirmed_eth_trend",
        "v2b_cross_asset_eth_btc_relative_strength_rotation": (
            "cross_asset_eth_btc_relative_strength_rotation"
        ),
    }
    for family_id, cid in _v2b_ids.items():
        if cid not in v2b:
            raise NegativeEvidenceError(f"v2b results omit candidate {cid!r}")
        decision, benchmark, gates = v2b[cid]
        add(
            NegativeEvidenceRecord(
                family_id=family_id,
                experiment_id="v2b_run_001",
                partition="research_train",
                primary_benchmark=benchmark,
                primary_endpoint="paired_log_excess_return",
                cost_scenarios=_ROBUSTNESS_COSTS,
                criteria=gates,
                decision=decision,
                status="no_nomination",
                result_digest=_digest(root, _V2B_RESULT),
                report_digest="",
                archive_digest=_digest(root, _V2B_ARCHIVE),
                limitations=(*_SHARED_LIMITS, _LIMIT_V2B),
                sealed_data_touched=False,
                sealed_access_disclosure=_DISCLOSURE,
                evidence_paths=(_V2B_RESULT, _V2B_ARCHIVE),
            )
        )

    return sorted(records, key=lambda r: r.family_id)


def _genesis_record() -> dict[str, object]:
    return {
        "kind": "negative_evidence_genesis",
        "schema_version": NEGATIVE_EVIDENCE_SCHEMA_VERSION,
        "domain": _DOMAIN,
        "milestone": "v2ab",
        "note": "cumulative negative-evidence index; append-only, hash-chained; no sealed read",
    }


def negative_evidence_ledger_records(repo_root: str | Path) -> list[dict[str, object]]:
    """Genesis line plus one dict per record, in chain order (no ``previous_line_sha256`` yet)."""
    records = build_negative_evidence_index(repo_root)
    return [_genesis_record(), *[r.to_ledger_dict() for r in records]]


def build_negative_evidence_index_bytes(repo_root: str | Path) -> bytes:
    """The canonical hash-chained JSONL bytes of the cumulative negative-evidence index."""
    return render_ledger_bytes(chained_line_bytes(negative_evidence_ledger_records(repo_root)))


def write_negative_evidence_index(repo_root: str | Path) -> Path:
    """Write the committed index to ``research/v2/negative_evidence_index.jsonl`` and return it."""
    root = Path(repo_root)
    path = root / NEGATIVE_EVIDENCE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_negative_evidence_index_bytes(root))
    return path


# --------------------------------------------------------------------------- #
# verifier -- refuses every enumerated tamper                                  #
# --------------------------------------------------------------------------- #
def _committed_record_dicts(raw: bytes) -> list[dict[str, Any]]:
    lines = split_ledger_lines(raw)
    return [require_mapping(f"line[{i}]", strict_json_loads(line)) for i, line in enumerate(lines)]


def _compare_record(
    family_id: str, committed: dict[str, Any], expected: dict[str, object], problems: list[str]
) -> None:
    for field in ("decision", "primary_endpoint", "status", "sealed_access_disclosure"):
        if committed.get(field) != expected[field]:
            problems.append(f"{family_id}: {field} changed from the derived evidence")
    if committed.get("cost_scenarios") != expected["cost_scenarios"]:
        problems.append(f"{family_id}: cost scenarios changed (a scenario was added or removed)")
    if committed.get("criteria") != expected["criteria"]:
        problems.append(f"{family_id}: pass/fail criteria vector changed")
    if committed.get("limitations") != expected["limitations"]:
        problems.append(f"{family_id}: limitations changed (a limitation was softened or dropped)")
    if committed.get("sealed_data_touched") is not False:
        problems.append(f"{family_id}: fabricated sealed access (sealed_data_touched is not false)")
    if "sealed_access_disclosure" not in committed:
        problems.append(f"{family_id}: sealed-access disclosure removed")
    status = committed.get("status")
    if status not in NEGATIVE_EVIDENCE_STATUSES:
        problems.append(f"{family_id}: unknown status {status!r}")


def verify_negative_evidence(repo_root: str | Path) -> list[str]:
    """Verify the committed negative-evidence index; empty return means it is intact.

    Rejects: an omitted or duplicated family, a changed decision or endpoint, a removed cost
    scenario, a softened limitation, fabricated sealed access, a removed sealed-access disclosure, a
    reordered or deleted line, a broken previous-line digest, and an unknown status.
    """
    root = Path(repo_root)
    path = root / NEGATIVE_EVIDENCE_RELPATH
    if not path.exists():
        return [f"{NEGATIVE_EVIDENCE_RELPATH} is missing"]

    problems: list[str] = []
    raw = path.read_bytes()

    # 1. hash chain integrity (broken previous digest / reordered / deleted / non-canonical line).
    try:
        load_and_verify_chain(root, NEGATIVE_EVIDENCE_RELPATH)
    except ValueError as exc:
        problems.append(f"hash chain invalid: {exc}")

    # 2. structural + semantic field checks against the independently derived records.
    try:
        committed = _committed_record_dicts(raw)
        expected = build_negative_evidence_index(root)
    except ValueError as exc:
        problems.append(f"index is unreadable: {exc}")
        return problems

    committed_body = committed[1:] if committed else []
    committed_ids = [require_nonempty_str("family_id", r["family_id"]) for r in committed_body]
    expected_by_id = {r.family_id: r.to_ledger_dict() for r in expected}

    seen: set[str] = set()
    for fid in committed_ids:
        if fid in seen:
            problems.append(f"duplicated negative-evidence record for family {fid!r}")
        seen.add(fid)
    for fid in sorted(set(expected_by_id) - seen):
        problems.append(f"omitted negative-evidence record for family {fid!r}")
    for fid in sorted(seen - set(expected_by_id)):
        problems.append(f"unexpected negative-evidence record for family {fid!r}")

    by_committed_id = {require_nonempty_str("family_id", r["family_id"]): r for r in committed_body}
    for fid in sorted(seen & set(expected_by_id)):
        _compare_record(fid, by_committed_id[fid], expected_by_id[fid], problems)

    # 3. the family census must match the independent enumeration (nothing silently omitted/added).
    try:
        enumerated = {r.family_id for r in fca.enumerate_historical_families(root)}
    except ValueError as exc:
        problems.append(f"enumeration cross-check failed: {exc}")
        enumerated = set(expected_by_id)
    if enumerated != set(expected_by_id):
        problems.append("negative-evidence family set does not match the independent enumeration")

    # 4. catch-all byte reproduction (ordering, whitespace, any residual drift).
    try:
        if raw != build_negative_evidence_index_bytes(root):
            problems.append(f"{NEGATIVE_EVIDENCE_RELPATH} does not reproduce byte-for-byte")
    except ValueError as exc:
        problems.append(f"rebuild failed: {exc}")
    return problems


def negative_evidence_status_distribution(repo_root: str | Path) -> dict[str, int]:
    """Return the count of records per negative-evidence status (for reporting)."""
    distribution: dict[str, int] = {}
    for record in build_negative_evidence_index(repo_root):
        distribution[record.status] = distribution.get(record.status, 0) + 1
    return dict(sorted(distribution.items()))


def main(argv: list[str] | None = None) -> int:
    """CLI: build or verify the cumulative negative-evidence index."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true", help="Generate and write the index.")
    group.add_argument("--check", action="store_true", help="Verify the committed index.")
    args = parser.parse_args(argv)
    if args.build:
        path = write_negative_evidence_index(args.repo_root)
        print(json.dumps({"ok": True, "problems": [], "wrote": str(path)}))
        return 0
    problems = verify_negative_evidence(args.repo_root)
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "NEGATIVE_EVIDENCE_RELPATH",
    "NEGATIVE_EVIDENCE_STATUSES",
    "NegativeEvidenceError",
    "NegativeEvidenceRecord",
    "build_negative_evidence_index",
    "build_negative_evidence_index_bytes",
    "negative_evidence_ledger_records",
    "negative_evidence_status_distribution",
    "verify_negative_evidence",
    "write_negative_evidence_index",
]
