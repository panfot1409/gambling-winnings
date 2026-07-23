# V2C Independent Acceptance & Merge-Readiness Audit

Independent acceptance / merge-readiness audit of Milestone V2C (candidate-free offline operational
qualification). Every claim below was **verified, not assumed**, against committed bytes and
production code paths. Six independent read-only auditors, a disposable merge simulation, and a
fresh-clone reconstruction were run. **Result: ACCEPTED for human merge review.** No Class-A
(scientific) or Class-D (sealed/immutable) defect exists; no fix beyond additive standing tests was
required.

## 1. Identity & PR state

| Item | Value |
|------|-------|
| Branch | `claude/v2c-prospective-operations-qualification` |
| Starting HEAD (audited) | `ed0ee06` |
| Final HEAD | the branch tip after this acceptance-docs commit = the current PR #18 head SHA (one commit beyond `e2db958`; recorded concretely in the terminal report and PR #18 status) |
| `main` / `origin/main` | `6e0d60e` (Merge PR #17 = M2) — the exact merge-base; main has not moved |
| PR | #18 — **open, draft, unmerged**, base `main`, head this branch. `mergeable_state` is `clean` once the branch-head CI completes (it reads `unstable` only transiently while checks are still in flight) |
| Version | `2.0.0.dev2` | 
| Runtime | CPython 3.12.3 (authoritative); 3.13.12 (compatibility) |
| Repository | private (`Private :: Do Not Upload`) |

The audit committed only additive artifacts (`docs/V2C_INDEPENDENT_ACCEPTANCE_PLAN.md`, this file,
`tests/test_v2c_oq_acceptance_matrix.py`). HEAD advanced `ed0ee06 → 5e5e26b → e2db958 → (this
acceptance-docs commit)`; every audit commit is additive documentation/tests and touches no governed
artifact, source, or frozen surface. A markdown file cannot contain its own commit hash, so the exact
final-HEAD SHA and the CI run URLs for it are recorded in the accompanying terminal report and in the
live PR #18 status rather than embedded here.

## 2. Commit chronology (origin/main..HEAD)

```
2098fc4 V2C-0: branch from merged main (M2); bump 2.0.0.dev1 -> 2.0.0.dev2
c9f3cd8 V2C 13: freeze the V2C plan
1ac5283 V2C-14: candidate-free execution firewall + cash_control target
4a98dbd..ea6808a  V2C-15..33 governance/platform/commercial/readiness scaffold
1a46bdb V2C section 34: pre-qualification red team fixes
e4b3cc3 V2C section 35 (OQ-E): operational-qualification source freeze   [premature]
7f2ec45 V2C: supersede the premature OQ source freeze (append-only, pre-registration)
a3cce03..8f5b3fd  executable OQ scaffold (registry v2, protocol, orchestrator, runner,
                  archive, deep verifier, oracle, CLIs)
2a9e528 V2C: supplemental pre-freeze red-team hardening (5 auditors, before OQ-E2)
8aa6fd2 V2C: update stale archive test for the tightened completion-intent path check
d0ed4ea V2C: allowlist v2c-replay.yml in the closed workflow-security set
cea86a5 V2C: OQ-E2 replacement source freeze (full transitive surface + evidence set)
f30e284 V2C: OQ-E2A activation anchor binding the OQ-E2 source-freeze commit
f4a7097 V2C: guard the live-qualification OQ tests to CPython 3.12 on compatibility CI
530f182 V2C: execute + independently accept the canonical OQ run (OQ-R/OQ-P/OQ-Q)
a7dee93 V2C: post-run hardening -- prove the committed digests re-derive from the frozen source
8847a51/6f7760e/8925215/ed0ee06  terminal documentation (parts 1-4)
5e5e26b acceptance plan (this audit) ; e2db958 acceptance adversarial matrix (this audit)
```

All commits are authored **and** committed by `Claude <noreply@anthropic.com>`. Missing GPG
signatures are an accepted environment-wide limitation (no signing key). `e4b3cc3`, `7f2ec45`,
`2a9e528`, `cea86a5`, `f30e284`, `f4a7097`, `530f182` are unchanged and are ancestors of HEAD.

### Superseded-freeze chronology

`e4b3cc3` was the **premature OQ-E freeze** (it froze the qualification-defining source before the
executable scaffold existed). `7f2ec45` records it **superseded** in the append-only, hash-chained
supersession ledger — the sole commit touching that file — while the registry and all three sealed
ledgers were byte-empty. The superseded freeze can never authorize registration or execution
(`assert_freeze_not_superseded` refuses it). The complete executable surface was then frozen by the
**OQ-E2** freeze (`cea86a5`), whose activation anchor (`f30e284`) records the freeze commit; only
then did OQ-R/P/Q (`530f182`) run.

## 3. Immutable artifacts (hashed from disk; last-touching commit)

| Artifact | sha256 | last commit |
|----------|--------|-------------|
| `oq_protocol.json` | `395821d8…32cc` | e4da166 |
| `oq_fixture_manifest.json` | `1ff358d0…f6ab` | e4da166 |
| `oq_fault_schedule.json` | `289263e4…23d2` | e4da166 |
| `oq_slo_contract.json` | `0bd69e07…1fc9` | e4da166 |
| `oq_cash_control_identity.json` | `f9ffb334…cd28` | e4da166 |
| `oq_source_freeze.json` | `e47ef8ec…25bd` | cea86a5 (OQ-E2) |
| `oq_e2_activation.json` | `482a4447…2ac0` | f30e284 |
| `oq_source_freeze_supersession.jsonl` | `2e730863…b7dd` | 7f2ec45 (singular) |
| `oq_result.json` | `739cec5d…b897` | 530f182 |
| `oq_report.md` | `9658ffc1…0c4e` | 530f182 |
| `oq_archive_manifest.json` | `68f6c49e…1980` | 530f182 |

No commit modifies any of these after its introducing/finalizing commit. Exactly one registry and
one archive run directory exist — no second execution, repaired result, lifecycle reset, or alternate
registry.

## 4. OQ lifecycle, digests, and read-only verification

- Registry `governance/v2c/oq_registry.jsonl`: exactly `registered(ord0) → started(ord1) →
  completed(ord2)`, **no failed event**, verdict `qualified`. The hash chain is complete
  (`entry_hash = canonical_sha256(body)`, `prev_hash` links from genesis `0*64`), independently
  recomputed by Auditor 1. All 11 shared-identity fields agree byte-for-byte across the three events.
- Terminal digests: `result_sha256 = 739cec5dca07b984d6fb624384e490dcab7722c5341053790d5ba8cd1945b897`,
  `result_bundle_sha256 = e52308a0ffd048ffe4283b51b052fd65e2aab4a37156e53952c16354a9dcb525`, slots `3800`.
- Read-only verification on the committed tree: `replay` = **16 checks**, `verify` (deep archive) =
  **10 checks**, OQ-Q oracle **accepted** (`derived_verdict=qualified`, no findings), `recover` =
  `no-intent`; OQ-E2 freeze reproduces, OQ-E2A activation reproduces, supersession ledger clean,
  `e4b3cc3` superseded.
- **Started-before-calculation:** the orchestrator register/start path invokes no harness/subprocess;
  `execute_qualification` calls `assert_started(token)` as its first statement before any
  computation; `StartedToken` is mintable only after the durable `started` event is written and read
  back; a forged StartedToken against a non-started registry is refused (Auditor 1).
- **From-source reproducibility:** re-executing the frozen source at `slots=3800` reproduces the
  committed `result`/`report`/`manifest`/`bundle` digests byte-identically (Auditor 2, on 3.12 and
  3.13), and the standing test `test_committed_digests_re_derive_from_the_frozen_source` locks it.
- **Sealed ledgers:** `research/m2b/test_evaluations.jsonl`, `research/m3a/development_gate_access.jsonl`,
  `research/m3d/prospective_evaluations.jsonl` are each **0 bytes**, not symlinks, sha256
  `e3b0c442…b855`.

## 5. Six independent auditors — all CLEAN, zero findings

| Auditor | Scope | Verdict |
|---------|-------|---------|
| 1 | Lifecycle & exactly-once governance | **CLEAN** — chain, one-shot budget (truncation-to-pristine attack fails closed), calc-before-start, all refusals reproduced fail-closed |
| 2 | Determinism & independent operational oracle | **CLEAN** — reimplemented oracle from spec reproduces every number; from-source digest re-derivation byte-identical; invariant to TZ/locale/PYTHONHASHSEED/3.12-vs-3.13 |
| 3 | Publication, archive, intent & recovery | **CLEAN** — closed output set, canonical JSON, immutable write-once, calc-free recovery, tamper refusals reproduced |
| 4 | Security & process isolation | **CLEAN** — buyer harness `-I -S -B` + minimal env (`-S` blocks package import); no network/credential/eval/dynamic-import/OIDC/upload |
| 5 | Sealed-partition & no-strategy firewall | **CLEAN** — firewall admits only `cash_control_operation`; full-run instrumentation recorded **zero file opens** of the sealed partitions; no strategy/candidate/market value |
| 6 | Merge mechanics, historical neutrality, CI & honesty | **CLEAN** — exact ancestry, strictly additive to governed state, merge sim clean, docs/PR honest, V2 not sell-ready |

No Class A/B/C/D finding survived verification. The auditors inspected committed bytes and production
paths and reproduced refusals in disposable clones — they did not merely trust unit tests.

## 6. Adversarial acceptance matrix (Phase 3)

168 existing V2C-OQ tests + the buyer-boundary isolation suite already cover the matrix; the six
auditors reproduced the production refusals. This audit adds `tests/test_v2c_oq_acceptance_matrix.py`
(12 runtime-agnostic standing tests) locking in the few scenarios lacking an explicit named test: a
freeze copied into a bare/unrelated tree (missing member), a duplicated `completed` registry tail
(broken chain), the firewall refusing real-data/market-data/loader/candidate request kinds, a
symlinked archive member, an undeclared archive entry, and a contaminated sealed ledger at verify.
No scanner was weakened. Green on 3.12 and 3.13.

## 7. Full reproduction (Phase 4)

- `ruff check .` clean; `ruff format --check .` clean (612 files); `mypy src tests examples` clean
  (606 source files); `uv lock --check` clean; `git diff --check` clean.
- Full `.venv/bin/pytest` (CPython 3.12.3): **3694 passed, 12 skipped, 0 failed** (3706 collected).
  The repo's `addopts` already carries `-q`, so an explicit `-q` doubles to `-qq`, which omits the
  printed one-line summary; the pass/skip counts are read from the per-item progress stream (3694
  `.` + 12 `s`, no `F`/`E`/`x`) and cross-checked against `pytest --co` (3706 items collected).
- Full suite on 3.13 (independent, at stable HEAD): 3632 passed, 62 skipped, 0 failed (prior run;
  the extra 3.12 passes vs 3.13 are the CPython-3.12-guarded live-lifecycle OQ tests, which skip on
  3.13; re-confirmed by the fresh-clone replay/verify below).
- Fresh disposable clone (no access to the working dir; import verified from the clone): replay 16 /
  verify 10 / oracle accepted on 3.12; replay 16 / verify 10 on 3.13; shallow depth-1 clone replay
  16 / status completed. No untracked derived files.
- Sealed-ledger hashes and local==remote re-confirmed.

## 8. Merge-readiness simulation (Phase 5) — the PR was NOT merged

In a disposable clone, a true two-parent `--no-ff` merge of the V2C head (`e2db958` at simulation
time) into current `main`:

- Clean merge; merge commit parents = `[6e0d60e main, e2db958 V2C head]` (both correct). The
  additive acceptance-docs commit(s) added after the simulation only extend the head with
  documentation/tests and do not change `main`, so the clean-merge property is preserved: the merged
  tree stays a superset of `main` with no governed artifact modified.
- **Merged tree == V2C head tree** (identical tree object) — because `main` is the exact merge-base.
- No commit lost or duplicated; sealed ledgers remain 0 bytes on the merged tree; V2C replay (16) +
  deep verify (10) + status `completed` pass on the merged tree.
- Historical neutrality: the origin/main..HEAD patch modifies only **non-governed** files (version
  bumps `pyproject.toml`/`__init__.py`/`uv.lock`/`test_version.py`, test allowlist/fixture updates,
  `provenance_graph.py`) — **no governed/sealed/accepted qualification artifact is modified**; all 19
  `governance/v2c/**` files are Added. Patch: `+15953 -34` across 99 files (88 Added, 11 Modified).

**Exact future human merge procedure** (external gate; not performed here): on GitHub, mark PR #18
ready for review, obtain human review, then "Create a merge commit" (true two-parent merge) into
`main`. Because `main == merge-base`, the merged tree will equal the current head tree; no rebase or
retarget is needed while `main` stays at `6e0d60e`. If `main` advances first, do not rebase — re-run
this merge simulation and re-verify a clean merge before merging.

## 9. Limitations (honest)

- The offline verifier proves internal consistency + source non-drift + from-source reproducibility.
  It is **keyless** (no signing key); a forgery that also rewrites the frozen source is out of scope
  and delegated to human review of signed git history (disclosed in the freeze statement and
  `docs/V2C_SECURITY.md`). GPG signatures are absent (environment limitation).
- The OQ is a **synthetic, candidate-free operational qualification**. It evaluates no strategy and
  computes no market performance. It certifies offline-operations readiness only — not profitability,
  deployment, live/paper validation, or sell-readiness.

## 10. Prohibited-action confirmation

This audit did **not**: merge, retarget, undraft, tag, release, publish, activate prospective
collection, run paper/shadow trading, access development-gate / final-holdout / M3D prospective
values, start V2D, begin the Fable 5 sweep, delete a branch, or rewrite history. No governed artifact
was mutated. No OQ was re-run against the real repository.

## 11. Exact next human action

1. Human review of PR #18 (kept draft). 2. When approved, perform the true two-parent merge above.
3. After V2 implementation is merged, the agreed next stage is the **Fable 5 full-system audit**,
then remediation + paper-release freeze, then **paper/shadow trading**, then a post-paper audit —
**before** any commercial-acceptance / sell-ready determination. V2 is **not** sell-ready.

## 12. CI (Phase 7)

CI is asserted from GitHub, not from local success. On every push the branch head re-runs the full
required workflow set — `checks (3.12)` / `checks (3.13)`, `authoritative-runtime`,
`authoritative-replay`, `authoritative-recovery`, `compat-replay (3.12/3.13)`,
`compat-recovery (3.12/3.13)`, `independent-verifier`, `readiness`, and the per-milestone replay
workflows (`v2a-replay`, `v2ab-replay`, `v2b-replay`, `v2c-replay`, `portfolio-replay`). The concrete
run/job URLs and terminal conclusions for the **final** HEAD (the acceptance-docs commit) are recorded
in the accompanying terminal report and are visible on the live PR #18 check list; this audit's
verdict is issued only after those required workflows reach terminal `success` on GitHub for the final
HEAD.

---

**Verdict:** V2C ACCEPTED FOR HUMAN MERGE REVIEW — OFFLINE OPERATIONS QUALIFICATION INDEPENDENTLY
REPRODUCED; NO STRATEGY EVALUATED; ALL SEALED PARTITIONS UNTOUCHED; PROSPECTIVE COLLECTION REMAINS
INACTIVE; V2 NOT SELL-READY.
