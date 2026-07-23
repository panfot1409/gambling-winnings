# V2 Fable 5 — Findings Summary

Human-readable companion to the machine-readable `governance/v2/fable5_findings.json` and the
detailed narrative in `docs/V2_FABLE5_BUG_LOG.md`. Findings are classified:

- **A** — scientific / accounting / financial / evidence / claim
- **B** — security / governance / provenance / lifecycle / buyer-boundary
- **C** — defense-in-depth / diagnostics / docs / test-strength
- **D** — sealed-partition access / immutable accepted-result drift / one-shot corruption / public
  exposure / uncontrolled-exposure capability (**hard stop**)

**Result: 0 × A, 0 × B, 0 × D. 5 × C** (all fixed forward or documented). No hard-stop condition
occurred; no accepted V2A/V2B/V2C artifact or sealed value was touched; all replay/oracle verifiers
reproduce byte-identically after the fixes.

| ID | Class | Severity | Title | Status |
|----|-------|----------|-------|--------|
| F5-C1 | C | Low | Sales-honesty scanner failed OPEN on a distant / cross-clause negator | fixed forward |
| F5-C1-note | C | Low | Paragraph example-marker exemption (author-controlled) | accepted by design |
| F5-C2 | C | Low | Terminal hypothetical liquidation crashed on collapsed trailing liquidity | fixed forward |
| F5-N1 | C | Low | `failed` OQ terminal event has no producer | documented readiness gap |
| F5-N2 | C | Low | Offline verifier does not self-re-bind frozen-input digests | covered by V2C C-001 |

## F5-C1 — Sales-honesty scanner failed open (fixed)

The scanner's negation detector exempted a forbidden superlative when *any* negator appeared within a
12-word window, even across a clause or line boundary, so a genuine unsupported claim like "This is
not a drill: our system is a proven alpha" passed. The window was tightened to same-clause scope
(`_NEGATION_WINDOW = 4`, scan stops at a clause terminator), so only a negator that actually negates
the phrase exempts it. The committed sales surface stays clean; both attack vectors are now flagged.
Regression: `tests/test_v2_fable5_remediation.py`.

### F5-C1 note — paragraph example-marker exemption (accepted, not fixed)

A single example-marker token exempts its whole paragraph. This **cannot** be line-scoped without a
false positive, because the committed `docs/V2AB_STACK_ACCEPTANCE_PLAN.md` relies on it (an
enumeration of forbidden phrases sits next to its "false-claim examples" marker). Retained as a
deliberate author-controlled exemption over the project's own committed spec text (not an
adversarial-input boundary); the fenced `FALSE-CLAIM-EXAMPLES` block remains the primary example
mechanism.

## F5-C2 — Terminal liquidation crashed on collapsed liquidity (fixed)

The fractional engine's *hypothetical* terminal liquidation priced its mark with impact even when the
trailing-30 median dollar-volume had collapsed to zero (a run of zero-volume bars into the terminal
bar), so `cost_model._impact_rate` raised `CostModelError` and escaped the backtest under the frozen
`CAUSAL_PROXY_BASE`/`STRESSED` scenarios. The terminal mark is now priced **impact-free** when no
lagged liquidity exists, mirroring the active-fill contract. This path is unreachable for the
committed runs (real daily dollar-volume is strictly positive over every trailing window), so no
accepted result changes. Regression: `tests/test_v2_fable5_remediation.py`,
`tests/test_v2_fable5_catastrophe.py`.

## F5-N1 — `failed` OQ terminal event has no producer (documented readiness gap)

The V2C OQ registry defines and read-validates a `failed` terminal event, but no code path appends
one — so a started-but-uncompletable run cannot be retired to a `failed` terminal. Not fixed here
because the V2C OQ execution surface is **frozen** (OQ-E2); adding a producer to frozen orchestration
would break the source freeze and cannot be claimed certified by the accepted OQ. The committed OQ
run *completed* successfully. Reserved for a future live/paper run's failure path and recorded in
`docs/V2_PAPER_READINESS_GAP.md`. The related keyless-registry limitation is re-affirmed (disclosed
in `docs/V2C_SECURITY.md`, finding F-6).

## F5-N2 — Offline verifier does not self-re-bind frozen-input digests (already covered)

`verify_oq_run_archive` + the OQ-Q oracle prove internal consistency and independent acceptance but
do not, by themselves, re-execute the frozen source, so a self-consistent forgery of the identity-
bound frozen-*input* digests would not be caught by the offline verifier alone. Already remediated by
V2C bug **C-001** (`tests/test_v2c_oq_committed_run.py::
test_committed_digests_re_derive_from_the_frozen_source`), which re-executes the frozen source at
`slots = 3800` and proves the re-derived digests equal the committed literals on the authoritative
CPython 3.12 leg. No further code change required.

## Relationship to prior milestones

None of these findings invalidates or supersedes any prior milestone's accepted result. F5-C1 and
F5-C2 strengthen defense-in-depth in `commercial_truth.py` and `fractional/engine.py`; F5-N1 and
F5-N2 are documented limitations/gaps, one reserved for a future live surface and one already covered.
The Fable 5 audit's own conclusions are frozen in `governance/v2/fable5_source_freeze.json` and
re-checked by the `V2 Fable 5 Replay` CI on CPython 3.12 + 3.13.
