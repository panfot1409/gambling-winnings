# V2D — DATA-ONLY Prospective-Collection Activation Plan (Plan of Record)

**Status: plan committed; nothing activated by this document.**
Branch: `claude/v2d-prospective-activation` (from `main` = `ccf2d45687942b010a0a28f9ae69f2fd3d9d2ec7`).

This document is the complete activation plan the V2D authorization requires. It records the
authorization verbatim, the preflight baseline, every design decision, the exact minimum change
set, the standing guards that must be *visibly re-scoped* (never silently evaded), the invariants
that must not move, the phase sequence with acceptance criteria, and the stop rule. It is a plan:
committing it changes no behavior, grants no permission, and activates nothing.

---

## 1. Authority

User authorization (2026-07-23), verbatim:

> I explicitly authorize a new, separately governed V2D milestone to activate DATA-ONLY
> prospective collection. This authorization permits building, independently auditing, merging,
> and activating the minimum reviewed acquisition/proposal mechanism required to grow the accepted
> prospective cohort from its current 3/365 observations. It does NOT authorize: strategy or
> candidate creation; backtesting or optimization; reading any sealed partition; evaluating
> prospective values; paper/shadow/live trading; broker/exchange authentication; order routing;
> wallet access; candidate nomination; changing any historical result; forcing
> paper_activation_authorized or sell_ready; public publication. Every acquired update must remain
> append-only, independently reacquired or verified, reviewable, provenance-bound, and incapable
> of exposing its values to strategy code. Production changes must remain draft-reviewed and fail
> closed. Begin with a read-only preflight and a complete V2D activation plan. Build and red-team
> the activation mechanism, open a draft PR, and stop before activation if any governance or
> integrity requirement cannot be satisfied. Once the activation PR is independently accepted,
> true-merge it, activate only the data-collection schedule, verify the first proposal/update
> end-to-end, and leave strategy evaluation permanently disabled. The required terminal state is:
> prospective collection active, cohort evidence accumulating, zero strategy evaluation, zero
> paper trading, all sealed partitions untouched, and V2 still not sell-ready.

This satisfies the "explicit human approval" prerequisite of the standing
`docs/M3E_ACTIVATION_READINESS.md` contract. The stop rule is binding: **stop before activation
if any governance or integrity requirement cannot be satisfied.**

## 2. Preflight baseline (completed, read-only)

- `main == origin/main == ccf2d45687942b010a0a28f9ae69f2fd3d9d2ec7` (two-parent merge of PR #19;
  parents `09fc9c02…`, `7a2c796a…`); working tree clean; full suite on main 3766 passed /
  12 skipped / 0 failed; all 14 workflows green at head.
- Accepted prospective cohort (`research/m3d/` + `research/m3e/accepted_base.json`): ETH-USD
  daily, coinbase-exchange, `cohort_start` 2026-07-12, `row_count` **3**, `last_open` 2026-07-14,
  `minimum_maturity_rows` 365, maturity `immature`, `evaluation_authorized` **false**, canonical
  content fingerprint `bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507`,
  accepted-base sha256 `c7af0ecc…`.
- Due window at plan time (2026-07-23): completed days 2026-07-15 … 2026-07-22 → **8 rows due**.
  Endpoint: `https://api.exchange.coinbase.com/products/ETH-USD/candles` (public market data; no
  authentication — broker/exchange authentication remains forbidden and is not needed).
- Safety flags all false and derived, not stored: `paper_activation_authorized`,
  `paper_trading_active`, `sell_ready`, `eligible_paper_candidate_present`,
  `evaluation_authorized`. Three sealed ledgers byte-empty
  (`research/m2b/test_evaluations.jsonl`, `research/m3a/development_gate_access.jsonl`,
  `research/m3d/prospective_evaluations.jsonl`).
- M3E mechanism READY, NOT ACTIVE: offline modules complete (accepted_base, cutoff, update_plan,
  lease, acquisition, runner_boundary, comparison, transition, assembly, proposal,
  verify_m3e_program [35 checks], publisher, orchestrator seam `prepare_update_proposal`,
  registry, review_policy, status/replay CLIs). Standing workflow
  `.github/workflows/m3e-prospective-update.yml` is a read-only DUE/NO-OP probe
  (`cron: "17 2 * * 1"` Mondays 02:17 UTC + `workflow_dispatch`, `contents: read`,
  repo-guarded). Registry: genesis + audit_noop (run 29441490761). Zero production proposals.

## 3. Design decisions

### D1 — One workflow, edited in place
The activation edits `m3e-prospective-update.yml` where it stands. **No new workflow file** (the
`KNOWN_WORKFLOW_FILES` allowlist of 18 basenames is unchanged). The repo guard
(`if: github.repository == 'panfot1409/gambling-winnings'`), SHA-pinned actions, concurrency
group, and schedule are retained. `workflow_dispatch` remains for the verified first run.

### D2 — Two isolated runners, hardened egress, minimal job-scoped writes
Per the retired `m3d-acquire.yml` precedent and the activation-readiness contract:

- `runner_a` and `runner_b` jobs: each independently emits the offline curl plan
  (`emit_curl_plan`), executes the hardened fetch
  (`curl --proto '=https' --tlsv1.2 --max-redirs 0 --fail --max-filesize 2097152` with pinned
  User-Agent; endpoint read from the offline-emitted plan JSON, never a YAML literal), then
  offline-verifies and writes the runner receipt (`verify_responses_and_write_receipt`). Distinct
  runner identities are asserted (`compare_runners` requires them).
- Runner bundles move between jobs via `actions/upload-artifact`/`download-artifact` (SHA-pinned)
  — the only transport that preserves job isolation. This requires a second narrow
  artifact-upload exemption (see §5) alongside `private-release-build.yml`.
- `assemble` job: fail-closed activation-anchor check (D3) → `verify_accepted_base` →
  orchestrator seam with a real GitPort → on `prepared_draft`: push the deterministic bot branch
  `bot/m3e-prospective-update/<YYYYMMDD>-<YYYYMMDD>-<key16>` and open exactly one **draft** PR.
  Outcomes `noop_not_due` / `skipped_existing_proposal` remain clean no-ops.
- Permissions, job-scoped and minimal: `contents: write` **only** on the job that pushes the bot
  branch; `pull-requests: write` **only** on the draft-PR-open job. Top-level default stays
  `contents: read`. Never `pull_request_target`, never auto-merge, no secrets, no id-token.

### D3 — Governed activation anchor, checked fail-closed at runtime
New `governance/v2d/prospective_activation.json` + a small verifier
(`eth_research.v2d.activation`): the anchor records the verbatim authorization scope and
exclusions, the cohort baseline it applies to (fingerprint `bb6dd392…`, row_count 3), the exact
authorized mechanism (workflow basename, job graph, the two permission grants), and the stop
conditions. The workflow's first step verifies the anchor **before any network step**; a missing,
malformed, or non-matching anchor is a hard refusal. Static guards define the reviewed *shape*;
the anchor is the runtime *switch*. Rollback = revert the activation PR (anchor and wiring leave
together). The `*activation*` basename auto-classifies into the Fable 5 inventory's
`categories.activation_anchors`, as designed.

### D4 — The proposal PR carries the staged cohort extension (single atomic review)
M3E stopped at "proposing (never applying)"; no apply step exists anywhere. Decision: the bot
branch carries, in one commit, (a) the proposal evidence `research/m3e/proposals/<id>/`
(runner_a/, runner_b/, comparison, transition, manifest), (b) the **staged cohort extension** —
updated `research/m3d/prospective_manifest.json`, appended `research/m3d/prospective_segments.jsonl`,
the raw-bundle evidence for the new window, refreshed `research/m3e/accepted_base.json`, and the
appended `research/m3e/proposal_registry.jsonl` entry. `verify_m3e_program` is extended so the
staged cohort files must be the **byte-exact deterministic rebuild** from (accepted base at the
PR base) + (the verified runner rows) — a forged staged file cannot match. One human merge then
lands evidence and growth atomically; `m3d status` grows exactly at merge; there is no window
where accepted evidence and cohort state disagree, and no second unreviewed "apply" step.
(Rejected alternative: a separate apply PR — doubles the review surface and leaves the cohort
state lagging its own accepted evidence.) The review policy is unchanged: draft-only, human
review required, no auto-merge, no retarget, bot never pushes to an accepted branch.

### D5 — Retarget the accepted-cohort base to `main`
`ACCEPTED_COHORT_BRANCH` currently pins `claude/m3d-prospective-evidence-governance` — correct
while the stack was unmerged, stale now: merging a proposal there would not grow the cohort where
it is accepted. The activation PR retargets the constant (publisher + `assert_draft_only` +
lease/tests that pin the value) to `main`. Proposal PRs will be drafts based on `main`, validated
by `m3e-update-pr-check.yml` and the full CI battery.

### D6 — Governed supersession of the static-stack freezes (the structural crux)
Three later acceptance layers froze the then-current cohort **byte-static** and will correctly
fail on any growth as built:

1. `research/m3f/freeze_catalog.json` + `m3f/catalog.py`: live-tree byte hashes (checks 03/04),
   anti-orphan enumeration over `research/{m2b,m3a,m3b,m3c,m3d,m3e}/` (check 08), exact
   `m3d_cohort_rows == 3` binding (check 12), and check 14 anchoring the accepted stack
   byte-for-byte to source-pinned `EXPECTED_ACCEPTED_MAIN_SHA = 7b75a981…`.
2. `research/m3f/honest_state.json`: binds `m3d_cohort_row_count = 3`, `m3e_active = false`,
   `m3e_production_proposal_count = 0`, `standing_workflow_can_write_contents = false`.
3. `docs/M3C_M3E_STACK_FREEZE_TABLE.json` + `tests/test_stack_freeze_table.py`: re-derives
   working-tree hashes of every accepted `research/**` artifact.

These layers were acceptance aids for a deliberately static "ready, not active" stack; the V2D
authorization changes exactly that premise. The supersession must **preserve each control's
anti-forgery intent while permitting only lawful growth**:

- **Catalog schema v2** with an explicit *growable cohort surface*: append-chain files
  (`prospective_segments.jsonl`, `proposal_registry.jsonl`) verify as **prefix-anchored** — the
  frozen bytes must remain a byte-exact prefix of the live file; current-state files
  (`prospective_manifest.json`, `accepted_base.json`) verify through their milestone verifiers
  plus bound immutable identity fields (product, granularity, `cohort_start`, genesis lineage),
  with `row_count` a **floor** (≥ 3, monotone) — and `evaluation_authorized` stays bound
  **exactly false**. New evidence directories (`research/m3e/proposals/**`, the new-window raw
  bundles under `research/m3d/raw/**`) become enumerated growable roots verified by
  `verify_m3e_program` / `verify_m3d_program`, not orphans. Check 14's byte-anchor keeps binding
  every non-growable accepted path to `EXPECTED_ACCEPTED_MAIN_SHA` and, for the growable surface,
  binds the **baseline prefix/lineage** instead of byte equality. The claim "zero production
  proposals" becomes the historical truth "zero at M3F acceptance", never a standing lie.
- **honest_state v2**: the changed facts become either derived-current (row count from the live
  verified base) or explicitly historical-at-acceptance; `m3e_active` flips only on the anchor's
  presence.
- **Stack-freeze-table v2**: the same growable-surface semantics as catalog v2.
- `tools/m3f_independent_verify.py` (the stdlib independent verifier) changes in lockstep, so
  the independent check still independently re-derives everything.

The baseline cohort remains byte-anchored as a mandatory prefix forever: growth can only append;
history cannot be rewritten without detection. Any weakening beyond this enumerated surface is
out of scope and a red-team target.

### D7 — Narrow, visible, basename-keyed guard re-scoping (never evasion)
Standing guards that currently (correctly) fail closed on activation capabilities, each re-scoped
by an explicit, tested exemption keyed to exactly `m3e-prospective-update.yml` (precedent: the
`private-release-build.yml` artifact exemption):

1. `tests/test_workflow_security.py` — no-`contents: write` and artifact-upload checks gain the
   single-basename, job-scoped exemption; the market-host policy is made **explicit**: this one
   workflow is the single authorized market-data egress point (the plan-file indirection keeps
   YAML literal-free, but the guard must *say* the egress exists, not merely fail to see it).
2. `tests/test_private_workflow_security.py` — the least-privilege table rows for this basename
   flip (`can_write_contents`/`can_push`/`contacts_market_host`/`uploads_artifact` true,
   job-scoped), with a standing test that **only** this basename carries them.
3. `verify_m3e_program` check 10 (`_no_unsafe_workflow`) — narrow allowance for this basename's
   two job-scoped grants + its artifact upload; everything else it rejects stays rejected
   (`pull_request_target`, auto-merge, any other `<scope>: write`, any other host).
4. The Fable 5 workflow inventory/freeze — `_WRITE_PERMISSION_RE` findings for this basename
   become declared-and-expected rather than forbidden; the inventory and
   `governance/v2/fable5_source_freeze.json` rebuild once, mechanically, inside the activation
   PR (workflow bytes and the new `governance/v2d/` artifact both feed `surface_digest`).
   Fable 5 does **not** enumerate `research/**`, so weekly growth thereafter never touches
   Fable 5 governance.
5. `tests/test_stack_freeze_table.py` — via D6's table v2.

The public-publication kill-switch is untouched (nothing here publishes anything publicly).
Every exemption ships with a negative test proving it does not generalize (a second workflow with
the same grant must still fail).

### D8 — Versioning and provenance
V2D introduces **no version change at any level** (corrected twice from this plan's first
draft, which said `M3E_PACKAGE_VERSION` and the project version bump). The milestone constants
`M3D_PACKAGE_VERSION` (`0.7.0`) and `M3E_PACKAGE_VERSION` (`0.8.0`) are **frozen and must not
bump**: committed accepted evidence — the m3d registry/segment chain/cohort/publication
manifests and the m3e accepted base/proposal registry — is verified by byte-identical
deterministic rebuild, and those rebuilds embed the milestone constants. Growth appends new
records stamped with the same frozen constants; a constant bump would falsify every committed
byte-rebuild. The **project version stays `2.0.0.dev2`** for the same law one level up: the
accepted V2C operational-qualification layer stamps the *live* `eth_research.__version__` into
its byte-frozen freeze manifest and re-verifies it continuously (`verify_oq_source_freeze`,
re-run by the standing v2c-replay CI on every push), so any project-version bump falsifies the
accepted OQ freeze reproduction; a bump is reserved for a future milestone that legitimately
supersedes the qualification. The Fable 5 audit milestone set the same no-bump precedent.
Every proposal manifest continues to bind
the package version, plan hash, idempotency key, runner identities, and accepted-base fingerprint.
Commits remain append-only (no rebase/amend/force-push); the standard commit trailer is used;
model identifiers never appear in commits or PRs.

## 4. Invariants that must not move (the untouchables)

- The three sealed ledgers stay **byte-empty**; nothing ever opens `prospective_evaluations.jsonl`.
- M3E import firewall (`_scan_m3e_imports`) and the M3D maturity/evaluation firewall
  (`DATA_ONLY_OPERATIONS` vs `FORBIDDEN_OPERATIONS`, `require_no_evaluation_capability`, the 365
  floor, maturity ≠ authorization) are unchanged: **no acquired value becomes readable by
  strategy code**; V2D adds zero strategy, candidate, metric, or evaluation code.
- `evaluation_authorized` stays exactly false everywhere it is bound (m3d base, m3f expected
  state, honest_state v2).
- Paper-readiness derivation is untouched: `paper_activation_authorized`, `paper_trading_active`,
  `sell_ready` keep deriving false; no forcing literal is introduced (the standing Fable 5 tests
  keep proving it).
- V2A/V2B/V2C accepted artifacts, all historical results, and all consumed one-shots are
  untouched; no history rewrite anywhere.
- No broker/exchange authentication, no order routing, no wallet access, no public publication.

## 5. Minimum change set (enumerated)

New: `governance/v2d/prospective_activation.json`; `src/eth_research/v2d/{__init__,activation}.py`;
`docs/V2D_PLAN.md` (this file); tests for the anchor, the exemption narrowness, the growable
surfaces, and the extended verifier checks.
Edited: `.github/workflows/m3e-prospective-update.yml` (D1/D2); `m3e-update-pr-check.yml`
(validate staged cohort extension too); `src/eth_research/m3e/{publisher,verify_m3e_program,…}.py`
(D4/D5/D7.3); `src/eth_research/m3f/{catalog,honest_state,…}.py` + `tools/m3f_independent_verify.py`
(D6); `tests/test_workflow_security.py`, `tests/test_private_workflow_security.py`,
`tests/test_stack_freeze_table.py`, m3e tests pinning the base branch (D5/D7);
`research/m3f/freeze_catalog.json`, `research/m3f/honest_state.json`,
`docs/M3C_M3E_STACK_FREEZE_TABLE.json` (regenerated v2, reviewed in the same PR);
`governance/v2/fable5_system_inventory.json` + `fable5_source_freeze.json` (mechanical rebuild);
`pyproject.toml`/`src/eth_research/__init__.py`/`uv.lock` (D8); README/docs status updates,
including marking `M3E_ACTIVATION_READINESS.md` satisfied-by-V2D.

Build-phase verification items (resolved mechanically during §6-B, each fail-closed):
orchestrator/GitPort contract details and idempotent PR-open on retry; lease coupling to the base
branch; registry append flow through the bot branch; exact m3d segment-chain/raw-bundle/quality
requirements for an appended window; residual M3F couplings (recovery capsule manifest, drill,
inventories) surfaced by running every verifier after the D6 change; the Actions repo setting
"allow Actions to create PRs" probed in preflight and failing closed (refused PR-open fails the
run; the lease makes retry idempotent).

## 6. Phases

- **A (done)** — read-only preflight; this plan committed alone as commit 1.
- **B — Build** (§341): implement §5 with failing-test-first for every guard re-scope; full local
  battery green at each commit; nothing activates (anchor exists only on this branch; schedules
  on feature branches are inert).
- **C — Red team** (§342): ≥3 independent read-only auditors (Agent tool) with distinct lenses —
  (i) egress/workflow/token security + exemption narrowness, (ii) value-isolation/evaluation-
  firewall/sealed partitions, (iii) governance/append-only/D6 supersession integrity (can growth
  be forged? does v2 still catch baseline tampering?). Class A/B/D = stop; Class C fixed forward
  with fresh CI.
- **D — Draft PR, acceptance, true merge** (§343): draft PR (base `main`); pre-merge guard (CI
  terminal-green, digest/verifier battery, neutrality of all non-V2D accepted artifacts);
  independent acceptance auditors; undraft solely as merge prerequisite; true two-parent merge;
  post-merge full battery + all workflows green. **Stop before merge on any unsatisfied
  requirement.**
- **E — Activation + first update end-to-end** (§344): on `main`, `workflow_dispatch` the
  workflow (schedule stays Mondays 02:17 UTC). Verify: two runners fetch the due window
  (≈ 2026-07-15…latest completed day; 8 rows if run 2026-07-23), byte-identical canonical rows,
  35+ checks pass, exactly one draft proposal PR opens with the staged cohort extension. Verify
  the proposal independently (local `verify_m3e_program`, fresh CI on the proposal PR, spot
  audit), then merge it under this authorization's "verify the first proposal/update end-to-end"
  (subsequent weekly proposals remain for the user to review/merge). Post-merge: `m3d status`
  row_count 3+N, maturity still `immature`, remaining 365−(3+N); sealed ledgers byte-empty; all
  safety flags still false; full battery + workflows green; repeat-dispatch is an idempotent
  no-op. Then the terminal report and verdict.

## 7. Rollback

Revert the activation PR with a revert commit (anchor + wiring leave together); close any
unmerged draft proposal PR; delete orphan `bot/m3e-prospective-update/*` branches. Never
force-push, never reset a shared branch, never mutate accepted data (proposals are drafts until
a human merges them).

## 8. Required terminal state (verbatim)

> prospective collection active, cohort evidence accumulating, zero strategy evaluation, zero
> paper trading, all sealed partitions untouched, and V2 still not sell-ready.

## 9. As-built realization notes (build-phase corrections to this plan)

Recorded during phase B so the plan of record matches what was actually built; none of these
weakens a decision above.

- **D4 (the apply step).** Realized as `eth_research.m3e.staging.stage_cohort_extension`: the
  orchestrator's transactional assembly stages the append-only cohort extension — ledger append
  (`research/m3d/update_attempts.jsonl`), segment-chain + quality rebuild, cohort publication,
  accepted base, proposal registry — with full rollback on any failure, then proves the staged
  tree with `verify_m3e_program.verify_landed_update` (checks L01–L11): the grown tree must be
  exactly the deterministic consequence of (accepted base at the PR base) + (the two-runner
  attested rows). The 35-check proposal graph still runs in full, but pre-staging inside the
  orchestrator (its manifest binds the pre-update base by design), so
  `m3e-update-pr-check.yml` verifies the LANDED graph (11 checks) on the bot branch rather than
  replaying the pre-staging graph against the grown tree.
- **D4 (growth provenance).** Per-attempt raw evidence lands under
  `research/m3d/raw/update-<attempt-id>/` and each accepted attempt appends one hash-chained
  entry to `research/m3d/update_attempts.jsonl`. With zero attempts every rebuilt artifact is
  byte-identical to its committed bytes — this activation PR changes nothing under `research/`.
- **D6 (supersession without regeneration).** `research/m3f/freeze_catalog.json`,
  `research/m3f/honest_state.json`, and `docs/M3C_M3E_STACK_FREEZE_TABLE.json` are **not**
  regenerated (the change-set list in §5 originally said "regenerated v2"): they remain
  byte-identical immutable at-acceptance records. The supersession is interpretive and
  anchor-gated (`eth_research.m3f.growable` + the v2 verification paths): with zero growth every
  cataloged artifact must still match byte-for-byte; with growth and a strictly-valid committed
  V2D anchor, chained artifacts must carry the committed bytes as an exact prefix, current-state
  snapshots re-verify through the milestone verifiers, and the recorded counters/floors may only
  move forward; growth without the anchor stays a hard stop, in both the m3f-native and the
  stdlib-independent verifier.
- **D7 (a sixth guard layer).** The V2AB stack-acceptance audit
  (`eth_research.v2ab.acquisition_audit._scan_workflows`) also flags any workflow granting
  `contents: write` — a layer the build-phase guard battery missed because its tests match none
  of the battery's keyword filters; the first post-activation full suite caught it. Re-scoped
  identically to the other five layers: the flag is suppressed only for the exact basename
  `m3e-prospective-update.yml` *and* only while the committed V2D activation anchor exists
  (fails closed otherwise); the audit's actual BTC-retirement facts — Coinbase endpoint
  literal, write-all/id-token/packages grants, acquire-named workflows, the consumed sentinel —
  stay unconditional for every workflow including this one, with an impostor + anchor-removal
  negative test.
- **D8 (versions).** Corrected in place above: `M3E_PACKAGE_VERSION` does **not** bump (frozen
  `0.8.0`, alongside `M3D_PACKAGE_VERSION` frozen `0.7.0`), and the project version does not
  move either. The build phase first applied the planned bump to `2.0.0.dev3` and the full
  suite immediately proved it impossible: every `tests/test_v2c_oq_*` rehearsal and archive
  verification failed because `verify_oq_source_freeze` rebuilds the committed
  `governance/v2c/oq_source_freeze.json` with the live package version stamped in — under any
  bumped version the accepted OQ freeze (and the standing v2c-replay CI, which re-runs that
  gate plus the OQ replay on every push) can never verify again without regenerating accepted
  V2C artifacts or editing frozen V2C qualification source, both of which §4 forbids. The bump
  was reverted; V2D runs at the unchanged `2.0.0.dev2`, per the Fable 5 no-bump precedent.
