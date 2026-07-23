# V2C Independent Acceptance & Merge-Readiness Audit — Plan

This is the plan of record for the **independent acceptance audit** of Milestone V2C (candidate-free
offline operational qualification). It is an acceptance/merge-readiness audit, **not** a new research
milestone: nothing here starts V2D, a Fable 5 full-system sweep, paper/shadow trading, prospective
collection, strategy research, or candidate evaluation. The audit verifies — not assumes — the
committed V2C state and produces a merge-readiness verdict while keeping PR #18 open and **draft**.

## Agreed sequence (context)

```
V2 implementation-complete
  → Fable 5 full-system audit
  → remediation and paper-release freeze
  → paper/shadow trading
  → post-paper audit
  → commercial acceptance
```

V2 cannot be called sell-ready — or completely finished — before the paper record and post-paper
audit exist. This audit establishes only that the V2C **implementation** is merge-ready.

## Non-negotiable constraints

- Use `.venv/bin/{python,pytest,ruff,mypy}` (CPython 3.12.3). Bare `python` may be 3.11 — not authoritative.
- Do **not** amend, rebase, reset, squash, force-push, or rewrite any existing commit. Preserve all
  commit identities. Missing GPG signatures are an accepted environment limitation.
- Do **not** merge, retarget, undraft, tag, release, publish, activate prospective collection, run
  paper/shadow trading, access development-gate / final-holdout / M3D prospective values, start V2D,
  or begin the Fable 5 sweep. No branch deletion, no history rewrite.
- Auditors are read-only on governed artifacts; disposable clones + scratch reproducers only.

## Phases

0. **Read-only preflight** — verify branch/HEAD/remote/merge-base/clean tree; local==remote; PR #18
   open/draft/unmerged/base main; version + runtime; hash the three sealed ledgers from disk; verify
   the OQ registry chain from committed bytes; hash every immutable qualification artifact; run the
   read-only replay/deep-verifier/oracle/recovery/supersession/freeze verifiers; confirm no
   LICENSE/release/tag/activation/adapter/credential/order-routing/public-publication; confirm no
   strategy/candidate/market value in outputs. Hard-stop on any sealed-ledger contamination,
   immutable drift, ambiguous lifecycle, or strategy/market evaluation.
1. **Immutability & chronology audit** — the full commit chronology (`e4b3cc3` premature freeze →
   `7f2ec45` supersession → executable scaffold → `2a9e528` pre-freeze red team → `cea86a5` OQ-E2 →
   `f30e284` OQ-E2A → `f4a7097` CI guard → `530f182` OQ-R/P/Q); byte-immutability of governed
   artifacts; exactly-once lifecycle; from-source re-derivation at `slots=3800`. Produce a commit +
   artifact map.
2. **Six independent read-only auditors** — (1) lifecycle & exactly-once governance; (2) determinism
   & independent operational oracle; (3) publication/archive/intent/recovery; (4) security & process
   isolation; (5) sealed-partition & no-strategy firewall; (6) merge mechanics / historical
   neutrality / CI / honesty. Each reproduces and classifies findings (A scientific, B
   governance/security, C defense-in-depth/docs/test, D sealed/immutable). Class A/D = hard stop;
   genuine Class B/C fixed failing-test-first, append-only.
3. **Adversarial acceptance matrix** — add or confirm standing tests for ~55 adversarial scenarios
   (freeze tamper, supersession, lifecycle, strict-JSON, symlinks, archive/output/bundle/intent
   tamper, recovery-calculation, process isolation/injection, framing, network/credential, workflow
   permissions, artifact upload, no-skipped acceptance test, shallow + cross-runtime replay), without
   weakening scanners.
4. **Full reproduction** — the complete gate battery (ruff/format/mypy/`uv lock --check`/`git diff
   --check`/full pytest with exact counts/all verifiers/prior-milestone replays/sealed-ledger hashes)
   quiescently, then a disposable fresh-clone reconstruction on CPython 3.12.3 and 3.13 (shallow where
   relevant). Result and verdict must reproduce within the committed numerical contract.
5. **Merge-readiness simulation** — in a disposable clone, a true two-parent merge of HEAD into
   current `main`: clean, correct parents, tree equals the accepted head tree (main is the exact
   base), no commit lost/duplicated, historical artifacts byte-identical, sealed ledgers empty,
   battery passes on the merged tree; patch digests + the exact future human merge procedure. The
   live PR is not merged, retargeted, or undrafted.
6. **Documentation & PR body** — this plan + `docs/V2C_INDEPENDENT_ACCEPTANCE_AUDIT.md`; update PR
   #18's body to reflect acceptance accurately while keeping it draft, with no profitability / alpha /
   live / paper / deployment / sell-ready / cryptographic-attestation claim.
7. **Final CI** — push only coherent, green, append-only commits; monitor every required workflow to
   terminal status; report run/job URLs and conclusions. CI-green is asserted from GitHub, not local.

## Terminal verdicts (verbatim)

- Accepted: `V2C ACCEPTED FOR HUMAN MERGE REVIEW — OFFLINE OPERATIONS QUALIFICATION INDEPENDENTLY
  REPRODUCED; NO STRATEGY EVALUATED; ALL SEALED PARTITIONS UNTOUCHED; PROSPECTIVE COLLECTION REMAINS
  INACTIVE; V2 NOT SELL-READY`
- Rejected: `V2C REJECTED FOR MERGE — OPERATIONAL QUALIFICATION, GOVERNANCE, SECURITY, OR SEALED-STATE
  INTEGRITY COULD NOT BE INDEPENDENTLY ESTABLISHED; NO MERGE PERMITTED; V2 NOT SELL-READY`
