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
| `experiment_registry.jsonl` | **recorded** | Append-only experiment history. Carries the fixed-baseline experiment as `registered → started → completed`; the terminal event pins the SHA-256 of the published results, report, and their bundle. Experiment ids are single-use. |
| `development_results.json` | **recorded** | The strict, byte-reproducible research-train walk-forward results (four strategies × three cost scenarios × five folds), three honest aggregation views, and the bootstrap intervals. Records zero development-gate and zero final-holdout events. |
| `development_report.md` | **recorded** | The honest Markdown report, rendered purely from the validated results model. |

## Reproduce on a fresh clone

```bash
uv sync --locked --all-extras --python 3.12.3
uv run --no-sync python -m eth_research.develop_m3a --repo-root . --check
uv run --no-sync python .github/scripts/verify_m3a_registry.py
```

The first check reconstructs the dataset from the committed raw bytes and
reproduces `development_results.json` and `development_report.md`
byte-for-byte, binding the registration commit label to the walk-forward
protocol freeze commit in git history. The second re-validates the registry
lifecycle and its binding to the published bytes. The `M3A Replay` workflow
runs both on the authoritative CPython 3.12.3 runtime and on Python
3.12 / 3.13, and asserts both access ledgers stay byte-empty.

## The firewall, in one paragraph

The evaluator loads **only** research-train rows. Every fold's training,
context, and out-of-sample frame is sliced positionally within the
research-train partition and guarded before it reaches a strategy or the
backtest engine: any row on or after 2022-06-22 (the development gate) is
rejected, and any gap, duplicate, or reordering is rejected. The four
strategies (cash, buy-and-hold, SMA 20/50, Donchian 55/20) are fixed and
were **never** optimized; the Donchian channels exclude the current bar
(`.shift(1)`), so signals are strictly causal. Test-suite firewall spies
assert no timestamp after 2022-06-21 ever reaches the engine or a strategy.

## Honest finding

Over the research-train period — an ETH bull market — **buy-and-hold
dominates median return**; the active strategies beat buy-and-hold in only
~40% of folds (a demonstration of temporal instability across a single
validation period), and every moving-block-bootstrap interval of mean daily
paired excess return versus buy-and-hold **straddles zero**. No alpha is
claimed, nothing was tuned, and losing folds and severe-cost failures are
retained exactly as computed. This is in-sample development evidence, not
live performance and not test performance.

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
