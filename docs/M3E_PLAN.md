# Milestone 3E — Review-Only Prospective Update Automation, Two-Runner Data Attestation, and Zero-Trust Data-PR Operations

This document preregisters Milestone 3E **before** any implementation, version
bump, model, ledger, workflow, or proposal is written. It is committed alone as
the first M3E commit. Everything M3E does must conform to what is written here;
any deviation is a defect to be corrected, not a silent change.

M3E is **data-only, governance-only, and review-only**. It does not create,
evaluate, rank, tune, promote, or report performance for any strategy, and it
moves no money. Its scientific outcome is deliberately uneventful:

> A facility now exists that can propose independently-verified, append-only
> growth of the prospective cohort as a **draft** pull request for **human**
> review — but it is *ready, not active*, it has evaluated no strategy, and at
> today's date it has nothing to propose.

No alpha claim. No candidate. No test result. No promotion. No merge.

---

## 1. Upstream state this milestone builds on (verified read-only)

The non-negotiable read-only preflight (§0 of the assignment) ran before this
document was written and was **fully clean**:

| Fact | Verified value |
| --- | --- |
| Upstream M3D branch | `claude/m3d-prospective-evidence-governance` |
| M3D accepted head | `2e5192bde24094d575f32d0cf1ec16afeaf7d92b` |
| M3C accepted head (M3D base) | `c50872431534f199dd0ba78ef86967bcd0b94e4c` |
| PR #7 | open · draft · unmerged · base `claude/m3c-adaptive-research-governance` · head `2e5192b` · 33 commits |
| CI run 29431640556 | success (all jobs) |
| M2B Replay 29431636952 | success |
| M3A Replay 29431637863 | success |
| M3B Replay 29431637572 | success |
| M3C Replay 29431636832 | success |
| M3D Replay 29431637129 | success |
| Worktree | clean; local == remote |
| Package version | `0.7.0` |
| `verify_m3d_program` | 25/25 checks pass |
| `replay --deep` | 25 checks, 5 artifacts byte-exact, no socket, no tracked mutation |
| Development-gate ledger `research/m3a/development_gate_access.jsonl` | tracked, 0 bytes, sha256 `e3b0c442…855` |
| Final-holdout ledger `research/m2b/test_evaluations.jsonl` | tracked, 0 bytes, sha256 `e3b0c442…855` |
| Prospective evaluation ledger `research/m3d/prospective_evaluations.jsonl` | tracked, 0 bytes, sha256 `e3b0c442…855` |
| M3C candidate decision | `rejected_for_development_gate_promotion` |
| Research train | exhausted for new candidate research |
| Accepted prospective cohort | 3 rows; opens `2026-07-12`/`13`/`14`; fingerprint `bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507` |
| Cohort maturity | `immature` (3/365); `evaluation_authorized: false` |
| Workflows at HEAD | `ci`, `m2b/m3a/m3b/m3c/m3d-replay` — none grants `contents: write`; none contacts Coinbase |
| Existing M3E branch / package / artifacts | none |

The accepted prospective cohort is the **only** thing M3E may grow, and it may
grow it only by **proposing** (never applying) a strictly append-only extension.

---

## 2. What M3E is, and what it must never be

### 2.1 Purpose

Let the accepted prospective ETH-USD daily cohort grow over time through update
proposals that are:

1. **Triggered** only by a trusted schedule or manual dispatch (never by
   untrusted PR content).
2. **Anchored** on the *verified* accepted base state (the M3D manifest, segment
   chain, canonical fingerprint, and byte-empty ledgers).
3. **Mechanically planned**: the first missing candle open is derived from the
   accepted base; the window covers only **fully completed** UTC days (the
   forming candle is always excluded).
4. **Independently attested**: the same new window is fetched on **two isolated
   runners**; each is strictly validated; the proposal proceeds only if the two
   runners produce **byte-identical canonical content**.
5. **Assembled offline** into an **append-only** update (the accepted rows are a
   byte-identical prefix; only new completed days are appended).
6. **Verified** old→new by a whole-proposal graph verifier before anything is
   published.
7. **Proposed as a DRAFT pull request** onto a **new, uniquely-named** proposal
   branch, whose CI **replays the complete proposed cohort**.
8. **Left for HUMAN REVIEW** — never auto-merged, never undrafted, never
   auto-applied to the accepted branch.

### 2.2 M3E must NEVER (absolute prohibitions — preserved verbatim in spirit)

M3E must never, in any code path, workflow, test, fixture, or document:

- evaluate any strategy; create a strategy or candidate; calculate a signal,
  weight, position, fill, fee, turnover, return, P&L, equity, drawdown, CAGR,
  Sharpe, Sortino, PSR, bootstrap, ranking, promotion rule, or investment
  conclusion; or move money;
- directly mutate an accepted branch; auto-merge; enable GitHub auto-merge;
  undraft or merge PR #6, PR #7, or the M3E PR; retarget any PR;
- access the development gate or the final holdout; authorize evaluation; append
  any evaluation or sealed-access ledger;
- re-execute M3A/M3B/M3C; create M3A run-004 / M3B run-002 / M3C run-002;
- modify accepted M2B/M3A/M3B/M3C artifacts; rewrite any accepted M3D raw,
  receipt, segment, chain, quality, or manifest byte;
- push to `main` or any accepted `claude/*` branch; create a non-draft update
  PR; use `pull_request_target`; run untrusted PR code in a write-permission job;
- use a PAT, deploy key, exchange credential, API key, wallet, or secret; add an
  exchange SDK or a Python network client; follow a redirect to another host;
- force-push, amend, rebase, reset; create a tag or GitHub Release; delete a
  branch (other than an ephemeral disposable test repo created and destroyed
  entirely within a test).

The final M3E code remains research-only and **cannot move money**: it computes
no order, holds no key, and opens no exchange connection.

---

## 3. The accepted base is trusted; everything else is not

M3E is a **zero-trust** data-PR facility. Its trust boundary is explicit:

- **Trusted**: the committed accepted base at the M3D HEAD (manifest, segment
  chain, receipts, raw bytes, byte-empty ledgers), the committed M3E code and
  plan, and the trusted trigger (schedule / manual dispatch on the repository's
  own branch).
- **Untrusted**: any bytes returned from the network; any bytes on a proposal
  branch or in a proposal PR; anything a second party could influence.

Consequences enforced throughout:

1. Network bytes are handled **only** by a hardened read-only `curl` boundary in
   the workflow and are re-derived byte-for-byte by an **offline** Python runner
   that never opens a socket (repo hygiene forbids `urllib`/`http`/`socket`/
   `ssl`/`requests`/`aiohttp` imports across `src`, `tests`, `examples`).
2. A proposal is **assembled and verified before it is published**; the accepted
   prefix is proven byte-identical; only strictly-later completed days are
   appended.
3. The PR-verification workflow that runs against untrusted proposal content is
   **read-only** (`contents: read`) and never runs untrusted code in a
   write-permission job; it never uses `pull_request_target`.
4. No workflow ever writes to a protected/accepted branch, enables auto-merge,
   or creates a non-draft update PR.

---

## 4. Trust-separated workflow architecture (why the write path is retired at HEAD)

The immediately-prior milestone (M3D) established, in this same repository, that
its terminal invariant `verify_m3d_program` check 25 — *no workflow at HEAD may
grant `contents: write` or contact a Coinbase host* — is enforced against the
current tree, including any workflow M3E adds. That check, and the M3D
adversarial tests that pin it, are **accepted M3D artifacts M3E must not weaken**.

M3E therefore keeps `verify_m3d_program` **byte-identical and green** by
splitting the update pipeline along the trust boundary and mirroring M3D's proven
*retire-at-HEAD* pattern for the single privileged action:

### 4.1 Standing workflows at the final HEAD (all `contents: read`, none contacts a Coinbase host in YAML text)

- **`m3e-prospective-update.yml`** — `schedule` (Mondays `17 2 * * 1`, 02:17 UTC)
  + `workflow_dispatch`. `permissions: contents: read`. It (a) verifies the
  accepted base, (b) mechanically computes the completed-day cutoff, (c) if a new
  completed day is due, fetches the new window on **two isolated runner jobs**
  via a hardened `curl` step whose endpoint is read from the committed protocol
  JSON (so the workflow YAML contains **no literal Coinbase host**, exactly as
  M3D's acquire workflow did), (d) validates each runner offline, (e) requires
  canonical content equality, (f) assembles the append-only proposal bundle
  offline, (g) runs the whole-proposal verifier, and (h) **uploads the verified
  proposal bundle and a human-review instruction as a workflow artifact**. It
  performs **no `git push`, creates no branch, and opens no PR** — hence "NO push
  at final HEAD." On the stacked feature branch a `schedule:` trigger is inert
  (only default-branch schedules fire), so the facility is literally *ready, not
  active*.
- **`m3e-update-pr-check.yml`** — the read-only verifier for a proposal PR.
  `permissions: contents: read`, `pull-requests: read`. On a PR touching proposal
  artifacts it checks out the proposal, **replays the complete proposed cohort**,
  verifies the old→new transition and the proposal bundle, and asserts the PR is a
  **draft**, append-only, human-review-required, and not auto-mergeable. It never
  writes and never runs untrusted code with write permission; it never uses
  `pull_request_target`.
- **`m3e-replay.yml`** — offline byte-exact replay of every M3E fixture/registry
  artifact on CPython 3.12.3 (authoritative) + 3.12 + 3.13, with the three ledgers
  byte-empty before and after and no tracked-file mutation.

None of these grants `contents: write`; none contains a literal Coinbase host in
its YAML. So `verify_m3d_program` check 25 stays green, and M3E's own
`verify_m3e_program` re-asserts the same and more.

### 4.2 The single privileged action, proven then retired

Creating the proposal **branch** and opening the **draft PR** is the only step
that needs `contents: write` + `pull-requests: write`. Per the zero-trust design
it is deliberately **not wired to run unattended** at the final HEAD. It is:

1. **Proven end-to-end offline** by a disposable-repo publisher rehearsal
   (§ commit 13): with **synthetic** new candles, the full lifecycle
   derive→two-runner→compare→assemble→verify→branch→**draft-PR shape** runs in a
   throwaway `git` repository created and destroyed inside the test.
2. **Proven live, fail-safe** by a temporary *audit-mode* bootstrap (§ commits
   16–17): a push-sentinel trigger runs the standing `m3e-prospective-update.yml`
   live through GitHub Actions at today's date; it verifies the base, computes the
   cutoff, and — because **no new completed day is available yet** (see §6) —
   correctly determines a **no-op** and produces **no proposal, no branch, no
   PR**. That is the honest, safe live outcome the facility must exhibit when
   nothing is due, and it is recorded as the milestone's live evidence.
3. **Retired** (§ commit 18): the temporary bootstrap sentinel is deleted, and
   the exact, reviewed definition of the write-capable branch/PR step is preserved
   as a **committed, non-executing template** under `research/m3e/` (outside
   `.github/workflows/`, so it neither runs nor is scanned by check 25), together
   with a written activation procedure requiring a **separate human-reviewed
   commit on the default branch** to enable it.

This is the precise meaning of the terminal verdict **"READY, NOT ACTIVE"**: the
attestation-and-assembly automation is standing and proven; the one privileged
publish action is proven and preserved but intentionally dormant.

---

## 5. Version and package isolation

- Freeze the immediately-prior milestone: change `eth_research.m3d`'s
  `M3D_PACKAGE_VERSION` from the **live** package version to the frozen literal
  `"0.7.0"`. This is **replay-neutral** — the M3D artifacts already stamp
  `0.7.0`, so every M3D artifact rebuilds byte-for-byte and `m3d-replay` stays
  green. It follows the established precedent (`M3C_PACKAGE_VERSION = "0.6.0"`,
  etc.): a completed milestone pins its own version once a later milestone bumps
  the running package.
- Bump the running package to **`0.8.0`** (`pyproject.toml`,
  `eth_research.__version__`, `uv.lock`); update `tests/test_version.py` to assert
  `0.8.0` and that M3D stays frozen at `0.7.0`.
- New code lives in an isolated **`src/eth_research/m3e/`** package that uses the
  live version (`M3E_PACKAGE_VERSION = _PACKAGE_VERSION` = `0.8.0`). An AST
  import **allow-list** (mirrored by `tests/test_m3e_architecture.py`) permits
  only strategy-free shared utilities (`eth_research._json`, `._atomic`,
  `.data.*`) and the **data-only / governance-only** M3D modules M3E legitimately
  reads (`eth_research.m3d.validation`, `._upstream`, `.chain`,
  `.acquisition_plan`, `.receipt`, `.raw_bundle`, `.segment`, `.cohort`,
  `.protocol`, `.quality`, `.publication`, `.maturity`). It imports **no** engine,
  strategy, backtest, accounting, metric, promotion-decision, or
  experiment-executor module (there are none to import), and **no** network or
  wallet module.

---

## 6. Mechanical planning: completed-day cutoff and the no-op case

Let `accepted_last_open` be the accepted cohort's last completed open
(`2026-07-14T00:00:00Z`). For an explicit `as_of` UTC (never a wall clock inside
the library):

- `completed_day_cutoff = floor_to_midnight(as_of)` — the first UTC midnight at
  or before `as_of`; the candle opening at `cutoff` is still **forming** and is
  always excluded.
- `first_missing_open = accepted_last_open + 1 day`.
- The proposed new window is the half-open `[first_missing_open, cutoff)`.
- If `first_missing_open >= cutoff` the window is **empty** → **NO-OP**: nothing
  is due, and the facility must produce no proposal.

At **today's date (2026-07-15)**: `cutoff = 2026-07-15T00:00:00Z`, the last
completed open is `2026-07-14`, and `first_missing_open = 2026-07-15 = cutoff`, so
the window is empty and the correct outcome is a **no-op**. The prospective cohort
is not due to grow until the `2026-07-15` candle completes at `2026-07-16T00:00:00Z`.
The live audit-mode rehearsal (§4.2) therefore legitimately exercises the pipeline
to a no-op — it fabricates no market data and proposes nothing.

The **positive** path (a real new completed day → a compliant draft proposal PR)
is proven with **synthetic** candles in the offline disposable-repo E2E and with a
committed **fixture** proposal that `m3e-update-pr-check.yml` verifies — never by
inventing real ETH-USD values.

---

## 7. Module design (`src/eth_research/m3e/`)

Every model shares the M3D strict-validation surface (canonical JSON, domain
hashing, hash-chained JSONL, strict field validators) via a thin
`m3e/validation.py` re-export, so a value rejected on load can never be produced
on build. All artifacts stamp `package_version = 0.8.0`.

| Module | Responsibility (commit) |
| --- | --- |
| `__init__.py` | Package doc; `M3E_PACKAGE_VERSION = _PACKAGE_VERSION` (2) |
| `validation.py` | Re-export of the M3D strict-validation surface (2) |
| `accepted_base.py` | `AcceptedProspectiveBase` — verify + bind the accepted M3D cohort (manifest, segment chain, canonical fingerprint, three byte-empty ledgers, immature/unauthorized) as the trusted input; `build`/`verify` (3) |
| `cutoff.py` | `CompletedDayCutoff` + `plan_update_window` — mechanical first-missing/cutoff derivation and the no-op decision (4) |
| `update_plan.py` | `ProspectiveUpdatePlan` — append-only window plan derived from (base fingerprint, cutoff); `plan_sha256`, deterministic `idempotency_key`; strict loader (5) |
| `lease.py` | `ProposalLease` + `proposal_branch_name` — deterministic, uniquely-named proposal branch keyed to the idempotency key; concurrency guard so overlapping runs cannot duplicate a proposal (6) |
| `acquisition.py` | Two-runner strict validators — per-runner window fetch validated offline (schema, half-open window bounds, completed-day, contiguity, receipt SHA-256 binding) reusing the reviewed M2B adapter (7) |
| `runner_boundary.py` | Workflow-artifact ↔ offline-runner boundary: parse the per-runner staged raw + status sidecar, bind to the update plan, never trust a value not re-derived from bytes (8) |
| `comparison.py` | `AcquisitionComparison` — require **byte-identical canonical content** between the two isolated runners; record distinct runner identities (9) |
| `transition.py` | `ProspectiveUpdateTransition` — old→new append-only extension: accepted prefix byte-identical, only completed new days appended, one-interval contiguity across the seam, no reorder/gap/overlap/rewrite (10) |
| `proposal.py` | Proposal bundle model + `build_update_proposal_bytes` / registry entry (11) |
| `verify_m3e_program.py` | `verify_update_proposal` — the un-skippable **35-check** whole-proposal graph verifier (11) |
| `assembly.py` | Transactional offline assembly of the proposal bundle with readback+reparse+rehash and rollback (12) |
| `publisher.py` | Disposable-repo end-to-end publisher rehearsal (offline; synthetic candles) (13) |
| `review_policy.py` | `ReviewPolicy` — draft-only, human-review-required, no-auto-merge, no-retarget, append-only invariants as data + guard API (19) |
| `registry.py` | `research/m3e/proposal_registry.jsonl` — append-only, hash-chained record of proposals (audit-mode + fixtures), leaking no OHLCV (19) |
| `status.py` / `replay.py` | Data-only status CLI (no OHLCV/return/metric leak) and byte-exact offline `replay --check/--deep` (20) |
| `acquire_runner.py` | Offline runner: `emit-plan` (fixed per-window request params for the workflow `curl`) + `verify` (strict offline validation → per-runner receipt); never opens a socket (7–8) |

The 35 verifier checks (indicative graph): accepted-base identity & three empty
ledgers; base fingerprint `bb6dd392…`; cutoff correctness & completed-day rule;
update-plan determinism & idempotency; two-runner presence, isolation & receipt
binding; canonical-equality of the two runners; append-only prefix identity;
one-interval seam contiguity; no reorder/gap/overlap; strict schema/UTC/finite
OHLCV; proposal-bundle rebuild & completeness marker; registry hash-chain; review
policy (draft, human-required, no auto-merge, no retarget); no evaluation
artifact/field (key **or** value) anywhere in the proposal; M3C candidate still
rejected; no accepted M2B/M3A/M3B/M3C/M3D byte changed; no workflow grants
`contents: write` or contacts Coinbase in YAML; no secret/PAT/force-push/
`pull_request_target`/auto-merge in any workflow; allow-listed imports only; no
socket/wallet import. The exact list is fixed in code and pinned by tests.

---

## 8. Commit sequence (append-only; no amend/rebase/force; fast-forward pushes only)

1. `docs/M3E_PLAN.md` alone (this document).
2. Version `0.8.0` + freeze M3D to `0.7.0` + `m3e` package boundary & AST
   allow-list + architecture test.
3. `AcceptedProspectiveBase` model (build/verify) + tests.
4. `CompletedDayCutoff` + no-op planner + tests.
5. `ProspectiveUpdatePlan` + idempotency + strict loader + tests.
6. `ProposalLease` + concurrency + deterministic proposal branch naming + tests.
7. Two-runner acquisition validators + offline `acquire_runner` + tests.
8. Workflow-artifact ↔ offline-runner boundary + tests.
9. `AcquisitionComparison` (canonical content equality) + tests.
10. `ProspectiveUpdateTransition` (old→new append-only) + tests.
11. Proposal bundle + `verify_update_proposal` (35 checks) + tests.
12. Transactional offline assembly with rollback + failure-injection tests.
13. Disposable-repo publisher E2E (offline, synthetic) + committed fixture proposal.
14. Standing workflow definitions (`m3e-prospective-update.yml`,
    `m3e-update-pr-check.yml`).
15. Workflow-security tests (no write / no Coinbase host / no secret / no force /
    no `pull_request_target` / no auto-merge; two isolated runner jobs; draft-only).
16. Audit-mode bootstrap trigger (temporary push sentinel).
17. Live audit-mode evidence (Actions run → no-op; recorded).
18. Trigger retirement (delete sentinel; preserve non-executing write-step
    template + activation procedure under `research/m3e/`).
19. Review policy + append-only proposal registry.
20. Status + replay CLIs.
21. `m3e-replay.yml` CI (3.12.3 / 3.12 / 3.13).
22. Standing adversarial suite (fail-closed on every tamper/contamination class).
23. Three independent read-only red teams + fixes (`docs/M3E_FINDINGS.md`).
24. Findings + documentation.
25. Terminal acceptance audit.
26. Final CI-only fixes.

Every commit footer:

```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0171EQbwzECfi8xxrek2gBj8
```

---

## 9. Definition of done

- The full local gate is green: `ruff check .`, `ruff format --check .`,
  `mypy src tests examples`, `uv lock --check`, `pytest`.
- `verify_m3d_program` still returns 25/25 and every M2B/M3A/M3B/M3C/M3D artifact
  is byte-identical; the three ledgers are byte-empty before and after.
- `verify_m3e_program` returns its full 35-check chain on the committed fixture
  proposal; `m3e replay --deep` rebuilds every M3E artifact byte-exact with no
  socket and no tracked mutation on 3.12.3 / 3.12 / 3.13.
- CI + all six prior replay workflows + `m3e-replay` are green at the final HEAD;
  no workflow grants `contents: write` or contacts a Coinbase host.
- A **draft, stacked** PR is opened (base
  `claude/m3d-prospective-evidence-governance`, head
  `claude/m3e-review-only-prospective-updates`) and **kept draft**; PR #6 and
  PR #7 are untouched.
- The terminal verdict is delivered:

  > **MILESTONE 3E COMPLETE — REVIEW-ONLY UPDATE AUTOMATION READY, NOT ACTIVE, NO
  > STRATEGY EVALUATED.**
