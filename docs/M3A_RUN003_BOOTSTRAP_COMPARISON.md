# run-003 bootstrap comparison (v1 vs fold-stratified v2 vs hierarchical)

run-003 corrects the bootstrap **seam handling** only. Every per-fold financial
result — all 60 fold cells and the 12 independent-fold / 12 pooled-reset / 12
full-train summaries — is **bit-identical** to run-002 (proven by
`eth_research.financial_equivalence`); the point estimates below are therefore
identical across all three methods. What changes is how the confidence interval
is resampled:

- **v1 (historical, run-001/002):** `moving-block-bootstrap-v1` over one
  concatenated series — blocks could cross the independent-reset fold seams,
  mixing observations from two folds into a single block.
- **v2 primary (run-003):** `fold-stratified-moving-block-bootstrap-v2` — blocks
  are drawn strictly within a fold, never crossing a seam.
- **hierarchical sensitivity (run-003):** `hierarchical-fold-block-bootstrap-v1`
  — resamples folds then blocks within them; deliberately unstable with only
  five clusters, reported as a sensitivity bound.

The statistic is the **arithmetic mean daily paired excess return versus
buy-and-hold** on the research train (2016-05-23 … 2022-06-21, 2221 rows, five
OOS folds of 226/225/225/225/225 observations, 1126 total). Intervals are 95%,
5000 resamples, block length 30, `numpy.random.Generator(PCG64)`.

## Effective RNG seeds (N7 corrected)

| method | base_seed | effective_rng_seed |
| --- | ---: | ---: |
| v1 moving-block | 20260713 | 20260713 |
| v2 primary fold-stratified | 20260713 | 20260713 |
| hierarchical sensitivity | 20260713 | **20260714** |

Run-001/002 recorded the hierarchical algorithm's seed as `20260713` while PCG64
was actually seeded `20260713 + 1 = 20260714` (defect N7). run-003 records the
exact effective seed for every interval.

## Intervals (all nine non-buy-and-hold cells)

`0∈CI` = does the interval contain zero. Width Δ = (v1 width − v2-primary width);
positive means the fold-stratified interval is **narrower**.

| strategy | scenario | point | v1 CI | 0∈v1 | v2 primary CI | 0∈v2 | hierarchical CI | 0∈hier | width Δ (v1−v2) |
| --- | --- | ---: | --- | :---: | --- | :---: | --- | :---: | ---: |
| cash | base | -0.2672% | [-0.5914%, +0.0087%] | yes | [-0.5064%, -0.0012%] | **no** | [-0.7592%, +0.2551%] | yes | +0.0949% |
| sma_20_50 | base | +0.0240% | [-0.1548%, +0.1650%] | yes | [-0.1318%, +0.1675%] | yes | [-0.1973%, +0.2651%] | yes | +0.0205% |
| donchian_55_20 | base | -0.0670% | [-0.2788%, +0.1123%] | yes | [-0.2291%, +0.1237%] | yes | [-0.3413%, +0.2530%] | yes | +0.0383% |
| cash | stressed | -0.2665% | [-0.5905%, +0.0089%] | yes | [-0.5064%, -0.0012%] | **no** | [-0.7592%, +0.2551%] | yes | +0.0942% |
| sma_20_50 | stressed | +0.0213% | [-0.1577%, +0.1631%] | yes | [-0.1354%, +0.1647%] | yes | [-0.2001%, +0.2620%] | yes | +0.0206% |
| donchian_55_20 | stressed | -0.0683% | [-0.2806%, +0.1108%] | yes | [-0.2313%, +0.1224%] | yes | [-0.3435%, +0.2515%] | yes | +0.0376% |
| cash | severe | -0.2645% | [-0.5887%, +0.0098%] | yes | [-0.5063%, -0.0010%] | **no** | [-0.7592%, +0.2551%] | yes | +0.0933% |
| sma_20_50 | severe | +0.0133% | [-0.1659%, +0.1547%] | yes | [-0.1457%, +0.1564%] | yes | [-0.2098%, +0.2521%] | yes | +0.0185% |
| donchian_55_20 | severe | -0.0722% | [-0.2856%, +0.1073%] | yes | [-0.2384%, +0.1172%] | yes | [-0.3507%, +0.2471%] | yes | +0.0374% |

## What changed, reported without cherry-picking

- **Width.** The v2 fold-stratified interval is narrower than v1 in every cell
  (width Δ positive throughout): removing seam-crossing blocks removes spurious
  cross-fold variance. The hierarchical interval is the widest everywhere —
  expected, and the honest sensitivity bound.
- **Zero-inclusion.** For `sma_20_50` and `donchian_55_20` the qualitative
  conclusion is unchanged across all three methods: every interval contains zero.
- **`cash` is the one qualitative change.** The v2 primary interval for `cash`
  marginally **excludes** zero — on the **negative** side (upper bound
  −0.0012% base/stressed, −0.0010% severe). This is the *opposite* of alpha: it
  says cash reliably **underperformed** buy-and-hold on a bull-trending research
  train, which is exactly what holding nothing versus a rising asset should do.
  It is **not** a promotable signal and claims no skill. The hierarchical
  sensitivity for `cash` still straddles zero, confirming the result is fragile.

## Precision caveat (report §5)

The committed run-003 report renders the `cash` primary interval as
`[-0.51%, -0.00%]` at 0.01% precision and its §5 summary states that every
interval "straddles zero." At the reported precision the `cash` upper bound
(−0.0012%) rounds to −0.00%, so the summary is defensible as stated; at full
precision that one interval excludes zero by 0.0012%, on the non-alpha
(negative) side, as tabulated above. The report is a single-use immutable
artifact bound to run-003 and reproduced byte-for-byte by `develop_m3a --check`;
it is not re-rendered here. This document is the full-precision record.

## Honest framing (required)

- Five folds are **weak evidence**; these intervals are **descriptive and
  unadjusted** (no multiple-comparison correction across nine cells and three
  methods).
- This is **research-train, in-sample development evidence** — not validation,
  not test, not live performance.
- **No alpha is claimed**, no profitability is claimed, nothing was tuned, and
  there is no promotion rule. No development-gate or final-holdout evidence
  exists or is authorized.
- The hierarchical sensitivity is **especially unstable** with five clusters and
  is reported only as a wider bound, never as the headline.
- The single interval that excludes zero (`cash` primary) does so on the
  underperformance side and is **not** validated alpha.
