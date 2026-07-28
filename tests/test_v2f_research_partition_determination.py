"""The V2F §12 determination, as executable assertions rather than prose.

``docs/V2F_RESEARCH_PARTITION_DETERMINATION.md`` concludes that no lawful, unconsumed,
non-sealed research partition exists, and that the one-shot therefore must not be spent. A
document is a claim; this module is the guard. If a future change makes any load-bearing fact
false — a seal broken, the exhaustion decision softened, containment silently lifted — the
determination stops being true and these tests say so, instead of the document quietly aging
into a lie.

Every group carries a **passing control**. A guard that is stuck shut passes every negative
assertion, so "the attack was refused" proves nothing on its own; the control proves the
mechanism can still say yes to something.

Deliberately NOT asserted here: that the prose of the document matches these values. Pinning
a document's wording to a test makes the test fail on copy-editing, which trains people to
weaken tests. What is pinned is the machine-readable state the document *describes*.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from eth_research.m3d import protocol as m3d_protocol
from eth_research.m3d.maturity import FORBIDDEN_OPERATIONS
from eth_research.v2c.maturity import MATURITY_POLICY

REPO_ROOT = Path(__file__).resolve().parents[1]

EXHAUSTION_PATH = REPO_ROOT / "research/m3d/research_train_exhaustion.json"
JOINT_IDENTITY_PATH = REPO_ROOT / "research/v2b/joint_partition_identity.json"
CONTAINMENT_PATH = REPO_ROOT / "governance/v2f/containment.json"
CLOSURE_PATH = REPO_ROOT / "research/v2/research_partition_closure.json"
NEGATIVE_EVIDENCE_PATH = REPO_ROOT / "research/v2/negative_evidence_index.jsonl"

#: The three ledgers whose emptiness IS the seal. Named individually, never globbed: a glob
#: that matches nothing passes vacuously, which is the failure mode this suite exists to catch.
SEALED_LEDGERS = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)


def _load(path: Path) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return parsed


# --- partition 1: research_train is exhausted by a committed decision ----------------------


def test_control_the_exhaustion_decision_exists_and_parses() -> None:
    """Without this, every assertion below could be passing on an unreadable file."""
    decision = _load(EXHAUSTION_PATH)
    assert decision["kind"] == "research_train_exhaustion_decision"
    assert decision["research_train"]["row_count"] == 2221


def test_research_train_is_classified_exhausted() -> None:
    assert _load(EXHAUSTION_PATH)["classification"] == "exhausted_for_new_candidate_research"


@pytest.mark.parametrize(
    "operation",
    [
        "new_candidate_generation",
        "new_parameter_selection",
        "new_performance_comparison",
        "new_statistical_inference",
        "new_strategy_ranking",
        "relabel_specification_to_evade",
        "select_candidate_for_development_gate",
    ],
)
def test_evaluating_a_new_candidate_on_research_train_is_a_named_prohibition(
    operation: str,
) -> None:
    """Each of these is something a one-shot evaluation would have to do."""
    assert operation in _load(EXHAUSTION_PATH)["forbidden_operations"]


def test_the_allowed_operations_do_not_include_anything_evaluative() -> None:
    """The permit list is replay/audit/verification only — no measurement of a strategy."""
    allowed = set(_load(EXHAUSTION_PATH)["allowed_operations"])
    evaluative = {"evaluate", "score", "rank", "backtest", "compute_metrics", "new_bootstrap"}
    assert not (allowed & evaluative), f"exhaustion decision permits {allowed & evaluative}"


# --- partition 2: the joint ETH+BTC partition adds no new timeline -------------------------


def test_the_joint_partition_shares_research_trains_cutoff() -> None:
    """BTC widened the cross-section; it did not extend the window past the research cutoff.

    If these ever diverge, the joint partition covers dates research_train does not, and the
    determination's "not a sixth source of information" reasoning needs redoing.
    """
    joint = _load(JOINT_IDENTITY_PATH)
    assert joint["research_cutoff_last_open"] == "2022-06-21T00:00:00Z"
    assert joint["last_open"] == joint["research_cutoff_last_open"]
    assert joint["no_row_at_or_after_cutoff"] is True
    assert joint["first_open"] == _load(EXHAUSTION_PATH)["research_train"]["first_open"].replace(
        "+00:00", "Z"
    )


# --- partitions 3 and 4: the seals are intact ---------------------------------------------


@pytest.mark.parametrize("relpath", SEALED_LEDGERS)
def test_each_sealed_ledger_is_byte_empty(relpath: str) -> None:
    path = REPO_ROOT / relpath
    assert path.is_file(), f"{relpath} is missing — an absent seal is not an intact seal"
    assert path.stat().st_size == 0, f"{relpath} has {path.stat().st_size} bytes; seal broken"


def test_control_the_sealed_ledger_check_can_detect_a_nonempty_file(tmp_path: Path) -> None:
    """Proves the size check is not stuck reporting zero for everything."""
    decoy = tmp_path / "not_empty.jsonl"
    decoy.write_text("{}\n", encoding="utf-8")
    assert decoy.stat().st_size != 0


# --- partition 5: unconsumed, but not evaluable --------------------------------------------


def test_the_prospective_cohort_is_immature() -> None:
    from eth_research.m3d.status import build_status  # local: keeps import cost off collection

    status = build_status(REPO_ROOT)
    assert status["maturity_state"] == "immature"
    assert status["row_count"] < status["minimum_maturity_rows"]
    assert status["evaluation_authorized"] is False
    assert status["strategy_evaluation_performed"] is False
    assert status["performance_metrics_computed"] is False


def test_maturity_would_not_authorize_evaluation_even_when_reached() -> None:
    """The trap: "wait for maturity" reads like the fix and is not one."""
    assert MATURITY_POLICY["maturity_means_data_availability_only"] is True
    assert MATURITY_POLICY["maturity_authorizes_evaluation"] is False
    assert MATURITY_POLICY["evaluation_requires_separate_future_human_authorization"] is True


def test_future_evaluation_requires_acts_no_autonomous_run_may_perform() -> None:
    required = set(m3d_protocol._FUTURE_EVALUATION_REQUIREMENTS)
    assert "separate_human_authorized_milestone" in required
    assert "candidate_declared_before_access" in required
    assert "new_single_use_evaluation_ledger" in required


@pytest.mark.parametrize(
    "operation",
    ["evaluate", "score", "rank", "backtest", "compute_metrics", "compare_performance", "decide"],
)
def test_the_cohort_firewall_forbids_every_evaluative_operation(operation: str) -> None:
    assert operation in FORBIDDEN_OPERATIONS


# --- no new partition can be acquired -------------------------------------------------------


def test_containment_is_active_and_refuses_dispatch() -> None:
    record = _load(CONTAINMENT_PATH)
    assert record["active"] is True
    assert record["scope"]["refuses_manual_dispatch_while_active"] is True
    assert record["scope"]["removes_schedule_trigger"] is True


def test_lifting_containment_requires_an_explicit_human_authorization() -> None:
    """No autonomous run can satisfy this, which is the whole point of the clause."""
    lift = _load(CONTAINMENT_PATH)["lift_requires"]
    joined = " ".join(lift)
    assert "explicit human authorization" in joined
    assert "lifted_by" in joined
    assert "lifted_on" in joined
    assert any("rights assessment" in item for item in lift)


def _run_gate(repo_root: Path) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools/v2f_containment_gate.py"), "--repo-root", "."],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def _scratch_repo(tmp_path: Path, record: dict[str, Any] | None) -> Path:
    """A throwaway root holding only a containment record. Never touches the real repository."""
    (tmp_path / "governance" / "v2f").mkdir(parents=True, exist_ok=True)
    if record is not None:
        (tmp_path / "governance/v2f/containment.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return tmp_path


# The gate refuses in three different states, and it would be easy to mistake a gate stuck shut
# for a working one. These four tests pin the whole truth table: three distinct refusal *reasons*
# plus the one state that genuinely opens it.


def test_the_containment_gate_refuses_here_because_containment_is_suspended() -> None:
    """Not "the record says active" — the enforcing script, executed, against the real repo.

    Asserts the *suspension* reason specifically. Asserting only "REFUSED" would also pass if
    the gate had silently fallen through to the unattributed-lift or absence path, which are
    different failures wearing the same word.
    """
    code, out = _run_gate(REPO_ROOT)
    assert code != 0, "containment gate exited 0 while containment is active"
    assert "SUSPENDED" in out, f"refused, but not for the suspension reason: {out!r}"


def test_the_gate_refuses_an_unattributed_lift(tmp_path: Path) -> None:
    """Flipping active=false is not enough; §5 of the determination depends on this."""
    record = _load(CONTAINMENT_PATH) | {"active": False}
    code, out = _run_gate(_scratch_repo(tmp_path, record))
    assert code != 0
    assert "lifted_by" in out
    assert "lifted_on" in out


def test_the_gate_refuses_a_missing_record(tmp_path: Path) -> None:
    """Absence refuses: deleting the record must never be a way to resume egress."""
    code, out = _run_gate(_scratch_repo(tmp_path, None))
    assert code != 0
    assert "absent" in out.lower()


def test_control_the_gate_opens_for_a_properly_attributed_human_lift(tmp_path: Path) -> None:
    """The passing control: the gate CAN say yes, so the three refusals above mean something.

    This is the only state that opens it, and every field it requires is a human act. Written
    into a scratch root; the real ``governance/v2f/containment.json`` is untouched.
    """
    record = _load(CONTAINMENT_PATH) | {
        "active": False,
        "lifted_by": "scratch fixture, not a real authorization",
        "lifted_on": "2026-07-28",
    }
    code, out = _run_gate(_scratch_repo(tmp_path, record))
    assert code == 0, f"gate refused even a fully attributed lift — it may be stuck shut: {out!r}"
    assert "open" in out.lower()


# --- addendum: the second, independent closure record --------------------------------------
#
# Found after the first eight sections of the determination were written. It reaches the same
# conclusion by a different route, so the two records corroborate rather than merely repeat.


def test_control_the_closure_record_exists_and_parses() -> None:
    closure = _load(CLOSURE_PATH)
    assert closure["closure_id"] == "legacy_research_partition_closure_v1"
    assert closure["historical_experiments"] == ["v2a_run_001", "v2b_run_001"]


def test_the_historical_partitions_are_closed_to_new_candidate_research() -> None:
    assert _load(CLOSURE_PATH)["closure_status"] == "closed_to_new_candidate_nomination_research"


@pytest.mark.parametrize(
    "operation",
    [
        "evaluate_new_candidate",
        "evaluate_modified_candidate",
        "run_new_experiment",
        "open_new_research_budget",
        "recombine_and_claim_new_trial",
        "claim_freshness_via_new_version",
        "claim_freshness_via_new_benchmark",
        "read_sealed_to_choose_family",
    ],
)
def test_the_closure_record_forbids_the_operation(operation: str) -> None:
    assert operation in _load(CLOSURE_PATH)["forbidden_operations"]


def test_two_independent_records_close_the_historical_partitions() -> None:
    """Corroboration, not repetition: different files, different authors, different reasons.

    If a future change softens one, this still fails on the other, which is the point of
    asserting both rather than picking whichever is convenient.
    """
    assert "evaluate_new_candidate" in _load(CLOSURE_PATH)["forbidden_operations"]
    assert _load(EXHAUSTION_PATH)["classification"] == "exhausted_for_new_candidate_research"


def test_every_v2a_expert_family_is_recorded_rejected() -> None:
    """The mixer's natural expert pool is three already-rejected families.

    This is why ``recombine_and_claim_new_trial`` is on point for it, and why its prior is poor
    on the science as well as blocked on the governance. Pinned so a later reader cannot assume
    the experts were neutral priors.
    """
    decisions: dict[str, str] = {}
    sealed_touched: dict[str, object] = {}
    for line in NEGATIVE_EVIDENCE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        family = entry.get("family_id")
        if isinstance(family, str) and family.startswith("v2a_"):
            decisions[family] = str(entry.get("decision"))
            sealed_touched[family] = entry.get("sealed_data_touched")

    assert decisions == {
        "v2a_meanrev_zscore_accumulation": "research_stage_rejected",
        "v2a_trend_regime_single_horizon": "research_stage_rejected",
        "v2a_vol_scaled_hold_drawdown_guard": "research_stage_rejected",
    }, f"V2A decision set changed: {decisions}"

    # Corroborates §3: those rejections were reached without reading any sealed partition, so
    # the seals being intact and the families being rejected are consistent facts, not a puzzle.
    assert set(sealed_touched.values()) == {False}, sealed_touched


# --- the conjunction: the determination itself ---------------------------------------------


def test_no_partition_is_simultaneously_unconsumed_and_evaluable() -> None:
    """The §12 determination in one assertion.

    Each partition must fail at least one of the three requirements (lawful, unconsumed,
    non-sealed). Written as an explicit table rather than a loop over discovered state, because
    a loop over a collection that silently becomes empty passes vacuously.
    """
    from eth_research.m3d.status import build_status

    status = build_status(REPO_ROOT)
    exhaustion = _load(EXHAUSTION_PATH)

    disqualified: dict[str, str] = {}

    if exhaustion["classification"] == "exhausted_for_new_candidate_research":
        disqualified["research_train"] = "exhausted"
        disqualified["v2b_joint"] = "exhausted (same window, spent by v2b_run_001)"

    for relpath, name in (
        (SEALED_LEDGERS[0], "development_gate"),
        (SEALED_LEDGERS[1], "final_holdout"),
    ):
        if (REPO_ROOT / relpath).stat().st_size == 0:
            disqualified[name] = "sealed and unbroken"

    if status["evaluation_authorized"] is False or status["maturity_state"] != "mature":
        disqualified["m3d_prospective"] = "immature and evaluation not authorized"

    assert set(disqualified) == {
        "research_train",
        "v2b_joint",
        "development_gate",
        "final_holdout",
        "m3d_prospective",
    }, f"partition inventory changed; determination needs redoing. got: {disqualified}"


def test_paper_activation_remains_unauthorized_and_says_why() -> None:
    """The mechanical consequence: no partition, so no qualification, so no activation."""
    from eth_research.v2.fable5.paper_readiness import derive_paper_readiness

    state = derive_paper_readiness(REPO_ROOT)
    assert state.paper_activation_authorized is False
    assert state.blocking_gates, "must name the blockers, not refuse silently"
    assert "human_activation_approval_recorded" in state.blocking_gates
