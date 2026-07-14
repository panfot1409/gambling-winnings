# Milestone 3A — run-003 terminal completion plan

This plan finishes, proves, executes, and closes the corrective research-train
run-003. It first corrects ten defects (N1–N10) found in the closure checkpoint
`18de743`, several of which were over-claimed as fixed. It authorizes **no**
development-gate or final-holdout access; run-003 is research-train only.

Starting checkpoint: `18de74334723c37f49bc7a0ab10d152430716930`. The registry
prefix `7920d9fd…e9af67`, both byte-empty ledgers, and the run-001/002 archives
are unchanged and must stay so.

## New defects N1–N10 (reproduced failing-test-first)

| id | defect | root cause | invariant restored |
| --- | --- | --- | --- |
| N1 | the "unforgeable" authorization is forgeable — `_AUTH_SENTINEL` is an importable module global | object identity / a private variable is not an access control | every privileged boundary re-reads the canonical registry and proves registered→started-only, the started-line hash, and identity/source/methodology/ledger agreement; possession of a token grants nothing |
| N2 | `publish_batch` writes outside the root: `Artifact("../escape.txt", …)` escapes | the publisher joins `root / relpath` with no traversal/symlink-parent check | a canonical safe-root resolver on every artifact path, enforced by the primitive itself |
| N3 | temp filenames are `filename+pid` and opened truncating | non-unique, clobbers a pre-existing regular file | `O_CREAT|O_EXCL|O_NOFOLLOW` unique same-directory temps |
| N4 | read-back/parse/reconcile verification runs *after* `publish_batch` returns | verification is outside rollback scope; a failure leaves finished-looking artifacts | verification executes while rollback is still possible; any failure restores the prior state |
| N5 | rollback restores bytes but does not fsync restored dirs and uses a fixed `.rollback.tmp` name | incomplete durability | unique rollback temps, fsync restored files and directories, deterministic new-dir handling, a distinct catastrophic-failure state |
| N6 | the promised calculation-free recovery finalizer does not exist | unimplemented | a completion-intent artifact + `m3a_recovery` finalizer that appends the exact precomputed completed event without any market calculation |
| N7 | the hierarchical interval records seed `20260713` but PCG64 was seeded `20260714` | `_interval` serializes `config.seed` for both algorithms | every interval records its exact effective RNG seed (`base_seed` + `effective_rng_seed`) |
| N8 | `results.execution_code_commit_sha` is set to the run HEAD while the registry keeps the pre-registration commit | one field overloaded with two meanings | distinct fields: execution-source commit, registration-container commit, run-head commit, methodology-freeze commit, source-tree fingerprint |
| N9 | no test exercises a *successful* end-to-end orchestration | only pre-start refusals were tested | a synthetic disposable-repo rehearsal drives the production lifecycle and every failure/recovery transition |
| N10 | R7 was never fixed — the workflows still pipe `curl … \| sh`, and the test passes *because* the vulnerability is present | documented as debt instead of fixed | no surviving workflow pipes downloaded bytes to a shell; `setup-uv` pinned to a verified full commit SHA |

## Commit-identity semantics (N8)

- `E` — final code/methodology commit before registration (execution-source).
- `R` — registry-only commit containing the run-003 `registered` line
  (registration-container). `E..R` changes **only** one appended registry line;
  `src/eth_research` at `E` == at `R`, so the source fingerprint is identical.
- Run starts at clean HEAD `R`; `run_head_commit_sha == R`.
- `P` — later commit containing `started`/`completed` and the run outputs; not
  knowable at calculation time, recorded only in the final audit/index.

A commit cannot contain its own SHA, so `R` is derived from Git history after the
registration commit, never written into the registered event.

## Publication transaction + crash recovery (N2–N6)

Explicit lifecycle: `prepare_batch(root, artifacts)` → `replace_all()` →
`verify(callback)` → `commit()`. Any exception before `commit()` rolls back.
Safe-root path resolution, `O_EXCL` temps, prior-byte retention until verify
passes, immutable-existence refusal, marker-last ordering, directory fsync, and
fsynced reverse rollback with a distinct catastrophic state. A
`completion_intent.json` immutable artifact carries the exact completed event
bytes; `m3a_recovery --status/--finalize` appends that exact event after
re-verifying every artifact, with spies proving no strategy/engine/metric/
bootstrap/ledger is touched.

## Registration + execution sequence

1. Land all code/workflow/test/recovery/replay/doc changes; checkpoint `E`
   green on CI (Sections 4–13).
2. **12A** — `m3a_register --append` appends exactly one `registered` line for
   `m3a-fixed-baseline-comparison-v2-run-003` (corrects
   `…-v1-run-002`, kind `methodology-and-publication-governance-correction`);
   commit registry-only, push, CI green, ledgers still zero.
3. **12B** — `develop_m3a --run-experiment …` once; the orchestrator appends
   `started`, evaluates, publishes transactionally, verifies, appends
   `completed`; migrate aliases to v2.
4. Prove every fold cell / summary / pooled / full-train value is bit-identical
   to run-002; report all v1/v2/hierarchical interval changes without
   cherry-picking; commit outputs `P`; post-run red-team; final CI green.

## Dual-state replay (Section 12)

M3A replay and `verify_m3a_registry` pass in **State A** (run-002 v1 latest,
run-003 registered-only, aliases v1) and **State B** (run-003 completed, aliases
v2, all three archives verify). `develop_m3a --check` dispatches the latest
completed experiment to v1 or v2 replay. All migration lands before `R`.

## Hard stops

Either ledger changes; any post-2022-06-21 row reaches calculation; the registry
prefix changes; a run-001/002 archive fails; R7 cannot be genuinely fixed; the
synthetic lifecycle fails; a real calculation precedes a green registration;
`E..R` contains anything but the one registry append; run-003 financials differ
from run-002; run-003 fails after `started` and cannot be recovered without
recalculation; source changes are required after registration; publication/
recovery leaves ambiguous state; final CI stays red; completion would require
history rewriting.

## Absolute final stop

After run-003 is completed, committed, pushed, reproduced, red-teamed, and all
final CI is green: stop. Do not spend the development gate, evaluate the final
holdout, promote a candidate, merge PR #4, or create `v0.4.0`.

## Expected commit sequence (small, named)

plan → reproduce N1–N10 → hardened publication primitive → completion intent +
recovery CLI → registry-verifiable context → bootstrap effective-seed + strict
fold validation → commit-identity model + registration CLI → CI supply-chain
fix → synthetic end-to-end rehearsal → dual-state replay + registry verifier →
checkpoint E → **12A registration (registry only)** → **12B run outputs** →
bootstrap/financial proof docs → post-run red-team → docs → final audit.
