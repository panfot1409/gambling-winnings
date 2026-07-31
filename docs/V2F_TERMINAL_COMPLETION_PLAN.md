# V2F terminal completion — live preflight and execution program

Every value below was measured on 2026-07-31 from the live checkout and the live GitHub API, not
inherited from the directive text or from an earlier handoff. Where a fact could not be measured,
it is recorded as **UNVERIFIABLE** rather than assumed.

---

## §1 live preflight — measured facts

### Environment change since the last session

Work moved from a Linux container to the owner's own workstation (`Darwin 25.5.0`, arm64,
`/Users/pp/Projects/gambling-winnings`). Two consequences matter:

* The GitHub MCP server disconnected. Live GitHub state is now read through the authenticated
  `gh` CLI (2.95.0, account `panfot1409`, scopes `gist, read:org, repo`) instead. Capability is
  restored, with one gap: billing endpoints need the `user` scope and return 404/403.
* The system Python is CPython **3.12.3** — the authoritative runtime the project requires. A
  fresh `.venv` was built from it with `uv`; `eth_research 2.0.0.dev2` imports.

| # | fact | measured value |
| --- | --- | --- |
| 1 | local branch / HEAD | `claude/v2f-adaptive-selector-paper` @ `642564beb7362364d868224394618e82e025be10` |
| 2 | remote branch SHA | `642564b` — identical, no divergence |
| 3 | `origin/main` | `220ff47a5a7edb2199bd31650e743ecdeffc54fe` |
| 4 | merge base with `main` | `220ff47a` — branch is a clean linear descendant, 11 ahead, 0 behind |
| 5 | working tree | clean; 0 porcelain lines |
| 6 | V2F PR | **none exists.** Open: #22 (draft, `bot/m3e-prospective-update/…` → main). #13–#21, #23, #24 merged |
| 7 | repository | **private**, `visibility: private`, `forks_count: 0`, default `main`, not archived, 1 star / 1 watcher |
| 8 | branch protection on `main` | **UNAVAILABLE — HTTP 403** `"Upgrade to GitHub Pro or make this repository public to enable this feature."` Rulesets: same 403 |
| 9 | M3E prospective workflow | `disabled_manually`; file present with **`workflow_dispatch` only**, no `schedule:` |
| 10 | write-capable workflows | none. `fable5 verify` asserts `no_workflow_write_permission`, `no_workflow_secret`, `no_unpinned_action` |
| 11 | three sealed ledgers | all **0 bytes**, regular files, not symlinks, 0 events, `sha256 = e3b0c442…b7852b855` (the empty-string digest) |
| 12 | V2F one-shot | **UNSPENT.** No file under `research/` names `adaptive_expert_mixer` at all |
| 13 | V2F governance artifacts | `containment.json` (active), `repository_visibility.json`, preregistration v1 + v2 |
| 14 | CI on HEAD `642564b` | **FAILURE** — see below |
| 15 | bot / proposal branches | 2 `bot/m3e-prospective-update/*` remote branches; PR #22 open draft |
| 16 | version / runtime | `2.0.0.dev2`, `requires-python >=3.12`, local venv CPython 3.12.3 |
| 17 | tags / releases | tag `v0.1.0` only; release `v0.1.0` only. No v0.9.0/v1.0.0/v1.1.0 — the known tag debt |
| 18 | public-exposure posture | **second exposure window opened and closed since the last session** — see below |

### Scale

349 source modules, 298 test files.

---

## Finding P-1 — GitHub Actions is unavailable account-wide, and making the repository public did not fix it

This is the most consequential preflight finding, because it invalidates the reason the repository
was made public.

Timeline, measured from `gh run list` and the jobs API:

| when | what | result |
| --- | --- | --- |
| 2026-07-29T04:31Z | last successful run anywhere in the repo | `success` |
| 2026-07-29T06:05Z, 06:12Z, 16:50Z | pushes while **private** | `startup_failure`, zero jobs created, `path: "BuildFailed"` |
| 2026-07-29T22:37Z, 22:38Z | pushes while **public** (`827fccd`, `642564b`) | runs created, **every job `failure`** |

The public-repo jobs are the decisive evidence. Sampling them:

```
checks (3.12)          started 22:38:59Z  completed 22:39:08Z  runner_name ""  steps []
independent-verifier   started 22:37:52Z  completed 22:37:56Z  runner_name ""  steps []
```

Nine seconds, **no runner assigned, zero steps executed**. Nothing in this repository failed. The
jobs were never scheduled onto a machine.

Public repositories get unmetered GitHub-hosted runners, so a minutes quota cannot explain a
public-repo job failing to schedule. The failure is therefore **account-level and
visibility-independent**: it predates the visibility change (04:31Z, while private) and survived
it. Going public changed only the symptom — `startup_failure` (no run records) became `failure`
(run records, unschedulable jobs).

**The exposure bought nothing.** It cost a second public window over third-party data whose
redistribution rights are unresolved, and returned no CI.

The billing API needs the `user` OAuth scope and is unreadable with the current token, so the
precise cause — spending limit, payment method, or account-level Actions suspension — is
**UNVERIFIABLE from here** and is an owner action.

---

## Finding P-2 — a second public-exposure window occurred and is now recorded

`governance/v2f/repository_visibility.json` carried a single observation dated 2026-07-28T11:33:55Z
reading `observed_private: true`. That observation predates a real exposure it did not describe:

* **Window 2 opened** ~2026-07-29T22:36Z when the owner made the repository public for Actions.
* **Window 2 closed** 2026-07-31T16:06:02Z (repository `updated_at`); re-observed private at 16:20Z.
* `forks_count` was 0 at close and no fork event is recorded.

The record has been re-observed and replaced, per its own instruction ("Re-observe and replace this
file whenever visibility changes"), and now carries a two-window `exposure_history`. The gate still
derives `repository_private = True`, because the repository **is** private now — but it now derives
that from a current observation rather than a stale one that happened to agree.

Nothing was falsified to keep the gate green. Had the repository still been public, this file would
say so and the gate would derive `False`.

**What privacy restoration does not do:** it does not recall clones, caches, scrapes or mirrors
made during either window, and it does not resolve the Coinbase redistribution question. That is
why `governance/v2f/containment.json` stays `active: true`.

---

## Finding P-3 — branch protection is not merely absent, it is unpurchasable on this plan

`GET /repos/…/branches/main/protection` and `GET /repos/…/rulesets` both return:

> HTTP 403 — *"Upgrade to GitHub Pro or make this repository public to enable this feature."*

This is not a configuration the owner forgot. On a **free account with a private repository**,
branch protection and rulesets are unavailable. The two ways to obtain them are mutually
exclusive with the current posture:

1. Upgrade the account to GitHub Pro (keeps the repository private), or
2. Make the repository public — which §1 of the directive names as a containment trigger, and
   which Finding P-1 shows does not even deliver the CI it was traded for.

§17 requires "main branch protection/ruleset is active" before paper activation, and §23 requires
"Confirm branch protection/ruleset is active" before merge. **Both requirements are currently
unsatisfiable without an owner purchasing decision.** The directive is explicit that I must not
weaken this: *"If branch protection is owner-only and not configured, finish all implementation
and stop before activation/merge with one exact owner action. Do not weaken the requirement
because the branch is currently unprotected."*

---

## Containment posture — verified, layered, holding

| control | measured state |
| --- | --- |
| acquisition workflow files | **absent from HEAD and from `origin/main`** — retired, not merely disabled. GitHub still lists `M2B Acquire`, `M3D Acquire`, `V2B Acquire` as `active`, but that is a stale server-side record for a deleted file; a workflow whose file is absent from the default branch cannot trigger |
| any `schedule:` trigger | **none in any workflow.** The only match in the tree is a comment in `m3e-prospective-update.yml` explaining that the cron was removed rather than commented out |
| M3E prospective update | `workflow_dispatch` only **and** `disabled_manually` — two independent controls |
| V2F containment gate | `tools/v2f_containment_gate.py` → `REFUSED`, **exit code 1** (verified directly, not through a pipe) |
| sealed ledgers | 3/3 byte-empty, re-checked by `fable5 verify` on every run |

Verifiers, all green at `642564b`:

```
fable5 verify        ok — 13 checks
fable5 freeze-verify ok —  4 checks
m3f_independent_verify.py  OK: 8 checks, 0 failures
```

---

## Derived state at `642564b` — 6 of 17

```
True   fable5_acceptance                 False  eligible_nominated_candidate
True   no_unresolved_class_abd_defect    False  immutable_candidate_fingerprint
True   kill_switch_qualified             False  valid_lineage
True   monitoring_qualified              False  candidate_not_previously_rejected
True   sealed_ledgers_intact             False  paper_protocol_preregistered
True   repository_private                False  risk_parameters_frozen
                                         False  data_feed_configuration_frozen
resting state: disabled                  False  cost_model_frozen
all_satisfied: False                     False  execution_simulator_frozen
                                         False  paper_release_source_freeze
                                         False  human_approval_artifact
```

Nine of the eleven false values are one fact wearing nine names: no one-shot has nominated a
candidate. `human_approval_artifact` is the owner's activation signature, correctly absent.

---

## The governing constraint: §7 partition verdict

`docs/V2F_RESEARCH_PARTITION_VERDICT.md` issues **`EXTERNAL_RIGHTS_REQUIRED`**, bound to live
artifacts: `research_train_exhaustion.json` reads `exhausted_for_new_candidate_research`;
`research_partition_closure.json` forbids `evaluate_new_candidate` **and**
`recombine_and_claim_new_trial` by name, and a mixture over rejected families is precisely the
second; `containment.json` is active because the Coinbase redistribution question is open.

Under §7 and §13 this means **the one-shot must not be registered or spent.** E → R → P → Q is
unreachable, and with it §15 qualification, §16 paper-release freeze, §17 activation, and §18 the
first forward cycle.

---

## Execution program from here

Given three independent blockers — no lawful partition (external/legal), no CI (account), no
branch protection (plan) — the reachable terminal outcome is §25 **D** or **E**, and the work that
remains is everything §26 says is not a terminal state.

**Phase A — honesty of record (this commit).** Re-observed visibility, two-window exposure
history, this plan.

**Phase B — complete the safe implementation surface.** §8 paper platform and §9 dashboard
acceptance, everything that does not require a research result: input boundary, selector state,
simulation-only broker, lifecycle, durable intent/recovery, risk controls, scheduling/concurrency,
observability; dashboard adversarial matrix and runbook.

**Phase C — §19 chaos and failure program** against the disabled paper engine, with synthetic
bars explicitly labelled synthetic and never mixed into any performance record.

**Phase D — §20 security and supply-chain terminal sweep**, extended for the second exposure
window.

**Phase E — §21 complete local battery** on CPython 3.12.3 and 3.13, recording exact-SHA CI as
**UNAVAILABLE — ACCOUNT-LEVEL**, never as passed.

**Phase F — §22 recursive acceptance and §23 draft PR**, stopping short of merge because §23's
branch-protection precondition is unsatisfiable.

**Phase G — terminal verdict** with the exact owner actions.

### Hard stops honoured throughout

No E/R/P. No one-shot registration. No paper activation. No forward paper cycle. No merge without
branch protection. No tag. No release. No LICENSE. No history rewrite. No sealed-partition access.
No synthetic data presented as a performance claim. `sell_ready` stays false.

### What I will not claim

That CI passed. That branch protection exists. That the candidate was evaluated. That the second
exposure was harmless. That privacy restoration undoes distribution.
