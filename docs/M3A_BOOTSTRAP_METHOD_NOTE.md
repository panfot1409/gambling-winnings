# M3A bootstrap method note — reset seams and fold-aware resampling

## What the interval describes

The bootstrap quantifies the sampling variability of one in-sample research-train
diagnostic: the observation-weighted arithmetic **mean daily paired excess
return** of a candidate strategy versus buy-and-hold, over the pooled OOS
observations of the five expanding-window walk-forward folds. It is not a
profitability proof, it is not annualized, and it removes no uncertainty.

## Independent-reset semantics and the four seams

Each of the five OOS folds is evaluated as an **independent** portfolio reset to
10,000 USD. Fold *k*'s daily return process is not a continuation of fold
*k − 1*'s: the equity is reset, the position is re-warmed from context, and the
first OOS bar pays a fresh entry cost. Concatenating the five folds' daily paired
excess returns end to end therefore introduces four **reset seams** at the fold
boundaries (after 226, 451, 676, and 901 pooled observations).

## The v1 defect (R4)

`moving-block-bootstrap-v1` drew moving blocks of 30 consecutive observations
over the single 1126-long concatenation. Of the 1097 possible block start
positions, **116 (~10.57%)** produce a block that spans one of the four reset
seams, and each 38-block resample contains **~4.02** seam-crossing blocks on
average. Those blocks glue the tail of one independently reset path to the head
of the next as though the return generation were continuous across the seam,
which it is not. This overstates the effective within-block dependence structure
and is scientifically wrong for independently reset folds.

v1 and its published intervals are **preserved unchanged** for run-001 and
run-002 as historical evidence. They are not silently replaced or relabelled.

## The corrected primary method — `fold-stratified-moving-block-bootstrap-v2`

The input is an ordered tuple of per-fold paired-excess series. Each resample
replaces every fold with a within-fold moving-block resample of its own length
(non-circular, drawn from that fold's `n − block + 1` starts, truncated to `n`),
concatenates the five resampled folds, and takes the observation-weighted mean.
**No sampled block can span two folds**, because blocks are only ever drawn
inside a single fold. Each fold contributes its original observation count, the
statistic is unchanged, and `block_length > min fold length` is refused (never
silently shortened). The configuration — block length 30, 5000 resamples, 95%
interval, seed 20260713, PCG64 — was frozen and CI-green before run-003 executed.

## The sensitivity method — `hierarchical-fold-block-bootstrap-v1`

A separate, clearly labelled sensitivity diagnostic resamples the five folds as
**clusters with replacement**, then draws within-fold blocks inside each selected
fold, on a domain-separated RNG stream (seed 20260714). It probes how sensitive
the interval is to the particular five folds observed. With only **five
clusters** this gives weak fold-level inference and is reported as sensitivity
only — never as the primary interval or a decision rule.

## Why the method is fixed by design, before seeing the corrected intervals

The corrected algorithm, its configuration, and this note were committed and
green in CI **before** run-003 computed any corrected interval. The choice was
not "whichever method produces the nicer interval": run-003 reports the v1
historical interval, the v2 primary interval, and the hierarchical sensitivity
interval together, including the one inconvenient change that did materialize —
the fold-stratified `cash` interval marginally **excludes** zero, on the
**underperformance** side (the opposite of alpha). See
`M3A_RUN003_BOOTSTRAP_COMPARISON.md` for the full-precision record.

## Limitations that no bootstrap removes

Five chronological folds are a small sample of regimes; the intervals are
in-sample research-train diagnostics; several strategy/scenario cells are shown,
so intervals are **descriptive and unadjusted for multiple comparisons** unless a
pre-registered simultaneous-inference method is added, and must never become a
promotion rule. No bootstrap — v1, v2, or hierarchical — can establish alpha or
live profitability.
