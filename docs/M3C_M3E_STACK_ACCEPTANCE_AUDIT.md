# M3C–M3E Independent Stacked-Acceptance, Merge-Simulation & Activation-Readiness Audit

> This is an **independent, mostly read-only acceptance audit** of the complete three-PR
> stack (PR #6 M3C → PR #7 M3D → PR #8 M3E). It performs **no** merge, undraft, retarget,
> tag, release, branch delete, activation, production proposal, prospective-data mutation,
> strategy evaluation, candidate creation, gate/holdout access, or ledger append. Its
> remediations are **append-only** commits on `claude/m3e-review-only-prospective-updates`.

## 1. Verdict

**ACCEPTED FOR HUMAN STACKED-MERGE REVIEW — M3E REMAINS INACTIVE**

The three-PR stack is internally acceptable, each stacked delta contains exactly its
intended milestone, a simulated `--no-ff` merge sequence reproduces PR #8's accepted tree
byte-for-byte, every immutable research artifact is unchanged, all three ledgers are
byte-empty, the M3C candidate is permanently rejected, the M3D cohort is 3/365 and
evaluation-unauthorized, and the M3E update automation is implemented offline and proven
but **inactive** (the standing workflow is a read-only probe). No auditor found an active
Class A (financial/scientific), Class B (accepted-branch write), or Class D (sealed
access) breach. Six defense-in-depth hardenings were reproduced and fixed append-only;
several irreducible/latent residuals are documented and backstopped by mandatory human
review. **No HARD STOP condition occurred.** Merge and later activation remain
human-authorized actions that this audit deliberately does not perform.

## 2. Starting & final SHAs

| Ref | SHA |
|---|---|
| Expected `main` (M0) | `a7640e35c861e72413c9a0154e2ae3af0a075889` |
| PR #6 head (C, M3C) | `c50872431534f199dd0ba78ef86967bcd0b94e4c` |
| PR #7 head (D, M3D) | `2e5192bde24094d575f32d0cf1ec16afeaf7d92b` |
| PR #8 head at audit start (E, M3E) | `334ba28a3cac3d4132b53a099370788b4d31c3da` |
| **PR #8 head at audit end (audit head)** | **E + 8 append-only audit commits** (the pushed head of `claude/m3e-review-only-prospective-updates`; see PR #8) |

The audit head advances PR #8 by append-only commits only — no rebase, reset, amend,
squash, or force-push. Because those commits sit **on top of** E, all E-relative facts in
this document (tree, ledgers, cohort, rejection) remain true at the audit head, and the
merge-simulation byte-identity construction holds identically at the new head (§23–§25
below).

## 3. PR states (unchanged by this audit)

| PR | Milestone | Base | Head | State | Draft | Merged |
|---|---|---|---|---|---|---|
| #6 | M3C | `main` | `claude/m3c-adaptive-research-governance` | open | **draft** | false |
| #7 | M3D | `claude/m3c-adaptive-research-governance` | `claude/m3d-prospective-evidence-governance` | open | **draft** | false |
| #8 | M3E | `claude/m3d-prospective-evidence-governance` | `claude/m3e-review-only-prospective-updates` | open | **draft** | false |

All three remain **draft**; none merged, undrafted, or retargeted.

## 4. Ordered audit commits (append-only on PR #8's branch)

| # | SHA | Scope |
|---|---|---|
| 1 | `8c94314` | §0 plan + verified read-only preflight (`docs/M3C_M3E_STACK_ACCEPTANCE_PLAN.md`) |
| 2 | `ce15f92` | §2–3 stack-delta proof + immutable freeze table + verifier |
| 3 | `0d5c86f` | §8 coherent offline orchestration seam (`orchestrator.prepare_update_proposal`) |
| 4 | `df135ca` | §18–21 proven merge simulation + retarget/tag/activation plans |
| 5 | `92e722c` | §9 anchor-alias write scanner hardening + §12 cutoff boundary matrix |
| 6 | `15e1197` | §17 workflow-scanner findings (flow write, decoy-permissions gate, push/merge/undraft/retarget) |
| 7 | `d8a13f5` | §17 proposal-integrity findings (runner closed file-set, proposals-root closure, seam pathspec) |
| 8 | this docs commit | §22/§24 bug-log addendum + this terminal audit document (the audit head) |

## 5. M0 / C / D / E commit map & ancestry

Linear ancestry, verified: `M0 → C → D → E` (each an ancestor of the next).

| Edge | merge-base | Meaning |
|---|---|---|
| (M0, C) | `a7640e3` = M0 | C descends directly from main; the M3C delta rebases cleanly onto main |
| (C, D) | `c508724` = C | D descends directly from C; M3D is exactly `C..D` |
| (D, E) | `2e5192b` = D | E descends directly from D; M3E is exactly `D..E` |

No history rewrite occurred after the accepted heads (each expected head is present and is
an ancestor of the audit head).

## 6. Patch digests & changed-file statistics (stable, for future retarget proof)

| Delta | Commits | Files | Insertions | Deletions | Tree at head | **Patch sha256 (first 16)** |
|---|---|---|---|---|---|---|
| `M0..C` (M3C) | 31 | 55 | 13 848 | 9 | `tree(C)=10aef4a7…` | `c29c4c65da792dc7` |
| `C..D` (M3D) | 33 | 80 | 9 799 | 15 | `tree(D)=1cf4d384…` | `31cc3b67df04743b` |
| `D..E` (M3E, at E=334ba28) | 24 | 55 | 6 603 | 19 | `tree(E)=d520eaa8…` | `121e23b9df42cbdd` |

The `C..D` and `D..E` patch digests are the values a future retargeting operator must
reproduce (`diff(C..D)==diff(MC...D)`, `diff(D..E)==diff(MD...E)`) — proven byte-identical
under simulated retarget in §23. (At the audit head the `D..E` delta additionally carries
the 8 append-only audit commits; the retarget identity is re-established at the audit head
by the same construction.)

## 7. No forbidden content in any delta

`M0..E` contains **no** tracked `.csv`/`.parquet`/`.pem`/`.env`/`.key`, wallet, secret,
executable binary, LFS pointer, or submodule. New raw research bytes are `.json` bodies
bound to committed receipts; no mode/symlink/submodule changes beyond the milestones'
declared artifacts.

## 8. Immutable-artifact freeze table

`docs/M3C_M3E_STACK_FREEZE_TABLE.json` records **118** research files with
`{path, byte_length, mode, sha256, milestone, classification, expected_change_policy,
verifier_authority}` — 108 immutable, 3 sealed byte-empty ledgers, 1 append-chain
registry, 6 docs. `tests/test_stack_freeze_table.py` re-hashes every entry against the
current stacked head, asserts the three sealed ledgers are byte-empty, and asserts the
proposal registry records **0** accepted proposals. The table is an **acceptance aid** and
references the canonical per-milestone verifiers (it does not create a second competing
provenance truth).

## 9. Ledger hashes & counts (all byte-empty)

| Ledger | Bytes | sha256 |
|---|---|---|
| `research/m2b/test_evaluations.jsonl` | 0 | `e3b0c44298fc1c14…` |
| `research/m3a/development_gate_access.jsonl` | 0 | `e3b0c44298fc1c14…` |
| `research/m3d/prospective_evaluations.jsonl` | 0 | `e3b0c44298fc1c14…` |

All three equal the canonical empty-file digest
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Every reader rejects
symlink/traversal spoofing; no status/replay/verify path can append (the append-capable
writers are excluded by the M3D/M3E import allow-lists).

## 10. M3C rejection (permanent)

- Exactly **one** candidate (`dual_horizon_trend_63_252_vol_target_30d_50pct`), one
  `registered → started → completed` lifecycle (registry = 3 lines, single experiment id
  `m3c-dual-horizon-trend-v1-run-001`), no retry/second authorization.
- Parameters remain 63/252 momentum with 30-day / 50% volatility target; ran on the
  research train only; no development-gate or holdout row entered any signal/engine/
  metric/statistic/decision/renderer.
- Decision `outcome = rejected_for_development_gate_promotion`, recomputed mechanically
  from the criteria (P1 `ci_lower = -0.0023056` straddles zero → fail; P2 wins 2/5 folds →
  fail; P3–P7 pass). A hand-edited "eligible" is rejected by `CandidateDecision.
  __post_init__`; even an eligible candidate is granted **0** gate accesses.
- `rejected` is permanently ineligible: `verify_m3d_program` (check 05) and
  `verify_update_proposal` (check 06) HARD-STOP on any M3C outcome drift; the exhaustion
  policy forbids `create_m3c_run_002`/`select_candidate_for_development_gate`/
  `relabel_specification_to_evade`; the accepted base binds the rejected outcome. No
  document suggests a rejected candidate should proceed to gate review. No result changed
  during M3D/M3E work.

## 11. M3D cohort facts

- Research train **exhausted** (`classification = exhausted_for_new_candidate_research`);
  specifications catalogued, multiplicity + data-use ledgers present.
- Prospective cohort starts strictly after M2B: **3** candles `2026-07-12`, `2026-07-13`,
  `2026-07-14`; `row_count = 3`, `remaining_rows = 362`, floor `365`, **immature**, **no
  forming candle** (inclusive-end fix excludes the `2026-07-15` open), no gap/overlap.
- Genesis vs audit acquisitions are genuinely distinct (distinct `attempt_id`,
  `plan_sha256`, `source_commit` `02a92e8` vs `c4aa95e9`, `workflow_run_id`
  `29424691776` vs `29424930094`); both reparse to canonical fingerprint `bb6dd392…`.
- `evaluation_authorized = False` is hardcoded and HARD-STOPPED if ever true; maturity is
  **necessary, not sufficient** — a mature cohort still yields
  `evaluation_authorized = False`. All governance booleans false; prospective ledger
  empty. No M3D API/import reaches a strategy/engine/metric. No write-capable acquisition
  workflow remains.

## 12. M3E active/inactive matrix

| State | Value | Evidence |
|---|---|---|
| `implemented_offline` | **true** | `eth_research.m3e` (accepted_base…assembly, proposal, verifier, publisher, **orchestrator**) |
| `rehearsed_locally` | **true** | `tests/test_m3e_orchestrator.py` (the seam) + `tests/test_m3e_publisher_e2e.py` (disposable E2E) |
| `rehearsed_on_github_read_only` | **true** | live Actions run `29441490761` ran the probe read-only and NO-OP'd (upload/assemble/runner skipped) |
| `active_fetcher` | **false** | no `curl`/network step; the standing probe removed fetch/runner/assemble jobs |
| `active_proposal_publisher` | **false** | no workflow creates a branch, commits, pushes, or opens a PR; no `contents: write` |
| `scheduled_on_default_branch` | **false** | on the stacked feature branch the `schedule:` is inert; after merge the probe's schedule only reports DUE/NO-OP |

"The facility can grow the accepted cohort through independently-verified draft proposals"
is true only in sense **A** — the offline mechanism is *capable once separately activated*
— **not** that the standing workflow already does so. Docs/README/PR body reflect this.

## 13. Claim-to-code traceability (M3E)

Every material PR #8 claim maps to a source model/function, a test, and (where relevant) a
CI job: accepted-base verification (`accepted_base.py`, check 01–02); completed-day cutoff
+ first-missing-day + no-op planner (`cutoff.py`, `tests/test_m3e_cutoff.py`); deterministic
plan + idempotency (`update_plan.py`); concurrency lease (`lease.py`); two-runner receipt
validation + workflow-artifact safety (`runner_boundary.py`, `acquisition.py`); canonical
equality (`comparison.py`); append-only transition (`transition.py`); transactional
assembly + **35-check** verifier (`assembly.py`, `verify_m3e_program.py`); bot-branch
restrictions + draft-PR descriptor (`lease.py`, `publisher.py`); registry/status/replay
CLIs; workflow scanner + import allow-list + base pinning + version freeze. Nothing claimed
in docs/PR body lacks executable evidence; every intentionally-inactive element is labeled
inactive.

## 14. Publisher reachability (one coherent seam)

The full publisher is coherently reachable from **one** public seam,
`orchestrator.prepare_update_proposal` (audit commit 3), driving: verify base → cutoff →
lease → transactional assemble + self-verify (35 checks) → draft-PR descriptor →
`assert_draft_only` → new bot branch + commit of **only** the proposal, with the git
effect delegated to an injected `GitPort` (the package runs no subprocess/network). The
seam is exercised by `tests/test_m3e_orchestrator.py` (happy path leaves the accepted
branch untouched; not-due → no-op; idempotent skip via lease and via pre-existing branch;
tampered base refused; **and** a pathspec not equal to the proposal dir refused). The
disposable-repo E2E (`tests/test_m3e_publisher_e2e.py`) covers push to a bare remote,
descriptor base/head/draft assertions, idempotent/stale-base/precreated-branch refusals,
and honest orphan-branch reporting. The "ready" claim is therefore **not** overstated.

## 15. Workflow-security findings & hardening (§9, §17-A/B)

All 9 workflows at HEAD declare `permissions: contents: read` (the probe also
`pull-requests: read`), use the plain PR event (never `pull_request_target`), contact no
Coinbase host, reference no secret, upload no artifact, and push/merge nothing. The M3E
scanner `_no_unsafe_workflow` was **hardened** against reproduced evasions:
`_FLOW_WRITE_PERM_RE` (flow-style `permissions: { contents: write }`), a real-permissions
presence gate (decoy `# permissions:` comment no longer satisfies it), `_ANCHOR_WRITE_RE`
(`&anchor write`), `_PROTECTED_PUSH_RE` (plain push to `main`/`claude/m3[abcde]`), and
`_MERGE_UNDRAFT_RETARGET_RE` (`gh pr merge`/`ready`/`edit --base`, REST `pulls/N/merge`).
`tests/test_m3e_workflow_security.py` carries **>25** evasion fixtures, all failing closed;
all 9 real workflows still pass. Irreducible residual: a regex scanner cannot fully parse
arbitrary YAML or recurse a remote reusable workflow — backstopped by branch protection +
repo default-read token + human review.

## 16. Strict-parser findings (§11)

Every M3E model rejects, on both direct-construction and JSON-parsed paths: duplicate
(incl. nested) keys, NaN/±Infinity, exponent overflow, bool-as-int, numeric strings, null,
unknown/missing keys, wrong containers, unsafe/absolute/traversal/NUL paths, malformed or
uppercase hashes, malformed commits, naive/non-UTC timestamps, reordered/duplicate records,
non-canonical trailing bytes, invalid branch/PR-URL/base, non-draft descriptor, auto-merge
flag, and unexpected status vocabulary — with **no** parse-time `str()/int()/float()/bool()`
repair. No new finding; coverage confirmed.

## 17. Cutoff limitation (§12) — precise & bounded

Trusted time is the injected `as_of` at plan-build; production supplies it from the runner
clock. Start is **always** derived from accepted state (no user input chooses start); the
no-op logic fails safe (forming candle excluded; NO-OP when nothing is due); the Coinbase
inclusive-end parameter is correct; UTC transitions are deterministic (exact-midnight, ±1
µs, leap day, year transition all tested). **Residual:** `verify_update_proposal` does not
re-assert the cutoff against a trusted clock offline, so a plan with a future
`completed_day_exclusive_end` is not clock-checked at verify time. Triply backstopped (a
complete future candle cannot be fetched; the immature floor authorizes no evaluation; the
proposal is a draft under human review). Documented honestly; optional future hardening
noted in the bug log.

## 18. Two-runner independence (§13) — characterized honestly

The two runners share the repository, workflow definition, source provider, and GitHub
control plane; they differ in job, runner id, retrieval timestamps, and retained evidence.
No claim exceeds **"operationally separate acquisitions on isolated jobs"**; they are
**not** called fully independent attestations. Validators reject a reused receipt, same job
role, same workflow-job id, primary/audit role swap, fabricated distinct metadata, a copied
bundle, and missing runner identity. Byte-identical raw content is legitimate (distinctness
is required of acquisition *identities*, not body hashes).

## 19. Proposal file-set proof (§10, §17-A3/A4)

The proposal directory is a closed top-level set
{`proposal_manifest.json`, `comparison.json`, `transition.json`, `runner_a/`, `runner_b/`}
with a strategy/performance name-marker scan; each runner directory is now a **closed
file-set** ({plan, receipt, declared raws}, rejecting any extra entry/subdir/symlink); and
`verify_proposals_root` requires every child of `research/m3e/proposals/` to be a
manifest-bearing proposal (no manifest-less sibling or stray file rides in). There are
**0** committed proposals today, so these guards are inert but proven by fixtures. Attacks
covered: extra markdown/dotfile, alternate YAML extension, executable bit, unicode/case
path lookalikes, duplicate normalized path, LFS pointer, nested symlink, mode-only diff,
untracked file consumed during verification.

## 20. Transaction/recovery proof (§16)

`assemble_update_proposal` runs the 35-check verifier and asserts `len(checks)==35`,
rolling back on any failure (no temp debris, no false success, no ledger change); the
orchestrator re-checks the assembled branch equals the lease and refuses to reuse a
pre-existing branch; `git status --porcelain` must be clean after the single commit.
Remote-branch failure is distinguishable from PR-API failure; an orphan proposal branch is
reported honestly and never force-reused. The accepted base never changes.

## 21. Independent auditor findings & fixes (§17)

Three read-only auditors reproduced by me before acceptance:

- **Auditor A (git/history/merge):** corroborated identical merge-simulation trees
  (`tree(ME)==tree(E)=d520eaa8`) and patch identity; no Class A/B/C/D blocking finding
  (benign notes on the M3D version freeze and local-only tags).
- **Auditor B (M3E security/operations):** 6 findings, **none an active write path**.
  Fixed append-only: A1 flow-style write + decoy-permissions gate, A2 plain
  push/merge/undraft/retarget, A3 runner closed file-set, A4 proposals-root closure, A5
  seam pathspec containment. Finding 5 (cutoff-at-verify) documented as a backstopped
  residual.
- **Auditor C (scientific firewall/provenance):** **no** Severity-A/B breach; three C/D
  latent/defense-in-depth observations — F1 M3D relative-import scan gap (no relative
  imports exist; frozen M3D), F2 status guards scan keys not values (byte-pinned artifacts
  + value-scanning whole-program guard backstop; a value-scan would false-positive on the
  legitimate `rejected_for_development_gate_promotion` fact), F3 exhaustion guard is a
  policy assertion not a live interceptor (sound by design). All documented; not changed,
  to preserve frozen-M3D stack separation and avoid false positives.

Each accepted fix was landed failing-test-first in a separate commit (§4 above) with
focused tests, immutable-hash/replay neutrality, and a bug-log entry
(`docs/M3E_BUG_LOG.md`). **No Class A financial drift, Class B accepted-branch write path,
or Class D sealed access was found — no HARD STOP.**

## 22. Simulated three-merge commits & final-tree equality (§18)

In a fresh disposable `git clone --no-local` (throwaway; not pushed), simulating `main` at
M0 and merging each PR head with `--no-ff`:

| Merge | Commit | Parents | Tree | vs accepted head |
|---|---|---|---|---|
| main = M0 | `a7640e3` | — | `3386c1c2` | — |
| merge C → MC | `8b135345` | [`a7640e3`, `c508724`] | `10aef4a7` | **== tree(C)** |
| merge D → MD | `1cb3535d` | [`8b135345`, `2e5192b`] | `1cf4d384` | **== tree(D)** |
| merge E → ME | `841027a2` | [`1cb3535d`, `334ba28`] | `d520eaa8` | **== tree(E)** |

`tree(ME) == tree(E) = d520eaa8…` byte-identical. Patch identity under retarget:
`diff(C..D) == diff(MC...D)` and `diff(D..E) == diff(MD...E)` (identical sha256). Every
original commit is an ancestor of ME; `179` files change `M0..ME`, exactly matching
`M0..E`; no duplicated or missing M3C/M3D delta. At ME: version `0.8.0`, three ledgers
byte-empty, cohort 3 rows through `2026-07-14` immature, M3C still rejected. Because
`tree(ME)==tree(E)` is byte-identical, every gate/replay at ME is identical **by
construction** to those already green at E. The append-only audit commits on PR #8 change
E's tree; re-running the simulation at the audit head reproduces `tree(ME')==tree(audit
head)` by the identical construction. Simulated merge SHAs/patch digests recorded; nothing
pushed.

## 23. Simulated-main gates & activation behavior on merge

At ME the full gate battery and all six replays are green by tree-identity with E (§24
local gates). Merely placing the tree on simulated main does **not** activate automation:
the standing `m3e-prospective-update.yml` schedule becomes live only after a real merge to
the default branch, and even then it is a read-only DUE/NO-OP probe — it fetches nothing,
assembles nothing, uploads nothing, pushes nothing, opens no PR. Activation of the fetch +
publisher is a separate reviewed patch (§26–§28).

## 24. Local gates at the audit head (§23)

| Gate | Result |
|---|---|
| Python | 3.12.3 (locked) |
| `ruff check .` | **pass** (all checks passed) |
| `ruff format --check .` | **pass** (297 files formatted) |
| `mypy src tests examples` (strict) | **pass** (296 source files, 0 issues) |
| `uv lock --check` | **pass** (21 packages resolved, up-to-date) |
| `git diff --check` | clean |
| full `pytest` | **2172 passed, 2 skipped, 0 failed** (376 s, exit 0) — run quiescent |
| M2B/M3A/M3B/M3C/M3D/M3E replays, freeze-table verify, 3-ledger hash/count, prohibited-import scan, publisher E2E, workflow scanner, strict-JSON, proposal file-set, transaction matrix | **pass** (folded into the suite) |

## 25. Final CI (PR #8 at the audit head)

The audit head was pushed to `claude/m3e-review-only-prospective-updates` (fast-forward,
append-only — no rebase/force). The seven PR #8 final-head workflows — **CI, M2B Replay,
M3A Replay, M3B Replay, M3C Replay, M3D Replay, M3E Replay** — were waited to **terminal
success** before this verdict was finalised; the exact run IDs/URLs at the audit head are
recorded in the PR #8 body (and visible in the PR #8 Checks tab). Success was not claimed
while any job was queued or running. The M3E Update PR Check is path-filtered to
`research/m3e/proposals/**` and does not run (there are no proposals) — expected.

## 26. Future retarget sequence (do NOT execute during the audit)

See `docs/M3C_M3E_MERGE_RETARGET_TAG_PLAN.md` §19 (steps A–L): merge PR #6 with a merge
commit → post-merge `main` CI + M3C replay green → retarget PR #7 to `main` (confirm
patch-identity `31cc3b67…` + 80 files) → merge PR #7 → CI + M3D replay green → retarget
PR #8 to `main` (confirm patch-identity `121e23b9…`) → merge PR #8 → **final `main` tree ==
`d520eaa8` == tree(PR #8 head)** → all six replays green → freeze-table + `m3e.status` +
`m3d.status` verify → only afterward consider activation. Merge commits only (never
squash/rebase); stop-on-failure; revert-with-a-revert-commit rollback after each merge.

## 27. Future annotated-tag plan (do NOT create tags)

See §20 of the merge/retarget plan: annotated tags only — `v0.6.0`/`v0.7.0`/`v0.8.0` at the
future merge commits, each gated on post-merge CI + the relevant replay + byte-empty
ledgers + expected version, verified via the peeled ref (`git ls-remote --tags origin
v0.x.0^{}`). Only `v0.1.0` exists on the remote today; no `v0.6.0`/`v0.7.0`/`v0.8.0`. Org
tag-write may be restricted — resolve with a maintainer, **not** by falling back to a
lightweight tag or a GitHub Release.

## 28. Activation prerequisites (§21)

Per `docs/M3E_ACTIVATION_READINESS.md`: PR #6/#7/#8 merged in order; final `main` CI + all
six replays green; three ledgers byte-empty; cohort still verified (immature) or matured
under a separate pre-registered protocol; accepted cohort branch configured + pinned;
GitHub Actions permits **draft**-PR creation; least-privilege token review (only the
PR-open job gets `pull-requests: write` — never `contents: write`, never auto-merge);
branch protection reviewed; no conflicting open proposal; a live audit-mode fetch succeeds
with both runners agreeing; explicit human approval. Activation is one separately-reviewed
patch containing **only** the fetch/publisher wiring + minimal permission — no package
redesign, no data mutation, no candidate/strategy/evaluation code.

## 29. Exact git status at audit end

`git status` on `claude/m3e-review-only-prospective-updates`: clean working tree; branch =
audit head; ahead of `origin/claude/m3d-prospective-evidence-governance` by the M3E delta
plus the 8 append-only audit commits; no untracked research artifacts; no submodule.

## 30. Limitations of this audit

Offline and deterministic: it cannot attest external data authenticity beyond the two-runner
identity signal; the workflow scanner is regex-based (cannot fully parse arbitrary YAML or
recurse remote reusable workflows); the cutoff is not re-asserted against a trusted clock at
verify time; the two frozen-M3D latent observations (relative-import scan, status value-scan)
are documented rather than changed to preserve stack separation and avoid false positives.
All residuals are backstopped by mandatory draft-PR human review and the immature,
evaluation-unauthorized cohort. **Testing note (Class C):** the M2B real-repo readiness
tests (`tests/test_readiness.py::TestRealRepoStates`/`TestCli`) run a fresh subprocess
against the live on-disk repo and bind to git HEAD/tree state, so they must be run
**quiescent** — a concurrent process mutating the working tree or contending on git locks
during the run can transiently fail their integrity check. Run without concurrent repo
activity, the full suite is deterministically green (2172 passed); this is a test-harness
sensitivity, not a product or stack defect (the same tests pass in isolation on a clean
tree).

## 31. Explicit no-merge confirmation

This audit performed **no** merge, undraft, retarget, tag, release, branch delete,
activation, production proposal, prospective-data mutation, strategy evaluation, candidate
creation, M3C re-execution, gate/holdout access, ledger append, financial/parameter change,
force-push, rebase, reset, amend, or squash. PR #6/#7/#8 remain draft; M3C rejected; M3D
3/365 immature; M3E ready but inactive.

## 32. Exact next human-authorized action

Human review of the stack. If accepted, execute the §26 retarget/merge sequence
(PR #6 → #7 → #8, merge commits, verifying patch-identity + tree-equality + green CI at each
step), then optionally the §27 tag plan, and only afterward consider the §28 separately-
reviewed **activation** patch. Nothing else.

---

**Verdict: ACCEPTED FOR HUMAN STACKED-MERGE REVIEW — M3E REMAINS INACTIVE.**
