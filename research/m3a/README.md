# Milestone 3A research records

Committable provenance records for the Milestone 3A **development research
laboratory**: a rigorous environment for developing future ETH strategy
candidates on a walk-forward protocol **without** abusing one validation
period and **without** ever touching the final holdout. No market data is
committed here — the dataset is reconstructed offline from the frozen
Milestone 2B raw Coinbase bytes (`../m2b/raw/coinbase/`). These files are
the immutable data-access model, the pre-registered protocol, the honest
research-train results, and the append-only experiment history.

## Three-level data-access model

The frozen M2B dataset (3 702 daily candles, 2016-05-23 .. 2026-07-11) is
split once, chronologically, into three immutable levels. Milestone 3A may
read **only** the research-train level; the development gate and the final
holdout are sealed here and their access ledgers stay byte-empty.

| level | window (UTC) | rows | M3A access |
| --- | --- | ---: | --- |
| research train | 2016-05-23 .. 2022-06-21 | 2221 | **evaluated** (development only) |
| development gate | 2022-06-22 .. 2024-06-30 | 740 | sealed — **not evaluated** |
| final holdout | 2024-07-01 .. 2026-07-11 | 741 | sealed — **not evaluated** |

## Status: research-train walk-forward run; gate and holdout sealed; no candidate promoted

| file | status | meaning |
| --- | --- | --- |
| `development_gate_access.jsonl` | **present, empty — pristine** | Append-only development-gate access ledger. Empty means **no development-gate access has ever occurred**. Empty SHA-256 `e3b0c442…b7852b855`. The final-holdout ledger lives at `../m2b/test_evaluations.jsonl` and is likewise byte-empty. |
| `development_partition.json` | **frozen** | The immutable three-level split, binding the frozen M2 dossier SHA-256, the dataset content fingerprint, and each level's row count and time bounds. |
| `walk_forward_protocol.json` | **pre-registered** | The expanding-window protocol: 1095 initial training rows, five contiguous OOS folds over the remaining 1126 rows (226, 225, 225, 225, 225), gap 0, context ≤ 55 bars, independent 10 000 USD per fold, the exact four fixed strategies, and the three predeclared cost scenarios. Bound to the committed partition. |
| `experiment_registry.jsonl` | **recorded** | Append-only experiment history (a schema-v1 prefix with a v2 append-chain). Carries three fixed-baseline experiments — run-001 and run-002 (v1) and the corrective run-003 (v2) — each `registered → started → completed`; each terminal event pins the SHA-256 of that run's published results, report, and their bundle. Experiment ids are single-use. |
| `development_results.json` | **recorded (run-003 v2)** | The compatibility alias for the latest completed experiment (run-003): the strict, byte-reproducible research-train walk-forward results (four strategies × three cost scenarios × five folds), three honest aggregation views, and the corrected fold-aware bootstrap intervals. Carries `experiment_id`/`methodology_id`; records zero development-gate and zero final-holdout events. |
| `development_report.md` | **recorded (run-003 v2)** | The honest Markdown report for run-003, rendered purely from the validated results model. |

## Closure remediation

A closure remediation (see `../../docs/M3A_CLOSURE_REMEDIATION.md` and the
bug-hunt table in `../../docs/M3A_BUG_LOG.md`) hardens the milestone:

- **Registry enforcement is inside the public execution path.** The only way
  to publish real research-train artifacts is the fail-closed
  `run_registered_development_experiment` orchestrator, which runs ordered
  pre-checks (repository/source/runtime/dossier/partition/protocol/methodology
  verification, both ledgers byte-empty, exactly one registered-only v2
  experiment) and appends a durable `started` event before any strategy,
  backtest, metric, or bootstrap runs. The unregistered `--write` path is gone.
- **Publication is a durable, rollback-safe batch transaction** (temp + fsync +
  ordered replace + manifest-last + directory fsync, reverse rollback),
  proven by a failure-injection matrix.
- **Registry schema v2** (version-dispatched, append-chained onto the immutable
  v1 prefix) and **results schema v2** (fully typed, strict-and-symmetric) make
  every result identify its exact experiment (`experiment_id`, `methodology_id`,
  execution source-tree fingerprint).
- **Fold-aware bootstrap.** Run-001 and run-002 used the historical moving-block
  bootstrap v1, whose blocks could cross independent-reset fold seams
  (116/1097 starts, ~10.57%). The corrective run-003 uses the primary
  fold-stratified bootstrap v2 (blocks strictly within a fold) plus a
  hierarchical fold-block sensitivity bootstrap; see
  `../../docs/M3A_BOOTSTRAP_METHOD_NOTE.md`.
- **Immutable history.** Run-001, run-002, and the corrective run-003 bodies are
  archived under `experiments/` and hash-verified against their registry events;
  they are never modified. Each run's per-run **return-evidence** artifact lets
  its pooled and bootstrap numbers be recomputed from raw daily observations.

All intervals remain in-sample research diagnostics over five folds — weak
evidence. No candidate is promoted; the development gate and the final holdout
remain sealed and their ledgers byte-empty. Unsigned commits are an
environment limitation (no signing key is available), **not** something to
repair by rewriting history; the missing `v0.3.0` tag is unrelated debt.

## Reproduce on a fresh clone

```bash
# Clone with full history (fetch-depth 0): --check binds the registration commit
# to git history, so a shallow clone cannot reproduce.
uv sync --locked --all-extras --python 3.12.3
uv run --no-sync python -m eth_research.develop_m3a --repo-root . --check
uv run --no-sync python .github/scripts/verify_m3a_registry.py
```

The first check dispatches on the latest completed experiment's schema: for the
corrective run-003 (v2) it regenerates the immutable v2 archive from the
committed raw bytes and the recorded commit identities, then byte-compares the
committed compatibility aliases and the archive; for a v1 latest it reconstructs
the dataset and reproduces the results and report byte-for-byte, binding the
registration commit label to the walk-forward protocol freeze commit in git
history. The second re-validates the registry lifecycle for all three
experiments and their binding to the published bytes. The `M3A Replay` workflow
runs both on the authoritative CPython 3.12.3 runtime and on Python
3.12 / 3.13, and asserts both access ledgers stay byte-empty.

## The firewall, in one paragraph

This is fixed-rule rolling-origin OOS evaluation with expanding information
sets — **no estimator is fit**. The expanding "training" row counts are the
information/history windows that define each fold's rolling origin and supply
indicator context; the fixed strategies are never fitted on them.

The evaluator loads **only** research-train rows. Every fold's training,
context, and out-of-sample frame is sliced positionally within the
research-train partition and guarded before it reaches a strategy or the
backtest engine: any row on or after 2022-06-22 (the development gate) is
rejected, and any gap, duplicate, or reordering is rejected. The four
strategies (cash, buy-and-hold, SMA 20/50, Donchian 55/20) are fixed and
were **never** optimized; the Donchian channels exclude the current bar
(`.shift(1)`), so signals are strictly causal. Test-suite firewall spies
assert no timestamp after 2022-06-21 ever reaches the M3A engine or a strategy.

One integrity re-derivation is disclosed for precision: loading the dataset
re-verifies the frozen M2B dossier, which recomputes M2B's *already published*
train+validation benchmark to prove it reproduces byte-for-byte. By construction
that runs the M2 validation segment — which is the development gate
(2022-06-22 .. 2024-06-30) — through the engine. It re-derives public M2B
numbers that are hash-compared and discarded, records **no** development-gate
ledger event, reveals nothing new to M3A development, and **never** touches the
final holdout; the research-train frame M3A evaluates is sliced and re-guarded
independently (`TestFrozenDossierReVerificationDisclosure`).

## Honest finding

Over the research-train period — an ETH bull market — **buy-and-hold
dominates median return**; the active strategies beat buy-and-hold in only
~40% of folds (a demonstration of temporal instability across a single
validation period). Under run-003's corrected **primary** bootstrap
(fold-stratified v2, whose blocks never cross an independent-reset fold seam),
the SMA and Donchian intervals of mean daily paired excess return versus
buy-and-hold still **straddle zero**; the one interval that excludes zero is
`cash`, and it does so on the **negative** (underperformance) side — the
opposite of alpha, and exactly what holding nothing versus a rising asset
should do. The wider hierarchical sensitivity straddles zero for every
strategy. No alpha is claimed, nothing was tuned, and losing folds and
severe-cost failures are retained exactly as computed. This is in-sample
development evidence, not live performance and not test performance. See
`../../docs/M3A_RUN003_BOOTSTRAP_COMPARISON.md` for the full-precision
v1/v2/hierarchical record.

The immutable run-003 report's Section 5 renders the cash primary upper bound as
`-0.00%` and states the universal "every … interval straddles zero", which is
false for the three cash primary cells. The immutable bytes are preserved; the
correction is recorded out-of-band by the machine-verified append-only erratum
`errata/m3a-run003-report-zero-inclusion-v1.json` (indexed in
`artifact_errata.jsonl`, verified by `verify_artifact_errata` and reported by
`develop_m3a --check` as `1 verified bound erratum`).

## Not authorized in Milestone 3A

No development-gate evaluation, no final-holdout evaluation, no candidate
promotion, and no signals on either sealed partition. No live or paper
trading, exchange authentication, wallets, transaction signing, leverage,
shorting, or fractional exposure. No parameter optimization, broad grids,
Bayesian search, or machine learning. Promoting a candidate would be a
separate, pre-registered process that spends exactly one recorded
development-gate access; the final holdout remains sealed and may be
consumed at most once, only for a promoted candidate under an independent
authorization.
