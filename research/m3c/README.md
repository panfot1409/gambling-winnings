# Milestone 3C — adaptive research governance and one preregistered experiment

This directory holds the governance layer and the single preregistered experiment
for **one** candidate strategy:

```
dual_horizon_trend_63_252_vol_target_30d_50pct
```

a 63/252-day dual-horizon trend-consensus signal composed with the reviewed
Milestone 3B 30-day / 50% annualized volatility target. The candidate, its
canonical fingerprint, the five-strategy benchmark grid, the three frozen cost
scenarios, the reused expanding-window folds with a common 252-bar context, the
frozen primary endpoint and its fold-seam-aware bootstrap, and the mechanical
seven-part promotion rule were all fixed **before** any candidate number was
computed. Nothing is optimized; no parameter is tuned; the engine cannot move
money.

## Files

| file | what it is |
| --- | --- |
| `research_lineage.json` | the adaptive research history (M3A/M3B families + this candidate) that motivates the one candidate — the reason a passing result is only *eligibility for review* |
| `research_budget.json` | the one-candidate budget: exactly one evaluation, no grid, no search |
| `protocol.json` | the frozen pre-registration: every constant + the lineage/budget/partition/dossier bindings (written at code-freeze E) |
| `experiment_registry.jsonl` | the append-only, hash-chained lifecycle log (`registered → started → completed`) |
| `candidate_results.json` | the strict 75-cell grid, aggregates, paired comparisons, primary bootstrap interval, and secondary PSR (published once) |
| `candidate_decision.json` | the mechanical P1–P7 promotion decision |
| `candidate_report.md` | the deterministic human report, leading with the decision |
| `experiments/run-001/manifest.json` | the immutable manifest binding the artifact digests + bundle + verdict to the registry lines |

The two **sealed access ledgers** — `research/m3a/development_gate_access.jsonl`
and `research/m2b/test_evaluations.jsonl` — stay byte-empty in every state. M3C
evaluates the research-train partition only; the development gate and the final
holdout are never accessed.

## Lifecycle (three committed, CI-green checkpoints)

1. **pristine** — protocol + empty registry committed, nothing executed.
2. **registered** — the `registered` event committed (registry-only), binding the
   committed protocol/lineage/budget digests.
3. **completed** — `registered → started → completed`, with the four immutable
   artifacts published and reproducible byte-for-byte.

## Reproduce

From a fresh clone, on the locked runtime (`uv sync --locked --all-extras`):

```bash
# Tri-state replay: pristine / registered / completed, byte-for-byte when published.
python -m eth_research.m3c.replay --repo-root . --check

# Comprehensive archive verification (re-derives results, decision, and report):
python -m eth_research.m3c.verify_archive --repo-root . --deep

# Crash-recovery status (a clean tree reports no pending intent):
python -m eth_research.m3c.recovery --repo-root . --status
```

The replay reconstructs the research-train partition offline from the committed
raw Coinbase bytes, re-runs the 5×3×5 grid through the one shared pipeline, and
requires the committed results, decision, and report to reproduce exactly —
including the fold-seam-aware bootstrap interval (seed `20260714`, 20 000
resamples). The mechanical decision is re-derived from the committed results and
must match byte-for-byte; a hand-edited outcome is rejected.

## Honest reading

A result here is a single, in-sample **research-train** measurement of one
**adaptively motivated** candidate. Even a passing primary yields **only**
`eligible_for_development_gate_review` — never "validated", "significant",
"alpha", or approval to trade. The independent development gate, sealed and never
touched in M3C, is the instrument that would address the adaptive history. See
`docs/M3C_STATISTICAL_METHOD_NOTE.md` for the estimator, the fold-seam-aware
bootstrap, and the deliberate omission of DSR and PBO/CSCV.
