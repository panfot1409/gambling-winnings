# V2F §12 — does a lawful, unconsumed, non-sealed research partition exist?

**Determination: NO.** Every ETH-USD and BTC-USD partition committed to this repository is
already consumed, sealed by standing policy, or immature and not authorized for evaluation.
No new partition can lawfully be acquired while V2F-R containment is active.

The directive requires the single adaptive candidate to be evaluated **exactly once on a
lawful, unconsumed, non-sealed research partition**, and instructs: *do not spend the one-shot
if a valid partition cannot be established*. This document establishes that it cannot, and
records the evidence so a later reader can re-derive the conclusion rather than trust it.

Determined at `d1f2f80bcbc83b3027997aa3d829aeb3087e3b2d`, on branch
`claude/v2f-adaptive-selector-paper`, dated 2026-07-28. Every figure below was produced by
running the committed code or reading the committed artifact named beside it; nothing here is
inferred from an earlier document.

---

## 1. The complete partition inventory

Only one market-data CSV exists in the tree (`data/m2b/coinbase-eth-usd-1d.csv`); the BTC
series lives as committed raw candle bundles under `research/v2b/raw/coinbase/`. Together they
produce exactly five candidate partitions.

| # | partition | instruments | window (candle opens, UTC) | rows | status | disposition |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `research_train` / `m2b_train` | ETH-USD | 2016-05-23 → 2022-06-21 | 2221 | **consumed & formally exhausted** | unusable |
| 2 | V2B joint partition | ETH-USD + BTC-USD | 2016-05-23 → 2022-06-21 | 2221 | **consumed** (`v2b_run_001` completed) | unusable |
| 3 | `development_gate` / `m2b_validation` | ETH-USD | 2022-06-22 → 2024-06-30 | — | **sealed** | forbidden by directive §2.12 |
| 4 | `final_holdout` | ETH-USD | 2024-07-01 → 2026-07-11 | — | **sealed** | forbidden by directive §2.12 |
| 5 | M3D prospective cohort | ETH-USD | 2026-07-12 → 2026-07-14 | 3 | **unconsumed but immature and unauthorized** | unusable |

Partition 2 is not a sixth source of information: its `research_cutoff_last_open` is
`2022-06-21T00:00:00Z`, identical to partition 1's `last_open`. Adding BTC widened the
cross-section, it did not extend the timeline. Both were spent inside the same window.

## 2. Partition 1 — exhausted by a committed decision, not by my judgement

`research/m3d/research_train_exhaustion.json` classifies it
`"exhausted_for_new_candidate_research"` and lists, under `forbidden_operations`:

    new_candidate_generation      new_parameter_selection      new_performance_comparison
    new_statistical_inference     new_strategy_ranking         new_bootstrap
    select_candidate_for_development_gate                      relabel_specification_to_evade

Evaluating `adaptive_expert_mixer_v1` here is `new_candidate_generation` followed by
`new_performance_comparison` and `new_statistical_inference` — three named prohibitions in one
run. The last entry in that list matters independently: the directive's own §2.13 forbids
*rejected-candidate relabelling*, and the exhaustion record anticipates the same evasion.

`research/m3d/research_data_use.jsonl` independently records the consumption, one `data_use`
entry per milestone — `m2b`, `m3a`, `m3b`, `m3c` — each with `metrics_computed: true` and
`pnl_computed: true` against dataset fingerprint
`sha256:60aa988e…b12033`. `research/v2b/research_exposure_ledger.jsonl` adds `v2a` and `v2b`
family exposures on the same partition. Six milestones have already looked at it.

## 3. Partitions 3 and 4 — sealed, and verified untouched

Directive §2.12 names both: *no development-gate, final-holdout, M3D sealed-value, accepted
prospective-value, or other sealed-partition access.* That is dispositive on its own. The
seals are also intact — all three access ledgers are byte-empty, which
`eth_research.m3e.status` reports as machine-readable state:

    "ledgers": {
      "development_gate_byte_count": 0,
      "final_holdout_byte_count": 0,
      "prospective_evaluation_byte_count": 0
    }

`research/m3a/development_gate_access.jsonl`, `research/m2b/test_evaluations.jsonl` and
`research/m3d/prospective_evaluations.jsonl` are each 0 bytes on disk. The seals are unbroken;
the point is that opening them is exactly what the directive forbids.

One honest note on partition 3: M2B computed *validation* metrics over the same date window
(`partition: "m2b_validation"`, `metrics_computed: true`). So that window is both sealed as a
development gate **and** already partly consumed under its M2B name. Either fact alone
disqualifies it.

## 4. Partition 5 — the only unconsumed partition, and it is not evaluable

This is the one that has to be ruled out carefully, because "unconsumed" is true of it and a
careless reading stops there. Live output of `eth_research.m3d.status`:

    "maturity_state":        "immature",
    "row_count":             3,
    "minimum_maturity_rows": 365,
    "remaining_rows":        362,
    "evaluation_authorized": false,
    "evaluation_ledger_byte_count": 0

Four independent reasons it cannot carry the one-shot, each sufficient alone:

1. **It is 3 rows.** Three daily bars support no walk-forward, no fold structure, no bootstrap,
   and no honest interval on any statistic. A "result" from it would be noise with a p-value
   attached.
2. **Maturity is a year away.** `m3d.protocol.NOMINAL_MATURITY_LAST_OPEN` is
   `2027-07-11T00:00:00Z` — 348 days after today. Reaching it requires the suspended
   acquisition workflow to run daily for a year, which §5 shows it cannot.
3. **Maturity would not authorize evaluation anyway.** `v2c.maturity.MATURITY_POLICY` states
   `maturity_means_data_availability_only: true`, `maturity_authorizes_evaluation: false`,
   `evaluation_requires_separate_future_human_authorization: true`. The protocol restates it as
   `_FUTURE_EVALUATION_REQUIREMENTS = ('separate_human_authorized_milestone', 'new_protocol',
   'candidate_declared_before_access', 'new_single_use_evaluation_ledger')`. Three of those four
   are human or governance acts that no autonomous run may perform.
4. **The directive seals it.** §2.12 forbids *M3D sealed-value* and *accepted prospective-value*
   access by name, and `m3d.maturity.FORBIDDEN_OPERATIONS` — `evaluate`, `score`, `rank`,
   `backtest`, `compute_metrics`, `compare_performance`, `decide` — is the enforcing list.

## 5. No new partition can be acquired

The obvious escape is to acquire fresh data outside every existing partition. It is closed.

`.github/workflows/m3e-prospective-update.yml` is the only acquisition-capable workflow in the
tree. `governance/v2f/containment.json` has `active: true` with
`refuses_manual_dispatch_while_active: true` and `removes_schedule_trigger: true`. The gate is
not advisory — run live at this commit:

    $ .venv/bin/python tools/v2f_containment_gate.py --repo-root .
    V2F-R CONTAINMENT GATE: REFUSED
    market-data egress is SUSPENDED under V2F-R containment: ...
    exit=1

Lifting it requires all four of `lift_requires`:

1. an independently accepted containment and remediation review;
2. a completed third-party market-data rights assessment resolving redistribution;
3. the repository verified private through the GitHub API, not inferred from a committed artifact;
4. **an explicit human authorization recorded in this file as `active=false` with `lifted_by`
   and `lifted_on`.**

Item 4 is an owner-only act. Item 2 is an external legal assessment. Neither exists, and the
directive grants no authority to manufacture either — §2.15 forbids the history operations
that faking item 4 would require, and §2.2 keeps public-exposure containment permanently
enforced. Coinbase data remains classified
`internal_research_only_pending_written_redistribution_permission`.

Writing `active: false` myself would not be a workaround, it would be the exact
self-authorization the containment record exists to prevent.

## 6. Consequence for the one-shot

The one-shot is **not spent**. `adaptive_expert_mixer_v1` is neither qualified nor rejected —
it is *unevaluated*, and the distinction is load-bearing:

- A **rejected** candidate has been measured against preregistered criteria and failed. That is
  a scientific result and belongs in the negative-evidence index.
- An **unevaluated** candidate has no result at all. Recording it as rejected would fabricate
  evidence of a test that never ran, and recording it as qualified would be worse.

So the mechanical consequence is that `paper_activation_authorized` stays `false` and paper
trading stays disabled — the same *posture* as directive §2.9's rejection branch, reached for a
different reason, and the reason is stated rather than collapsed into the nearer-sounding label.

Derived state at this commit is unchanged and honest:

    authorized     : False
    trading_active : False
    sell_ready     : False
    blocking       : eligible_paper_candidate_present, candidate_lineage_valid,
                     strategy_specification_immutable, paper_release_candidate_frozen,
                     paper_duration_and_success_criteria_preregistered,
                     human_activation_approval_recorded

Note `human_activation_approval_recorded` is independently `false`. Even had a partition
existed and the candidate qualified, activation would still have been blocked on an owner act.

## 7. What is still in scope, and what is not

Nothing above blocks work that consumes no research partition. Still in scope and being built:

- §11 — `adaptive_expert_mixer_v1` and its scalar oracle, developed against **synthetic**
  series only, which is the established practice from V2A and V2B (both froze candidate source
  before touching real data).
- §13–15 — accounting, costs, risk, statistics; the private paper platform; the private
  dashboard. All verifiable on deterministic fixtures.
- §7 — the remaining remediation items.

Out of scope until a human resolves the gate:

- Any evaluation of any candidate on any of the five partitions.
- Any new market-data acquisition.
- Any paper-trading activation.
- Any `sell_ready` transition.

## 8. What would change this determination

Stated concretely so the owner knows exactly what unblocks the program, and so no future run
can claim the bar was met vaguely:

1. A completed third-party rights assessment resolving Coinbase redistribution, committed.
2. An independently accepted containment and remediation review.
3. Repository privacy verified through the GitHub API at the time of lift.
4. `governance/v2f/containment.json` set to `active: false` with `lifted_by` and `lifted_on`, by
   a human.
5. Then, and only then, a fresh forward acquisition window that is genuinely disjoint from
   partitions 1–5, preregistered before any evaluation.

Items 1–4 are the record's own `lift_requires`, unmodified. Item 5 is mine, and it matters: a
lifted containment would restore acquisition, but data acquired into the existing prospective
cohort inherits that cohort's separate evaluation prohibition. A lawful evaluation needs a new
partition with its own preregistration and its own single-use evaluation ledger.

## 9. Addendum, same day — a second closure record, found after §1–8 were written

While designing the candidate under §11 I found a governance record I had not consulted when
writing the sections above: `research/v2/research_partition_closure.json`. It does not change
the determination; it independently reaches it by a different route, and it forbids something
the candidate's natural design was heading straight toward. Recording it as a dated addendum
rather than editing the earlier sections, per this document's own rule.

    "closure_status": "closed_to_new_candidate_nomination_research"
    "closure_reason": "V2A nominated no ETH candidate (3 families) and V2B no cross-asset
                       candidate (2 families) under cumulative multiplicity; the historical
                       partitions are closed to further candidate-nomination research to
                       prevent strategy mining."

Its `forbidden_operations` list names, among others:

    evaluate_new_candidate            run_new_experiment
    evaluate_modified_candidate       open_new_research_budget
    recombine_and_claim_new_trial     claim_freshness_via_new_version
    read_sealed_to_choose_family      claim_freshness_via_new_benchmark

Two things follow.

**First, `evaluate_new_candidate` is forbidden outright.** That is the §12 operation, named. So
the historical partitions are closed by two independent records — the M3D exhaustion decision
(§2) and this closure — written at different times for different reasons. Neither depends on the
other, and neither depends on my reading of the other.

**Second, `recombine_and_claim_new_trial` is aimed precisely at the candidate I was about to
build.** The natural construction of an adaptive expert mixer is a weighted combination of
existing expert signals, and the obvious experts to hand are the three V2A families. All three
are recorded in `research/v2/negative_evidence_index.jsonl` as `research_stage_rejected`:

    v2a_meanrev_zscore_accumulation        research_stage_rejected
    v2a_trend_regime_single_horizon        research_stage_rejected
    v2a_vol_scaled_hold_drawdown_guard     research_stage_rejected

So a mixer over those three is a recombination of rejected families, and calling its evaluation
a fresh trial is the named prohibition. I want to be exact about the boundary rather than
comfortable:

- **Writing** the mixer is not forbidden. The closure governs evaluation, nomination and trial
  accounting, not the existence of source code. §11 of the directive instructs building it, and
  that instruction is unconditional.
- **Evaluating** it on the historical partitions is forbidden twice over — as
  `evaluate_new_candidate` and as `recombine_and_claim_new_trial`.
- **Claiming** its evaluation would be a new trial is forbidden by name.

There is also a scientific point independent of governance, and it is the more interesting one.
An adaptive mixture of the Hedge/exponential-weights kind carries a *relative* guarantee: its
regret against the best single expert in hindsight is bounded. It does not manufacture edge. If
every expert in the pool has already been measured and rejected, the mixture's best realistic
outcome is "approximately as good as the least bad rejected expert" — which is not a qualifying
outcome under any honest preregistered criterion. A mixer over rejected experts has a poor prior
by construction, and that belongs in a preregistration written before any result, not in a
discussion section written after one.

This does not change the terminal position: the one-shot is not spent, the candidate is built
and left unevaluated. It adds a third independent reason why, and it means any future attempt to
evaluate this candidate must clear the closure record as well as the containment record and the
partition problem.

## 10. Limits of this determination

- It is a statement about **this repository at this commit**. It does not assert that no data
  exists anywhere that could lawfully support the study.
- It reports the governance and legal posture as recorded in committed artifacts. It is **not a
  legal conclusion** about Coinbase's terms; the rights question remains open, which is exactly
  why containment is active.
- It was produced by the primary writer. An independent read-only audit of the same question is
  running in parallel; if that audit contradicts any figure here, the contradiction is recorded
  in a new dated section rather than by editing this one.
