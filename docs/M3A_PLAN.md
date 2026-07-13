# Milestone 3A — Development-Only Walk-Forward Research Laboratory

Research-only. This milestone builds methodology and accountability, not a
promotable candidate. It makes **no** profitability claim, produces **no**
test result, and touches **neither** the development gate nor the final
holdout.

## Motivation

Milestone 2B froze a real Coinbase Exchange ETH-USD daily history, sealed a
one-time test holdout, and recorded that the fixed SMA(20/50) is
`rejected_for_test_promotion` — it materially underperformed buy-and-hold in
the M2 validation period (−203.19 pp). The lesson is methodological: a single
validation period, reused repeatedly, is a scarce resource that ordinary
iterative development silently burns. M3A builds an environment where future
candidate families can be developed and stress-tested **without** repeatedly
abusing one validation period and **without** ever touching the final
holdout.

The test remains sealed: nothing in M3A constructs a final-holdout
authorization, evaluates the holdout, or computes any test performance.

## Three-level data-access model (immutable)

The 3702-row canonical dataset partitions mechanically into three
contiguous, non-overlapping levels:

| level | name | dates (UTC, inclusive) | rows | M3A access |
| --- | --- | --- | ---: | --- |
| 1 | research train | 2016-05-23 .. 2022-06-21 | 2221 | reusable for exploration, synthetic dev, the fixed baseline experiment, debugging |
| 2 | development gate | 2022-06-22 .. 2024-06-30 | 740 | **forbidden** (the M2 validation period; spent later via a separate pre-registered process) |
| 3 | final holdout | 2024-07-01 .. 2026-07-11 | 741 | **absolutely forbidden** |

Permitted operations on the two forbidden partitions are integrity-only:
schema validation, mechanical splitting, row count, time boundaries, and
opaque content fingerprints. No market value from either forbidden partition
may reach a strategy or the backtest engine. No frozen M2 artifact may be
silently modified.

## Module architecture

- `eth_research.development` — the data firewall: `DevelopmentPartition`,
  `DevelopmentDataset`, `DevelopmentBoundary`, `DevelopmentAccessError`. It
  derives the three partitions mechanically from verified M2 data + protocol,
  hands downstream code the research-train rows **only**, and rejects any
  frame or context carrying a row after 2022-06-21.
- `eth_research.walkforward` — the pre-registered expanding walk-forward
  protocol and its strict models.
- `eth_research.strategies.cash`, `eth_research.strategies.donchian` — the
  two new fixed baselines (cash and Donchian(55/20)); SMA and buy-and-hold
  are reused unchanged.
- `eth_research.costs` — the three predeclared cost scenarios.
- `eth_research.bootstrap` — the deterministic moving-block bootstrap.
- `eth_research.development_evaluation` — the walk-forward evaluator, strict
  result models, honest aggregation, and the report renderer.
- `eth_research.development_ledger`, `eth_research.experiment_registry` — the
  development-gate access ledger and the experiment registry.
- `eth_research.replay_m3a` — fresh-clone reproduction.

## Strict model schemas

Every committed artifact is a frozen dataclass validated in `__post_init__`
through the shared `require_*` validators, serialized deterministically
(sorted keys, indent 2, trailing newline, `allow_nan=False`), and parsed
through the strict `strict_json_loads` decoder (duplicate keys, NaN/Inf,
bool-as-int, and unknown keys all rejected). A model that constructs is a
model that parses, and vice versa.

## Walk-forward semantics

This is **fixed-rule rolling-origin out-of-sample evaluation with expanding
information sets — no estimator is fit**. The expanding "training" row counts
below define each fold's rolling origin and provide indicator history/context;
the fixed strategies are never fitted on them (there is no parameter estimation
step anywhere in this milestone).

Research train (2221 rows) only. Initial information/history window 1095 rows;
five contiguous expanding-window OOS folds tile the remaining 1126 rows as
evenly as possible (226, 225, 225, 225, 225). Every research-train row belongs to
the initial training block or exactly one OOS fold — no overlap, no gap, no
shuffle. Information gap 0 bars (no ML label horizon exists; a signal from
the prior close executes at the next open). Context for a fold comes only
from rows strictly before its OOS start, capped at 55 bars, and contributes
no P&L. Each fold resets to an independent 10,000 USD — a comparison device,
**not** one continuously traded portfolio. Both marked and hypothetical
liquidation equity are reported.

## Cost-stress semantics

Every strategy is evaluated under all three **predeclared** cost scenarios;
no scenario is selected after seeing results:

| scenario | fee_rate | slippage_rate |
| --- | ---: | ---: |
| base | 0.001 | 0.0005 |
| stressed | 0.002 | 0.001 |
| severe | 0.005 | 0.0025 |

No frictionless headline scenario. Marked and liquidation-adjusted returns
are always reported side by side; the marked figure is never silently
substituted for the liquidation figure.

## Bootstrap semantics

Moving-block bootstrap (`moving-block-bootstrap-v1`) on paired daily OOS
excess returns versus buy-and-hold: seed 20260713, block length 30, 5000
resamples, 95% interval, statistic = arithmetic mean daily paired excess
return, non-circular, with replacement, `numpy.random.Generator(PCG64)`
recorded exactly. It quantifies sampling variability of an in-sample
research-train diagnostic; it is not a profitability proof and its interval
is not annualized.

## Experiment registry + development-gate ledger

`research/m3a/experiment_registry.jsonl` records every real-data M3A
experiment (registered → started → completed/failed), including failures,
with output hashes verified before `completed`. Exactly one family is
registered: `m3a-fixed-baseline-comparison-v1`.

`research/m3a/development_gate_access.jsonl` is a **separate**, strict,
append-only future-use ledger for the development gate. It begins and ends
M3A **byte-empty**; no real event is appended in M3A. The M2 final-holdout
ledger also stays byte-empty. CI asserts both.

## Replay design

`python -m eth_research.replay_m3a --check` on a fresh clone: replay/verify
M2, verify the frozen M2 dossier, derive the development partition, exercise
the firewall, load the committed protocol, regenerate all permitted fold
results + bootstrap + report, compare every committed byte/hash, verify the
registry, and assert both access ledgers unchanged.

## CI plan

`.github/workflows/m3a-replay.yml`: authoritative CPython 3.12.3 +
compatibility 3.12/3.13, frozen `uv.lock`, actions pinned by full SHA,
read-only permissions, no secrets, no Coinbase contact, no contents write,
no market-data artifacts uploaded, exact ledger hashes asserted before/after.

## Active bug-hunt plan

After ordinary tests pass, deliberately attack: data-boundary slicing,
look-ahead (centered/current-bar Donchian, same-bar execution, overnight-gap
capture), accounting (negative cash, hidden leverage, cost monotonicity,
terminal liquidation, fold reset), statistics (misalignment, RNG drift,
forbidden observations), registry/publication (out-of-order events, omitted
failure, truncated registry, overwrite), and report truthfulness (rederive
every table from JSON, label discipline). Each genuine bug gets a failing
regression test, a root-cause fix, and a bug-hunt-table entry.

## Exact exclusions

No development-gate or final-holdout evaluation; no signals on either
forbidden partition; no live/paper trading; no exchange auth; no wallets or
transaction signing; no leverage; no shorting; no fractional exposure; no
parameter optimization, grids, Bayesian optimization, or ML; no new strategy
beyond the four fixed identities; no merging the M3A PR; no v0.4.0 tag.

## Expected commit sequence

1. This plan. 2. Version 0.4.0. 3. Firewall + partition. 4. Gate ledger.
5. Walk-forward protocol. 6. Cash baseline. 7. Donchian baseline. 8. Cost
scenarios. 9. Fold diagnostics. 10. Deterministic bootstrap. 11. Experiment
registry. 12. Evaluator + result models. 13. Pre-register experiment. 14.
Boundary/look-ahead red team. 15. Run real experiment. 16. Publish report.
17. Replay command. 18. Replay CI. 19. Hygiene/security tests. 20. Docs. 21.
Separate fixes for genuine bugs. Small commits, no amend/squash/rebase/
force-push, safe checkpoints pushed, CI inspected repeatedly.

## Threat model

Accidental development-gate slicing; accidental final-holdout slicing;
computing strategy signals on the full frame before slicing; context crossing
a forbidden boundary; fold overlap; fold gaps; future-dependent indicators;
same-bar execution; current-bar Donchian-channel leakage; cost-scenario
cherry-picking; parameter-search laundering; omitted failed experiments;
registry rewriting; result/protocol mismatch; fold-reset distortions; fake
stitched equity; terminal-position cost omission; bootstrap instability;
report/model divergence; compatibility-runtime numerical drift; reliance on
ignored local files; misleading statistical language. Each is countered by a
firewall check, a strict schema, an accounting reconciliation, a determinism
pin, or a red-team test named in the bug-hunt table.

## Hard stop conditions

Stop immediately and report if: a development-gate or final-holdout row
reaches a strategy/backtest; either access ledger changes unexpectedly; folds
overlap; committed results cannot reproduce; the frozen M2 dossier fails; or
final CI stays red. Never evaluate the gate or holdout, never optimize
parameters, never add live/paper/wallet/auth functionality.

## Honest limitations

Research-train walk-forward is in-sample development evidence, not live
performance and not test performance. The fixed Donchian(55/20) parameters
are declared, never optimized. Independent fold resets are a comparison
device, not a tradable compounding path. The pooled-reset OOS series is a
diagnostic concatenation, not a continuously traded portfolio. The bootstrap
quantifies sampling variability only; it does not prove alpha or remove
uncertainty. One venue, one instrument, one daily dataset. Computational
sealing of the forbidden partitions is not epistemic sealing — the human
operator knows the broad 2022-2026 market history.
