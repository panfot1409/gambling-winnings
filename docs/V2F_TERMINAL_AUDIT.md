# V2F terminal audit

Every claim here is bound to something executed or queried on 2026-07-31. Where a required check
could not run, it is recorded as **NOT RUN** or **UNVERIFIABLE**, never as passed. §21 of the
directive and the standing correction *"a skipped or unavailable verification is never reported as
passed"* both require that, and there are three such items in this audit.

---

## 1. Terminal verdict

**§25 class E — implementation and acceptance complete; owner-only controls required.**

```
V2F IMPLEMENTATION AND ACCEPTANCE COMPLETE — OWNER-ONLY CONTROL REQUIRED BEFORE MERGE OR
ZERO-CAPITAL PAPER ACTIVATION; ONE-SHOT/PAPER STATE REPORTED EXACTLY; ALL SEALED PARTITIONS
UNTOUCHED; V2 NOT SELL-READY.
```

Class D (hard stop) also describes the research half accurately, and the two are not in conflict:
the one-shot is blocked by an external-rights gate, and the merge and activation are blocked by
owner-only controls. E is returned because it is the one that names an action the owner can take.

## 2. Scientific outcome

**The candidate was not evaluated.** Not qualified, not rejected — a third state, which must not
be relabelled as either. `one_shot_spent: false` in all three preregistration records, and no file
under `research/` names `adaptive_expert_mixer` at all.

Partition verdict: **`EXTERNAL_RIGHTS_REQUIRED`** (`docs/V2F_RESEARCH_PARTITION_VERDICT.md`).

## 3. Commit map — 12 commits, `220ff47a..`

| SHA | what |
| --- | --- |
| `d1f2f80` | paper activation decided by exact required-gate set, not a vacuous `all()` |
| `e122df2` | no lawful unconsumed partition; one-shot not spent |
| `e80cb6b` | second independent closure record for the same partitions |
| `7c3d422` | path confinement in the independent verifier; two audit findings |
| `6dc405e` | `adaptive_expert_mixer_v1` built and preregistered; not evaluated |
| `d18fc89` | reported paper state stopped outrunning its own requirements (V2F-EC-003) |
| `e6fc519` | kill switch + monitoring qualified — last two implementation gates closed |
| `0a3f6b5` | two dashboard claims bound to the derivation that supports them |
| `93cd76b` | two pre-freeze semantic findings recorded (MSF-1, MSF-2) |
| `827fccd` | MSF-1 fixed; preregistration superseded append-only to v2 |
| `642564b` | partition verdict issued |
| `3813060` | visibility re-observed, second exposure recorded, host-dependent tests fixed |
| `db72245` | binary-vs-convex frozen; degenerate matrix; v3 supersession |

## 4. Candidate constitution — reconciled

§4 anticipated a conflict between a six-expert fixed-share design and the implemented four-expert
Hedge. **That conflict does not exist in this repository.** A tracked-tree search returns zero
matches for `fixed-share`, `six expert`, or those horizons as expert parameters — the single `168`
hit is a coincidental substring inside a SHA-256 digest. Exactly one candidate specification has
ever been committed.

The real ambiguity was different and is now closed: the docstring described a binary majority vote
in one paragraph and argued long-only/unlevered from `mixture_weight ∈ [0,1]` in another, which
reads as a convex allocation. Frozen to one reading — **the traded value is binary** — and proven
by execution: over random paths the value reaching the engine takes exactly `{0.0, 1.0}`, while
`mixture_weight` genuinely takes intermediate values, so the distinction is real rather than
vacuous.

## 5. Supersession chain — append-only, each link re-hashed by test

| v | sha256 | fingerprint | why |
| --- | --- | --- | --- |
| 1 | `cb7462c7…` | `7608e9c9…` | original |
| 2 | `a4b7a8d0…` | `f6bbcb8d…` | MSF-1 code fix, MSF-2 claim withdrawal — fingerprint **moved**, the algorithm changed |
| 3 | *(active)* | `f6bbcb8d…` | documentation-only — fingerprint **unchanged**, and the contrast is the evidence |

v3's doc-only claim is proven, not asserted: 25 seeded paths × 500 bars, sha256 over every
`(weights, exposures, mixture_weight, decision)` tuple — `a3fdb82915bf2d9e…` before and after.

## 6. Degenerate-case matrix — executed, no defect found

| case | behaviour |
| --- | --- |
| exact-half tie | resolves **flat** via strict `>`, deterministically |
| zero / negative-zero return | charges nobody |
| duplicate bar | zero return, no weight moves |
| all-equal pool | weights stay exactly uniform |
| all-wrong pool | weights stay exactly uniform — the honest face of the *relative* guarantee |
| NaN / ±Inf / zero / negative close | each refused with a distinct message |
| control | a clean path is still accepted, so the refusals are not vacuous |

## 7. Activation matrix — 6 of 17

`True`: `fable5_acceptance`, `no_unresolved_class_abd_defect`, `kill_switch_qualified`,
`monitoring_qualified`, `sealed_ledgers_intact`, `repository_private`.

Nine of the eleven `False` values are one fact wearing nine names — no one-shot has nominated a
candidate. `human_approval_artifact` is the owner's signature, correctly absent.
`paper_release_source_freeze` requires a release that cannot exist for an unevaluated candidate.

Resting state `disabled`; `all_satisfied False`; no activation token has ever been minted.

## 8. Integrity — measured, not asserted

```
research/m2b/test_evaluations.jsonl            0 bytes  e3b0c442…b7852b855
research/m3a/development_gate_access.jsonl     0 bytes  e3b0c442…b7852b855
research/m3d/prospective_evaluations.jsonl     0 bytes  e3b0c442…b7852b855
```
All three regular files, not symlinks, zero events — `e3b0c442…` is the SHA-256 of the empty
string.

```
fable5 verify              ok — 13 checks
fable5 freeze-verify       ok —  4 checks
m3f_independent_verify.py  OK: 8 checks, 0 failures
v2f_containment_gate.py    REFUSED, exit 1
```

## 9. Security sweep

**Full-history secret scan.** 34,731,443 bytes across **every git object** (2,408 blobs, including
unreachable ones). Four matches, all four provably synthetic negative-test fixtures: a PEM whose
body is literally `AAAA`, a bare PEM header with no body, `AKIAABCDEFGHIJKLMNOP` (the alphabet),
and a doc that already documents the other two. **No real credential exists in any git object.**

**Prohibited-capability proof — AST, not grep.** A token grep flagged `ccxt`, `web3`,
`eth_account`, `binance`, `httpx`, `aiohttp`, `websocket`. Every one is a string inside the
project's *own deny-lists* (`_NETWORK_CLIENTS`, `_PROHIBITED_NETWORK_PREFIXES`) or a redaction
regex — a token grep over a security codebase always hits the names of the things it defends
against. Parsing all 349 source files as ASTs and inspecting actual `Import`/`ImportFrom` nodes
yields **exactly one** banned-root import: `http.server` in the dashboard, which is a local server,
not a network client.

**Dashboard.** Default bind `127.0.0.1`; `0.0.0.0` appears nowhere; non-loopback requires
`allow_lan=True`; `POST`/`PUT`/`PATCH`/`DELETE` all route to `_refuse_mutation`; `HEAD` delegates
to `GET`. 24 security tests pass.

**Containment.** No acquisition workflow file exists on HEAD or on `main` — retired, not merely
disabled. GitHub still lists `M2B Acquire` / `M3D Acquire` / `V2B Acquire` as `active`, which is a
stale server-side record for a deleted file; a workflow absent from the default branch cannot
trigger. No `schedule:` trigger exists anywhere. M3E prospective update is `workflow_dispatch`-only
**and** `disabled_manually`.

## 10. Data-rights statement

Coinbase ETH-USD daily candles remain classified
`internal_research_only_pending_written_redistribution_permission`. Containment is `active: true`
because the redistribution question is **open**. Nothing in this branch distributes, packages, or
publicly displays that data.

**Two public-exposure windows are on record**, the second of which occurred during this work:
~2026-07-29T22:36Z → 2026-07-31T16:06:02Z, opened deliberately to obtain free Actions minutes.
`forks_count` was 0 at close. Privacy restoration does not recall clones, caches or mirrors, and
does not decide the rights question.

## 11. §21 battery — local, clean tree, both interpreters

Run on a clean working tree after all edits, so no result is contaminated by a mid-run change.
(An earlier run was: five `test_readiness.py` failures appeared purely because I edited governed
artifacts while it was executing, and vanished on re-run. That is why this one was run last.)

| | results | passed | skipped | failed | errors |
| --- | --- | --- | --- | --- | --- |
| **CPython 3.12.3** (authoritative) | 4227 | 4208 | 19 | **0** | **0** |
| **CPython 3.13.14** (compatibility) | 4227 | 4160 | 67 | **0** | **0** |

The 48 additional skips on 3.13 are deliberate runtime pins, each with an explicit reason —
*"the integrity-ready state requires the authoritative CPython runtime"* (whose invariant the file
asserts separately) and *"argparse help text is pinned to CPython 3.12"*. Not silent coverage loss.

```
ruff check          clean
ruff format         658 files already formatted
mypy --strict       Success: no issues found in 655 source files
uv lock --check     Resolved 21 packages
git diff --check    clean
```

## 12. NOT RUN / UNVERIFIABLE — the three honest gaps

1. **Exact-SHA CI — NOT RUN, and cannot be.** Every job in this repository since 2026-07-29T04:31Z
   has completed in under ten seconds with `runner_name ""` and `steps []`. Runs created while the
   repository was **public** failed identically, which is the proof the cause is account-level and
   visibility-independent — public repositories get unmetered runners, so a minutes quota cannot
   explain a public-repo job failing to schedule. Billing endpoints need the `user` OAuth scope and
   return 404/403. **The battery in this audit is local only.**
2. **Adversarial refutation — NOT RUN.** 9 of 13 red-team agents died on an account spend limit,
   including every refuter and the synthesizer. MSF-1 and MSF-2 are my own independent
   reproductions; they never faced an agent whose job was to kill them.
3. **Independently-authored second implementation — DOES NOT EXIST.** The in-module scalar oracle
   agrees with the vectorized path, but same author, same session, same assumptions.

Also open: the 0/1 loss is computed **gross**, so turnover is invisible to the selector (MSF-2,
unchanged).

## 13. Prohibited-action confirmation

Not done, at any point: live capital; broker or exchange order; wallet, key, or signing; order
route; sealed-partition access; consumed-partition reuse; re-evaluation of a rejected candidate;
post-result parameter change; one-shot registration or spend; paper activation; backfill; public
deployment; package publication; LICENSE addition; tag; release; force-push, rebase, amend, reset,
squash, or history rewrite; branch deletion.

`sell_ready` is false. `validated_live` is false. `meaningful_track_record` is false.

## 14. Exact owner actions

1. **GitHub Actions.** Determine why jobs are not scheduling — spending limit, payment method, or
   account-level suspension — at github.com/settings/billing. Not readable with the current token
   scopes. Until then no CI evidence can exist for any SHA. *(Note: making the repository public
   does not fix this. It was tried, and did not.)*
2. **Branch protection.** Both endpoints return 403 *"Upgrade to GitHub Pro or make this repository
   public."* On a free plan with a private repository this is unpurchasable without upgrading. §17
   and §23 both require it, so **PR #25 must not be merged** until it exists. It was not weakened.
3. **Spend limit**, if the refutation stage is to run.
4. **Third-party market-data rights assessment** — the only thing that can unblock the one-shot.
   No amount of engineering substitutes for it.

## 15. Criteria for a future forward record

None of this begins until 1–4 above are resolved **and** a lawful partition exists. Then, in order:
preregister against that partition → freeze E → register R once → execute P once → reconstruct Q
independently → mechanical verdict. Only if it qualifies: paper-release freeze, activation with
every gate derived true, and a first cycle at the first settled bar **strictly after** activation.

`sell_ready` stays false through all of it, until a meaningful forward record exists and separate
commercial and legal acceptance is completed. A newly started paper record is not proof of edge.
