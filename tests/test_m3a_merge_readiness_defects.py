"""Phase 1 reproductions of the four known merge-readiness discrepancies K1-K4.

These tests *document the defective current state as facts* (they pass now and
anchor the later fixes). Each corresponds to a known discrepancy in the M3A
merge-readiness plan (``docs/M3A_MERGE_READINESS_PLAN.md``):

- K1 the PR #4 body is materially stale (fixed forward in Phase 7);
- K2 the immutable run-003 report contains a false universal straddle claim
  (corrected out-of-band by the append-only erratum in Phase 2 — the immutable
  bytes are preserved);
- K3 the successful end-to-end lifecycle test skips once run-003 is completed
  (made standing in Phase 3);
- K4 the terminal audit names a stale "Final HEAD" (reworded in Phase 6).

Nothing here evaluates a sealed partition or mutates any committed artifact.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import eth_research
from eth_research.development_results_v2 import load_development_results_v2

REPO = Path(eth_research.__file__).resolve().parents[2]
RUN003_DIR = REPO / "research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003"
RUN003_REPORT = RUN003_DIR / "development_report.md"
RUN003_RESULTS = RUN003_DIR / "development_results.json"

# The immutable run-003 report hash, pinned by the plan.
RUN003_REPORT_SHA256 = "d6e920760fd4217cbac00cf6126b0da2afc1f0a9e673aacfc9aee5fc6baa3bfd"
# The exact false universal clause in the immutable report (Section 5).
FALSE_UNIVERSAL_CLAUSE = (
    "every fold-aware bootstrap interval of mean daily paired excess return "
    "versus buy-and-hold straddles zero"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=str(REPO),
            capture_output=True,
        ).returncode
        == 0
    )


# --------------------------------------------------------------------------- #
# K1 — the PR #4 body is materially stale.
# --------------------------------------------------------------------------- #
class TestK1PrBodyIsStale:
    """The committed repository state contradicts the (stale) PR #4 body clauses.

    The PR body still describes run-002 as terminal, claims 'every bootstrap
    interval straddles zero', and says the review found no statistics defects.
    We do not reach GitHub here; we prove the *repository* now contradicts those
    clauses, so the body is materially false until rewritten (Phase 7).
    """

    def test_registry_has_three_completed_experiments_not_run002_terminal(self) -> None:
        from eth_research.experiment_registry import (
            EXPERIMENT_REGISTRY_RELPATH,
            read_registry,
        )

        events = read_registry(REPO / EXPERIMENT_REGISTRY_RELPATH)
        completed = [e.experiment_id for e in events if e.event == "completed"]
        assert completed == [
            "m3a-fixed-baseline-comparison-v1-run-001",
            "m3a-fixed-baseline-comparison-v1-run-002",
            "m3a-fixed-baseline-comparison-v2-run-003",
        ]
        # The PR body's "run-002 is terminal / two experiments" framing is stale:
        # run-003 is the latest completed experiment.
        assert completed[-1].endswith("run-003")

    def test_run003_archive_exists_but_pr_body_omits_it(self) -> None:
        for name in (
            "development_results.json",
            "development_report.md",
            "return_evidence.json",
            "artifact_manifest.json",
        ):
            assert (RUN003_DIR / name).is_file()

    def test_pr_body_universal_straddle_claim_is_contradicted_by_data(self) -> None:
        # The PR body repeats 'every bootstrap interval ... straddles zero'; the
        # committed results contradict it (see K2). This is the shared falsehood.
        results = load_development_results_v2(RUN003_RESULTS)
        excludes_zero = [c for c in results.bootstrap_cells if c.primary.ci_upper < 0.0]
        assert len(excludes_zero) == 3
        assert {c.strategy for c in excludes_zero} == {"cash"}


# --------------------------------------------------------------------------- #
# K2 — the immutable run-003 report contains a false universal summary.
# --------------------------------------------------------------------------- #
class TestK2ReportUniversalStraddleClaimIsFalse:
    def test_target_report_hash_is_the_immutable_run003_hash(self) -> None:
        assert _sha256(RUN003_REPORT) == RUN003_REPORT_SHA256

    def test_report_contains_the_universal_straddle_statement(self) -> None:
        text = RUN003_REPORT.read_text("utf-8")
        assert FALSE_UNIVERSAL_CLAUSE in text

    def test_three_cash_primary_intervals_exclude_zero_on_the_negative_side(self) -> None:
        results = load_development_results_v2(RUN003_RESULTS)
        excluding = {
            (c.strategy, c.cost_scenario): (c.primary.ci_lower, c.primary.ci_upper)
            for c in results.bootstrap_cells
            if not (c.primary.ci_lower <= 0.0 <= c.primary.ci_upper)
        }
        # Exactly the three cash primary cells, each strictly below zero.
        assert set(excluding) == {
            ("cash", "base"),
            ("cash", "stressed"),
            ("cash", "severe"),
        }
        for lo, hi in excluding.values():
            # excludes zero on the negative side: both bounds strictly below zero
            assert lo < 0.0
            assert hi < 0.0

    def test_universal_claim_is_false_because_at_least_one_primary_excludes_zero(
        self,
    ) -> None:
        results = load_development_results_v2(RUN003_RESULTS)
        any_primary_excludes_zero = any(
            not (c.primary.ci_lower <= 0.0 <= c.primary.ci_upper) for c in results.bootstrap_cells
        )
        text = RUN003_REPORT.read_text("utf-8")
        # Report asserts *every* interval straddles zero, yet >=1 primary does not.
        assert FALSE_UNIVERSAL_CLAUSE in text
        assert any_primary_excludes_zero

    def test_sma_and_donchian_primary_and_all_sensitivity_do_contain_zero(self) -> None:
        results = load_development_results_v2(RUN003_RESULTS)
        for c in results.bootstrap_cells:
            # every sensitivity (hierarchical) interval contains zero
            assert c.sensitivity.ci_lower <= 0.0 <= c.sensitivity.ci_upper
            if c.strategy in ("sma_20_50", "donchian_55_20"):
                assert c.primary.ci_lower <= 0.0 <= c.primary.ci_upper

    def test_existing_comparison_note_acknowledges_the_discrepancy(self) -> None:
        note = (REPO / "docs/M3A_RUN003_BOOTSTRAP_COMPARISON.md").read_text("utf-8")
        assert "cash" in note
        assert "exclude" in note.lower()
        assert "negative" in note.lower()


# --------------------------------------------------------------------------- #
# K3 — the successful E2E lifecycle is now STANDING (skip is runtime-gated only).
# --------------------------------------------------------------------------- #
class TestK3EndToEndLifecycleIsStanding:
    def test_run003_is_completed_in_the_real_repo(self) -> None:
        import test_m3a_orchestrator_e2e as e2e

        # The precondition that used to trip the (now removed) completion gate.
        assert e2e._run003_state_in_real_repo() == "completed"

    def test_rehearsable_skip_is_runtime_gated_not_completion_gated(self) -> None:
        import test_m3a_orchestrator_e2e as e2e

        # The skip predicate now depends ONLY on the runtime, never on run-003's
        # completion — so the successful lifecycle runs on the authoritative
        # CPython 3.12.3 runtime even though run-003 is already completed.
        (condition,) = e2e._REHEARSABLE.mark.args
        assert condition == (not e2e._on_frozen_runtime())
        # Completion no longer forces a skip: on the frozen runtime the standing
        # lifecycle is not skipped despite run-003 being completed.
        if e2e._on_frozen_runtime():
            assert condition is False
            assert e2e._run003_state_in_real_repo() == "completed"


# --------------------------------------------------------------------------- #
# K4 — the terminal audit names a stale "Final HEAD".
# --------------------------------------------------------------------------- #
class TestK4TerminalAuditNamesStaleFinalHead:
    AUDIT = "docs/M3A_RUN003_TERMINAL_AUDIT.md"
    STALE_FINAL_HEAD = "b4e90726b26d69f94e40ad76e7c9675dea11ed32"

    def test_audit_declares_the_stale_final_head(self) -> None:
        text = (REPO / self.AUDIT).read_text("utf-8")
        assert f"Final HEAD: `{self.STALE_FINAL_HEAD}`" in text

    def test_declared_final_head_precedes_the_audits_own_commit(self) -> None:
        # The commit that last modified the audit file.
        doc_commit = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", self.AUDIT],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        # The declared "Final HEAD" strictly precedes the doc's own commit — a
        # self-contradiction: a file cannot honestly name a later HEAD as final
        # while itself being committed afterwards.
        assert doc_commit != self.STALE_FINAL_HEAD
        assert _is_ancestor(self.STALE_FINAL_HEAD, doc_commit)
