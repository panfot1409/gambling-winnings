# adaptive_expert_mixer_v1 — pre-freeze semantic red team

Directive item 4 requires the candidate's *actual* mathematical and economic semantics to be
red-teamed before freezing, and any inconsistency fixed before E with the preregistration
regenerated append-only through an explicit supersession.

Two inconsistencies were found. Both are between what
`governance/v2f/adaptive_expert_mixer_v1_preregistration.json` **claims** and what
`src/eth_research/v2f/mixer.py` **does**. Neither is a bug in the sense of a crash or a wrong
number; both are places where the frozen commitment would have described a different algorithm
than the one that ran. A preregistration cannot be corrected after it is spent, which is why this
had to happen now.

**The candidate remains unevaluated. Nothing below was learned from market data.** Every figure
comes from synthetic series constructed to exercise a specific mechanism, and no research
partition was opened.

---

## Provenance of these findings, stated honestly

A 13-agent adversarial workflow was launched against the candidate. **Four agents completed; nine
died on an account spend limit**, including *every* refutation agent and the synthesizer. So the
adversarial-refutation stage of the intended design never ran.

That matters for how much weight these findings can carry, and the honest answer is: they carry
the weight of my own independent reproduction, not of a surviving adversarial process. I
re-derived both findings from scratch with my own inputs rather than accepting the agent's. The
reproductions below are what I executed; where my numbers differ from the agent's, mine are the
ones recorded.

A skipped verification is never reported as passed. **The refutation stage is outstanding.**

---

## MSF-1 — the preregistered uniform prior is never the prior at any tradeable bar

**Status: confirmed by independent reproduction. Blocking before freeze.**

### The claim in the preregistration

> `"initial_weights": "uniform 1/N, the maximum-entropy prior"`

### What actually happens

`target_positions` masks the warm-up *output* — it holds cash until `WARMUP_BARS` — but `run_mixer`
runs the full Hedge update across the warm-up anyway. So the weights entering the first tradeable
bar are 200 bars of updates driven by experts that had no opinion to express.

`trend_signal_at` returns `0.0` while `len(closes) < TREND_HORIZON`. That is bitwise identical to
cash's hard-coded `0.0`. Identical exposures produce identical losses, so the two weights move in
lockstep for the entire warm-up:

```
WARMUP_BARS = 200
w_trend == w_cash BITWISE for t in [0,200): 200/200
  t=199 w_trend=0.4991592237629742
  t=199 w_cash =0.4991592237629742
  distinct trend exposures during warm-up: [0.0]
```

The trend expert spends the warm-up carrying cash's record for an opinion it never held. And by
the first tradeable bar the prior is gone:

```
weights entering FIRST TRADEABLE bar t=200:
    meanrev_zscore             0.001681
    always_long                0.000000
    single_horizon_sma_gate    0.499159
    cash                       0.499159
  total-variation distance from uniform 1/N: 0.4983
  eta(1)=3.3302  eta(200)=0.2355
```

`always_long` is at `0.000000` before a single tradeable bar. It cannot recover, because `eta` has
already decayed by an order of magnitude — the learning rate that would let a crushed expert climb
back is spent on bars nobody traded.

### Why it matters

This is an undeclared initialization rule. The preregistration freezes "uniform 1/N", which is true
only at bar 0, a bar that is never traded. The rule that actually governs the first tradeable bar is
"whatever 200 bars of sentinel-driven updates produced", which is path-dependent, half a
total-variation unit from uniform, and was never written down. §2.14 forbids exactly this class of
silent structural choice.

The existing suite cannot see it. The one behavioural test uses `drift=0.004, vol=0.005` — a
strongly trending regime where `always_long` wins the warm-up outright — so the degenerate case
lies outside the only regime tested.

### Fix, and why it introduces no fitted constant

Suppress the weight update while any expert is still unwarmed. `WARMUP_BARS` is already derived as
the maximum over expert warm-ups, so no new number enters the specification; the code simply starts
matching the preregistration text that is already written. The source pin must be regenerated and
the preregistration superseded append-only.

---

## MSF-2 — the mechanism named as the sole source of edge cannot operate in the regime it was named for

**Status: confirmed by independent reproduction, more strongly than reported. Blocking before
freeze.**

### The claim in the preregistration

> The cash expert is the only element making the pool strictly richer than any constituent — a
> mixture can decline to participate. **Any genuine improvement would have to come from there.**

### What actually happens

Under the 0/1 directional loss, `log(w_cash / w_always_long)` is a *bar-count* race:
`sum over down-bars of eta_s` minus `sum over up-bars of eta_s`. There is no magnitude term. Cash
therefore gains weight only when down-bars **outnumber** up-bars — which is not the same condition
as "holding cash would have been better".

For a negatively skewed asset — frequent small gains, occasional large losses, the defining shape
of crypto returns — those two conditions come apart completely:

```
  up bars 567 / down bars 332  (up-bars OUTNUMBER down-bars)
  buy-and-hold total return: -82.5%
  final w_cash        = 0.000000
  final w_always_long = 1.000000
  fraction of tradeable bars the mixture is LONG: 1.000
  cash alternative return over the same window  : +0.0%
```

The mixture is fully long on every tradeable bar of a path that loses 82.5%, while the expert that
would have preserved capital is at exactly zero weight.

Magnitude blindness at trajectory level makes the point sharper. Two series sharing one sign path,
one ending +5.9% and one ending −100%:

```
  mild : terminal return  +5.9%   final w_cash/w_always_long = 2.7994900858624893e-05
  harsh: terminal return -100.0%  final w_cash/w_always_long = 2.7994900858624846e-05
```

Agreement to fourteen significant figures. The residual is float rounding in the per-bar
normalization, not signal. **A total wipeout and a modest gain are the same event to this loss
function.**

### Why it matters

`mixer.py` justifies charging cash an opportunity cost as "what stops `cash` from winning by
default in a rising market". That justification is sound. Its symmetric consequence was never
stated: the same charge stops cash from winning in a *falling* market whenever the losses arrive by
magnitude rather than by frequency.

The preregistration does not merely overstate the mechanism's strength — it already declares the
prior weak and honest. It misdescribes the mechanism. It names cash as the one place a genuine
improvement could come from, and cash is structurally unable to deliver one on the return shape
this candidate would actually be pointed at.

### Fix

Correct the preregistration, not the loss. The 0/1 directional loss is the textbook Hedge loss and
the regret bound is stated for it; replacing it with a magnitude-weighted loss would be a different
algorithm needing its own derivation, and choosing that weighting after seeing which one behaves
better on synthetic paths is the parameter-selection-after-viewing-results this project forbids.

The honest supersession states the derived fact — under a 0/1 directional loss the cash expert
gains weight only when down-bars outnumber up-bars — and withdraws the claim that cash is a
plausible source of improvement on a negatively skewed series.

---

## Secondary observation: the pool is often unable to go long at all

Cash's guaranteed flat vote imposes a ceiling `mixture_weight <= 1 - w_cash`, so once cash holds
half the weight, a unanimous long vote from the other three cannot clear the strict 0.5 threshold.

```
  of 200 GBM paths: 1 never goes long, 9 go long on <5% of tradeable bars
```

Recorded rather than actioned. This is a consequence of Weighted Majority with a strict-half rule
and a guaranteed abstainer, not a defect, and MSF-1's fix changes the weight distribution at the
first tradeable bar, so any measurement taken now would be superseded. It should be re-measured
after MSF-1 is fixed and before freeze.

---

## What is NOT claimed

- Not claimed that either finding is a coding error. `run_mixer` computes what it says it computes.
- Not claimed that the candidate has been evaluated, or that anything is known about its
  performance on real data. It has not, and nothing is.
- Not claimed that these two are the complete set. Nine of thirteen red-team agents died before
  reporting, including all refuters; the sub-questions they carried — cost asymmetry, degenerate
  ties/zero-return/missing-bar handling, and the independent scalar reimplementation — were **not
  answered**, and item 4 lists them explicitly.
- Not claimed that fixing MSF-1 makes the candidate promising. Hedge's guarantee is relative regret
  against the best expert in hindsight; three of the four experts are recorded
  `research_stage_rejected`. The preregistered honest prior stands.
