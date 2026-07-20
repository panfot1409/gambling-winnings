# V2B §26 pre-registration red-team — bug log

Five independent auditors reviewed the frozen V2B research machinery **before** the source freeze
(E), the registration (R), and the one authorized research-train execution (P), and **before** any
real ETH/BTC observation was read (the sealed-data firewall was intact throughout). The red team's
purpose is to close every Class A / Class D defect while the design can still be corrected without
consuming the one-shot budget.

**Outcome:** exactly one Class A finding and zero Class D findings. The Class A is fixed below,
together with a linked Class B design flaw it exposed and every Class C hardening item. Each fix
ships with a regression test that fails against the pre-fix code and passes after. The whole battery
(`ruff check .`, `ruff format --check .`, `mypy src tests examples`, `pytest`) is green.

No frozen *accepted* artifact (M2B/M3x/M4x/V2A) and no committed V2B research artifact
(`research/v2b/*`) was modified; all fixes are to `src/eth_research/v2b/*` source and `tests/*`.

---

## Class A — anti-conservative Monte-Carlo sign-flip p-value (Auditor C, Finding 1)

**File:** `src/eth_research/v2b/statistics.py` — `mc_sign_flip_p_value` (gate 6 input).

**Defect.** The observed statistic was computed with Python's `sum()` (in raw fold order) while every
permuted statistic used numpy's `.sum(axis=1)` (in sorted order). The two disagree at the last ULP,
so for an all-positive candidate the sampled identity draws (all `+1`) could fail `>= observed` and
be dropped, collapsing the p-value from the correct ~`1/2**k` toward the floor `1/(resamples+1)`.
The error is strictly one-sided in the anti-conservative direction — it never wrongly blocks, only
ever wrongly passes — which is the worst direction for a Type-I safeguard. A demonstrated
`None → nominate` flip was possible on a synthetic panel.

**Fix.** The observed statistic is now produced as the all-`+1` row of the **same**
`(signs * sums).sum(axis=1)` reduction that produces every permuted statistic (row 0 of a stacked
matrix), so the identity draw is bit-for-bit equal to `observed` and always counts in its own upper
tail. No summation-method mismatch remains.

**Regression:** `tests/test_v2b_statistics.py::`
`test_observed_configuration_counts_in_its_own_tail_no_ulp_dropout` — a two-block space whose
all-`+1` configuration is the unique maximum returns p ≈ 0.25 (reached by ~1/4 of draws), never the
~5e-5 collapse.

---

## Class B — gate 6 was uncrossable by a correct computation (Auditor C, Finding 2)

**Files:** `src/eth_research/v2b/statistics.py`; threshold in `src/eth_research/v2b/nomination.py`
(`mc_supports` iff `mc_p_value <= corrected_alpha`, with `corrected_alpha = 0.05/10 = 0.005`).

**Defect.** A **whole-fold** sign-flip over six folds has only `2**6 = 64` sign configurations, so
the smallest achievable *correct* permutation p-value is `1/64 = 0.0156 > 0.005`. Gate 6 was
therefore impossible to satisfy by a correct computation, which made the *only* path through it the
Class A floating-point artifact — and, once that artifact was removed, made a nomination structurally
impossible regardless of the data. Preregistering a gate that cannot be satisfied is not conservative,
it is vacuous.

**Fix.** The flip unit is now a **non-overlapping contiguous block** of the accepted
`floor(n**(1/3))` length (taken within a fold so a block never crosses a fold seam), not a whole
fold. This gives the pooled statistic full-sample resolution (~300 blocks ⇒ a floor far below
0.005), so gate 6 is crossable *in principle* by a strong enough edge, while still preserving the
within-block autocorrelation the accepted moving-block bootstrap respects. The strict corrected
`0.005` threshold is **unchanged** — the fix strengthens resolution, it does not relax the bar, and
it introduces no new free parameter (the block length is the accepted one). Because gate 6 remains
conjunctive with the rigorous family-wise-corrected bootstrap (gate 5), overall Type-I control is
governed by gate 5 and is not weakened.

Observation-level sign-flipping was rejected: it would break the return autocorrelation and make the
test anti-conservative — the wrong direction for a backstop.

**Regression:** `tests/test_v2b_statistics.py::`
`test_mc_gate_is_crossable_at_six_folds_and_still_discriminates` (a strong six-fold edge clears
`0.005`, a mean-zero null does not) and `test_real_mc_p_value_feeds_the_nomination_gate_at_six_folds`
(a *real* `mc_sign_flip_p_value` at the real fold count feeds `build_gates` — the integration the
prior unit tests never exercised, so the impossibility had been invisible to a green suite).

---

## Class C — order-consistent pooled point estimate (Auditor C, Finding 3)

**File:** `src/eth_research/v2b/statistics.py` — `_pooled`.

**Defect.** `_pooled` summed folds in the given order while `_resample_means` sums them sorted by
`fold_index`; on unsorted input the reported point estimate would diverge at ULP scale. Latent —
callers pass sorted folds — hence Class C.

**Fix.** `_pooled` now iterates `sorted(folds, key=fold_index)`. On the already-sorted folds every
caller passes this is a no-op, so the bit-for-bit reconciliation with the accepted bootstrap is
preserved (proven by the pre-existing
`test_corrected_bootstrap_reproduces_the_accepted_95pct_bounds_exactly`).

**Regression:** `test_block_partition_sums_reconstruct_the_fold_total` covers the partition identity
the block statistic relies on.

---

## Class C — the linear execution basis must refuse a sqrt-impact scenario (Auditor D)

**File:** `src/eth_research/v2b/execution.py` — `simulate_target_path`.

**Defect.** The vectorized basis models only the linear (fee + half-spread + base-slippage) turnover
cost. A cost scenario carrying a non-zero `impact_coefficient` / `impact_cap` would have its
sqrt-impact term silently dropped, under-charging turnover.

**Fix.** `simulate_target_path` now raises if `cost_scenario.impact_cap != 0.0` or
`impact_coefficient != 0.0`, directing impact analysis to the participation-based capacity report.
The two scenarios the nomination rule routes through the basis (`primary`, `stressed`) are
linear-only, so the guard never fires on the governed path; it only refuses the `proxy_impact_*`
scenarios, which belong in the capacity report.

**Regression:** `tests/test_v2b_execution.py::test_linear_basis_refuses_a_sqrt_impact_scenario`.

---

## Class C — direct firewall assertion, not only via the loader (Auditor A)

**File:** `src/eth_research/v2b/execution.py` — `_assert_firewall`.

**Defect.** The firewall checked only the last engine timestamp; a non-monotonic index, or an
interior open at/after the research cutoff, could in principle slip a later bar close past the seal.

**Fix.** `_assert_firewall` now additionally asserts the index is strictly increasing and that
**every** open is at/before the research cutoff, in addition to the last-open-equals-cutoff and
last-close-strictly-before-seal checks.

**Regression:** `tests/test_v2b_execution.py::test_firewall_rejects_a_non_monotonic_index` and
`test_firewall_rejects_an_open_at_or_after_the_cutoff`.

---

## Class C — strict, accepted-parity registry reader and protocol binding (Auditor E)

**File:** `src/eth_research/v2b/governance.py`.

**Defects.** (1) `_from_line` was weaker than the accepted V2A reader: it coerced fields with
`str(...)`, silently emptied a non-mapping payload, and did not validate the exact key set or that
the fingerprint/hashes were 64-hex. (2) `append_event` did not validate the fingerprint/timestamp at
write time. (3) There was no cross-check that a registry event's `protocol_fingerprint` matches the
committed protocol identity.

**Fixes.**
- `_from_line` now mirrors the accepted `eth_research.v2.registry.read_events` field validation
  exactly: `require_exact_keys`, `require_int(seq)`, `require_choice(event)` over the V2B vocabulary,
  `require_slug(run_id)`, `require_hex64(protocol_fingerprint / prev / entry)`,
  `require_nonempty_str(timestamp)`, `require_mapping(payload)` — so a hash-valid but hand-forged
  line is still rejected on its fields.
- `append_event` now `require_hex64`s the fingerprint and `require_nonempty_str`s the timestamp
  (accepted-writer parity).
- New `verify_registry_bound(repo_root)` subsumes `verify_registry` (chain + lifecycle) and binds
  every event's fingerprint to `protocol_fingerprint(repo_root)`; it is wired into the module CLI.
- The module docstring's reader-reuse claim is corrected to state the reader applies the *same*
  strict field validation as the accepted reader.

**Regressions:** `tests/test_v2b_governance.py::`
`test_append_event_rejects_a_non_hex64_fingerprint`,
`test_reader_rejects_a_hash_valid_but_non_hex64_fingerprint`,
`test_reader_rejects_a_non_mapping_payload`, `test_reader_rejects_an_unexpected_key`,
`test_verify_registry_bound_passes_for_the_committed_fingerprint`,
`test_verify_registry_bound_flags_a_foreign_fingerprint`.

---

## Class C — documentation precision (Auditors D, E)

- `execution.py` module docstring no longer claims the basis reuses the M4B accounting convention
  "EXACTLY"; it states the basis is a *separate* vectorized computation proven bit-for-bit against
  the engine only under the zero-cost reconciliation, and applies the same linear turnover rate (not
  a bit-identical cost derivation) under costs.
- `statistics.py` module and function docstrings state the flip is at the block level and why (the
  whole-fold `1/2**6` resolution floor).
- `governance.py` module docstring states the reader applies the same strict field validation as the
  accepted reader.

---

## What the red team did **not** change

No candidate family was added, removed, renamed, or revived; the two frozen cross-asset families and
the `≤ 1` nomination rule are unchanged. The corrected per-family alpha stays `0.005`. No sealed
partition was read, no acquisition ran, and the one-shot budget was not consumed — all fixes precede
the freeze. The scientific posture is unchanged: V2 remains **not sell-ready**, and a nomination (if
any) forwards a candidate to an *independent* development-gate review, never a validation or
deployment claim.
