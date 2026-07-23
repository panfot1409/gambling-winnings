# V2 Fable 5 Bug Log

Defects and observations from the Fable 5 full-system audit of the merged V2 platform (branch
`claude/v2-fable5-full-system-audit`, from `main` = `09fc9c0` = the V2C merge MV2C). Five independent
primary auditors plus a cross-auditor challenge round examined the scientific, governance, security,
operations, and buyer surfaces. **No Class-A (scientific), Class-B (governance/security), or Class-D
(sealed-state / immutable-drift / uncontrolled-exposure) defect was found.** The genuine findings are
all **Class C** (defense-in-depth / test-strength / robustness); each was independently reproduced
before being fixed, with a failing-test-first regression. No fix touches a sealed value, a frozen
governed artifact, or any committed V2A/V2B/V2C result — all replay/oracle verifiers reproduce
byte-identically after the fixes.

Class taxonomy: **A** scientific/accounting/financial/evidence/claim · **B**
security/governance/provenance/lifecycle/buyer-boundary · **C** defense-in-depth/diagnostics/docs/
test-strength · **D** sealed-partition access / immutable accepted-result drift / one-shot corruption
/ public exposure / uncontrolled-exposure capability (hard stop). No Class-D condition occurred.

## F5-C1 — Sales-honesty scanner failed OPEN on a distant / cross-clause negator (fixed)

- **Class / severity:** C (claim-integrity / test-strength). Low. Fail-open but latent (the committed
  sales surface is clean).
- **Discoverer:** cross-auditor challenge (Auditor 4 challenging Auditor 5). Auditor 5 had
  characterised the scanner as "at worst over-flags / fails safe"; the challenger reproduced that it
  fails **open**.
- **Invariant:** `scan_sales_material` must flag a genuine unsupported superlative; a negator exempts a
  forbidden phrase only when it actually negates *that phrase*.
- **Pre-fix behavior / reproducer** (`.venv/bin/python`):
  `scan_sales_material("This is not a drill: our system is a proven alpha.", source="x") == []`
  and `scan_sales_material("There is no reason to doubt our validated alpha.", source="x") == []`.
  `_is_negated` treated any negator within a 12-word window (even spanning the previous line) as a
  negation, so a distant or cross-clause negator silently exempted a real overclaim.
- **Root cause:** `eth_research/v2ab/commercial_truth.py::_is_negated` — over-wide window, no clause
  boundary.
- **Fix:** the negation window is reduced (`_NEGATION_WINDOW = 4`) and the backward scan stops at a
  clause terminator (`. ; ! ?`), so only a negator immediately before the phrase (including one that
  wraps to the previous physical line) exempts it. Committed materials stay clean; both attack vectors
  are now flagged.
- **Accepted-artifact / sealed-state impact:** none. **Paper-readiness impact:** none (strengthens the
  honesty gate).
- **Regression tests:** `tests/test_v2_fable5_remediation.py::test_scanner_negation_no_longer_fails_open`
  (both vectors) and `::test_scanner_still_exempts_legitimate_negations_and_markers` and
  `::test_committed_sales_surface_stays_clean`.
- **Status:** fixed forward.

### F5-C1 note — paragraph example-marker exemption (accepted as author-controlled, not fixed)

The same challenge also showed a single `EXAMPLE_MARKERS` token exempts its whole paragraph, so a
marker dropped into a paragraph can suppress an overclaim on an adjacent line. This **cannot** be
tightened to line scope without a false positive: the committed `docs/V2AB_STACK_ACCEPTANCE_PLAN.md`
relies on exactly this behavior — an enumeration line of the forbidden phrases sits next to its
"false-claim examples" marker line (verified: line-scoping flags six phrases at
`V2AB_STACK_ACCEPTANCE_PLAN.md:108`). The two are structurally identical, so the paragraph marker is
retained as a **deliberate, author-controlled** exemption over the project's *own* committed
sales/spec text (it is not an adversarial-input boundary), documented in `commercial_truth.py` and
covered by `::test_paragraph_marker_exemption_is_intentional_author_controlled`. The fenced
`FALSE-CLAIM-EXAMPLES` block remains the primary example mechanism.

## F5-C2 — Terminal hypothetical liquidation crashed on a collapsed trailing liquidity (fixed)

- **Class / severity:** C (robustness). Low. Committed runs unaffected.
- **Discoverer:** cross-auditor challenge (Auditor 5 challenging Auditor 1). Auditor 1 had reasoned the
  path "unreachable"; the challenger reproduced the crash on schema-valid input.
- **Invariant:** `run_fractional_backtest` reports a finite hypothetical terminal-liquidation value;
  it never crashes on canonical OHLCV.
- **Pre-fix behavior / reproducer:** a valid daily frame with a high-volume warm-up (BuyAndHold buys
  and holds) followed by ≥31 zero-volume bars collapses the trailing-30 median dollar-volume to 0; at
  the terminal bar `_terminal_liquidation_equity` calls `fill_price` with impact on and no lagged
  liquidity, so `_impact_rate` raises `CostModelError("impact requires positive lagged dollar
  volume")`, which escapes the backtest (under `CAUSAL_PROXY_BASE` and `CAUSAL_PROXY_STRESSED`).
- **Root cause:** `eth_research/fractional/engine.py::_terminal_liquidation_equity` priced the
  *hypothetical* terminal mark with impact even when no causal lagged liquidity existed — unlike the
  active-fill path, whose participation cap yields no fill in that state.
- **Fix:** when impact is enabled and the lagged dollar-volume is `None`/`≤ 0`, the hypothetical
  terminal mark is priced **impact-free** (spread + base slippage only) via
  `replace(scenario, impact_coefficient=0.0)`, mirroring the active-fill contract, rather than
  propagating a `CostModelError`. This path is unreachable for the committed runs — real daily
  dollar-volume is strictly positive over every trailing window — so no accepted result changes.
- **Accepted-artifact / sealed-state impact:** none. Proven: `V2A replay OK`, `V2B replay OK`,
  `V2C replay ok`, and the fractional-engine binary-parity suite (including the committed
  `terminal_liquidation_equity` values) all reproduce after the fix.
- **Regression test:**
  `tests/test_v2_fable5_remediation.py::test_terminal_liquidation_never_crashes_on_collapsed_liquidity`
  (both frozen impact scenarios).
- **Status:** fixed forward.

## F5-N1 — `failed` OQ terminal event has no producer (documented readiness gap, not fixed)

- **Class / severity:** C (lifecycle-completeness / readiness gap). Low. Non-live platform.
- **Discoverer:** cross-auditor challenge (Auditor 3 challenging Auditor 4).
- **Observation:** the V2C OQ registry defines and read-validates a `failed` terminal event, but no
  code path in `src/eth_research/v2c/` ever *appends* one (`grep -rn "event=OQ_EVENT_FAILED"
  src/eth_research/v2c/` → no producer; the pattern exists in sibling `fractional`/`m3c`
  orchestrators). So a started-but-uncompletable OQ run cannot be retired to a `failed` terminal.
- **Why not fixed here:** the entire V2C OQ execution surface is **frozen** (OQ-E2, `cea86a5`); adding
  a producer to the frozen orchestrator would break the source freeze and cannot be claimed to be
  certified by the accepted OQ. The committed OQ run *completed* successfully, so no failure needed to
  be recorded. This is an honest **readiness gap** reserved for a future live/paper run's failure
  path, recorded in `docs/V2_PAPER_READINESS_GAP.md` rather than patched into frozen code.
- **Related known limitation (re-affirmed, not new):** the registry `entry_hash` is an *unkeyed*
  sha256 over public body fields — the chain provides tamper-**evidence** against editing/truncating
  existing lines, not authenticity against a writer with filesystem access hand-appending a byte-valid
  forged terminal event. This keyless-integrity property is already disclosed (V2C `docs/V2C_SECURITY.md`,
  finding F-6) and delegated to human review of signed git history; it is not a new defect.

## F5-N2 — Offline verifier does not self-re-bind the frozen-input digests (already covered)

- **Class / severity:** C (audit-completeness). Low.
- **Discoverer:** cross-auditor challenge (Auditor 1 challenging Auditor 2).
- **Observation:** `verify_oq_run_archive` + the OQ-Q oracle prove internal consistency and
  independent acceptance but do not, by themselves, re-execute the frozen source, so a self-consistent
  forgery of the identity-bound frozen-input digests would not be caught by the offline verifier
  alone.
- **Disposition:** already remediated by V2C bug **C-001** — `tests/test_v2c_oq_committed_run.py::
  test_committed_digests_re_derive_from_the_frozen_source` re-executes the frozen source at the
  canonical `slots = 3800` and proves the re-derived digests equal the committed literals (on the
  authoritative CPython 3.12 leg). A forged frozen-input digest cannot pass that from-source
  re-derivation. No further code change required; recorded here for completeness.

## F5-C3 — Scanner failed open on affirming negator-lookalikes and plural inflections (fixed)

- **Class / severity:** C (claim-integrity / test-strength). Low. Fail-open but latent (the
  committed sales surface is clean).
- **Discoverer:** the pre-merge independent acceptance **spot audit** (scope 5, paper-readiness and
  commercial honesty), run before true-merging PR #19 — not the original five-auditor round.
- **Invariant:** a negator exempts a forbidden phrase only when it actually negates it, and an
  inflected form of a forbidden phrase is the same overclaim.
- **Pre-fix behavior / reproducers** (`.venv/bin/python`):
  `scan_sales_material("This is not merely a proven alpha.", source="x") == []` — the affirming
  adverb between the negator and the phrase means the sentence *asserts* the claim, yet the 4-word
  negation window exempted it; and `scan_sales_material("We have proven alphas.", source="x") == []`
  — the exact word-boundary phrase patterns did not match a simple plural.
- **Fix:** `_is_negated` now refuses to exempt when an affirming adverb (`merely`, `just`, `only`,
  `simply`, `purely`) sits between the negator and the phrase, and `_PHRASE_PATTERNS` matches a
  simple plural/`-es` inflection of each phrase's final word. The `_is_negated` docstring no longer
  overclaims ("only a real negation … exempts") and states the heuristic's honest scope. Committed
  materials stay clean; genuine negations of inflected forms ("These are not proven alphas.") stay
  exempt.
- **Accepted-artifact / sealed-state impact:** none. **Paper-readiness impact:** none (the derived
  state is byte-identical; only the honesty gate strengthens).
- **Regression tests:** `tests/test_v2_fable5_remediation.py::
  test_scanner_flags_affirming_negators_and_plural_inflections` (5 vectors) and
  `::test_scanner_still_exempts_genuine_negations_of_inflected_forms`.
- **Status:** fixed forward on the feature branch before the true merge, per the merge directive's
  new-Class-C rule.

## Summary

| id | class | severity | fixed | accepted-artifact impact | sealed impact |
|----|-------|----------|-------|--------------------------|---------------|
| F5-C1 | C | Low | yes (negation) | none | none |
| F5-C1 note | C | Low | accepted by-design | none | none |
| F5-C2 | C | Low | yes | none | none |
| F5-N1 | C | Low | documented readiness gap | none | none |
| F5-N2 | C | Low | covered by V2C C-001 | none | none |
| F5-C3 | C | Low | yes (affirming adverbs + plurals) | none | none |

Zero Class-A / Class-B / Class-D defects. The five primary auditors independently confirmed causality,
accounting, numerical, governance, provenance, immutability, security, isolation, supply-chain, IP,
operations, recovery, buyer-boundary, and sell-ready-derivation invariants hold; the challenge round
converted their residual "weakest boundary" observations into the reproduced Class-C items above.
