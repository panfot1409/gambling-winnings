# V2 Negative-Evidence Synthesis

Descriptive aggregation over the cumulative negative-evidence index
(`research/v2/negative_evidence_index.jsonl`) and the frozen family catalog. It restates, in prose,
what the committed records already hold. It performs no new strategy calculation, and it does not
pool incompatible experiments into a meta-analysis. Every statement below traces to a record's
decision, status, criteria vector, or bound digest.

## Scope

Twelve families are indexed: ten candidate families and two benchmark references. The ten candidates
are eight historical families (M3A SMA and Donchian, M3B two volatility-target overlays, M3C
dual-horizon trend, and three V2A families) plus two V2B cross-asset families. The two benchmarks
(passive ETH buy-and-hold and cash) are comparators, not candidates, and are excluded from the
cumulative alpha budget.

Status distribution across the twelve records: `benchmark_only` (2), `not_eligible` (2),
`risk_reduction_observation` (2), `rejected_for_promotion` (4), `no_nomination` (2).
The status set is closed; decisions are preserved exactly, never flattened to one "failed" label.

## Broad hypotheses tested

- Moving-average crossover trend following (M3A SMA 20/50).
- Channel-breakout trend following (M3A Donchian 55/20, reused as an M3B/M3C baseline).
- Volatility targeting laid over passive hold and over breakout (M3B, 30-day 50% target).
- Dual-horizon trend consensus composed with a volatility target (M3C, 63/252-day).
- Mean-reversion z-score accumulation (V2A).
- Single-horizon trend-regime gate (V2A).
- Volatility-scaled hold with a drawdown guard (V2A).
- BTC-confirmed ETH trend, a genuinely new cross-asset input (V2B).
- ETH/BTC relative-strength rotation, cross-sectional (V2B).

## What was rejected, and why

- M3A SMA and Donchian are recorded `not_eligible`: fixed-rule diagnostics, no promotion pathway.
  Their paired excess-return intervals versus buy-and-hold span zero.
- M3C dual-horizon trend is `rejected_for_promotion`: its mechanical seven-part rule failed the
  primary lower-bound criterion (P1) and the fold-majority criterion (P2), so it did not promote.
- The three V2A families are `rejected_for_promotion`: none cleared the primary lower-bound gate,
  and none cleared the stressed-robustness gate, so no candidate was nominated.
- The two V2B cross-asset families are `no_nomination`: neither cleared a full gate under
  the cumulative multiplicity correction, so no cross-asset candidate was nominated.

## Risk reduction without excess return

The two M3B volatility-target overlays are recorded `risk_reduction_observation`. The overlay cut
realized drawdown relative to buy-and-hold, yet the overlaid families did not beat buy-and-hold on a
majority of folds and earned no measured excess return. Risk was reshaped, not converted to alpha.

## Temporal instability

M3A is the clearest instability signal: over a single research-train interval that was an ETH bull
market, the active strategies beat buy-and-hold in only about 40% of folds. Performance that depends
on which fold is examined is weak evidence, and the index preserves the losing folds exactly.

## Failure under realistic costs, uncertainty, robustness, and multiplicity

- Costs: every candidate was scored under multiple predeclared cost scenarios (base and stressed
  variants, plus causal execution proxies). None survived to promotion under them.
- Uncertainty: the primary endpoint is a bootstrap interval on paired log excess return; the
  lower bound sat at or below zero for each promoted-primary check.
- Robustness: V2A stressed-robustness gates and V2B sensitivity, latency, and stressed gates all
  came back negative.
- Multiplicity: V2B applied a cumulative family-wise correction over every family ever evaluated;
  the corrected lower bound did not clear zero.

## What remains unknown

- The development gate and the final holdout were never opened; both sealed access ledgers are
  byte-empty and every record carries `sealed_data_touched=false`.
- Prospective data has not been collected; the prospective evaluation ledger is empty.
- Whether any tested structure would hold on an unseen partition is therefore untested and unknown.

## The narrow conclusion

No evaluated candidate has earned access to a sealed development gate under the project's
preregistered standards.

## What this evidence does NOT claim

- It does not claim technical analysis never works.
- It does not claim momentum never works.
- It does not claim crypto markets have no exploitable structure.
- It does not claim that all future candidates will fail.
- It does not claim buy-and-hold is alpha.
- It does not treat accumulated negative evidence as proof of future failure.
