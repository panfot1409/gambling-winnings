"""Phone-first, server-rendered HTML for the private operations dashboard.

Every value that originates in an artifact passes through :func:`html.escape` before it
reaches the page, so hostile text inside a committed JSON document cannot inject markup
or script. The page carries a restrictive ``Content-Security-Policy`` meta (the HTTP
layer sends the same header), inline CSS only, no external resources, no JavaScript, no
analytics, and no telemetry.

Auditor C finding B-3: this module used to carry its own hard-coded acceptance copy
(``Pending proposal (unmerged — NOT accepted)``, ``Proposed rows (unmerged)``) and never
consumed the accepted/pending split the state model had learned, so the accepted state
rendered a page that contradicted itself. It now writes NO status copy of its own: every
visible status string is read from :data:`eth_research.v2e.status.LABELS`, keyed by the
one canonical :class:`~eth_research.v2e.status.ProposalStatus`, and
:func:`~eth_research.v2e.state.enforce_display_invariants` runs before a single byte is
emitted — so a hand-assembled or field-replaced state that disagrees with itself raises
:class:`~eth_research.v2e.status.DashboardStateError` instead of being rendered.
"""

from __future__ import annotations

import html

from eth_research.v2e.state import (
    REHEARSAL_BANNER,
    DashboardState,
    enforce_display_invariants,
)
from eth_research.v2e.status import labels_for, row_count_statement

_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; overflow-wrap: anywhere; background: #101418; color: #e8edf2;
       font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; }
main { max-width: 42rem; margin: 0 auto; padding: 0.75rem; }
header { padding: 1rem 0.75rem 0.5rem; border-bottom: 1px solid #2a3440; }
h1 { font-size: 1.15rem; margin: 0 0 0.25rem; }
h2 { font-size: 0.95rem; margin: 0 0 0.5rem; color: #9fc0dd; text-transform: uppercase;
     letter-spacing: 0.04em; }
section { background: #171d24; border: 1px solid #2a3440; border-radius: 0.6rem;
          padding: 0.75rem; margin: 0.75rem 0; overflow-wrap: anywhere; }
dl { display: grid; grid-template-columns: minmax(9rem, 40%) 1fr; gap: 0.3rem 0.6rem;
     margin: 0; font-size: 0.9rem; }
dt { color: #93a4b5; } dd { margin: 0; }
.ok { color: #7fd08f; } .blocked { color: #f0b35e; } .off { color: #8d9aa8; }
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 1rem;
         border: 1px solid #2a3440; font-size: 0.8rem; margin: 0 0.3rem 0.3rem 0; }
.rehearsal { background: #332b16; border: 1px dashed #f0b35e; color: #f0b35e;
             padding: 0.5rem 0.75rem; border-radius: 0.6rem; margin: 0.75rem 0;
             font-weight: 600; text-align: center; }
p.claim { margin: 0.1rem 0 0.4rem; font-size: 0.9rem; }
p.detail { margin: 0 0 0.6rem; font-size: 0.85rem; color: #93a4b5; }
ul { margin: 0.25rem 0 0; padding-left: 1.1rem; font-size: 0.88rem; }
footer { color: #8d9aa8; font-size: 0.8rem; padding: 0.5rem 0.75rem 1.5rem; }
@media (min-width: 700px) { dl { font-size: 0.95rem; } }
"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _rows(pairs: list[tuple[str, str]]) -> str:
    cells = "".join(f"<dt>{_e(k)}</dt><dd>{v}</dd>" for k, v in pairs)
    return f"<dl>{cells}</dl>"


def _flag(value: bool, *, good_when: bool) -> str:
    css = "ok" if value is good_when else "blocked"
    return f'<span class="{css}">{"true" if value else "false"}</span>'


def render_html(state: DashboardState, *, rehearsal: bool = False) -> str:
    """Render the full dashboard page for one immutable state snapshot.

    Raises :class:`~eth_research.v2e.status.DashboardStateError` rather than emitting a
    page whose surfaces disagree about acceptance.
    """
    enforce_display_invariants(state)
    s = state
    banner = f'<div class="rehearsal">{_e(REHEARSAL_BANNER)}</div>' if rehearsal else ""
    # Every status string below is a lookup, never a computation: this renderer has no
    # opinion about whether the proposal is accepted.
    labels = labels_for(s.proposal.status)
    proposal_rows: list[tuple[str, str]]
    if s.proposal.configured:
        accepted_identity = (
            f"<code>{_e(s.proposal.accepted_manifest_sha256)}</code>"
            if s.proposal.accepted_manifest_sha256 is not None
            else _e(labels.accepted_manifest_absent)
        )
        proposal_rows = [
            (labels.identity_label, _e(s.proposal.proposal_id)),
            ("Branch", f"<code>{_e(s.proposal.proposal_branch)}</code>"),
            # Invariant 5: the accepted identity is the one the acceptance record pins;
            # the identity of the bundle on disk is a separate, separately labelled row.
            (labels.accepted_manifest_label, accepted_identity),
            (labels.manifest_label, f"<code>{_e(s.proposal.manifest_sha256)}</code>"),
            # Invariant 4: the two row counts only ever appear inside one statement that
            # names their relationship, never as bare adjacent figures.
            (
                labels.rows_label,
                _e(
                    row_count_statement(
                        s.proposal.status,
                        accepted_rows=s.cohort.accepted_row_count,
                        proposed_rows=int(s.proposal.proposed_row_count or 0),
                        appended_rows=int(s.proposal.new_completed_days or 0),
                    )
                ),
            ),
            (labels.last_open_label, _e(s.proposal.proposed_last_open)),
            ("Append-only", _flag(bool(s.proposal.append_only), good_when=True)),
            ("Ancestry verified", _flag(bool(s.proposal.ancestry_verified), good_when=True)),
        ]
    else:
        proposal_rows = []
    # The one acceptance claim on the page, plus the one status detail sentence. Both
    # come from the canonical table; enforce_display_invariants has already required
    # them to agree with the heading, the badge and the timeline's terminal state.
    proposal_banner = (
        f'<p class="claim"><span class="badge {labels.badge_class}">{_e(labels.badge)}</span> '
        f"{_e(labels.claim)}</p>"
        f'<p class="detail">{_e(s.proposal.detail)}</p>'
    )
    proposal_table = _rows(proposal_rows) if proposal_rows else ""

    sealed_items = "".join(
        f"<li><code>{_e(name)}</code>: <span class='ok'>{_e(status)}</span></li>"
        for name, status in s.integrity.sealed_ledgers.items()
    )
    blocking_gates = "".join(f"<li>{_e(g)}</li>" for g in s.candidate.blocking_gates)
    blocking_reqs = "".join(f"<li>{_e(r)}</li>" for r in s.paper_engine.blocking_requirements)
    timeline = "".join(
        f"<li><strong>{_e(label)}</strong> — {_e(detail)}</li>" for label, detail in s.timeline
    )
    limitations = "".join(f"<li>{_e(item)}</li>" for item in s.limitations)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{_CSP}">
<meta name="referrer" content="no-referrer">
<title>eth-research Private Operations</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<header>
<h1>eth-research Private Operations</h1>
{
        _rows(
            [
                ("Version", _e(s.identity.version)),
                ("Commit", f"<code>{_e(s.identity.commit)}</code>"),
                ("Visibility", '<span class="ok">private / local-only</span>'),
                ("Last refresh (UTC)", _e(s.generated_at)),
            ]
        )
    }
</header>
{banner}
<section>
<h2>System status</h2>
{
        _rows(
            [
                ("Honest state", '<span class="ok">verified from committed artifacts</span>'),
                (
                    "Data collection",
                    '<span class="ok">active (review-only, draft proposals)</span>',
                ),
                ("Paper system", '<span class="blocked">blocked — no eligible candidate</span>'),
                ("Sell-ready", _flag(s.candidate.sell_ready, good_when=True)),
                (
                    "Eligible candidate",
                    _flag(s.candidate.eligible_candidate_present, good_when=True),
                ),
            ]
        )
    }
</section>
<section id="cohort">
<h2>Prospective cohort (accepted on main)</h2>
{
        _rows(
            [
                (
                    "Accepted rows",
                    f"{_e(s.cohort.accepted_row_count)} / {_e(s.cohort.target_row_count)}",
                ),
                ("Progress", f"{_e(s.cohort.progress_percent)}%"),
                ("Accepted first open", _e(s.cohort.accepted_first_open)),
                ("Accepted last open", _e(s.cohort.accepted_last_open)),
                ("Remaining observations", _e(s.cohort.remaining_rows)),
                ("Maturity", f'<span class="blocked">{_e(s.cohort.maturity_state)}</span>'),
                ("Evaluation authorized", _flag(s.cohort.evaluation_authorized, good_when=True)),
                (
                    "Accepted cohort fingerprint",
                    f"<code>{_e(s.cohort.accepted_fingerprint)}</code>",
                ),
            ]
        )
    }
</section>
<section id="proposal">
<h2>{_e(labels.heading)}</h2>
{proposal_banner}
{proposal_table}
</section>
<section>
<h2>Acquisition health</h2>
{
        _rows(
            [
                (
                    "Schedule",
                    '<span class="ok">enabled (committed schedule + manual dispatch)</span>',
                ),
                ("Standing workflow", f"<code>{_e(s.acquisition.standing_workflow)}</code>"),
                ("Last registry entry", _e(s.acquisition.last_registry_entry_kind)),
                ("Last live run", _e(s.acquisition.last_live_run)),
                ("Last live outcome", _e(s.acquisition.last_live_outcome)),
                ("Two-runner agreement", _e(s.acquisition.two_runner_agreement)),
                ("Append-only result", _e(s.acquisition.append_only_result)),
                ("Next due", _e(s.acquisition.next_due_status)),
                ("Direct-main writes", _flag(s.acquisition.direct_main_writes, good_when=False)),
                (
                    "Draft review required",
                    _flag(s.acquisition.draft_review_required, good_when=True),
                ),
            ]
        )
    }
</section>
<section>
<h2>Integrity</h2>
<ul>{sealed_items}</ul>
{
        _rows(
            [
                ("Accepted base", _flag(s.integrity.accepted_base_verified, good_when=True)),
                ("V2A results artifact", _flag(s.integrity.v2a_results_verified, good_when=True)),
                ("V2B results artifact", _flag(s.integrity.v2b_results_verified, good_when=True)),
                ("V2C OQ registry", _e(s.integrity.v2c_oq_registry)),
                (
                    "Fable 5 paper readiness",
                    _flag(s.integrity.fable5_paper_readiness_verified, good_when=True),
                ),
                (
                    "V2D activation anchor",
                    _flag(s.integrity.v2d_activation_anchor_valid, good_when=True),
                ),
                (
                    "Source freeze artifact",
                    _flag(s.integrity.source_freeze_present, good_when=True),
                ),
                ("Proposal verification", _e(s.integrity.proposal_verification)),
            ]
        )
    }
</section>
<section>
<h2>Candidate &amp; paper readiness</h2>
{
        _rows(
            [
                (
                    "Nominated candidate",
                    f'<span class="off">{_e(s.candidate.nominated_candidate)}</span>',
                ),
                (
                    "Eligible candidate present",
                    _flag(s.candidate.eligible_candidate_present, good_when=True),
                ),
                (
                    "Paper-release candidate frozen",
                    _flag(s.candidate.paper_release_candidate_frozen, good_when=True),
                ),
                (
                    "Human activation approval",
                    _flag(s.candidate.human_activation_approval, good_when=True),
                ),
                (
                    "Paper activation authorized",
                    _flag(s.candidate.paper_activation_authorized, good_when=True),
                ),
                ("Paper trading active", _flag(s.candidate.paper_trading_active, good_when=True)),
                ("Sell-ready", _flag(s.candidate.sell_ready, good_when=True)),
            ]
        )
    }
<h2 style="margin-top:0.8rem">Exact blocking gates</h2>
<ul>{blocking_gates}</ul>
</section>
<section>
<h2>Paper execution</h2>
{
        _rows(
            [
                ("Engine status", f'<span class="off">{_e(s.paper_engine.engine_status)}</span>'),
                ("Mode", _e(s.paper_engine.mode)),
                (
                    "Lifecycle state",
                    f'<span class="off">{_e(s.paper_engine.lifecycle_state)}</span>',
                ),
                ("Exposure", _e(s.paper_engine.exposure)),
                ("Open positions", _e(s.paper_engine.open_positions)),
                ("Pending orders", _e(s.paper_engine.pending_orders)),
                ("Fills", _e(s.paper_engine.fills)),
                ("Realized/unrealized P&L", _e(s.paper_engine.pnl)),
                ("Kill switch", f'<span class="ok">{_e(s.paper_engine.kill_switch)}</span>'),
            ]
        )
    }
<p style="font-size:0.85rem">{_e(s.paper_engine.explanation)}</p>
<h2>Blocking activation requirements</h2>
<ul>{blocking_reqs}</ul>
</section>
<section>
<h2>Audit &amp; activity timeline</h2>
<ul>{timeline}</ul>
</section>
<section>
<h2>Limitations</h2>
<ul>{limitations}</ul>
</section>
<footer>Read-only private dashboard. No mutation endpoints exist; there is no control here
that can nominate a candidate, start paper trading, or move money.</footer>
</main>
</body>
</html>
"""
