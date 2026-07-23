# M3E Activation-Readiness Contract

M3E is delivered **READY, NOT ACTIVE**. This document defines exactly what remains after
the three-PR stack is merged, and the precise, separately-reviewed step that would later
*activate* the review-only update automation. **The audit does not activate anything.**

## What "ready, not active" means (state matrix)

| State | Value | Evidence |
|---|---|---|
| `implemented_offline` | **true** | `eth_research.m3e` (accepted_base, cutoff, update_plan, lease, acquisition, comparison, transition, assembly, proposal, verifier, publisher, **orchestrator**). |
| `rehearsed_locally` | **true** | `tests/test_m3e_orchestrator.py` (the seam) + `tests/test_m3e_publisher_e2e.py` (disposable-repo E2E). |
| `rehearsed_on_github_read_only` | **true** | Live Actions run `29441490761` executed the update workflow read-only and no-opped (`NO-OP: no new completed day is due…`; upload/assemble/runner **skipped**; no fetch/push/PR). The current standing workflow is a strict read-only probe by syntax + the workflow-security scan. |
| `active_fetcher` | **false** | No `curl`/network step runs; the current probe removed the fetch/runner/assemble jobs entirely. |
| `active_proposal_publisher` | **false** | No workflow creates a branch, commits, pushes, or opens a PR; no `contents: write`. |
| `scheduled_on_default_branch` | **false** | On the stacked feature branch the `schedule:` is inert. **After merge to `main` the read-only probe's schedule becomes active** — but the probe only verifies the base and reports DUE/NO-OP; it still does not fetch, assemble, upload, push, or open a PR. |

"The facility can grow the accepted cohort through independently-verified draft proposals"
means **(A) the offline mechanism is capable once separately activated** — **not** that the
standing workflow currently does so. Automatic proposal creation is **not** active.

## What remains after the stack is merged

The offline machinery and the coherent seam (`orchestrator.prepare_update_proposal`) exist
and are proven. What is deliberately **absent** and would be added only by a separate,
reviewed **activation PR**:

1. A trusted `schedule`/`workflow_dispatch` job that actually **fetches** the due window on
   two isolated runners over the hardened `curl` boundary (the network step);
2. wiring that hands the two verified runner bundles to the orchestrator seam and supplies a
   real `GitPort` + a **draft** PR-creation step;
3. the **minimal** workflow permission the draft-PR creation needs (`pull-requests: write`
   for the PR-open step only — never `contents: write`, never auto-merge), scoped to that
   one job.

The activation PR must contain **only** the above. It must **not**: redesign package logic,
mutate accepted data, add candidate/strategy/evaluation code, grant evaluation
authorization, weaken any accepted control (the 35-check verifier, the review policy, the
import firewall, the workflow-security scan, the byte-empty ledgers), or use
`pull_request_target`/auto-merge/`contents: write`.

## Activation prerequisites (all must hold before an activation PR is considered)

- PR #6, #7, #8 merged into `main` in order (see `docs/M3C_M3E_MERGE_RETARGET_TAG_PLAN.md`);
- final `main` CI green; all six replays green;
- the three sealed ledgers byte-empty; the cohort still verified (immature) or matured under
  a **separate** pre-registered protocol;
- the accepted cohort branch (the PR base) configured explicitly and pinned;
- the repository's GitHub Actions setting permits **draft**-PR creation by Actions;
- workflow token permissions reviewed (least privilege: only the PR-open job gets
  `pull-requests: write`);
- branch protection on `main`/accepted branches reviewed (no Actions bypass);
- no active conflicting open proposal (idempotency lease);
- a live audit-mode fetch succeeds and both runners agree (canonical equality);
- explicit human approval.

## Activation acceptance tests (for the future activation PR)

- The standing update workflow, on a **due** window, fetches on two isolated runners,
  produces byte-identical canonical content, assembles + self-verifies (35 checks) through
  the orchestrator seam, opens exactly one **draft** PR onto the accepted cohort branch, and
  performs no push to any accepted branch and no auto-merge;
- on a **not-due** window it is a clean NO-OP;
- a repeat run is an idempotent skip (existing branch / open proposal);
- the workflow-security scan still passes (no new write grant, secret, upload, force-push,
  auto-merge, or exchange host beyond the single hardened `curl` fetch step);
- the three ledgers remain byte-empty; no strategy/candidate/metric artifact appears.

## Rollback

If an activation run misbehaves, disable the workflow (remove the schedule / revert the
activation PR with a revert commit), close any draft proposal PR unmerged, and delete the
orphan `bot/m3e-prospective-update/*` branch. No accepted data is ever mutated by a proposal
(it is a draft PR under human review), so rollback is: revert the activation wiring and
close the draft. **Do not** force-push or reset any shared branch.

## The audit does not activate

No activation step above has been performed. M3E remains ready and inactive.

## V2D addendum (2026-07-23): the anticipated activation PR exists

The separately governed, separately authorized **V2D** milestone (`docs/V2D_PLAN.md`)
implements exactly the activation PR this contract anticipated:

1. the standing update workflow (`.github/workflows/m3e-prospective-update.yml`) gains the
   trusted scheduled/dispatch fetch — two isolated runners over the hardened `curl`
   boundary — plus the orchestrator wiring with a real GitPort and a draft-PR step;
2. permissions stay least-privilege and **job-scoped**: `pull-requests: write` only on the
   draft-PR job, and — one deliberate, documented deviation from item 3 above —
   `contents: write` only on the assemble job, because pushing the new
   `bot/m3e-prospective-update/*` branch (the reviewable draft proposal itself) requires it.
   The workflow still cannot push to `main` or any accepted branch (branch-shape guard in the
   push step, no force-push, and the workflow-security suites pin both grants to this single
   basename and prove they do not generalize);
3. activation is gated by the committed, self-hashed governance anchor
   `governance/v2d/prospective_activation.json` (`python -m eth_research.v2d verify`): every
   growth path — staging, landed verification, the M3F supersession lattice, the independent
   stdlib verifier — fails closed without a strictly-valid anchor.

The activation acceptance tests above are discharged by the V2D test program
(`tests/test_v2d_activation.py`, `tests/test_m3e_staging.py`,
`tests/test_m3d_update_attempts.py`, the workflow-security suites, and
`verify_landed_update`, which proves a landed proposal is the byte-exact staged consequence
of its two-runner attested evidence). Nothing in V2D evaluates prospective values: the
mechanism is DATA-ONLY, `evaluation_authorized` stays false everywhere, the three sealed
ledgers stay byte-empty, and V2 remains not sell-ready. This document above the addendum is
the unchanged historical readiness record.
