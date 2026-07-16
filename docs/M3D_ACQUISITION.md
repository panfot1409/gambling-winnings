# M3D Acquisition Record — Prospective ETH-USD Daily Cohort

This is the factual record of how the Milestone 3D prospective cohort was
acquired. It is a **data-only** acquisition: no strategy, metric, ranking, or
decision was computed from the acquired candles.

## What was acquired

A strictly non-overlapping, future-only cohort of completed public Coinbase
Exchange ETH-USD **daily** candles beginning after the final M2B candle:

- Cohort start (fixed): `2026-07-12T00:00:00Z` — the first UTC midnight after the
  final M2B open (`2026-07-11T00:00:00+00:00`).
- Completed observations at freeze: **3** — opens `2026-07-12`, `2026-07-13`,
  `2026-07-14` (the `2026-07-15` candle was still forming and was excluded).
- Canonical content fingerprint:
  `bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507`.
- Maturity: **immature** (the maturity floor is 365 completed observations;
  362 remain). No eligibility, and no evaluation authorization, is implied.

## How it was acquired (network boundary)

Acquisition mirrors the reviewed M2B facility, scoped to the future window. The
network boundary is a **hardened `curl` step inside a one-shot GitHub Actions
workflow** (TLS-only, no cross-host redirect, fail-on-error, bounded body size,
explicit user agent, no secret / key / account / wallet / private endpoint). The
Python runner (`eth_research.m3d.acquire_runner`) is **offline only**: it emits
the fixed request parameters from a committed, validated plan and then strictly
validates the downloaded bodies offline, writing a receipt that records body
hashes and lengths — never candle values.

Because the workflow lived only on the stacked feature branch (never on the
default branch), `workflow_dispatch` was not dispatchable; the operative trigger
was a `push` that modified a single committed sentinel
(`research/m3d/acquire.trigger`), branch- and path-scoped — the same reviewed
bootstrap the M2B acquisition used.

## Two independent acquisitions

| | Genesis | Audit reacquisition |
|---|---|---|
| attempt id | `coinbase-eth-usd-prospective-genesis-001` | `coinbase-eth-usd-prospective-audit-002` |
| plan sha256 | `4b2be218…c88c8d9` | `ed978a6b…d3cb5eeb` |
| source commit | `02a92e8` | `c4aa95e9` |
| workflow run | `29424691776` | `29424930094` |
| request window | `[2026-07-12, 2026-07-14]` inclusive | identical |
| raw body sha256 | `866e7b5d…702355ae` | `866e7b5d…702355ae` (byte-identical) |
| canonical fingerprint | `bb6dd392…7966507` | `bb6dd392…7966507` (identical) |

The audit plan differs from the genesis plan only in `attempt_id` and the derived
`plan_sha256`; the request window, granularity, and raw filename are identical.
The independent reacquisition reproduced the canonical cohort exactly — same row
count, zero differing candles or fields — under distinct plan hashes, source
commits, and workflow runs (`research/m3d/reacquisition_audit.json`). This is an
integrity cross-check, never a performance comparison.

## The Coinbase inclusive-end fix

The first genesis run hard-stopped in offline validation: Coinbase's `/candles`
`start`/`end` query parameters are **inclusive bucket opens**, so a request with
`end == window_end` returns the still-forming candle whose open is `window_end`.
The reviewed M2B adapter already documents the correct convention (`start ==
window_start`, `end == window_end - 1 day` = the last completed bucket in the
half-open window). Three M3D sites conflated the inclusive request params with the
half-open parse window; they were corrected so the request covers
`[window_start, window_end - 1 day]` inclusive while parsing stays half-open
`[window_start, window_end)`. See `docs/M3D_BUG_LOG.md`. The corrected genesis
run and the independent audit run then succeeded and matched.

## Provenance chain (all re-derivable offline from committed raw bytes)

```
acquisition_plan.json ─┐
raw candle json ───────┼─► raw bundle (SHA-bound) ─► canonical OHLCV rows ─► cohort fingerprint
acquisition_receipt.json ─┘                                   │
                                                              ├─► prospective_segments.jsonl (hash chain)
                                                              ├─► prospective_quality.json (integrity only)
                                                              ├─► reacquisition_audit.json (genesis == audit)
                                                              └─► prospective_manifest.json (binds everything)
                                                                        └─► publication_manifest.json (completeness marker)
```

`python -m eth_research.m3d.replay --repo-root . --deep` rebuilds every artifact
byte-exact from the committed raw bytes and runs the 25-check whole-program graph
verifier, with all three ledgers byte-empty before and after.
