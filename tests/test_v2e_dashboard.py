"""V2E dashboard: strict state model, fail-closed builder, honest rendering.

The happy path runs against the real repository (read-only). Corruption paths run
against a disposable ``--local`` clone (the ``m3a_checkout`` fixture) so the real
repository is never touched. Rendering tests prove artifact-derived text cannot inject
markup and that the page never fabricates activity.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from eth_research.v2e.render import render_html
from eth_research.v2e.state import (
    REHEARSAL_BANNER,
    DashboardState,
    DashboardStateError,
    build_dashboard_state,
    to_status_document,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def real_state() -> DashboardState:
    return build_dashboard_state(REPO_ROOT)


class TestHappyPath:
    def test_reflects_the_accepted_honest_state(self, real_state: DashboardState) -> None:
        s = real_state
        assert s.schema_version == 1
        assert s.cohort.accepted_row_count == 3
        assert s.cohort.target_row_count == 365
        assert s.cohort.maturity_state == "immature"
        assert s.cohort.evaluation_authorized is False
        assert s.candidate.eligible_candidate_present is False
        assert s.candidate.paper_activation_authorized is False
        assert s.candidate.paper_trading_active is False
        assert s.candidate.sell_ready is False
        assert s.paper_engine.engine_status == "disabled"
        assert s.paper_engine.lifecycle_state == "disabled"
        assert s.paper_engine.open_positions == 0
        assert s.paper_engine.fills == 0
        assert len(s.identity.commit) == 40
        assert s.identity.private_local_only is True

    def test_pnl_is_unavailable_not_zero(self, real_state: DashboardState) -> None:
        assert "UNAVAILABLE" in real_state.paper_engine.pnl
        assert "not zero performance" in real_state.paper_engine.pnl

    def test_blocking_reasons_are_exact_and_nonempty(self, real_state: DashboardState) -> None:
        assert real_state.candidate.blocking_gates
        assert "eligible_paper_candidate_present" in real_state.candidate.blocking_gates
        assert "eligible_nominated_candidate" in real_state.paper_engine.blocking_requirements
        assert "human_approval_artifact" in real_state.paper_engine.blocking_requirements

    def test_status_document_publishes_only_approved_facts(
        self, real_state: DashboardState
    ) -> None:
        doc = to_status_document(real_state)
        assert doc["kind"] == "v2e_dashboard_status"
        payload = json.dumps(doc)
        assert "/home/" not in payload  # no filesystem paths
        assert "PATH" not in payload  # no environment dump
        assert "HOME" not in payload
        assert "43cfa2ea" not in payload  # no raw candle payload hashes required either

    def test_state_is_immutable(self, real_state: DashboardState) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            real_state.cohort.accepted_row_count = 999  # type: ignore[misc]


class TestFailClosed:
    def test_malformed_accepted_base_refuses(self, m3a_checkout: Path) -> None:
        (m3a_checkout / "research/m3e/accepted_base.json").write_text("{not json", "utf-8")
        with pytest.raises(DashboardStateError):
            build_dashboard_state(m3a_checkout)

    def test_duplicate_keys_in_v2a_results_refuse(self, m3a_checkout: Path) -> None:
        target = m3a_checkout / "research/v2a/results.json"
        target.write_text('{"a": 1, "a": 2}\n', "utf-8")
        with pytest.raises(DashboardStateError):
            build_dashboard_state(m3a_checkout)

    def test_symlinked_artifact_refuses(self, m3a_checkout: Path) -> None:
        target = m3a_checkout / "research/v2b/v2b_results.json"
        real = target.with_name("v2b_results_real.json")
        target.rename(real)
        target.symlink_to(real.name)
        with pytest.raises(DashboardStateError, match="symlink"):
            build_dashboard_state(m3a_checkout)

    def test_nonempty_sealed_ledger_refuses(self, m3a_checkout: Path) -> None:
        ledger = m3a_checkout / "research/m3d/prospective_evaluations.jsonl"
        ledger.write_text('{"forged": true}\n', "utf-8")
        with pytest.raises(DashboardStateError, match="nonempty"):
            build_dashboard_state(m3a_checkout)

    def test_missing_activation_anchor_refuses(self, m3a_checkout: Path) -> None:
        (m3a_checkout / "governance/v2d/prospective_activation.json").unlink()
        with pytest.raises(DashboardStateError):
            build_dashboard_state(m3a_checkout)

    def test_forged_paper_readiness_refuses(self, m3a_checkout: Path) -> None:
        path = m3a_checkout / "governance/v2/paper_readiness_state.json"
        doc = json.loads(path.read_text("utf-8"))
        doc["paper_activation_authorized"] = True
        path.write_text(json.dumps(doc) + "\n", "utf-8")
        with pytest.raises(DashboardStateError):
            build_dashboard_state(m3a_checkout)

    def test_forged_sell_ready_refuses(self, m3a_checkout: Path) -> None:
        path = m3a_checkout / "governance/v2/paper_readiness_state.json"
        doc = json.loads(path.read_text("utf-8"))
        doc["sell_ready"] = True
        path.write_text(json.dumps(doc) + "\n", "utf-8")
        with pytest.raises(DashboardStateError):
            build_dashboard_state(m3a_checkout)


class TestProposalCheckout:
    def test_absent_checkout_is_honestly_unconfigured(self, real_state: DashboardState) -> None:
        assert real_state.proposal.configured is False
        assert "no proposal checkout configured" in real_state.proposal.detail

    def test_wrong_parent_proposal_refuses(self, m3a_checkout: Path, tmp_path: Path) -> None:
        # A "proposal checkout" whose manifest binds to a different accepted base.
        checkout = tmp_path / "proposal"
        pdir = checkout / "research/m3e/proposals/20990101-20990102-deadbeefdeadbeef"
        pdir.mkdir(parents=True)
        (pdir / "proposal_manifest.json").write_text(
            json.dumps(
                {
                    "proposal_id": "20990101-20990102-deadbeefdeadbeef",
                    "proposal_branch": "bot/m3e-prospective-update/x",
                    "accepted_base_sha256": "0" * 64,
                    "accepted_base_fingerprint": "0" * 64,
                }
            )
            + "\n",
            "utf-8",
        )
        (pdir / "update_transition.json").write_text(
            json.dumps(
                {
                    "is_append_only": True,
                    "old_row_count": 3,
                    "new_window_row_count": 9,
                    "proposed_row_count": 12,
                    "proposed_last_open": "2026-07-23T00:00:00Z",
                }
            )
            + "\n",
            "utf-8",
        )
        with pytest.raises(DashboardStateError, match="stale or wrong-parent"):
            build_dashboard_state(m3a_checkout, proposal_checkout=checkout)

    def test_tampered_runner_comparison_refuses(self, tmp_path: Path) -> None:
        # auditor-4 F3: the two-runner byte-agreement claim must be READ from the
        # bundle's comparison record, so a falsified record refuses the build.
        import shutil

        source = Path("/tmp/claude-0/v2e-proposal-checkout")
        if not source.is_dir():
            pytest.skip("real proposal checkout not present in this environment")
        checkout = tmp_path / "tampered"
        shutil.copytree(source / "research", checkout / "research")
        pdir = next((checkout / "research/m3e/proposals").iterdir())
        comparison = pdir / "acquisition_comparison.json"
        doc = json.loads(comparison.read_text("utf-8"))
        doc["canonical_content_match"] = False
        comparison.write_text(json.dumps(doc, sort_keys=True) + "\n", "utf-8")
        with pytest.raises(DashboardStateError, match="runner comparison"):
            build_dashboard_state(REPO_ROOT, proposal_checkout=checkout)


class TestRendering:
    def test_page_is_phone_ready_and_csp_locked(self, real_state: DashboardState) -> None:
        page = render_html(real_state)
        assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in page
        assert "Content-Security-Policy" in page
        assert "default-src 'none'" in page
        assert "<script" not in page.lower()
        assert "http://" not in page  # no external resources
        assert "https://" not in page

    def test_accepted_and_proposed_states_are_distinguished(
        self, real_state: DashboardState
    ) -> None:
        page = render_html(real_state)
        assert "accepted on main" in page
        assert "unmerged — NOT accepted" in page

    def test_artifact_text_cannot_inject_markup(self, real_state: DashboardState) -> None:
        hostile = dataclasses.replace(
            real_state,
            acquisition=dataclasses.replace(
                real_state.acquisition,
                last_live_outcome="<script>alert(1)</script><img src=x onerror=y>",
            ),
        )
        page = render_html(hostile)
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page

    def test_rehearsal_banner_is_exact_and_optin(self, real_state: DashboardState) -> None:
        assert REHEARSAL_BANNER == "UI/OPERATIONS REHEARSAL — NOT PAPER TRADING"
        assert REHEARSAL_BANNER not in render_html(real_state)
        assert REHEARSAL_BANNER in render_html(real_state, rehearsal=True)

    def test_pnl_label_is_not_double_escaped(self, real_state: DashboardState) -> None:
        page = render_html(real_state)
        assert "P&amp;L" in page  # single, correct escape of "P&L"
        assert "amp;amp;" not in page  # auditor-4 F2: no double escaping anywhere

    def test_body_wraps_long_tokens_for_phones(self, real_state: DashboardState) -> None:
        # auditor-4 F1: the 40-hex commit in the header must be breakable at 390px.
        page = render_html(real_state)
        assert "body { margin: 0; overflow-wrap: anywhere;" in page
        assert "color-scheme: dark" in page  # F7: page is dark-only by design

    def test_timeline_pending_row_tracks_proposal_visibility(
        self, real_state: DashboardState
    ) -> None:
        # auditor-4 F5: without a checkout the timeline must not assert unverified
        # external PR state as fact.
        labels = dict(real_state.timeline)
        assert "not locally verified" in labels["Pending proposal"]

    def test_no_fabricated_activity(self, real_state: DashboardState) -> None:
        page = render_html(real_state)
        assert "UNAVAILABLE" in page  # P&L never a fake number
        assert "ENGAGED BY POLICY" in page
        assert "none — paper trading has never started" in page
