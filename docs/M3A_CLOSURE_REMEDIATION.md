# Milestone 3A — Closure Remediation Plan

This plan makes Milestone 3A genuinely closure-ready: it closes the governance,
transactional-durability, strict-parsing, scientific-inference, provenance, and
supply-chain gaps an audit reproduced, while keeping the **development gate and
final holdout completely sealed**. No gate or holdout access is authorized by
any part of this work.

> **Update — run-003 executed.** The corrective run-003 pre-registration and
> execution sequence described in §9 has since been carried out by the run-003
> terminal-completion milestone, which first corrected ten further defects
> (N1–N10). run-003 is registered, executed once, financially bit-identical to
> run-002, and committed; both ledgers stayed byte-empty and the v1 registry
> prefix is unchanged. See `M3A_RUN003_TERMINAL_PLAN.md` and the terminal audit
> `M3A_RUN003_TERMINAL_AUDIT.md`.

## 0. Ground rules (unchanged throughout)

- The existing six registry lines are immutable. Their exact byte prefix hashes
  to `7920d9fdf4e936ef6c6d79dfd1c10cdd12dcb9b2db264b9ab9d5640332e9af67` and must
  stay byte-for-byte unchanged.
- run-001 and run-002 financial results are frozen history; run-003 must
  reproduce every per-fold financial number bit-for-bit.
- Both access ledgers stay exactly zero bytes
  (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).
- No history rewrite, amend, squash, rebase, or force-push. No merge/undraft of
  PR #4. No v0.4.0 tag. No repair of the v0.3.0 tag debt or the unsigned-commit
  environment limitation.

## 1. Reproduced defects, root causes, invariants

| id | severity | reproduced symptom | root cause | invariant |
| --- | --- | --- | --- | --- |
| R1 | critical | `develop_m3a --write` publishes results+report with `REGISTRY_EXISTS=False` and `RETURN_CODE=0` | `develop_m3a` never imports the experiment registry; `--write` calls `generate()`+`_atomic_write` with no registered/started check | no public real-data evaluation/publication may proceed unless executing exactly one canonical, pre-registered, not-yet-started experiment; `started` is durably appended before the first strategy/backtest/return/metric/bootstrap call |
| R2 | high | injected failure on the 2nd artifact left `RESULTS_BYTES=NEW`, `REPORT_BYTES=OLD` | `_atomic_write` makes each rename atomic but the results+report batch is neither atomic nor rollback-safe, and never fsyncs file or directory | a failed fresh publication leaves no final artifacts; a failed correction restores every prior final byte; no mixed pair, temp, or backup remains |
| R3 | high | `load_development_results_payload` accepted `schema_version=999`, `fold_results="not-a-list"`, `bootstrap_cells=[{"forged":true}]` → `FORGED_RESULTS_ACCEPTED=True` | it validates only the top-level key set and the two event counts; nested containers, schema version value, and cell identities are unchecked; construction and parsing use different surfaces | construction and parsing share one strict symmetric validation surface refusing unknown/missing keys, bool-as-int, non-finite, invalid containers, duplicate/incomplete cells, false identities, and wrong schema versions |
| R4 | scientific | flat concatenation of five reset folds (226/225×4, block 30) has 116/1097 seam-crossing starts (~10.6%), ~4.0 seam-crossing blocks per resample | `moving_block_bootstrap` samples blocks over one concatenated series, treating independently reset portfolio paths as continuous across reset seams | the corrected primary bootstrap never draws a block spanning two independently reset folds; v1 stays as historical evidence, unreplaced |
| R5 | medium | `development_results.json` carries `experiment_family_id` but no `experiment_id` | the v1 results model omits per-run identity; identity is inferred from the external "latest completed" convention | every v2 result/report/return-evidence/manifest/terminal event carries the same exact `experiment_id` |
| R6 | medium | only run-002 bodies exist in the tree; run-001 recoverable only from Git | published bodies were overwritten in place; no per-experiment archive | every completed experiment has immutable, directly verifiable artifacts under a per-experiment directory, labelled if recovered from history |
| R7 | security | `ci.yml`, `m2b-replay.yml`, `m3a-replay.yml` run `curl -LsSf https://astral.sh/uv/0.8.17/install.sh \| sh` | unverified network content piped into a shell | no workflow pipes network content into a shell; the installer is a full-SHA-pinned reviewed action or a SHA-256-verified binary |
| R8 | docs | "training rows"/"training window" implies a fit that does not occur | fixed-rule strategies are never fitted on the expanding frames | describe as fixed-rule rolling-origin OOS evaluation with expanding information sets; do not imply estimation |

## 2. Immutable-artifact layout

```
research/m3a/experiments/
  m3a-fixed-baseline-comparison-v1-run-001/
    development_results.json      # recovered byte-for-byte from its publishing commit
    development_report.md
    artifact_manifest.json
  m3a-fixed-baseline-comparison-v1-run-002/
    development_results.json      # copied from the currently committed bytes
    development_report.md
    artifact_manifest.json
  m3a-fixed-baseline-comparison-v2-run-003/
    development_results.json      # results schema v2
    development_report.md
    return_evidence.json          # per-fold OOS net-return vectors (research-train only)
    artifact_manifest.json
  experiment_index.json           # strict, deterministic index over every archived experiment
```

Each `artifact_manifest.json` records: `experiment_id`, historical schema
version, the source commit bytes were recovered from (or "originally published"
for run-003), results/report/(evidence)/bundle SHA-256s, the registry
completed-event position and hash, and an explicit
`materialization` = `originally_present` | `recovered_from_history`. All paths
are canonical, safe, repository-relative; symlinks, traversal, alternate roots,
unsafe filenames, hash mismatch, duplicate ids, and output aliasing refuse. The
top-level `development_results.json` / `development_report.md` remain as
compatibility aliases of the latest completed experiment.

CI verifies **every** completed historical event against its archived bytes,
not only the latest.

## 3. Registry migration (preserve the v1 prefix)

The reader is version-dispatched with exact per-version key sets. The existing
six v1 lines are parsed by the v1 schema unchanged and remain a byte prefix. New
events are schema v2 and additionally bind: methodology id, correction/
supersession lineage (the completed experiment a correction names), execution
source-tree fingerprint, immutable results/report/evidence/manifest paths, the
terminal artifact hashes, and a deterministic append-chain binding
(`previous_event_sha256`) over the prior registry line. Experiment ids are
globally single-use across v1 and v2. A correction may not masquerade as a new
scientific hypothesis when only rendering/inference method changed. Contamination
blocks all execution and append; appends are one fsynced `O_APPEND` write; there
is no repair or truncation path.

## 4. Fail-closed orchestrator + durable transaction (crash-recovery state machine)

`run_registered_development_experiment(...)` is the only public real-data write
path. Before any real calculation it: locates the canonical root; refuses
symlinked/foreign repos; verifies a clean tree (modulo the expected append);
resolves HEAD; verifies the running package source tree, the frozen runtime, the
M2B dossier, the committed partition, the selected protocol, and both byte-empty
ledgers; uses only the canonical tracked registry; resolves exactly one
registered v2 experiment with no started/terminal event; checks id/family/
protocol/commit/source-hash/paths/methodology agree; refuses output collisions;
then appends+fsyncs `started`. Only after `started` may reconstruction feed a
frame to a strategy/backtest/return/metric/bootstrap.

State machine:

```
REGISTERED --started(fsync)--> STARTED --generate+publish+verify--> VERIFIED --completed(fsync)--> DONE
   |                              |                                      |
   |                              +--any failure--> append failed(fsync)--> FAILED (id consumed)
   +-- refusal before started (no artifacts, no ledger, registry byte-identical)
```

Publication is a durable batch transaction: precompute all bytes; per file write
a unique temp in the destination dir, fsync, refuse non-regular targets,
`os.replace` finals in deterministic order preserving replaced prior bytes in
memory, write the bundle/artifact manifest last as the completeness marker,
fsync directories; on any exception roll back in reverse (remove new finals,
restore replaced bytes, remove temps). Immutable per-run paths never overwrite;
`overwrite` never reuses an experiment id; a correction requires a new id. A
narrowly scoped recovery verifier may finalize already-published byte-identical
artifacts of a `started`-but-not-terminal experiment **without** recomputing.

## 5. Results schema v2 (strict, symmetric)

A fully typed `DevelopmentResultsV2` whose construction and JSON parsing share
one invariant surface: exact key sets at every nesting level; no bool-as-int, no
numeric strings, no NaN/Inf/overflow; 40-hex commits; lowercase sha256/
fingerprints; UTC-aware times; safe paths; complete 5×4×3 fold grid; exactly 12
independent/pooled/full-train cells; the expected bootstrap grid; per-fold
boundary/size/context agreement with the protocol; every OOS row in exactly one
fold; identity checks (total-return, turnover/notional/fills, cash flat with
undefined ratios, B&H one funded entry per reset fold, exposure∈[0,1],
drawdown∈[-1,0], positive equity, liquidation ≤ marked); summaries rederive from
fold rows, pooled/bootstrap point estimates rederive from their evidence; exact
data-access declaration; gate/holdout event counts exactly zero; carries
`experiment_id`. `load_development_results` returns the validated typed model.

## 6. Return evidence + reconciliation

A deterministic `return_evidence.json` carrying per-fold/strategy/scenario OOS
net-return vectors (research-train only, every timestamp ≤ 2022-06-21), strictly
parsed, bound into results/manifest/registry/replay/report, from which every
pooled diagnostic and bootstrap input recomputes and reconciles byte-for-byte
against a fresh engine replay. It exposes no sealed-partition prices.

## 7. Fold-aware bootstrap

`moving-block-bootstrap-v1` and its historical intervals are preserved verbatim
for run-001/002. The primary corrected method is
`fold-stratified-moving-block-bootstrap-v2`: input is an ordered tuple of
per-fold paired-excess series; blocks are drawn strictly within a fold (no block
crosses a reset seam); each fold contributes its original observation count; the
statistic stays the observation-weighted arithmetic mean daily paired excess;
block length/resamples/confidence/RNG/seed frozen before real execution;
deterministic bytes; sentinel tests prove no block crosses a seam. A separate,
clearly labelled hierarchical fold/block bootstrap (resample the five folds as
clusters, then blocks within each, domain-separated RNG) is reported as
**sensitivity only**, with the explicit caveat that five clusters give weak
fold-level inference. All intervals are descriptive and unadjusted, never a
promotion rule. `docs/M3A_BOOTSTRAP_METHOD_NOTE.md` explains the reset semantics,
the four seams, the 116/1097 calculation, why the corrected method is chosen by
design before seeing corrected intervals, and why no bootstrap establishes alpha
or live profitability.

## 8. Protocol v2

An immutable v2 methodology/protocol artifact for run-003 pins the research-train
identity, exact folds/boundaries, fixed strategies and costs, fixed-rule/no-fit
semantics, bootstrap v2 + hierarchical algorithms, seeds/block/resamples/
confidence/statistic/fold-weighting/RNG, family/version, permitted data level,
and exact artifact schema versions. The v1 protocol bytes stay available for
run-001/002; the historical protocol is never mutated then claimed as used by old
runs. The parser is strict and symmetric.

## 9. Pre-registration sequence for run-003

12A (before any real computation): finish implementation + synthetic tests;
commit the v2 protocol; append only a v2 `registered` event for
`m3a-fixed-baseline-comparison-v2-run-003`, stating it corrects methodology/
publication governance (not strategy parameters) and binding run-001/002 lineage;
commit+push; wait for CI + replay green; confirm both ledgers still zero bytes.
12B: run exactly once through the orchestrator (`started` before any real call);
publish immutable run-003 artifacts transactionally; verify; append `completed`.
Every per-fold financial result and full-train metric must be bit-identical to
run-002; only provenance/layout/schema, corrected bootstrap inference, and
dependent report text may change. Any change to a price/signal/fill/equity/
return/fold-metric/cost is a hard stop.

## 10. Tests, failure injection, red-team

Failing-test-first regressions for R1–R8. Failure-injection over every artifact
position (fresh publish, alias replace, fsync/replace/read-back/parse/hash/
regen/completed-append/rollback failures, symlink, temp collision, output
collision) asserting correct registry state, exact-or-absent artifacts, no mixed
pair, no temp leftovers, no gate/holdout access, no unauthorized retry. An active
red-team matrix over registry/orchestrator, publication, results, bootstrap, and
firewall attacks; each attack gets a regression test or a documented scope reason.
An independent second red-team pass that never touches a sealed partition.

### Red-team coverage map

| attack class | attacks | covering tests |
| --- | --- | --- |
| registry / orchestrator | unknown / reused / already-started / already-terminal id; v2-as-first-line; broken append-chain; correction without a completed parent; unsafe/foreign artifact path; unknown/missing v2 key; contaminated registry blocks reads; no-registered-experiment fail-closed with no side effects; unforgeable authorization | `test_experiment_registry.py::TestRegistryV2`, `test_development_orchestrator.py` |
| publication | replace failure; fsync-dir failure; immutable-existing target; pre-existing symlink; duplicate path; empty batch; marker-written-last; fresh-publish and correction rollback restore exact prior bytes | `test_publication.py` |
| results v2 | schema ≠ 2; unknown/missing top-level key; forged data-access declaration; incomplete 5×4×3 grid; liquidation > marked; cash with a fill; buy-and-hold ≠ one fill; exposure ∉ [0,1]; drawdown ∉ [−1,0]; summary that does not rederive; pooled/bootstrap that do not recompute from evidence; mismatched experiment id | `test_development_results_v2.py` |
| return evidence | observation on/after the development gate; boundary after the gate; incomplete grid; per-fold length mismatch; NaN return; reordered / duplicated fold axis | `test_return_evidence.py` |
| bootstrap | block longer than the smallest fold (would cross a seam); within-fold sentinel proves no seam crossing; symmetric interval parse pins RNG/percentile/statistic | `test_bootstrap_v2.py`, `test_m3a_closure_defects.py::TestR4SeamCrossingBootstrap` |
| firewall | forbidden timestamp reaching the engine or a strategy; boundary mutated after validation; forbidden observation smuggled through return evidence | `test_development_evaluation.py` firewall spies, `test_return_evidence.py::TestFirewall` |
| no unregistered write path | develop_m3a exposes no `--write`; `publish_batch` is called only from the orchestrator's publication module | `test_m3a_closure_defects.py::TestNoUnregisteredRealDataWritePath` |

Scope notes: orchestrator happy-path attacks that require a *registered* v2
experiment (output collision, source-modified-after-registration, runtime/version
drift) are exercised end-to-end when run-003 executes and by the strict replay of
that completed experiment; the component invariants they rely on are unit-tested
above. The `curl | sh` installer SHA pin (R7) stays documented CI debt: the
sandbox egress policy blocks github.com and astral.sh, so no trusted SHA can be
obtained offline and a guessed one must not be committed.

## 11. CI / security changes

Remove every `curl … | sh`; install uv via a full-SHA-pinned `astral-sh/setup-uv`
(explicit 0.8.17) or a SHA-256-verified binary. Workflow-hygiene tests assert:
no piped installer, every `uses:` is a full SHA, uv version fixed, `contents:
read`, no secrets/`id-token`/write, no Coinbase contact, no market-data artifact
upload, both ledgers checked before/after M3A replay, full history only where
required. A new immutable-experiment verifier runs in CI over every completed
event.

## 12. Documentation changes

README, `docs/PLAN.md`, `docs/M3A_PLAN.md`, `research/m3a/README.md`, and the
development report: fixed-rule rolling-origin OOS (no fit); expanding windows are
information sets; v1 vs v2 bootstrap; historical results unmodified; transaction/
registry-enforcement/run-identity guarantees; all intervals in-sample and weak;
no promotion; gate/holdout sealed; ETH bull-market caveat; B&H is a benchmark; no
live/profitability claim; unsigned commits and the v0.3.0 tag debt are unrelated
environment limitations not to be "repaired" by rewriting history. A bug-hunt
table (defect → root cause → correction → test → commit).

## 13. Commit sequence (small, named)

1. this plan
2. R1–R8 failing-test-first reproductions + bug log
3. registry v2 reader/writer + append-chain (v1 prefix preserved)
4. immutable experiment archive + manifests + index + run-001/002 recovery
5. results schema v2 (strict symmetric) + adversarial tests
6. return-evidence artifact + reconciliation
7. fold-stratified bootstrap v2 + hierarchical sensitivity + method note
8. protocol v2
9. fail-closed orchestrator + durable batch transaction + failure injection
10. remove unregistered real-data test path + AST hygiene
11. CI supply-chain hardening + workflow-security tests
12. run-003 pre-registration (12A) — commit+push+green before 12B
13. run-003 registered research-train execution (12B) + immutable artifacts
14. active red-team matrix
15. documentation + bug-hunt table
16. final gates, CI, audit

## 14. Hard stops

Stop and report (no workaround) if: either ledger changes; any gate/holdout row
reaches a strategy/engine/return/metric/bootstrap/plot/report; the registry
prefix changes; run-001/002 bytes cannot be recovered to their recorded hashes;
run-003 per-fold financials differ from run-002; a real run happens before its
registration commit is pushed and green; publication cannot be made rollback-safe;
the source/runtime binding cannot be proven; the frozen M2B dossier fails; final
CI stays red; or completing the task would require history rewriting/force-push.

## 15. Authorization statement

**No development-gate access and no final-holdout access is authorized by this
milestone.** The development gate and final holdout remain sealed even if every
remediation succeeds. No candidate is promoted; no authorization for either
sealed partition is constructed.
