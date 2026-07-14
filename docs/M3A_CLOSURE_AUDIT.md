# Milestone 3A — closure remediation audit (read-only handoff)

This is the final read-only audit of the Milestone 3A closure remediation. It
records exactly what changed, proves the sealed invariants held throughout, and
names the single remaining scientifically-honest step.

> **Update — terminal milestone.** The single remaining step named below (§16,
> §17, §30 — the corrective run-003) has since been executed and closed by the
> run-003 terminal-completion milestone. run-003 was pre-registered (12A),
> executed exactly once through the fail-closed orchestrator (12B), proven
> financially bit-identical to run-002 across all 60 fold cells and the 12+12+12
> summaries, and committed; both access ledgers stayed byte-empty and the v1
> registry prefix is unchanged. See `M3A_RUN003_TERMINAL_PLAN.md`,
> `M3A_RUN003_BOOTSTRAP_COMPARISON.md`, and the terminal audit
> `M3A_RUN003_TERMINAL_AUDIT.md`. The sections below are preserved as the
> closure-checkpoint record.

## 1. Starting SHA, final SHA, branch, PR state

- Starting HEAD: `8e076165ad07fcbeb4c5350e9d835439495b1489`
- **Closure-milestone** final HEAD (historical; superseded — see the banner
  above and `docs/M3A_MERGE_READINESS_AUDIT.md`):
  `18de74334723c37f49bc7a0ab10d152430716930` (that milestone's audit-handoff
  commit; its parent `d1dbb68` is the last pre-audit commit, at which the CI and
  working-tree observations in §26–§27 were taken — a commit cannot contain its
  own SHA). The "to be recorded when run-003 executes" placeholders in §16–§17
  were fulfilled by run-003 and are tabulated in
  `docs/M3A_RUN003_BOOTSTRAP_COMPARISON.md`.
- Branch: `claude/m3a-development-research-lab`
- PR: **#4 open and draft** — not merged, not undrafted.

## 2. Registry-prefix SHA before/after

The six-line v1 registry prefix (run-001 r/s/c + run-002 r/s/c) is byte-for-byte
unchanged: SHA-256
`7920d9fdf4e936ef6c6d79dfd1c10cdd12dcb9b2db264b9ab9d5640332e9af67` before and
after. No existing registry line was rewritten.

## 3. Ordered commits

1. `9c88cf3` closure-remediation plan
2. `def94cf` reproduce defects R1–R8 as executable tests + bug log
3. `6597730` immutable per-experiment artifact archive (R6)
4. `9297d10` fold-aware bootstraps that never cross a reset seam (R4)
5. `b0e18d5` allow the archive subtree in M3A hygiene
6. `e58554f` harden the development-results parser against forged inputs (R3)
7. `13baba1` extend CI supply-chain security tests; record R7 debt
8. `963eabd` clarify fixed-rule rolling-origin OOS terminology (R8)
9. `6131163` durable rollback-safe batch publisher (R2 machinery)
10. `7f21648` experiment-registry schema v2 with an append-chain (Phase 5)
11. `bc51fff` immutable v2 methodology/protocol artifact (Phase 11)
12. `fb489e8` per-run OOS return-evidence artifact (Phase 9)
13. `1ae04bd` strict symmetric development-results schema v2 (Phase 8)
14. `6562a87` fail-closed orchestrator; remove the unregistered write path (R1/R2)
15. `6f9824d` reproduce only the registered experiment in real-data tests (Phase 13)
16. `0774f3f` bind the registered execution commit by source fingerprint
17. `788604f` document the closure remediation; correct the bug-hunt table (Phase 16)
18. `04a30da` extend the closure red-team matrix and document coverage (Phase 15)
19. `d1dbb68` raw-string regex match patterns and a typed dict in the closure tests

## 4–5. Reproduced defects, root causes, invariants, fixes

See `M3A_BUG_LOG.md` for the full table. Summary:

| id | defect | root cause | invariant restored | fix |
| --- | --- | --- | --- | --- |
| R1 | public `--write` published with no registry gate | governance outside the publisher | registration precedes any real calculation; the only real-data publish path is the orchestrator | `6562a87` |
| R2 | per-file `os.replace`, no fsync → mixed pair on crash | non-transactional publication | durable temp+fsync+ordered-replace+marker-last+dir-fsync+reverse-rollback batch | `6131163`/`6562a87` |
| R3 | results parser accepted forged schema/containers | only top-level keys checked | strict schema-version, container, grid-count, cell-object enforcement | `e58554f` |
| R4 | moving blocks crossed reset-fold seams | one concatenated series | fold-stratified bootstrap v2 draws blocks strictly within a fold | `9297d10` |
| R5 | results omit per-run identity | v1 schema | results v2 requires `experiment_id`/`methodology_id`/source fingerprint | `1ae04bd` (committed artifact lands with run-003) |
| R6 | historical bodies overwritten in place | no per-run archive | immutable hash-verified `experiments/<id>/` archive + index | `6597730` |
| R7 | `curl \| sh` installer unpinned | unverified network content | supply-chain invariants enforced; SHA-pin blocked by egress policy (documented debt) | `e58554f`+ (residual) |
| R8 | "training rows" implied a model fit | fixed-rule strategies are not fitted | prose states fixed-rule rolling-origin OOS, no estimator fit | `963eabd` |

## 6. Registry v1/v2 schema and lifecycle

Version-dispatched parsing. v1 (run-001/002) lines parse unchanged; v2 events add
correction lineage, exact cost scenarios, methodology id, immutable artifact
paths, execution source-tree fingerprint, and a `previous_event_sha256`
append-chain onto the immutable v1 prefix. Lifecycle `registered → started →
completed|failed`; experiment ids globally single-use across v1 and v2; shared
lifecycle-identity fields constant; timestamps never move backward; a correction
must name an experiment already `completed`; one fsynced `O_APPEND` write; no
repair/truncation path.

## 7. Orchestrator event sequence

`run_registered_development_experiment` → ordered pre-checks (repo root; refuse
symlinked/foreign package; clean tracked tree; real HEAD; running source ==
committed source at HEAD + source fingerprint; frozen numerical runtime;
dossier-bytes bound to the partition; committed partition; v1 protocol +
immutable v2 methodology bound to it; both sealed ledgers byte-empty; canonical
tracked registry only; exactly one registered-only v2 experiment whose bound
fields all agree; no output collision) → append+fsync `started` → mint an
unforgeable `DevelopmentRunAuthorization` → evaluate → build → publish
transactionally → read back, strict-parse, reconcile → append `completed`. On
failure after `started`, append `failed`; the id stays consumed.

## 8. Transaction algorithm and rollback

`publish_batch`: precompute all bytes; write each to a unique temp in its
destination dir and fsync; refuse symlink/non-regular targets and immutable
existing finals; `os.replace` finals in order with the completeness marker last;
fsync every touched directory; on any exception roll back in reverse (restore
each replaced final's prior bytes or remove new finals; delete all temps).

## 9. Failure-injection matrix

`tests/test_publication.py`: successful publish leaves no temps; a failed fresh
publish leaves no finals; a failed correction restores every prior byte; an
fsync-dir failure still rolls back; immutable-existing / symlink / duplicate /
empty batches are refused; the marker is replaced last.

## 10. Results-v2 schema and cross-field identities

Strict symmetric `DevelopmentResultsV2`: schema 2; exact nested key sets; 40-hex
commits; lowercase SHA-256/fingerprints; exact strategy/cost tuples; complete
5×4×3 fold grid with ordered non-overlapping OOS windows; per-cell accounting
(liquidation ≤ marked, return identities, cash never trades, buy-and-hold funds
once per fold, exposure ∈ [0,1], drawdown ∈ [−1,0], positive equity); twelve
summaries rederived from the fold rows; pooled/bootstrap recomputed from the
return evidence; exact data-access declaration; zero sealed event counts.

## 11. Immutable paths/hashes for run-001, run-002, run-003

- run-001: `research/m3a/experiments/m3a-fixed-baseline-comparison-v1-run-001/`
  (recovered from Git, results `b8616248…`, report `9362c631…`).
- run-002: `…-run-002/` (originally present, results `dc4564fe…`, report `34baa74c…`).
- run-003: paths pre-declared for
  `research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003/`
  (`development_results.json`, `development_report.md`, `return_evidence.json`,
  `artifact_manifest.json`); **materialized when run-003 executes** (see §17).

## 12. Historical terminal events match their bodies

`verify_experiment_archive('.')` binds every completed registry event to the
archived bytes and passes for run-001 and run-002; `verify_m3a_registry.py`
binds the latest completed event to the committed files.

## 13. Bootstrap v1 seam-crossing analysis

Five reset folds 226/225/225/225/225 (1126 obs), block 30 → **116 of 1097**
block starts (~10.57%) cross an interior reset seam (`M3A_BOOTSTRAP_METHOD_NOTE.md`,
`TestR4SeamCrossingBootstrap`).

## 14–15. Bootstrap v2 exact algorithm and hierarchical sensitivity

- Primary `fold-stratified-moving-block-bootstrap-v2`: each resample replaces
  every fold with a within-fold moving-block resample of its own length,
  concatenates them, and takes the observation-weighted mean; no block spans a
  reset seam. Seed 20260713, block 30, 5000 resamples, 95%, `PCG64`.
- Sensitivity `hierarchical-fold-block-bootstrap-v1`: resample folds as clusters
  (with replacement) then blocks within, RNG stream domain-separated (seed+1).
  Five clusters give weak fold-level inference — reported as sensitivity only.

## 16. Old versus corrected intervals

To be recorded from run-003's committed results versus run-002's v1 intervals,
without cherry-picking, when run-003 executes (§17). By construction the
per-fold financials do not change; only the inference method does.

## 17. Remaining step — run-003 (Phase 12)

The full run-003 pipeline is implemented, strict, and green on Python 3.12 and
3.13; the fail-closed orchestrator refuses today only because no run-003 v2
`registered` event exists yet. The mandatory, CI-gated sequence to finish is:

1. **12A** — append a v2 `registered` event for
   `m3a-fixed-baseline-comparison-v2-run-003` (execution commit = the
   pre-registration HEAD, source fingerprint of that tree, methodology + partition
   SHAs, archive paths), stating it corrects methodology/publication governance
   only and binding the run-001/002 lineage; commit (registry only, no `src`
   change), push, and **wait for CI + both replays to be green** with both
   ledgers still zero bytes.
2. **12B** — `python -m eth_research.develop_m3a --run-experiment
   m3a-fixed-baseline-comparison-v2-run-003`, exactly once. The orchestrator
   appends `started` before the first real call, publishes the immutable run-003
   artifacts + updated index + compatibility aliases transactionally, reads back,
   reconciles, and appends `completed`.
3. Prove every per-fold financial result, full-train metric, and pooled raw
   observation is bit-identical to run-002 (only provenance, schema/layout,
   corrected bootstrap inference, and dependent report text change); report all
   v1-vs-v2 interval changes; migrate the replay/`--check` path and the M3A
   Replay CI to the v2 alias; push and confirm final CI green.

This step was **deferred** at the closure checkpoint: it requires a real registry
mutation that must be committed, pushed, and CI-green *before* the run, and a
replay/CI migration that must itself stay green — a multi-round CI-gated sequence
left set up rather than rushed. It was **not blocked**, and it has since been
executed and closed by the terminal milestone (see the update note at the top of
this document).

## 18. Exact experiment id carried by every new artifact

Results v2, registry v2 events, return evidence, and the artifact manifest all
carry `experiment_id`; the run-003 id is `m3a-fixed-baseline-comparison-v2-run-003`.

## 19. Proof no unregistered public write path remains

`develop_m3a` defines no `--write` flag and no `_atomic_write`;
`run_registered_development_experiment` is the only real-data publish path;
`publish_batch(` is called only from `development_publication.py`
(`TestNoUnregisteredRealDataWritePath`).

## 20. Proof started precedes all real calculation

The real evaluation (`_evaluate_authorized`) and the publication both require a
`DevelopmentRunAuthorization`, which is minted only after the `started` event is
durably appended, inside the orchestrator; the token cannot be forged
(`TestUnforgeableAuthorization`). Pre-start refusals append nothing.

## 21–22. Both sealed partitions untouched; exact ledger bytes

`research/m3a/development_gate_access.jsonl` and
`research/m2b/test_evaluations.jsonl` are each **0 bytes**, SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`, before and
after. No development-gate or final-holdout row reached any strategy, engine,
return, metric, bootstrap, or report.

## 23. Supply-chain installer changes

`test_workflow_security.py` enforces full-SHA `uses:`, no floating tags,
`contents: read`, no secrets/`id-token`/writes, a host allowlist, a version-pinned
installer, no market-data artifact upload, and both ledgers checked around the
M3A replay. The `curl | sh` installer SHA cannot be pinned offline (egress policy
blocks github.com and astral.sh, 403); recorded as CI debt, not worked around.

## 24. Red-team attacks and regression tests

See the coverage map in `M3A_CLOSURE_REMEDIATION.md` §10: registry/orchestrator,
publication, results, return evidence, bootstrap, firewall, and
no-unregistered-write-path attacks each map to a regression test or a documented
scope reason.

## 25. Local command outputs (final gates, this HEAD)

- `ruff check .` → clean; `ruff format --check .` → all formatted.
- `mypy src tests examples` → Success (107 files).
- `pytest` → all pass (3.12.3); closure modules also pass on 3.13.12.
- `git diff --check` → clean; `uv lock --check` → resolved, no change.
- `develop_m3a --check` → reproducible; `verify_m3a_registry.py` → verified.
- `verify_experiment_archive('.')` → run-001 + run-002 verified.
- Orchestrator preflight is fail-closed (refuses: no registered v2 experiment).

## 26. CI run/job URLs

Branch CI at `d1dbb68`: M2B Replay and M3A Replay green; the `CI` (ruff/mypy/
pytest on 3.12 + 3.13) workflow re-run after the raw-string lint fix.
`https://github.com/panfot1409/gambling-winnings/actions` (branch
`claude/m3a-development-research-lab`).

## 27. Exact git status

Clean working tree at `d1dbb68`; branch ahead only by the closure commits listed
in §3, all pushed.

## 28. Remaining limitations

Five folds are weak evidence; every interval is an in-sample research diagnostic,
not annualized and not a profitability proof. Independent fold resets are a
comparison device, not a compounding path. One venue, one instrument, one daily
dataset. Computational sealing of the forbidden partitions is not epistemic
sealing. Commits are unsigned (no signing key is available) — an environment
limitation, not history to rewrite. The `v0.3.0` tag debt and the R7 installer
SHA pin are unrelated/environment-blocked.

## 29. Explicit confirmation

- PR #4 remains **draft**; nothing merged.
- No `v0.4.0` tag created.
- No candidate promoted.
- No development-gate authorization; no final-holdout authorization.
- No live/paper/wallet/exchange functionality.

## 30. Exact next scientifically honest step

Execute the run-003 sequence in §17 (pre-register → CI-green → run once through
the orchestrator → prove bit-identical financials → migrate replay/CI to the v2
alias → final CI green), then stop: do not spend the development gate, do not
evaluate the final holdout, do not merge PR #4, do not create a release tag.
